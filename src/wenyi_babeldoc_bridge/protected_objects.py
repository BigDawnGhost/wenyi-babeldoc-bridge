"""Project confirmed mathematical glyphs into immutable, contiguous IL objects."""

from __future__ import annotations

import re
import unicodedata
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


def prepare_protected_annotations(
    para: Any,
    links: list[dict[str, Any]],
    *,
    fonts: list[Any],
    bb: dict[str, Any],
    offsets: dict[int, tuple[int, int]] | None = None,
) -> tuple[str, list[dict[str, Any]], tuple[int, ...]]:
    """Freeze formula seeds and adjacent mathematical tokens using original glyphs.

    Reading-order offsets, captured before native regrouping, determine membership.
    Formula runs can interleave variable styles; neither composition order nor the
    PDF's lossy Unicode spelling determines which glyph gets restored.
    Return clean prose, annotations and the original-to-clean source boundary map.
    """
    source = para.unicode or ""
    chars = _source_characters(para, offsets)
    original = list(para.pdf_paragraph_composition or [])
    names = {font.font_id: font.name or "" for font in fonts}
    formula_indices = {
        i
        for i, comp in enumerate(original)
        if getattr(comp, "pdf_formula", None) is not None
    }
    seeds = [
        (start, end)
        for ci, start, end, char in chars
        if ci in formula_indices
        or _MATH_FONT.search(names.get(char.pdf_style.font_id, ""))
        or any(
            unicodedata.category(c) == "Sm"
            or "MATHEMATICAL" in unicodedata.name(c, "")
            or "\u2070" <= c <= "\u209f"
            for c in char.char_unicode or ""
        )
    ]
    # A native formula can be discontinuous in source order. Protect its entire
    # interval, including interleaved variable glyphs, as a single object.
    for ci in formula_indices:
        spans = [(start, end) for index, start, end, _ in chars if index == ci]
        if spans:
            seeds.append((min(a for a, _ in spans), max(b for _, b in spans)))
    tokens = _tokens(source, seeds)
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
            while 0 <= j < len(tokens) and mathematical(tokens[j]):
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
    for token, chosen in zip(tokens, selected):
        if not chosen:
            continue
        start, end = token.span()
        if regions and not source[regions[-1][1] : start].strip():
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
        boxes = [char.box for char in glyphs] + [
            value.box for value in formulas if getattr(value, "box", None) is not None
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
        if len(formulas) == 1 and {id(char) for char in glyphs} == {
            id(char)
            for char in formulas[0].pdf_character
            if (char.char_unicode or "").strip()
        }:
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
