"""Repair bounded model-box errors before native glyph assignment."""

from __future__ import annotations

import unicodedata
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator, Sequence
from math import ceil, floor
from typing import Any

from .annotations import _visible_rect

Detection = tuple[tuple[tuple[int, float], ...], float, str]
Rect = tuple[float, float, float, float]


def _bounds(box: Detection) -> Rect:
    (_, x), (_, y), (_, x2), (_, y2) = box[0]
    return x, y, x2, y2


def _merge_captions(boxes: Sequence[Detection]) -> list[Detection]:
    boxes = list(boxes)
    bounds = [_bounds(box) for box in boxes]
    captions = [i for i, (_, _, role) in enumerate(boxes) if role == "figure_caption"]
    areas = {
        i: (bounds[i][2] - bounds[i][0]) * (bounds[i][3] - bounds[i][1])
        for i in captions
    }
    kept: list[int] = []
    duplicates: set[int] = set()
    for i in sorted(captions, key=lambda i: (-areas[i], -boxes[i][1], i)):
        x, y, x2, y2 = bounds[i]
        for j in kept:
            a, b, c, d = bounds[j]
            overlap = max(min(c, x2) - max(a, x), 0) * max(min(d, y2) - max(b, y), 0)
            if not 0 < areas[j] * 0.85 <= overlap or overlap < areas[i] * 0.98:
                continue
            # Keep the full extent; detections of the same caption need not have
            # exactly equal top and bottom edges.
            outer, confidence, role = boxes[j]
            inner = boxes[i][0]
            coords = tuple(
                fn(left, right, key=lambda axis: axis[1])
                for fn, left, right in zip((min, min, max, max), outer, inner)
            )
            boxes[j] = (coords, confidence, role)
            bounds[j] = _bounds(boxes[j])
            duplicates.add(i)
            break
        else:
            kept.append(i)
    return [box for i, box in enumerate(boxes) if i not in duplicates]


def _connected(previous: Any, char: Any, size: float) -> bool:
    return (
        char.xobj_id == previous.xobj_id
        and char.render_order == previous.render_order + 1
        and char.pdf_style.font_id == previous.pdf_style.font_id
        and abs(char.pdf_style.font_size - previous.pdf_style.font_size) <= size * 0.05
        and abs(char.box.y - previous.box.y) <= size * 0.15
        and -size * 0.15 <= char.box.x - previous.box.x2 <= size * 0.16
    )


def _latin_letter(text: str) -> bool:
    return len(text) == 1 and text.isalpha() and "LATIN" in unicodedata.name(text, "")


def _model_rect(char: Any, page_height: int) -> Rect:
    x, y, x2, y2 = _visible_rect(char)
    return x, page_height - y2, x2, page_height - y


def _word_bounds(chars: list[Any], page_height: int) -> list[tuple[Rect, float]]:
    """Index tightly spaced Latin words in model coordinates, not OCR text."""
    words: list[tuple[Rect, float]] = []
    previous = None
    bounds: Rect = (0, 0, 0, 0)
    letters = 0
    word_size = 0.0
    for char in chars:
        text = char.char_unicode or ""
        size = getattr(char.pdf_style, "font_size", None)
        if not size or char.vertical or char.render_order is None:
            previous = None
            continue
        latin = _latin_letter(text)
        connected = previous is not None and _connected(previous, char, size)
        # An immediately adjacent sentence mark can be the only clipped glyph.
        tail = text in {".", ",", ";", ":", "!", "?"} and connected
        if not latin and not tail:
            previous = None
            continue
        x, top, x2, bottom = _model_rect(char, page_height)
        if connected:
            left, high, right, low = bounds
            bounds = min(x, left), min(top, high), max(x2, right), max(bottom, low)
            letters += latin
        else:
            if letters >= 2:
                words.append((bounds, word_size))
            bounds = x, top, x2, bottom
            letters = 1
            word_size = size
        previous = char if latin else None
    if letters >= 2:
        words.append((bounds, word_size))
    words.sort(key=lambda word: word[0][1])
    return words


def _padded_rect(box: Detection) -> Rect:
    # Native conversion adds a point of padding and truncates in PDF coordinates.
    x, top, x2, bottom = _bounds(box)
    return floor(x - 1), ceil(top - 1), floor(x2 + 1), ceil(bottom + 1)


def _overlaps(a: Rect, b: Rect) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _contains(outer: Rect, inner: Rect) -> bool:
    return (
        outer[0] <= inner[0] <= inner[2] <= outer[2]
        and outer[1] <= inner[1] <= inner[3] <= outer[3]
    )


