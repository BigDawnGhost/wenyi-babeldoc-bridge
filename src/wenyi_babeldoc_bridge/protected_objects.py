"""Project confirmed mathematical glyphs into immutable, contiguous IL objects."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from copy import copy
from typing import Any

from . import _native
from .annotations import (
    _characters,
    _rect,
    _source_characters,
    extract_inline_annotations,
)

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
    seed_boundaries = sorted({position for span in seeds for position in span})
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
            inner = [left]
            if source[left:right] not in _FUNCTIONS:
                inner.extend(
                    seed_boundaries[
                        bisect_right(seed_boundaries, left) : bisect_left(
                            seed_boundaries, right
                        )
                    ]
                )
            inner.append(right)
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
    """Prepare objects atomically so a mapping failure can preserve the original IL."""
    compositions = para.pdf_paragraph_composition
    link_states = [(link, dict(link)) for link in links]
    try:
        return _prepare_protected_annotations(
            para,
            links,
            fonts=fonts,
            bb=bb,
            offsets=offsets,
            attachments=attachments,
            fixed_glyphs=fixed_glyphs,
        )
    except ValueError:
        para.pdf_paragraph_composition = compositions
        for link, original in link_states:
            link.clear()
            link.update(original)
        raise


def _prepare_protected_annotations(
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
    spans_by_composition: dict[int, list[tuple[int, int]]] = {}
    for ci, start, end, _ in chars:
        if ci in formula_indices:
            spans_by_composition.setdefault(ci, []).append((start, end))
    for ci in formula_indices:
        formula = original[ci].pdf_formula
        spans = spans_by_composition.get(ci, [])
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
    if not seeds:
        return (
            source,
            extract_inline_annotations(para, links, offsets=offsets),
            tuple(range(len(source) + 1)),
        )
    tokens = _tokens(source, seeds)

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

    # Keep Python's Unicode database/tokenization and pass only geometry and
    # scalar indices to Rust. The original glyphs stay in this projection.
    cleaned, regions, boundary_list = _native.protect_source(
        source,
        [
            (
                token.span(),
                mathematical(token),
                int(token.group() in "([{") - int(token.group() in ")]}"),
            )
            for token in tokens
        ],
        seeds,
        atomic_spans,
        [
            (
                (start, end),
                _rect(char.box),
                char.pdf_style.font_size,
                getattr(char, "xobj_id", None),
                intact_native.get(id(char)),
                id(char) in fixed_ids,
            )
            for _, start, end, char in chars
        ],
    )
    boundaries = tuple(boundary_list)
    if not regions:
        return (
            source,
            extract_inline_annotations(para, links, offsets=offsets),
            boundaries,
        )
    starts = [left for left, _ in regions]
    members = [[] for _ in regions]
    frozen_ids = set()
    for ci, start, end, char in chars:
        region = bisect_right(starts, start) - 1
        if region >= 0 and end <= regions[region][1]:
            members[region].append((ci, start, char))
            frozen_ids.add(id(char))
    compositions = []
    for comp in original:
        glyphs = _characters(comp)
        remaining = [
            char
            for char in glyphs
            if id(char) not in frozen_ids and (char.char_unicode or "").strip()
        ]
        if not remaining:
            continue
        if len(remaining) == len(glyphs):
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

    for region_members in members:
        glyphs = [char for _, _, char in sorted(region_members, key=lambda row: row[1])]
        formulas = [
            original[ci].pdf_formula
            for ci in sorted({ci for ci, _, _ in region_members})
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
