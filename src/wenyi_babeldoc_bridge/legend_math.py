"""Identify fallback paragraphs that together draw a fixed chart assignment."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .annotations import _characters
from .protected_objects import _variable_letter

_ASSIGNMENT_TAIL = re.compile(r"=[+\-−]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")


def _contains(outer: Any, inner: Any) -> bool:
    return (
        outer.x <= inner.x <= inner.x2 <= outer.x2
        and outer.y <= inner.y <= inner.y2 <= outer.y2
    )


def _is_scripted_assignment(base: Any, sub: Any, equals: Any) -> bool:
    style, sub_style, eq_style = base.pdf_style, sub.pdf_style, equals.pdf_style
    if any(item is None for item in (style, sub_style, eq_style)):
        return False
    size, sub_size, eq_size = style.font_size, sub_style.font_size, eq_style.font_size
    if not (size and sub_size and eq_size and style.font_id):
        return False
    if not (
        style.font_id == sub_style.font_id == eq_style.font_id
        and 0.50 * size <= sub_size <= 0.85 * size
        and abs(eq_size - size) <= 0.05 * size
    ):
        return False
    b, s, e = base.box, sub.box, equals.box
    return (
        0.15 * size <= b.y - s.y <= 0.65 * size
        and abs(b.y - e.y) <= 0.10 * size
        and -0.10 * size <= s.x - b.x2 <= 0.25 * size
        and -0.10 * size <= e.x - s.x2 <= 0.25 * size
    )


def fixed_legend_paragraphs(page: Any) -> set[int]:
    """Keep a split ``variable + subscript + =number`` as original figure glyphs."""
    figures = [
        layout.box
        for layout in getattr(page, "page_layout", None) or []
        if layout.class_name == "figure" and layout.box is not None
    ]
    if not figures:
        return set()

    paragraphs = page.pdf_paragraph or []
    # Original glyph order connects the pieces even when the paragraph finder
    # orders them differently. Keep collisions ambiguous rather than guessing.
    runs: dict[tuple[int, int], list[tuple[int, Any]]] = defaultdict(list)
    for index, para in enumerate(paragraphs):
        if (
            para.layout_label != "fallback_line"
            or para.vertical
            or para.layout_id is None
        ):
            continue
        source = (para.unicode or "").strip()
        if not (
            (len(source) == 1 and (_variable_letter(source) or source.isdecimal()))
            or _ASSIGNMENT_TAIL.fullmatch(source)
        ):
            continue
        chars = [
            char
            for comp in para.pdf_paragraph_composition or []
            for char in _characters(comp)
        ]
        if not chars or "".join(char.char_unicode or "" for char in chars) != source:
            continue
        first = chars[0]
        if first.render_order is not None and not first.vertical:
            runs[first.xobj_id, first.render_order].append((index, first))

    fixed: set[int] = set()
    for (xobj, order), candidates in runs.items():
        subs = runs.get((xobj, order + 1), [])
        tails = runs.get((xobj, order + 2), [])
        if not len(candidates) == len(subs) == len(tails) == 1:
            continue
        (base_index, base), (sub_index, sub), (tail_index, equals) = (
            candidates[0],
            subs[0],
            tails[0],
        )
        base_para, sub_para, tail_para = (
            paragraphs[base_index],
            paragraphs[sub_index],
            paragraphs[tail_index],
        )
        # The fallback finder actually detected a single baseline for the
        # variable and numeric tail, but broke them around a smaller script.
        if (
            len(base_para.unicode.strip()) != 1
            or not _variable_letter(base.char_unicode)
            or len(sub_para.unicode.strip()) != 1
            or equals.char_unicode != "="
            or base_para.layout_id != tail_para.layout_id
            or not _is_scripted_assignment(base, sub, equals)
        ):
            continue
        boxes = (base_para.box, sub_para.box, tail_para.box)
        if any(
            all(box and _contains(figure, box) for box in boxes) for figure in figures
        ):
            fixed.update((base_index, sub_index, tail_index))
    return fixed
