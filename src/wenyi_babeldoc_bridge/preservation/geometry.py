"""Geometry shared by pre-segmentation layout repairs."""

from __future__ import annotations

from math import ceil, floor
from typing import Any

from ..annotations import _visible_rect

Detection = tuple[tuple[tuple[int, float], ...], float, str]
Rect = tuple[float, float, float, float]


def detection_bounds(box: Detection) -> Rect:
    (_, x), (_, y), (_, x2), (_, y2) = box[0]
    return x, y, x2, y2


def model_rect(char: Any, page_height: int) -> Rect:
    x, y, x2, y2 = _visible_rect(char)
    return x, page_height - y2, x2, page_height - y


def padded_rect(box: Detection) -> Rect:
    # Native conversion adds a point of padding and truncates in PDF coordinates.
    x, top, x2, bottom = detection_bounds(box)
    return floor(x - 1), ceil(top - 1), floor(x2 + 1), ceil(bottom + 1)


def overlaps(a: Rect, b: Rect) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])
