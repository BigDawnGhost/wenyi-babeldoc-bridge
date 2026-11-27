"""Prepare and apply the bridge's pre-segmentation layout repairs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf

from ..math_attachments import math_accent_checker
from . import toc
from .boxes import repair_layout_boxes
from .geometry import Detection

if TYPE_CHECKING:
    from babeldoc.format.pdf.document_il import il_version_1 as il


def prepare_layout_repair(
    input_file: str | Path, pdf: pymupdf.Document, pages: Sequence[il.Page]
) -> Callable[[il.Page, list[Detection], float], list[Detection]]:
    """Read original evidence once, then repair each model result in order."""
    selected = set()
    for page in pages:
        if page.page_number is None:
            raise ValueError("Parsed page is missing its physical page number")
        selected.add(page.page_number)
    # Preparation may remove annotations or change page coordinates. Use
    # the original for TOC evidence and fail closed on an unknown transform.
    with pymupdf.open(input_file) as original:
        contents = {
            n: entries
            for n, entries in toc.front_toc(original, selected).items()
            if not pdf[n].rotation
            and pdf[n].cropbox == pdf[n].mediabox
            and pdf[n].rect == original[n].rect
            and pdf[n].transformation_matrix == original[n].transformation_matrix
        }

    def repair(page: il.Page, boxes: list[Detection], height: float) -> list[Detection]:
        chars = page.pdf_character
        boxes = repair_layout_boxes(
            boxes, chars, height, is_accent=math_accent_checker(pdf, page)
        )
        if page.page_number in contents:
            boxes = toc.separate_cells(boxes, contents[page.page_number], chars, height)
        return boxes

    return repair
