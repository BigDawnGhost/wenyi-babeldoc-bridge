"""Recognize repeated unknown list markers without guessing their Unicode spelling."""

from __future__ import annotations

import math
import re
from statistics import median
from typing import Any

from wenyi_babeldoc_bridge.annotations import _characters
from wenyi_babeldoc_bridge.schema import row_range_errors

_CID = re.compile(r"\(cid:(\d+)\)")


def _size(char: Any) -> float:
    return getattr(getattr(char, "pdf_style", None), "font_size", None) or 0


def _ink(char: Any) -> bool:
    if getattr(char, "vertical", False):
        return False
    if getattr(char, "visual_roundtrip_text_render_mode", None) in (3, 7):
        return False
    box = getattr(getattr(char, "visual_bbox", None), "box", None) or char.box
    return box.x < box.x2 and box.y < box.y2


def _unknown(char: Any) -> bool:
    match = _CID.fullmatch(char.char_unicode or "")
    return match is not None and getattr(char, "pdf_character_id", None) == int(
        match[1]
    )


def _prose(chars: list[Any]) -> bool:
    # Count glyphs, not letters in expanded spellings of ligatures/math radicals.
    return sum((char.char_unicode or "").isalpha() for char in chars) >= 12


def capture_list_rows(
    para: Any, offsets: dict[int, tuple[int, int]]
) -> tuple[list[dict[str, Any]], tuple[Any, ...]]:
    """Require repeated left prefixes, aligned prose and multiple hanging continuations.

    Only the native parser's explicit CID fallback is unknown-character evidence.
    A real tab/space is never reinterpreted as a bullet. Work in relative font units
    and preserve every glyph, source offset and native composition unchanged.
    """
    if getattr(para, "vertical", False):
        return [], ()
    chars = [
        char
        for comp in para.pdf_paragraph_composition or []
        for char in _characters(comp)
        if (char.char_unicode or "").strip()
    ]
    sizes = [
        _size(char)
        for char in chars
        if (char.char_unicode or "").isalpha() and _size(char) > 0
    ]
    if not sizes or any(not math.isfinite(size) for size in sizes):
        return [], ()
    size = median(sizes)
    # Reconstruct body baselines: tall inline formulas can bridge two of the
    # native paragraph finder's visual lines. Small scripts do not start rows.
    lines: list[list[Any]] = []
    for char in sorted(chars, key=lambda char: char.box.y, reverse=True):
        if not 0.85 * size <= _size(char) <= 1.15 * size or not _ink(char):
            continue
        if lines and abs(median(c.box.y for c in lines[-1]) - char.box.y) <= size * 0.2:
            lines[-1].append(char)
        else:
            lines.append([char])
    prose_lines = [
        sorted(line, key=lambda char: char.box.x) for line in lines if _prose(line)
    ]
    candidates = []
    for line in prose_lines:
        marker, body = line[0], line[1:]
        if not _unknown(marker) or not _prose(body):
            continue
        gap = body[0].box.x - marker.box.x2
        if (
            size * 0.1 <= marker.box.x2 - marker.box.x <= size * 0.9
            and size * 0.2 <= gap <= size * 1.5
            and all(
                getattr(c, "xobj_id", None) == getattr(marker, "xobj_id", None)
                for c in line
            )
        ):
            candidates.append((marker, body[0].box.x, line))
    if len(candidates) < 3:
        return [], ()
    first, body_x, _ = candidates[0]
    identity = (
        first.pdf_style.font_id,
        first.pdf_character_id,
        getattr(first, "xobj_id", None),
    )
    if any(
        (char.pdf_style.font_id, char.pdf_character_id, getattr(char, "xobj_id", None))
        != identity
        or abs(char.box.x - first.box.x) > size * 0.15
        or abs(x - body_x) > size * 0.15
        for char, x, _ in candidates
    ):
        return [], ()
    markers = tuple(char for char, _, _ in candidates)
    if any(
        not size * 1.5 <= left.box.y - right.box.y <= size * 8
        for left, right in zip(markers, markers[1:])
    ):
        return [], ()
    marker_ids = {id(char) for char in markers}
    continuations = set()
    for line in prose_lines:
        if id(line[0]) in marker_ids:
            continue
        if abs(line[0].box.x - body_x) > size * 0.15:
            return [], ()
        preceding = [
            index
            for index, marker in enumerate(markers)
            if marker.box.y > line[0].box.y
        ]
        if not preceding:
            return [], ()
        continuations.add(preceding[-1])
    if len(continuations) < 2:
        return [], ()
    if any(id(char) not in offsets for char in chars):
        return [], ()
    # Painting order need not be left-to-right: an original marker may follow
    # the body glyphs in its native line. Keep source order but include that
    # entire first line, not just text after the marker's serialized position.
    starts = [min(offsets[id(char)][0] for char in line) for _, _, line in candidates]
    if starts != sorted(set(starts)):
        return [], ()
    source = para.unicode or ""
    rows = []
    for start, end in zip(starts, starts[1:] + [len(source)]):
        end = len(source[:end].rstrip())
        members = [char for char in chars if start <= offsets[id(char)][0] < end]
        if not members:
            return [], ()
        rows.append(
            {
                "source_start": start,
                "source_end": end,
                "box": [
                    min(char.box.x for char in members),
                    min(char.box.y for char in members),
                    max(char.box.x2 for char in members),
                    max(char.box.y2 for char in members),
                ],
            }
        )
    if row_range_errors(source, rows, "source"):
        return [], ()
    return rows, markers
