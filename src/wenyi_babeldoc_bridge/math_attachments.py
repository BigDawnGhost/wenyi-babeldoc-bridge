"""Attach only unambiguous detached math marks before freezing source objects."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterator
from functools import lru_cache
from itertools import pairwise
from typing import Any

from . import _native
from .annotations import _characters, _rect, _source_characters
from .protected_objects import _MATH_FONT, _variable_letter

logger = logging.getLogger(__name__)
# These are accent candidates, not replacements for the original PDF glyphs.
_ACCENTS = frozenset(
    unicodedata.normalize("NFKC", char).strip() for char in "^ˆ~˜ˉ¯˙¨ˇ˘"
)
# TeX math extension fonts can draw one of these glyphs at a code whose
# Unicode fallback is an ordinary letter. Trust explicit PDF glyph names,
# not a font-name or letter substitution.
_WIDE_ACCENTS = {
    "hatwide": "^",
    "hatwider": "^",
    "hatwiderr": "^",
    "tildewide": "~",
    "tildewider": "~",
    "tildewiderr": "~",
}
_INDIRECT_REFERENCE = re.compile(r"([0-9]+)\s+[0-9]+\s+R")
_DIFFERENCE_TOKEN = re.compile(r"/([^\s()<>\[\]{}/%]*)|([+-]?[0-9]+)|\S")
_OPERATORS = frozenset("=<>≤≥≠±+−×÷")
_EXPONENT_OPERATORS = frozenset("+−-×÷=")
Attachment = tuple[Any, Any]  # Original base glyph, original attached glyph.


def _font_scopes(page: Any) -> Iterator[tuple[int, list[Any]]]:
    yield 0, page.pdf_font
    for obj in page.pdf_xobject:
        yield obj.xobj_id, obj.pdf_font


def _wide_accents_from_differences(value: str) -> dict[int, str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return {}
    # MuPDF serializes the array without comments, possibly without spaces
    # between names. Reject unexpected tokens rather than salvaging part of a
    # malformed encoding.
    code = -1
    named: dict[int, str] = {}
    for token in _DIFFERENCE_TOKEN.finditer(value, 1, len(value) - 1):
        name, start = token.groups()
        if start is not None:
            try:
                code = int(start)
            except ValueError:
                return {}
            if not 0 <= code <= 255:
                return {}
        elif name is None or not 0 <= code <= 255:
            return {}
        else:
            if accent := _WIDE_ACCENTS.get(name):
                named[code] = accent
            else:
                named.pop(code, None)
            code += 1
    return named


def encoded_math_accents(pdf: Any, pages: list[Any]) -> dict[int, dict[int, str]]:
    """Read explicit wide accent codes from the PDF that owns the IL font xrefs."""
    xrefs = {
        font.xref_id
        for page in pages
        for _, fonts in _font_scopes(page)
        for font in fonts
        if font.xref_id and font.xref_id > 0
    }
    accents = {}
    for xref in xrefs:
        try:
            kind, value = pdf.xref_get_key(xref, "Encoding/Differences")
            if kind == "xref":
                reference = _INDIRECT_REFERENCE.fullmatch(value)
                if reference is None:
                    continue
                target = int(reference[1])
                if not 0 < target < pdf.xref_length():
                    continue
                value = pdf.xref_object(target)
            elif kind != "array":
                continue
        except (ValueError, RuntimeError):
            # A missing or unreadable object is not evidence of a wide accent.
            continue
        if named := _wide_accents_from_differences(value):
            accents[xref] = named
    return accents


def _text(char: Any) -> str:
    return unicodedata.normalize("NFKC", char.char_unicode or "").strip()


def _mark_text(
    page: Any, encoded_accents: dict[int, dict[int, str]] | None
) -> Callable[[Any], str]:
    if not encoded_accents:
        return _text
    encoded_fonts = {
        (context, font.font_id): encoded_accents[font.xref_id]
        for context, fonts in _font_scopes(page)
        for font in fonts
        if font.xref_id in encoded_accents
    }

    def text_of(char: Any) -> str:
        text = _text(char)
        codes = encoded_fonts.get((char.xobj_id, char.pdf_style.font_id))
        code = getattr(char, "pdf_character_id", None)
        if codes and code is not None and text not in _ACCENTS:
            return codes.get(code, text)
        return text

    return text_of


def math_accent_checker(pdf: Any, page: Any) -> Callable[[Any], bool]:
    """Check PDF glyph names lazily when layout finds plausible accent geometry."""

    @lru_cache(maxsize=1)
    def encoded_text() -> Callable[[Any], str]:
        return _mark_text(page, encoded_math_accents(pdf, [page]))

    def is_accent(char: Any) -> bool:
        return _text(char) in _ACCENTS or encoded_text()(char) in _ACCENTS

    return is_accent


def _same_context(left: Any, right: Any) -> bool:
    return (
        not getattr(left, "vertical", False)
        and not getattr(right, "vertical", False)
        and getattr(left, "xobj_id", None) == getattr(right, "xobj_id", None)
    )


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


def _movable(composition: Any, text_of: Callable[[Any], str]) -> bool:
    formula = getattr(composition, "pdf_formula", None)
    if formula is None:
        return True
    if getattr(formula, "pdf_curve", None) or getattr(formula, "pdf_form", None):
        return False
    members = [(text, c) for c in formula.pdf_character if (text := text_of(c))]
    if getattr(formula, "is_corner_mark", False) and not any(
        text in _ACCENTS for text, _ in members
    ):
        return False
    # Complete native formulas stay intact. Only mark-only carriers may be split.
    # Native grouping can mix an operator into detached marks; without a full-size
    # variable or constant this is still not evidence of a complete expression.
    largest = max((c.pdf_style.font_size for _, c in members), default=0)
    return len(members) == 1 or all(
        text in _ACCENTS
        or text in _OPERATORS
        or (
            len(text) == 1 and text.isalnum() and c.pdf_style.font_size <= largest * 0.8
        )
        for text, c in members
    )


def _isolated_in_formula(mark: Any, composition: Any) -> bool:
    """Allow an accent incorrectly grouped with distant, unrelated math glyphs."""
    formula = composition.pdf_formula
    if getattr(formula, "pdf_curve", None) or getattr(formula, "pdf_form", None):
        return False
    for char in formula.pdf_character:
        if char is mark or not _text(char):
            continue
        size = max(mark.pdf_style.font_size, char.pdf_style.font_size)
        gap = max(mark.box.x - char.box.x2, char.box.x - mark.box.x2, 0)
        if gap <= size * 0.65 and abs(mark.box.y - char.box.y) <= size * 0.8:
            return False
    return True


def _opposed_script_bases(
    para: Any,
    chars: list[tuple[int, int, int, Any]],
    text_of: Callable[[Any], str],
) -> dict[int, Any]:
    """Find base / native exponent / detached subscript in source order."""
    comps = para.pdf_paragraph_composition
    rows = sorted(chars, key=lambda row: row[1])
    bases = {}
    for i in range(1, len(rows) - 1):
        ci, start, _, first = rows[i]
        prev_ci, _, base_end, base = rows[i - 1]
        if ci == prev_ci or base_end != start:
            continue
        upper = getattr(comps[ci], "pdf_formula", None)
        if (
            upper is None
            or not getattr(upper, "is_corner_mark", False)
            or getattr(upper, "pdf_curve", None)
            or getattr(upper, "pdf_form", None)
        ):
            continue
        # Only an entire corner run qualifies, not an incidental part of a formula.
        end = i + sum(bool(_text(c)) for c in upper.pdf_character)
        if end >= len(rows):
            continue
        lower_ci, lower_start, lower_end, lower = rows[end]
        if (
            getattr(comps[lower_ci], "pdf_formula", None) is not None
            or lower.pdf_style.font_id != base.pdf_style.font_id
            or para.unicode[rows[end - 1][2] : lower_start] not in ("", " ")
        ):
            continue
        letter = text_of(lower)
        if len(letter) != 1 or not _variable_letter(letter):
            continue
        script = rows[i:end]
        text = [text_of(c) for _, _, _, c in script]
        size = base.pdf_style.font_size
        small = lower.pdf_style.font_size
        # The upper run provides math evidence that a citation number alone cannot.
        if (
            not size
            or not small
            or not any(c in _EXPONENT_OPERATORS for c in text[1:-1])
            or not (text[0].isalnum() and text[-1].isalnum())
            or abs(first.box.x - lower.box.x) > 0.2 * size
            or not 0.15 * size <= first.box.y - base.box.y <= 0.85 * size
            or any(
                owner != ci
                or not _same_context(base, c)
                or abs(c.box.y - first.box.y) > 0.1 * size
                or abs((c.pdf_style.font_size or 0) - small) > 0.12 * size
                or len(t) != 1
                or not (
                    t.isdecimal()
                    or _variable_letter(t)
                    or t in _EXPONENT_OPERATORS
                    or t == "/"
                )
                for (owner, _, _, c), t in zip(script, text)
            )
            or any(
                prev_end != next_start
                or not -0.15 * size <= nxt.box.x - prev.box.x2 <= 0.2 * size
                for (_, _, prev_end, prev), (_, next_start, _, nxt) in pairwise(script)
            )
        ):
            continue
        # Do not claim one letter of a longer lowered run.
        if end + 1 < len(rows):
            _, next_start, _, nxt = rows[end + 1]
            if (
                next_start == lower_end
                and _same_context(lower, nxt)
                and abs(nxt.box.y - lower.box.y) <= 0.1 * size
                and -0.15 * size <= nxt.box.x - lower.box.x2 <= 0.2 * size
                and text_of(nxt).isalnum()
            ):
                continue
        bases[id(lower)] = base
    return bases


def _rewrite_source(
    para: Any,
    offsets: dict[int, tuple[int, int]],
    pairs: list[tuple[Any, Any, str]],
    *,
    bb: dict[str, Any],
    text_of: Callable[[Any], str],
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
            emit(text_of(mark), mark)
        emit(source[start:end], char)
        for mark in after[id(char)]:
            emit(text_of(mark), mark)
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
    encoded_accents: dict[int, dict[int, str]] | None = None,
) -> dict[int, list[Attachment]]:
    """Repair new horizontal source projections, never restored session snapshots.

    Native styles have already been grouped; offsets still identify the original
    reading order. Paragraph indices, glyph positions and draw identities stay
    unchanged. Directory rows and existing complete formulas are not rewritten.
    """
    names = {font.font_id: font.name or "" for font in page.pdf_font}
    text_of = _mark_text(page, encoded_accents)
    owners: dict[int, tuple[int, Any]] = {}
    peers: dict[int, list[Any]] = {}
    opposed: dict[int, Any] = {}
    bases: list[tuple[int, Any]] = []
    marks: list[tuple[int | None, Any, bool]] = []

    def add_mark(owner: int | None, char: Any, text: str) -> None:
        accent = text in _ACCENTS
        if not getattr(char, "vertical", False) and (
            accent or (len(text) == 1 and (text.isdecimal() or _variable_letter(text)))
        ):
            marks.append((owner, char, accent))

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
        opposed.update(_opposed_script_bases(para, chars, text_of))
        peers[index] = [char for _, _, _, char in chars]
        movable: dict[int, bool] = {}
        for ci, _, _, char in chars:
            comp = para.pdf_paragraph_composition[ci]
            owners[id(char)] = (index, comp)
            text = text_of(char)
            if (
                not getattr(char, "vertical", False)
                and len(text) == 1
                and _variable_letter(text)
            ):
                bases.append((index, char))
            if ci not in movable:
                movable[ci] = _movable(comp, text_of)
            if movable[ci] or (text in _ACCENTS and _isolated_in_formula(char, comp)):
                add_mark(index, char, text)
    for char in page.pdf_character or []:
        if id(char) not in all_owned:
            add_mark(None, char, text_of(char))

    contexts: dict[int | None, int] = {}

    def geometry(char: Any) -> tuple[int, tuple[float, float, float, float], float]:
        return (
            contexts.setdefault(getattr(char, "xobj_id", None), len(contexts)),
            _rect(char.box),
            char.pdf_style.font_size or 0,
        )

    candidates_by_mark = _native.math_attachment_candidates(
        [(index, *geometry(base)) for index, base in bases],
        [(owner, *geometry(mark), accent) for owner, mark, accent in marks],
    )
    proposed: list[tuple[int, Any, Any, str]] = []
    in_place: set[int] = set()
    for (_, mark, accent), nearby in zip(marks, candidates_by_mark):
        candidates = [
            (*bases[i], slot) for i, slot in nearby if bases[i][1] is not mark
        ]
        unambiguous = len(candidates) == 1
        if len(candidates) == 2 and not accent:
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
        existing_pair = (
            unambiguous and slot == "right-lower" and opposed.get(id(mark)) is base
        )
        base_peers = (
            [char for char in peers[index] if char is not mark]
            if accent
            else peers[index]
        )
        # Either a unique accent or an opposed exponent can confirm an isolated
        # ordinary-font base without needing a second baseline math glyph.
        if not _math_base(base, base_peers, names, accent=accent or existing_pair):
            continue
        _, composition = owners[id(base)]
        formula = getattr(composition, "pdf_formula", None)
        if formula and (
            getattr(formula, "pdf_curve", None) or getattr(formula, "pdf_form", None)
        ):
            continue
        if existing_pair:
            in_place.add(id(mark))
        elif slot != "accent" and not _has_continuation(
            base, slot, peers[index], names
        ):
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
        # Opposed scripts already span the base and exponent in reading order.
        # Keep that interval for protection instead of inserting the subscript anew.
        moves = [pair for pair in pairs if id(pair[1]) not in in_place]
        if moves:
            _rewrite_source(
                page.pdf_paragraph[index], offsets[index], moves, bb=bb, text_of=text_of
            )
            transferred.update(id(mark) for _, mark, _ in moves)
    page.pdf_character = [
        char for char in page.pdf_character or [] if id(char) not in transferred
    ]
    return {
        index: [(base, mark) for base, mark, _ in pairs]
        for index, pairs in by_paragraph.items()
    }
