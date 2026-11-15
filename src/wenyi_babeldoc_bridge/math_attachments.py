"""Attach only unambiguous detached math marks before freezing source objects."""

from __future__ import annotations

import logging
import unicodedata
from collections import defaultdict
from typing import Any

from .annotations import _characters, _source_characters
from .protected_objects import _MATH_FONT, _variable_letter

logger = logging.getLogger(__name__)
# These are accent candidates, not replacements for the original PDF glyphs.
_ACCENTS = frozenset(
    unicodedata.normalize("NFKC", char).strip() for char in "^ˆ~˜ˉ¯˙¨ˇ˘"
)
_OPERATORS = frozenset("=<>≤≥≠±+−×÷")
Attachment = tuple[Any, Any]  # Original base glyph, original attached glyph.


def _text(char: Any) -> str:
    return unicodedata.normalize("NFKC", char.char_unicode or "").strip()


def _same_context(left: Any, right: Any) -> bool:
    return (
        not getattr(left, "vertical", False)
        and not getattr(right, "vertical", False)
        and getattr(left, "xobj_id", None) == getattr(right, "xobj_id", None)
    )


def _relation(mark: Any, base: Any) -> str | None:
    """Return a local attachment slot, in bottom-up PDF coordinates."""
    if not _same_context(mark, base):
        return None
    size = base.pdf_style.font_size
    small = mark.pdf_style.font_size
    if not size or not small or size <= 0 or small <= 0:
        return None
    m, b = mark.box, base.box
    dy = (m.y - b.y) / size
    text = _text(mark)
    if text in _ACCENTS:
        overlap = min(m.x2, b.x2) - max(m.x, b.x)
        width = min(m.x2 - m.x, b.x2 - b.x)
        if (
            width > 0
            and overlap >= width * 0.6
            and abs((m.x + m.x2 - b.x - b.x2) / 2) <= size * 0.25
            and 0.12 <= dy <= 0.8
            and 0.5 <= small / size <= 1.2
        ):
            return "accent"
        return None
    if len(text) != 1 or not (text.isdecimal() or _variable_letter(text)):
        return None
    if not 0.45 <= small / size <= 0.8:
        return None
    if 0.15 <= dy <= 0.85:
        vertical = "upper"
    elif -0.5 <= dy <= -0.1:
        vertical = "lower"
    else:
        return None
    if -0.15 * size <= m.x - b.x2 <= 0.25 * size:
        return f"right-{vertical}"
    if -0.15 * size <= b.x - m.x2 <= 0.25 * size:
        return f"left-{vertical}"
    return None


def _math_base(
    char: Any, peers: list[Any], names: dict[str, str], *, accent: bool = False
) -> bool:
    """Require math evidence or a unique accent over an isolated variable."""
    text = _text(char)
    if len(text) != 1 or not _variable_letter(text):
        return False
    size = char.pdf_style.font_size
    if not size or size <= 0:
        return False
    if _MATH_FONT.search(names.get(char.pdf_style.font_id, "")) or any(
        "MATHEMATICAL" in unicodedata.name(c, "") for c in char.char_unicode or ""
    ):
        return True
    nearby = [
        other
        for other in peers
        if other is not char
        and _same_context(char, other)
        and abs(other.box.y - char.box.y) < size * 0.15
        and max(char.box.x - other.box.x2, other.box.x - char.box.x2, 0) <= size * 0.6
    ]
    # Do not turn the last letter of a word into a mathematical variable.
    if any(
        _text(other).isalpha()
        and max(char.box.x - other.box.x2, other.box.x - char.box.x2, 0) < size * 0.15
        for other in nearby
    ):
        return False
    return accent or any(_text(other) in _OPERATORS for other in nearby)


