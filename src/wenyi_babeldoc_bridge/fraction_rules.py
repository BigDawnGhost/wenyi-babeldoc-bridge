"""Claim original inline image-mask rules between stacked mathematical glyphs."""

from __future__ import annotations

import base64
import json
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from .annotations import _rect, _visible_rect

_MASK_KEY_ALIASES = {
    "IM": "ImageMask",
    "W": "Width",
    "H": "Height",
    "BPC": "BitsPerComponent",
    "D": "Decode",
    "I": "Interpolate",
    "L": "Length",
}
_PDF_WHITESPACE = b"\x00\t\n\f\r "
# This heuristic only needs small stencils; bound the base64 input before decoding.
_MAX_MASK_BASE64_LENGTH = 8192


@dataclass(frozen=True)
class InlineFraction:
    span: tuple[int, int]
    gap: tuple[int, int]
    rule: Any


def _is_solid_inline_mask(form: Any) -> bool:
    """Recognize a solid raw stencil, leaving other images in the page stream."""
    image = form.pdf_form_subtype and form.pdf_form_subtype.pdf_inline_form
    if image is None or not isinstance(image.image_parameters, str):
        return False
    encoded = image.form_data
    if not isinstance(encoded, str) or len(encoded) > _MAX_MASK_BASE64_LENGTH:
        return False
    try:
        params = json.loads(image.image_parameters)
    except ValueError:
        return False
    if not isinstance(params, dict):
        return False
    fields = {}
    for key, value in params.items():
        key = key.removeprefix("/")
        key = _MASK_KEY_ALIASES.get(key, key)
        # In particular, do not treat filtered data or ambiguous aliases as samples.
        if key not in _MASK_KEY_ALIASES.values() or key in fields:
            return False
        fields[key] = value

    width, height = fields.get("Width"), fields.get("Height")
    bpc = fields.get("BitsPerComponent", 1)
    decode = fields.get("Decode", [0, 1])
    if (
        fields.get("ImageMask") is not True
        or type(width) is not int
        or type(height) is not int
        or width <= 0
        or height <= 0
        or type(bpc) is not int
        or bpc != 1
        or type(fields.get("Interpolate", False)) is not bool
        or not isinstance(decode, list)
        or not all(type(n) in (int, float) for n in decode)
        or decode not in ([0, 1], [1, 0])
    ):
        return False

    full_bytes, tail_bits = divmod(width, 8)
    stride = (width + 7) // 8
    size = stride * height
    length = fields.get("Length", size)
    if type(length) is not int or length != size:
        return False
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        return False
    # Without /Length the native projection retains the separator before EI.
    # Split at the expected raster size: a whitespace byte can be a valid sample.
    if len(data) < size or (
        len(data) > size and ("Length" in fields or data[size:].strip(_PDF_WHITESPACE))
    ):
        return False

    # The stencil paints decoded zero. Only inspect real samples: rows are
    # byte-aligned, with the leftmost sample in the high bit.
    paint = 0xFF if decode == [1, 0] else 0x00
    solid = bytes([paint]) * full_bytes
    tail_mask = (0xFF << (8 - tail_bits)) & 0xFF
    for start in range(0, size, stride):
        if data[start : start + full_bytes] != solid or (
            tail_bits and (data[start + full_bytes] ^ paint) & tail_mask
        ):
            return False
    return True


def _fits_rule(rule: Any, numerator: Any, denominator: Any, body_size: float) -> bool:
    size = max(numerator.pdf_style.font_size, denominator.pdf_style.font_size)
    if not 0 < size <= body_size * 0.85:
        return False
    x, y, x2, y2 = _rect(rule.box)
    width, height = x2 - x, y2 - y
    if height > size * 0.15:
        return False
    for glyph, above in ((numerator, True), (denominator, False)):
        if glyph.vertical or not size * 0.85 <= glyph.pdf_style.font_size <= size:
            return False
        a, b, c, d = _visible_rect(glyph)
        overlap = min(c, x2) - max(a, x)
        gap = b - y2 if above else y - d
        if overlap < max(c - a, width) * 0.65 or not 0 <= gap <= size * 0.5:
            return False
    return True


class FractionRules:
    """Track page forms that can move into a frozen fraction, at most once."""

    def __init__(self, forms: list[Any]):
        self._rules: dict[tuple[int, int], Any] = {}
        ambiguous = set()
        self._claimed: set[int] = set()
        for form in forms:
            if form.render_order is None or form.box is None:
                continue
            x, y, x2, y2 = _rect(form.box)
            if not 0 < y2 - y <= (x2 - x) * 0.25 or not _is_solid_inline_mask(form):
                continue
            key = (form.xobj_id, form.render_order)
            if key in self._rules:
                ambiguous.add(key)
            self._rules[key] = form
        for key in ambiguous:
            del self._rules[key]

    def match(
        self,
        source: str,
        chars: list[tuple[int, int, int, Any]],
        body_size: float,
    ) -> list[InlineFraction]:
        if not self._rules:
            return []
        candidates = []
        for (_, start, mid, top), (_, mid2, end, bottom) in pairwise(
            sorted(chars, key=lambda row: row[1])
        ):
            order = getattr(top, "render_order", None)
            if (
                order is None
                or getattr(bottom, "render_order", None) != order + 2
                or bottom.xobj_id != top.xobj_id
            ):
                continue
            rule = self._rules.get((top.xobj_id, order + 1))
            if rule is None or id(rule) in self._claimed:
                continue
            if mid > mid2 or source[mid:mid2].strip():
                continue
            if all(
                len(text) == 1 and text.isalnum()
                for text in (source[start:mid], source[mid2:end])
            ) and _fits_rule(rule, top, bottom, body_size):
                candidates.append(InlineFraction((start, end), (mid, mid2), rule))
        # A glyph or mask with two possible roles is not a confirmed fraction.
        uses = Counter(start for f in candidates for start in (f.span[0], f.gap[1]))
        forms = Counter(id(f.rule) for f in candidates)
        return [
            f
            for f in candidates
            if uses[f.span[0]] == uses[f.gap[1]] == forms[id(f.rule)] == 1
        ]

    def claim(self, fractions: list[InlineFraction]) -> None:
        self._claimed.update(id(f.rule) for f in fractions)

    def remaining(self, forms: list[Any]) -> list[Any]:
        return [form for form in forms if id(form) not in self._claimed]
