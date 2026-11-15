"""Carry explicit item boundaries without changing native paragraph/formula grouping."""

from __future__ import annotations

import re
from copy import copy
from typing import Any, NamedTuple

from wenyi_babeldoc_bridge.annotations import inject_aligned_translation
from wenyi_babeldoc_bridge.lists import capture_list_rows
from wenyi_babeldoc_bridge.schema import row_range_errors

_ENTRY = re.compile(r"^(\d+(?:\.\d+)*)\s+\S.*?(?:\.\s*){3,}(\d+|[ivxlcdm]+)\s*$", re.I)


class RowStructure(NamedTuple):
    rows: list[dict[str, Any]]
    markers: tuple[Any, ...] = ()


def capture_rows(para: Any, offsets: dict[int, tuple[int, int]]) -> RowStructure:
    """Keep directory entries and confidently identified list items on one protocol."""
    rows = capture_toc_rows(para, offsets)
    if rows:
        return RowStructure(rows)
    rows, markers = capture_list_rows(para, offsets)
    return RowStructure(rows, markers)


def capture_toc_rows(
    para: Any, offsets: dict[int, tuple[int, int]]
) -> list[dict[str, Any]]:
    """Recognize aligned, numbered sibling entries; ordinary wrapping stays soft."""
    if getattr(para, "vertical", False):
        return []
    source = para.unicode or ""
    rows = []
    numbers = []
    for composition in para.pdf_paragraph_composition or []:
        line = getattr(composition, "pdf_line", None)
        if line is None or line.box is None:
            return []
        spans = [
            offsets[id(char)]
            for char in line.pdf_character or []
            if id(char) in offsets
        ]
        if not spans:
            return []
        start = min(start for start, _ in spans)
        end = max(end for _, end in spans)
        match = _ENTRY.fullmatch(source[start:end])
        if match is None:
            return []
        numbers.append(tuple(int(part) for part in match[1].split(".")))
        box = line.box
        rows.append(
            {
                "source_start": start,
                "source_end": end,
                "box": [float(box.x), float(box.y), float(box.x2), float(box.y2)],
            }
        )
    if len(rows) < 2 or row_range_errors(source, rows, "source"):
        return []
    if any(number[:-1] != numbers[0][:-1] for number in numbers):
        return []
    if any(left[-1] >= right[-1] for left, right in zip(numbers, numbers[1:])):
        return []
    tolerance = float(
        getattr(getattr(para, "pdf_style", None), "font_size", None) or 10
    )
    for coordinate in (0, 2):
        positions = [row["box"][coordinate] for row in rows]
        if max(positions) - min(positions) > tolerance:
            return []
    return rows


def remap_source_rows(
    source: str,
    rows: list[dict[str, Any]],
    boundaries: tuple[int, ...],
) -> list[dict[str, Any]]:
    """Project row offsets into clean prose without changing row boxes or order."""
    remapped = [
        {
            **row,
            "source_start": boundaries[row["source_start"]],
            "source_end": boundaries[row["source_end"]],
        }
        for row in rows
    ]
    errors = row_range_errors(source, remapped, "source")
    if errors:
        raise ValueError("Cannot preserve structured rows: " + "; ".join(errors))
    return remapped


def partition_row_annotations(
    items: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Split cross-row styles/links, retaining their frozen composition/link IDs."""
    result = []
    for item in items:
        start, end = item["source_start"], item["source_end"]
        parts = []
        for index, row in enumerate(rows):
            left, right = row["source_start"], row["source_end"]
            if start == end and left <= start <= right:
                parts.append((index, start, end))
            elif start < right and left < end:
                parts.append((index, max(start, left), min(end, right)))
        if item["kind"] == "formula" and (
            len(parts) != 1 or parts[0][1:] != (start, end)
        ):
            raise ValueError("A formula crosses structured rows")
        for index, left, right in parts:
            result.append(
                {
                    **item,
                    "id": f"{item['id']}:row:{index}" if len(parts) > 1 else item["id"],
                    "source_start": left,
                    "source_end": right,
                }
            )
    return result


def anchor_row_markers(
    para: Any,
    items: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    markers: tuple[Any, ...],
) -> list[dict[str, Any]]:
    """Place confirmed prefixes at item starts, independent of PDF painting order."""
    result = [dict(item) for item in items]
    for marker, row in zip(markers, rows, strict=True):

        def owns_marker(item: dict[str, Any]) -> bool:
            formula = para.pdf_paragraph_composition[
                item["composition_index"]
            ].pdf_formula
            glyphs = [
                char
                for char in formula.pdf_character
                if (char.char_unicode or "").strip()
            ]
            return len(glyphs) == 1 and glyphs[0] is marker

        candidates = [
            item for item in result if item.get("protected") and owns_marker(item)
        ]
        if len(candidates) != 1:
            raise ValueError("A list marker shares an indivisible native object")
        [item] = candidates
        if not row["source_start"] <= item["source_start"] <= row["source_end"]:
            raise ValueError("A list marker crosses its original item boundary")
        item["source_start"] = item["source_end"] = row["source_start"]
    return result


def validate_target_rows(text: str, rows: Any, *, count: int) -> None:
    """Validate explicit target ranges, never infer semantic breaks from model text."""
    errors = row_range_errors(text, rows, "target")
    if errors or len(rows) != count:
        raise ValueError(
            "Structured row ranges are missing or invalid; update Wenyi and reparse the PDF"
        )


def inject_rows(
    bb: dict[str, Any],
    para: Any,
    unit: Any,
    text: str,
    targets: list[dict[str, int]],
    placements: list[dict[str, Any]],
    skipped: dict[str, str],
) -> tuple[list[Any], list[tuple[Any, list, list, list]]]:
    """Typeset each row in its original box, including rows containing formulas."""
    paragraphs, plans = [], []
    by_id = {row["id"]: row for row in placements}
    for source, target in zip(unit.rows, targets, strict=True):
        start, end = target["target_start"], target["target_end"]
        row_items = [
            item
            for item in unit.annotations
            if source["source_start"] <= item["source_start"]
            and item["source_end"] <= source["source_end"]
        ]
        local = []
        for item in row_items:
            placement = by_id.get(item["id"])
            if placement is None:
                continue
            left, right = placement["target_start"], placement["target_end"]
            if not start <= left <= right <= end:
                skipped[item["id"]] = "cross_row_alignment"
                continue
            local.append(
                {**placement, "target_start": left - start, "target_end": right - start}
            )
        row_para = copy(para)
        row_para.box = copy(para.box)
        row_para.box.x, row_para.box.y, row_para.box.x2, row_para.box.y2 = source["box"]
        row_para.first_line_indent = False
        row_para.optimal_scale = None
        plan = inject_aligned_translation(
            bb, row_para, text[start:end], row_items, local, skipped=skipped
        )
        paragraphs.append(row_para)
        plans.append((row_para, plan, row_items, local))
    return paragraphs, plans


def sequence_row_glyphs(paragraphs: list[Any]) -> None:
    """Keep sibling glyphs contiguous without changing their parent's draw order."""
    sub_order = 1
    for para in paragraphs:
        for composition in para.pdf_paragraph_composition or []:
            char = getattr(composition, "pdf_character", None)
            if char is not None:
                char.sub_render_order = sub_order
                sub_order += 1