def _has_continuation(
    base: Any, slot: str, peers: list[Any], names: dict[str, str]
) -> bool:
    """Claim loose scripts only inside math, not as trailing citation/footnote marks."""
    size = base.pdf_style.font_size
    for other in peers:
        if other is base or not _same_context(base, other):
            continue
        if abs(other.box.y - base.box.y) > size * 0.15:
            continue
        gap = (
            other.box.x - base.box.x2
            if slot.startswith("right")
            else base.box.x - other.box.x2
        )
        if not -size * 0.1 <= gap <= size * 1.5:
            continue
        if (
            _text(other) in _OPERATORS
            or _math_base(other, peers, names)
            or (
                other.pdf_style.font_id == base.pdf_style.font_id
                and _math_base(other, peers, names, accent=True)
            )
        ):
            return True
    return False


def _movable(char: Any, composition: Any | None) -> bool:
    if composition is None:
        return True
    formula = getattr(composition, "pdf_formula", None)
    if formula is None:
        return True
    if getattr(formula, "pdf_curve", None) or getattr(formula, "pdf_form", None):
        return False
    members = [c for c in formula.pdf_character if _text(c)]
    if getattr(formula, "is_corner_mark", False) and not any(
        _text(c) in _ACCENTS for c in members
    ):
        return False
    # Complete native formulas stay intact. Only mark-only carriers may be split.
    # Native grouping can mix an operator into detached marks; without a full-size
    # variable or constant this is still not evidence of a complete expression.
    largest = max((c.pdf_style.font_size for c in members), default=0)
    return len(members) == 1 or all(
        _text(c) in _ACCENTS
        or _text(c) in _OPERATORS
        or (
            len(_text(c)) == 1
            and _text(c).isalnum()
            and c.pdf_style.font_size <= largest * 0.8
        )
        for c in members
    )


def _rewrite_source(
    para: Any,
    offsets: dict[int, tuple[int, int]],
    pairs: list[tuple[Any, Any, str]],
    *,
    bb: dict[str, Any],
) -> None:
    rows = sorted(_source_characters(para, offsets), key=lambda row: row[1])
    source = para.unicode
    moved = {id(mark) for _, mark, _ in pairs}
    before: dict[int, list[Any]] = defaultdict(list)
    after: dict[int, list[Any]] = defaultdict(list)
    for base, mark, slot in pairs:
        (before if slot.startswith("left") else after)[id(base)].append(mark)
        if id(mark) not in offsets:
            para.pdf_paragraph_composition.append(
                bb["PdfParagraphComposition"](pdf_character=mark)
            )
    parts: list[str] = []
    mapped: dict[int, tuple[int, int]] = {}
    length = 0

    def emit(text: str, char: Any | None = None) -> None:
        nonlocal length
        parts.append(text)
        if char is not None:
            mapped[id(char)] = (length, length + len(text))
        length += len(text)

    cursor = 0
    for _, start, end, char in rows:
        emit(source[cursor:start])
        cursor = end
        if id(char) in moved:
            continue
        for mark in before[id(char)]:
            emit(_text(mark), mark)
        emit(source[start:end], char)
        for mark in after[id(char)]:
            emit(_text(mark), mark)
    emit(source[cursor:])
    para.unicode = "".join(parts)
    offsets.clear()
    offsets.update(mapped)


