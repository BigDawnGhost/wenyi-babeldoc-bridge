"""Project confirmed mathematical glyphs into immutable, contiguous IL objects."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from copy import copy
from typing import Any

from .annotations import _characters, _source_characters, extract_inline_annotations

# Font names are evidence of mathematical glyphs, not a Unicode correction table.
# Missing ToUnicode or italics alone must never turn prose into an opaque object.
_MATH_FONT = re.compile(
    r"AdvPSM[PI]|AdvSPSMI|AdvP4C4E|AdvPSMSAM|"
    r"Math|Symbol|CMSY|CMEX|CMMI|MSAM|MSBM",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"\(cid:\d+\)|[^\W\d_]+|\d+(?:\.\d+)?|[^\w\s]|\w")
_FUNCTIONS = {"sin", "cos", "tan", "sinh", "cosh", "log", "ln", "exp", "Re", "Im"}


def _variable_letter(char: str) -> bool:
    """Allow unseeded Latin/Greek variables, not arbitrary single-letter prose."""
    name = unicodedata.name(char, "")
    return char.isalpha() and ("LATIN" in name or "GREEK" in name)


def _tokens(source: str, seeds: list[tuple[int, int]]) -> list[re.Match[str]]:
    """Split words at exact seed boundaries and between variable/prose scripts."""
    seed_boundaries = {position for span in seeds for position in span}
    tokens = []
    for token in _TOKEN.finditer(source):
        if not token.group().isalpha():
            # Numbers (including decimals) and CID spellings are atomic tokens.
            tokens.append(token)
            continue
        start, end = token.span()
        cuts = {start, end}
        cuts.update(
            position
            for position in range(start + 1, end)
            if _variable_letter(source[position - 1])
            != _variable_letter(source[position])
        )
        ordered = sorted(cuts)
        for left, right in zip(ordered, ordered[1:]):
            inner = [left, right]
            if source[left:right] not in _FUNCTIONS:
                inner.extend(
                    position for position in seed_boundaries if left < position < right
                )
            inner.sort()
            for a, b in zip(inner, inner[1:]):
                tokens.extend(_TOKEN.finditer(source, a, b))
    return tokens


def restore_protected_formula_baselines(para: Any, items: list[dict[str, Any]]) -> None:
    """Anchor protected objects to their original prose line before injection.

    Native typesetting places ``box.y - y_offset`` on the new text baseline.
    A merged object's bounding-box bottom is not that baseline: subscripts and
    tall operators can extend below it. Recover the anchor from frozen glyphs on
    every fillback, including snapshots made before this policy existed. Never
    move individual glyphs or rewrite the durable snapshot.
    """
    compositions = para.pdf_paragraph_composition or []
    prose = [
        char
        for comp in compositions
        if getattr(comp, "pdf_formula", None) is None
        for char in _characters(comp)
        if (char.char_unicode or "").strip() and not getattr(char, "vertical", False)
    ]
    if not prose or getattr(para, "vertical", False):
        return
    size = para.pdf_style.font_size
    for item in items:
        if item["kind"] != "formula" or not item.get("protected"):
            continue
        formula = compositions[item["composition_index"]].pdf_formula
        if getattr(formula, "is_corner_mark", False) or not formula.pdf_character:
            continue
        # Prefer body-size math glyphs over numerator/subscript glyphs. Compare
        # original line coordinates, not source order (native runs are regrouped).
        closest_size = min(
            abs(char.pdf_style.font_size - size) for char in formula.pdf_character
        )
        anchors = [
            char
            for char in formula.pdf_character
            if abs(char.pdf_style.font_size - size) <= closest_size + 0.1
        ]

        def distance(char: Any) -> tuple[float, float]:
            vertical = min(abs(char.box.y - anchor.box.y) for anchor in anchors)
            horizontal = max(
                formula.box.x - char.box.x2, char.box.x - formula.box.x2, 0
            )
            return round(vertical, 1), horizontal

        neighbor = min(prose, key=distance)
        if distance(neighbor)[0] <= size * 0.6:
            formula.y_offset = formula.box.y - neighbor.box.y


def prepare_protected_annotations(
    para: Any,
    links: list[dict[str, Any]],
    *,
    fonts: list[Any],
    bb: dict[str, Any],
    offsets: dict[int, tuple[int, int]] | None = None,
    attachments: Sequence[tuple[Any, Any]] = (),
    fixed_glyphs: Sequence[Any] = (),
) -> tuple[str, list[dict[str, Any]], tuple[int, ...]]:
    """Freeze formulas and confirmed structural glyphs using their original identity.

    Reading-order offsets, captured before native regrouping, determine membership.
    Formula runs can interleave variable styles; neither composition order nor the
    PDF's lossy Unicode spelling determines which glyph gets restored.
    Return clean prose, annotations and the original-to-clean source boundary map.
    """
    source = para.unicode or ""
    chars = _source_characters(para, offsets)
    original = list(para.pdf_paragraph_composition or [])
    names = {font.font_id: font.name or "" for font in fonts}
    attached_ids = {id(char) for pair in attachments for char in pair}
    relocated_ids = {id(mark) for _, mark in attachments}
    fixed_ids = {id(char) for char in fixed_glyphs}
    formula_indices = {
        i
        for i, comp in enumerate(original)
        if getattr(comp, "pdf_formula", None) is not None
    }
    seeds = [
        (start, end)
        for ci, start, end, char in chars
        if ci in formula_indices
        or id(char) in attached_ids
        or id(char) in fixed_ids
        or _MATH_FONT.search(names.get(char.pdf_style.font_id, ""))
        or any(
            unicodedata.category(c) == "Sm"
            or "MATHEMATICAL" in unicodedata.name(c, "")
            or "\u2070" <= c <= "\u209f"
            for c in char.char_unicode or ""
        )
    ]
    # Text-only native formulas can incorrectly collect distant accents. Seed
    # their actual glyphs, not the intervening prose. Graphics-bearing objects
    # remain atomic: splitting their curves/forms needs a different ownership rule.
    locations = {id(char): (start, end) for _, start, end, char in chars}
    atomic_spans = [
        (
            min(locations[id(base)][0], locations[id(mark)][0]),
            max(locations[id(base)][1], locations[id(mark)][1]),
        )
        for base, mark in attachments
    ]
    intact_native = {}
    for ci in formula_indices:
        formula = original[ci].pdf_formula
        spans = [(start, end) for index, start, end, _ in chars if index == ci]
        if spans and (
            getattr(formula, "pdf_curve", None) or getattr(formula, "pdf_form", None)
        ):
            span = (min(a for a, _ in spans), max(b for _, b in spans))
            seeds.append(span)
            atomic_spans.append(span)
        # Do not split existing fractions/multiline expressions just because
        # their glyphs are farther apart. Mark-only carriers are not evidence.
        if any(
            any(c.isalnum() for c in char.char_unicode or "")
            for char in formula.pdf_character
        ) and not any(id(char) in relocated_ids for char in formula.pdf_character):
            intact_native.update((id(char), ci) for char in formula.pdf_character)
    # Extending an intact base object must not break its existing fraction/line
    # structure. Only the mark's former carrier loses its native grouping.
    for base, mark in attachments:
        if id(base) in intact_native:
            intact_native[id(mark)] = intact_native[id(base)]
    tokens = _tokens(source, seeds)
    token_chars = [
        [
            char
            for _, start, end, char in chars
            if start < token.end() and token.start() < end
        ]
        for token in tokens
    ]

    def connected(left: int, right: int) -> bool:
        """Whitespace in lossy reading order is not evidence of spatial adjacency."""
        if any(
            start <= min(tokens[left].start(), tokens[right].start())
            and max(tokens[left].end(), tokens[right].end()) <= end
            for start, end in atomic_spans
        ):
            return True
        for a in token_chars[left]:
            for b in token_chars[right]:
                if id(a) in intact_native and intact_native[id(a)] == intact_native.get(
                    id(b)
                ):
                    return True
                # A structural prefix must not seed a new mathematical expression.
                if id(a) in fixed_ids or id(b) in fixed_ids:
                    continue
                if getattr(a, "xobj_id", None) != getattr(b, "xobj_id", None):
                    continue
                size = max(a.pdf_style.font_size, b.pdf_style.font_size)
                gap = max(a.box.x - b.box.x2, b.box.x - a.box.x2, 0)
                if gap <= size * 0.65 and abs(a.box.y - b.box.y) <= size * 0.8:
                    return True
        return False

    selected = [
        any(start < token.end() and token.start() < end for start, end in seeds)
        for token in tokens
    ]
    seeded = list(selected)

    def mathematical(token: re.Match[str]) -> bool:
        text = token.group()
        if text in _FUNCTIONS or text.startswith("(cid:") or text[0].isdigit():
            return True
        if len(text) == 1 and _variable_letter(text):
            if text not in {"a", "A", "I"}:
                return True
            adjacent = (
                source[: token.start()].rstrip()[-1:]
                + source[token.end() :].lstrip()[:1]
            )
            return any(c in "=+-*/<>" for c in adjacent)
        return len(text) == 1 and (
            text in "()[]{}|+-*/^_=<>" or unicodedata.category(text) == "Sm"
        )

    for i in range(len(tokens)):
        if not selected[i]:
            continue
        for step in (-1, 1):
            j = i + step
            while (
                0 <= j < len(tokens)
                and mathematical(tokens[j])
                and connected(j - step, j)
            ):
                selected[j] = True
                j += step
    # Do not absorb the opening delimiter of a prose parenthesis such as
    # "m < k (traveling)". Mathematical brackets containing seeded tokens stay.
    for i, token in enumerate(tokens):
        if not selected[i] or seeded[i] or token.group() not in "([{":
            continue
        depth = 1
        j = i + 1
        while j < len(tokens) and selected[j]:
            if tokens[j].group() in "([{":
                depth += 1
            elif tokens[j].group() in ")]}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth:
            selected[i] = False
    regions: list[tuple[int, int]] = []
    for i, (token, chosen) in enumerate(zip(tokens, selected)):
        if not chosen:
            continue
        start, end = token.span()
        if (
            regions
            and not source[regions[-1][1] : start].strip()
            and connected(i - 1, i)
        ):
            regions[-1] = (regions[-1][0], end)
        else:
            regions.append((start, end))
    if not regions:
        return (
            source,
            extract_inline_annotations(para, links, offsets=offsets),
            tuple(range(len(source) + 1)),
        )

    parts = []
    cursor = 0
    for start, end in regions:
        parts.append(source[cursor:start])
        cursor = end
    parts.append(source[cursor:])
    cleaned = "".join(parts)
    frozen_ids = {
        id(char)
        for _, start, end, char in chars
        if any(left <= start and end <= right for left, right in regions)
    }
    compositions = []
    for comp in original:
        remaining = [
            char
            for char in _characters(comp)
            if id(char) not in frozen_ids and (char.char_unicode or "").strip()
        ]
        if not remaining:
            continue
        if len(remaining) == len(_characters(comp)):
            compositions.append(comp)
            continue
        run = getattr(comp, "pdf_same_style_characters", None)
        line = getattr(comp, "pdf_line", None)
        carrier = copy(run or line)
        if carrier is None:
            raise ValueError("Cannot split a mathematical glyph carrier safely")
        carrier.pdf_character = remaining
        replacement = copy(comp)
        if run is not None:
            replacement.pdf_same_style_characters = carrier
        elif line is not None:
            replacement.pdf_line = carrier
        else:
            raise ValueError("Cannot split a mathematical glyph carrier safely")
        compositions.append(replacement)

    for left, right in regions:
        members = [
            (ci, start, char)
            for ci, start, end, char in chars
            if left <= start and end <= right
        ]
        glyphs = [char for _, _, char in sorted(members, key=lambda row: row[1])]
        formulas = [
            original[ci].pdf_formula
            for ci in sorted({ci for ci, _, _ in members})
            if ci in formula_indices
        ]
        glyph_ids = {id(char) for char in glyphs}
        for formula in formulas:
            if (
                getattr(formula, "pdf_curve", None)
                or getattr(formula, "pdf_form", None)
            ) and any(
                id(char) not in glyph_ids
                for char in formula.pdf_character
                if (char.char_unicode or "").strip()
            ):
                raise ValueError(
                    "Cannot split a mathematical object with attached graphics"
                )
        boxes = [char.box for char in glyphs] + [
            item.box
            for value in formulas
            for item in [
                *(getattr(value, "pdf_curve", None) or []),
                *(getattr(value, "pdf_form", None) or []),
            ]
            if getattr(item, "box", None) is not None
        ]
        box = bb["Box"](
            x=min(value.x for value in boxes),
            y=min(value.y for value in boxes),
            x2=max(value.x2 for value in boxes),
            y2=max(value.y2 for value in boxes),
        )
        formula = bb["PdfFormula"](
            box=box,
            pdf_character=glyphs,
            pdf_curve=[
                curve
                for value in formulas
                for curve in (getattr(value, "pdf_curve", []) or [])
            ],
            pdf_form=[
                form
                for value in formulas
                for form in (getattr(value, "pdf_form", []) or [])
            ],
            x_offset=0,
            y_offset=0,
            x_advance=box.x2 - box.x,
            is_corner_mark=False,
        )
        if (
            len(formulas) == 1
            and not glyph_ids & attached_ids
            and glyph_ids
            == {
                id(char)
                for char in formulas[0].pdf_character
                if (char.char_unicode or "").strip()
            }
            and not any(
                not (char.char_unicode or "").strip()
                and char.box.x2 - char.box.x > char.pdf_style.font_size
                for char in formulas[0].pdf_character
            )
        ):
            # A standalone native object already owns offsets such as a citation's
            # superscript baseline; do not reset its geometry while protecting it.
            formula = formulas[0]
        compositions.append(bb["PdfParagraphComposition"](pdf_formula=formula))
    para.pdf_paragraph_composition = compositions
    # Reuse exact offsets after regrouping, including NFKC-expanded glyph spellings.
    mapped = {id(char): (start, end) for _, start, end, char in chars}
    # Formula-only paragraphs are omitted from translation inputs. Their links
    # retain original PDF rectangles rather than becoming text-alignment links.
    items = extract_inline_annotations(
        para, links if cleaned.strip() else [], offsets=mapped
    )

    def offset(position: int) -> int:
        return position - sum(
            max(0, min(position, end) - start) for start, end in regions
        )

    boundaries = tuple(offset(position) for position in range(len(source) + 1))
    original_spans = {
        item["id"]: (item["source_start"], item["source_end"]) for item in items
    }
    result = []
    for item in items:
        start, end = item["source_start"], item["source_end"]
        item["source_start"], item["source_end"] = boundaries[start], boundaries[end]
        if item["kind"] == "formula":
            item.update(
                mode="point",
                protected=True,
                # Reading-order text is context only, never a glyph reconstruction.
                object_source=source[start:end],
            )
        elif boundaries[start] == boundaries[end]:
            if item["kind"] == "link":
                for obj in items:
                    left, right = original_spans[obj["id"]]
                    if obj["kind"] == "formula" and start < right and left < end:
                        obj.setdefault("link_ids", []).append(item["link_id"])
            continue
        result.append(item)
    return cleaned, result, boundaries
