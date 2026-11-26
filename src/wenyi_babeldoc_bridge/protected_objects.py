"""Project confirmed mathematical glyphs into immutable, contiguous IL objects."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from copy import copy
from itertools import pairwise
from typing import Any

from . import _native
from .annotations import (
    _characters,
    _rect,
    _source_characters,
    extract_inline_annotations,
)
from .fraction_rules import FractionRules, InlineFraction

# Font names are evidence of mathematical glyphs, not a Unicode correction table.
# Missing ToUnicode or italics alone must never turn prose into an opaque object.
_MATH_FONT = re.compile(
    r"AdvPSM[PI]|AdvSPSMI|AdvP4C4E|AdvPSMSAM|"
    r"Math|Symbol|CMSY|CMEX|CMMI|MSAM|MSBM",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"\(cid:\d+\)|[^\W\d_]+|\d+(?:\.\d+)?|[^\w\s]|\w")
_FUNCTIONS = {"sin", "cos", "tan", "sinh", "cosh", "log", "ln", "exp", "Re", "Im"}
_SET_NUMBER = re.compile(r"[+−-]?\s*\d+(?:\.\d+)?")


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


def _scripted_variable_runs(
    tokens: list[re.Match[str]],
    chars: list[tuple[int, int, int, Any]],
    seeds: list[tuple[int, int]],
    fixed_ids: set[int],
) -> set[int]:
    """Recognize unseeded letter runs between a math coefficient and exponent."""
    candidates = [
        (left, word, right)
        for left, word, right in zip(tokens, tokens[1:], tokens[2:])
        if left.end() == word.start()
        and word.end() == right.start()
        and left.group()[0].isdecimal()
        and right.group().isdecimal()
        and len(word.group()) > 1
        and all(_variable_letter(c) for c in word.group())
    ]
    if not candidates:
        return set()
    by_start = {start: (end, char) for _, start, end, char in chars}
    by_end = {end: (start, char) for _, start, end, char in chars}
    seeded = set(seeds)
    result = set()
    for left, word, right in candidates:
        coefficient = by_end.get(left.end())
        exponent = by_start.get(right.start())
        if coefficient is None or exponent is None:
            continue
        a, b = coefficient[1], exponent[1]
        if (coefficient[0], left.end()) not in seeded or (
            right.start(),
            exponent[0],
        ) not in seeded:
            continue
        letters = []
        for pos in range(*word.span()):
            glyph = by_start.get(pos)
            if glyph is None or glyph[0] != pos + 1:
                break
            letters.append(glyph[1])
        else:
            size = letters[-1].pdf_style.font_size
            if not size or not (
                0.9 * size <= a.pdf_style.font_size <= 1.1 * size
                and abs(a.box.y - letters[-1].box.y) <= 0.1 * size
                and 0.45 * size <= b.pdf_style.font_size <= 0.8 * size
                and 0.15 * size <= b.box.y - letters[-1].box.y <= 0.8 * size
            ):
                continue
            if any(
                char.pdf_style.font_id != letters[-1].pdf_style.font_id
                or abs(char.pdf_style.font_size - size) > 0.05 * size
                or abs(char.box.y - letters[-1].box.y) > 0.1 * size
                for char in letters
            ):
                continue
            run = [a, *letters, b]
            if any(
                getattr(char, "vertical", False)
                or getattr(char, "xobj_id", None) != getattr(a, "xobj_id", None)
                or id(char) in fixed_ids
                for char in run
            ):
                continue
            # Tighter than normal formula expansion: words separated by ordinary
            # spacing are not a product just because they sit between math tokens.
            if all(
                -0.15 * size <= nxt.box.x - prev.box.x2 <= 0.2 * size
                for prev, nxt in pairwise(run)
            ):
                result.add(word.start())
    return result


def _index_commas(
    tokens: list[re.Match[str]],
    chars: list[tuple[int, int, int, Any]],
    body_size: float,
) -> set[int]:
    """Connect a reduced-size comma only between script glyphs, not prose."""
    commas = [i for i in range(1, len(tokens) - 1) if tokens[i].group() == ","]
    if not commas:
        return set()
    by_start = {start: char for _, start, _, char in chars}
    by_end = {end: char for _, _, end, char in chars}
    result = set()
    for i in commas:
        left, comma, right = tokens[i - 1 : i + 2]
        if not all(
            text.isdecimal() or (len(text) == 1 and _variable_letter(text))
            for text in (left.group(), right.group())
        ):
            continue
        mark = by_start.get(comma.start())
        a, b = by_end.get(left.end()), by_start.get(right.start())
        if mark is None or a is None or b is None:
            continue
        size = mark.pdf_style.font_size
        if not 0 < size <= body_size * 0.8:
            continue
        if (
            not a.box.x <= mark.box.x <= b.box.x
            or max(mark.box.x - a.box.x2, b.box.x - mark.box.x2) > size * 0.35
        ):
            continue
        if all(
            getattr(char, "xobj_id", None) == getattr(mark, "xobj_id", None)
            and 0 < char.pdf_style.font_size <= size * 1.05
            and abs(char.box.y - mark.box.y) <= size * 0.3
            for char in (a, b)
        ) and any(
            abs(char.pdf_style.font_size - size) <= size * 0.05
            and abs(char.box.y - mark.box.y) <= size * 0.1
            for char in (a, b)
        ):
            # One neighbor may itself have a nested subscript, e.g. Y₀,Y₁.
            result.add(comma.start())
    return result


def _set_literal_tokens(
    source: str,
    tokens: list[re.Match[str]],
    chars: list[tuple[int, int, int, Any]],
    seeds: list[tuple[int, int]],
    fixed_ids: set[int],
) -> set[int]:
    """Allow separators in a closed, same-line set of scalar values."""
    if not any(token.group() == "{" for token in tokens):
        return set()
    seeded = set(seeds)
    ordered = sorted(chars, key=lambda row: row[1])
    starts = [start for _, start, _, _ in ordered]
    result = set()
    opening = None
    for i, close in enumerate(tokens):
        if close.group() == "{":
            opening = i
            continue
        if close.group() != "}" or opening is None:
            continue
        begin, opening = opening, None
        brace = tokens[begin]
        values = [v.strip() for v in source[brace.end() : close.start()].split(",")]
        if len(values) < 2 or not all(
            _SET_NUMBER.fullmatch(v) or (len(v) == 1 and _variable_letter(v))
            for v in values
        ):
            continue
        # Braces alone are punctuation. Require a set relation or math evidence
        # on the delimiters, not merely some other math elsewhere in the paragraph.
        first = begin
        if brace.span() not in seeded or close.span() not in seeded:
            if not begin or tokens[begin - 1].group() not in {"∈", "∉", "="}:
                continue
            first -= 1
        left = bisect_left(starts, tokens[first].start())
        right = bisect_left(starts, close.end())
        glyphs = [char for _, _, _, char in ordered[left:right]]
        if not glyphs:
            continue
        anchor = glyphs[0]
        context = getattr(anchor, "xobj_id", None)
        size = anchor.pdf_style.font_size
        if size <= 0 or any(
            getattr(char, "vertical", False)
            or getattr(char, "xobj_id", None) != context
            or id(char) in fixed_ids
            or abs(char.box.y - anchor.box.y)
            > min(size, char.pdf_style.font_size) * 0.25
            for char in glyphs
        ):
            continue
        if all(
            a.box.x <= b.box.x
            and b.box.x - a.box.x2
            <= min(a.pdf_style.font_size, b.pdf_style.font_size) * 0.5
            for a, b in pairwise(glyphs)
        ):
            # Also admit variables like "a" and "I" that otherwise look like prose.
            result.update(token.start() for token in tokens[begin : i + 1])
    return result


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
    size = getattr(para.pdf_style, "font_size", None)
    if not size:
        return
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
    fraction_rules: FractionRules | None = None,
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
            fraction_rules=fraction_rules,
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
    fraction_rules: FractionRules | None = None,
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
    # The layout fallback can produce paragraphs with glyph styles but no body
    # style. Only run heuristics that compare to a body size when it is known.
    body_size = getattr(para.pdf_style, "font_size", None)
    fractions = (
        fraction_rules.match(source, chars, body_size)
        if fraction_rules is not None
        and body_size
        and not getattr(para, "vertical", False)
        else []
    )
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
    for fraction in fractions:
        seeds.append(fraction.span)
        atomic_spans.append(fraction.span)
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
    index_commas = _index_commas(tokens, chars, body_size) if body_size else set()
    set_tokens = _set_literal_tokens(source, tokens, chars, seeds, fixed_ids)
    variable_runs = _scripted_variable_runs(tokens, chars, seeds, fixed_ids)

    def mathematical(token: re.Match[str]) -> bool:
        if token.start() in set_tokens:
            return True
        text = token.group()
        if text == ",":
            return token.start() in index_commas
        if (
            text in _FUNCTIONS
            or text.startswith("(cid:")
            or text[0].isdigit()
            or token.start() in variable_runs
        ):
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
    fraction_members: list[list[InlineFraction]] = [[] for _ in regions]
    for fraction in fractions:
        left, right = fraction.span
        region = bisect_right(starts, left) - 1
        if region < 0 or right > regions[region][1]:
            raise ValueError("Cannot keep the original inline fraction together")
        fraction_members[region].append(fraction)
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

    for region_members, inline_fractions in zip(members, fraction_members):
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
        curves = [
            curve
            for value in formulas
            for curve in (getattr(value, "pdf_curve", None) or [])
        ]
        forms = [
            form
            for value in formulas
            for form in (getattr(value, "pdf_form", None) or [])
        ] + [fraction.rule for fraction in inline_fractions]
        boxes = [char.box for char in glyphs] + [
            item.box
            for item in (*curves, *forms)
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
            pdf_curve=curves,
            pdf_form=forms,
            x_offset=0,
            y_offset=0,
            x_advance=box.x2 - box.x,
            is_corner_mark=False,
        )
        if (
            len(formulas) == 1
            and not inline_fractions
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
            # Spell a confirmed stack with "/" for model context only. The
            # rendered rule is the original form, not a replacement slash.
            reference = []
            cursor = start
            for fraction in fractions:
                if start <= fraction.span[0] and fraction.span[1] <= end:
                    left, right = fraction.gap
                    reference.extend((source[cursor:left], "/"))
                    cursor = right
            reference.append(source[cursor:end])
            item.update(
                mode="point",
                protected=True,
                object_source="".join(reference),
            )
        elif boundaries[start] == boundaries[end]:
            if item["kind"] == "link":
                for obj in items:
                    left, right = original_spans[obj["id"]]
                    if obj["kind"] == "formula" and start < right and left < end:
                        obj.setdefault("link_ids", []).append(item["link_id"])
            continue
        result.append(item)
    if fraction_rules is not None:
        fraction_rules.claim(fractions)
    return cleaned, result, boundaries