def _raised_inline_accents(
    chars: list[Any], page_height: int
) -> Iterator[tuple[Any, Rect, Rect, Rect, float]]:
    for index in range(2, len(chars) - 1):
        previous, left, mark, base = chars[index - 2 : index + 2]
        if (
            not _latin_letter(left.char_unicode or "")
            or not _latin_letter(base.char_unicode or "")
            or not _latin_letter(previous.char_unicode or "")
            or not (mark.char_unicode or "").strip()
            or previous.render_order is None
            or left.render_order is None
            or mark.render_order != left.render_order + 1
            or base.render_order != left.render_order + 2
            or not (left.xobj_id == mark.xobj_id == base.xobj_id)
            or previous.vertical
            or left.vertical
            or mark.vertical
            or base.vertical
        ):
            continue
        size = left.pdf_style.font_size
        base_size = base.pdf_style.font_size
        if (
            not size
            or not base_size
            or not _connected(previous, left, size)
            or abs(base_size - size) > size * 0.1
            or abs(base.box.y - left.box.y) > size * 0.15
            or not -size * 0.1 <= base.box.x - left.box.x2 <= size * 0.65
        ):
            continue
        m = _model_rect(mark, page_height)
        b = _model_rect(base, page_height)
        if (
            0 < m[3] - m[1] <= size * 0.25
            and 0 <= b[1] - m[3] <= size * 0.4
            and b[0] - size * 0.15 <= m[0] < m[2] <= b[2] + size * 0.15
            and abs(m[0] + m[2] - b[0] - b[2]) <= size * 0.4
        ):
            yield mark, m, _model_rect(left, page_height), b, size


def _trim_accent_capture(
    boxes: list[Detection],
    chars: list[Any],
    page_height: int,
    is_accent: Callable[[Any], bool],
) -> None:
    """Keep an inline accent from starting a spurious paragraph in an upper box."""
    padded = [_padded_rect(box) for box in boxes]
    ink = None
    for mark, mark_box, left, base, size in _raised_inline_accents(chars, page_height):
        # Both neighbors are on the same line and unambiguously assigned to one
        # prose box. The accent is already partly inside this box's leading edge.
        owners = [
            i
            for i, rect in enumerate(padded)
            if _overlaps(rect, left) or _overlaps(rect, base)
        ]
        if len(owners) != 1:
            continue
        target = owners[0]
        body = padded[target]
        if (
            boxes[target][2] != "plain text"
            or not (_contains(body, left) and _contains(body, base))
            or not mark_box[1] < body[1] < mark_box[3]
            or not _overlaps(body, mark_box)
        ):
            continue
        competitors = [
            i
            for i, rect in enumerate(padded)
            if i != target and _overlaps(rect, mark_box)
        ]
        if not competitors:
            continue
        cutoff = floor(mark_box[1])
        if any(
            boxes[i][2] != "plain text"
            or _bounds(boxes[i])[1] >= cutoff - 1
            or padded[i][3] - cutoff > size * 0.5
            for i in competitors
        ) or not is_accent(mark):
            continue
        # Trim only blank fringe and this one mark. In particular, never clip
        # a descender in the preceding paragraph to join the lower one.
        if ink is None:
            ink = [(char, _model_rect(char, page_height)) for char in chars]
        fringes = [(padded[i][0], cutoff, *padded[i][2:]) for i in competitors]
        if any(
            char is not mark and _overlaps(rect, fringe)
            for fringe in fringes
            for char, rect in ink
        ):
            continue
        for i in competitors:
            coords, confidence, role = boxes[i]
            boxes[i] = ((*coords[:3], (64, cutoff - 1)), confidence, role)
            padded[i] = _padded_rect(boxes[i])


def repair_layout_boxes(
    boxes: Sequence[Detection],
    chars: list[Any],
    page_height: float,
    *,
    is_accent: Callable[[Any], bool] | None = None,
) -> list[Detection]:
    """Correct bounded, evidence-backed model errors without changing glyphs."""
    boxes = _merge_captions(boxes)
    # Use pre-repair geometry so an earlier expansion cannot establish ownership.
    text_rects = [
        (i, _padded_rect(box)) for i, box in enumerate(boxes) if box[2] == "plain text"
    ]
    words = _word_bounds(chars, ceil(page_height)) if text_rects else []
    tops = [rect[1] for rect, _ in words]
    repaired = []
    for i, box in enumerate(boxes):
        coords, confidence, role = box
        x0, top, x1, bottom = _bounds(box)
        left, right = x0, x1
        if role == "plain text":
            for word, size in words[
                bisect_left(tops, top - 1) : bisect_right(tops, bottom)
            ]:
                x, _, x2, y2 = word
                # Only extend the horizontal edge of a single line, not a whole
                # paragraph that could absorb another column or neighboring text.
                if y2 > bottom + 1 or bottom - top > size * 1.65:
                    continue
                clips_left = x < x0 < x2 and x0 - x <= size * 3
                clips_right = x < x1 < x2 and x2 - x1 <= size * 3
                if not (clips_left or clips_right):
                    continue
                # Another prose box already covers this word at glyph assignment.
                # Expanding would create a tie that could steal it from that box.
                if any(j != i and _contains(rect, word) for j, rect in text_rects):
                    continue
                if clips_left:
                    left = min(left, floor(x))
                if clips_right:
                    right = max(right, ceil(x2))
        if left != x0:
            coords = ((64, left), *coords[1:])
        if right != x1:
            coords = (*coords[:2], (64, right), coords[3])
        repaired.append((coords, confidence, role))
    if is_accent is not None and sum(box[2] == "plain text" for box in repaired) > 1:
        _trim_accent_capture(repaired, chars, ceil(page_height), is_accent)
    return repaired