def attach_math_marks(
    page: Any,
    offsets: dict[int, dict[int, tuple[int, int]]],
    *,
    bb: dict[str, Any],
    excluded: set[int] | None = None,
) -> dict[int, list[Attachment]]:
    """Repair new horizontal source projections, never restored session snapshots.

    Native styles have already been grouped; offsets still identify the original
    reading order. Paragraph indices, glyph positions and draw identities stay
    unchanged. Directory rows and existing complete formulas are not rewritten.
    """
    names = {font.font_id: font.name or "" for font in page.pdf_font}
    owners: dict[int, tuple[int, Any]] = {}
    peers: dict[int, list[Any]] = {}
    bases: list[tuple[int, Any]] = []
    marks: list[tuple[int | None, Any, Any | None]] = []
    all_owned = {
        id(char)
        for para in page.pdf_paragraph
        for comp in para.pdf_paragraph_composition
        for char in _characters(comp)
    }
    for index, para in enumerate(page.pdf_paragraph):
        if (
            index not in offsets
            or index in (excluded or set())
            or getattr(para, "vertical", False)
        ):
            continue
        chars = _source_characters(para, offsets[index])
        peers[index] = [char for _, _, _, char in chars]
        for ci, _, _, char in chars:
            comp = para.pdf_paragraph_composition[ci]
            owners[id(char)] = (index, comp)
            text = _text(char)
            if len(text) == 1 and _variable_letter(text):
                bases.append((index, char))
            if _movable(char, comp):
                marks.append((index, char, comp))
    marks.extend(
        (None, char, None)
        for char in page.pdf_character or []
        if id(char) not in all_owned
    )
    proposed: list[tuple[int, Any, Any, str]] = []
    for owner, mark, _ in marks:
        candidates = [
            (index, base, slot)
            for index, base in bases
            if base is not mark
            and (owner is None or index == owner)
            and (slot := _relation(mark, base)) is not None
        ]
        if len(candidates) == 2 and _text(mark) not in _ACCENTS:
            left, right = sorted(candidates, key=lambda row: row[1].box.x)
            index, anchor, slot = left
            other_index, other, other_slot = right
            # A small mark between neighboring math bases belongs unambiguously
            # to their common expression even if its individual base is unclear.
            # Use a source insertion point, not a guessed semantic attachment;
            # the original glyph geometry is retained inside the whole object.
            if (
                index == other_index
                and slot.startswith("right-")
                and other_slot == slot.replace("right-", "left-")
                and _math_base(anchor, peers[index], names)
                and (
                    _math_base(other, peers[index], names)
                    or (
                        other.pdf_style.font_id == anchor.pdf_style.font_id
                        and _math_base(other, peers[index], names, accent=True)
                    )
                )
            ):
                end = offsets[index][id(anchor)][1]
                start = offsets[index][id(other)][0]
                if (
                    end <= start
                    and not page.pdf_paragraph[index].unicode[end:start].strip()
                ):
                    candidates = [left]
        if len(candidates) != 1:
            if len(candidates) > 1:
                logger.debug(
                    "Ambiguous mathematical attachment; keeping original glyph"
                )
            continue
        index, base, slot = candidates[0]
        if not _math_base(base, peers[index], names, accent=slot == "accent"):
            continue
        _, composition = owners[id(base)]
        formula = getattr(composition, "pdf_formula", None)
        if formula and (
            getattr(formula, "pdf_curve", None) or getattr(formula, "pdf_form", None)
        ):
            continue
        if slot != "accent" and not _has_continuation(base, slot, peers[index], names):
            continue
        proposed.append((index, base, mark, slot))
    slots: dict[tuple[int, str], int] = defaultdict(int)
    for _, base, _, slot in proposed:
        slots[id(base), slot] += 1
    base_ids = {id(base) for _, base, _, _ in proposed}
    mark_ids = {id(mark) for _, _, mark, _ in proposed}
    by_paragraph: dict[int, list[tuple[Any, Any, str]]] = defaultdict(list)
    for index, base, mark, slot in proposed:
        # Nested attachments need their own structure. Do not partially rewrite
        # a chain (and accidentally consume an anchor before emitting its mark).
        if (
            slots[id(base), slot] == 1
            and id(base) not in mark_ids
            and id(mark) not in base_ids
        ):
            by_paragraph[index].append((base, mark, slot))
    transferred = set()
    for index, pairs in by_paragraph.items():
        _rewrite_source(page.pdf_paragraph[index], offsets[index], pairs, bb=bb)
        transferred.update(id(mark) for _, mark, _ in pairs)
    page.pdf_character = [
        char for char in page.pdf_character or [] if id(char) not in transferred
    ]
    return {
        index: [(base, mark) for base, mark, _ in pairs]
        for index, pairs in by_paragraph.items()
    }
