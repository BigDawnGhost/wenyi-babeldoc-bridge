"""Identify printed destination cells in a confirmed front-of-book contents run."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from math import ceil
from statistics import median
from typing import NamedTuple

import pymupdf

from .geometry import Detection, Rect, model_rect, overlaps, padded_rect

_HEADINGS = {"contents", "tableofcontents", "目录", "目錄"}
_FRONT_LIMIT = 32  # Do not search an unbookmarked book for a mid-body contents list.
_INNER_PAGE_LABEL = re.compile(r"\.{3,}\d")
_COLUMN_TOLERANCE = 3.0  # Points at the right edge of the printed number column.


@dataclass(frozen=True)
class ContentsRow:
    title: pymupdf.Rect
    number: pymupdf.Rect
    printed: str


@dataclass(frozen=True)
class _PageRun:
    rows: list[ContentsRow]
    first_destination: int | None
    can_continue: bool


class _Glyph(NamedTuple):
    baseline: float
    box: Rect
    text: str
    size: float


def _visual_lines(textpage):
    # PDFs can paint the section number, title and page label in different
    # blocks, or concatenate them into one span. Join by baseline, not by block.
    chars = []
    for block in textpage.extractRAWDICT()["blocks"]:
        for line in block.get("lines", ()):
            if line["dir"][0] < 0.999 or abs(line["dir"][1]) > 0.01:
                continue
            for span in line["spans"]:
                chars.extend(
                    _Glyph(ch["origin"][1], ch["bbox"], ch["c"], span["size"])
                    for ch in span["chars"]
                    if ch["c"].strip()
                )
    lines = []
    for char in sorted(chars, key=lambda c: c.baseline):
        if not lines or char.baseline - lines[-1][0].baseline > 1:
            lines.append([])
        lines[-1].append(char)
    return [sorted(line, key=lambda c: c.box[0]) for line in lines]


def _extent(chars):
    rect = pymupdf.Rect(chars[0].box)
    for char in chars[1:]:
        rect |= char.box
    return rect


def _entry(line, split, size, links) -> tuple[ContentsRow, int | None] | None:
    """Confirm one title and one page-number column on this baseline."""
    prefix = line[:split]
    text = "".join(c.text for c in prefix)
    # A second leader/label pair (even with no gap before the digits) or an
    # intervening numeric column would turn unrelated cells into one title.
    if _INNER_PAGE_LABEL.search(text) or any(
        c.text.isdecimal() and c.box[0] - prev.box[2] > size * 1.5
        for prev, c in zip(prefix, prefix[1:])
    ):
        return None
    title, number = _extent(prefix), _extent(line[split:])
    title_center = (title.tl + title.br) / 2
    number_center = (number.tl + number.br) / 2
    hits = [
        link
        for link in links
        if link["from"].height <= 2 * number.height
        and (number_center in link["from"] or title_center in link["from"])
    ]
    if hits and any(
        (link["page"], link.get("to")) != (hits[0]["page"], hits[0].get("to"))
        for link in hits[1:]
    ):
        return None
    if not text.endswith("..."):
        on_number = any(number_center in link["from"] for link in hits)
        if not hits or number.x0 - title.x1 < size * (0.3 if on_number else 1):
            return None
    row = ContentsRow(title, number, "".join(c.text for c in line[split:]))
    return row, hits[0]["page"] if hits else None


def _wrapped_title(title, pending, size, previous_title):
    """Include adjacent wrapped lines, not intervening body text or a header."""
    for line in reversed(pending[-2:]):
        box = _extent(line)
        center = (box.tl + box.br) / 2
        if center in title or (previous_title is not None and center in previous_title):
            # A shifted baseline inside an existing line (e.g. a superscript)
            # is not a new text line. Leave its ownership to the native engine.
            continue
        if (
            not any(c.text.isalpha() for c in line)
            or not -size * 0.3 <= title.y0 - box.y1 <= size * 0.5
            or abs(line[0].size - size) > size / 4
            or min(box.x1, title.x1) <= max(box.x0, title.x0)
        ):
            return title if previous_title is None else None
        title = title | box
    return title


def _page_run(page, *, opening: bool) -> _PageRun | None:
    if page.rotation or page.cropbox != page.mediabox or page.rect != page.mediabox:
        return None
    flags = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    textpage = page.get_textpage(flags=flags)
    if opening:
        # Cheap prefilter only. Fragmented text blocks can still form one
        # heading; the visual line below must match it exactly.
        text = "".join(textpage.extractText().casefold().split())
        if not any(heading in text for heading in _HEADINGS):
            return None
    links = [
        link
        for link in page.get_links()
        if link["kind"] in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED)
        and 0 <= link.get("page", -1) < len(page.parent)
    ]
    rows = []
    pending = []
    first_destination = None
    active = not opening
    can_continue = False
    for line in _visual_lines(textpage):
        value = "".join(c.text for c in line).casefold()
        if value in _HEADINGS:
            active = True
            pending.clear()
            continue
        if not active:
            continue
        if value.removeprefix("page").isdecimal() and not (
            0.1 * page.rect.height <= line[0].baseline <= 0.9 * page.rect.height
        ):
            continue  # A margin folio is neither a title continuation nor body text.
        size = median(c.size for c in line)
        split = len(line)
        while split and line[split - 1].text.isdecimal():
            if (
                split < len(line)
                and line[split].box[0] - line[split - 1].box[2] > size / 3
            ):
                break
            split -= 1
        if not 0 < split < len(line) or not any(c.text.isalpha() for c in line[:split]):
            pending.append(line)
            # At most a running header plus two lines of a wrapped title.
            # Do not resume in a similar-looking table after a block of prose.
            if len(pending) > (2 if rows or opening else 3):
                break
            continue
        entry = _entry(line, split, size, links)
        if entry is None:
            break
        row, destination = entry
        title = _wrapped_title(
            row.title, pending, size, rows[-1].title if rows else None
        )
        pending.clear()
        if title is None or (rows and title.y0 - rows[-1].number.y1 > 3 * size):
            break
        rows.append(ContentsRow(title, row.number, row.printed))
        if first_destination is None:
            first_destination = destination
    else:
        # Hitting contrary evidence and reaching the end of the page are
        # different. Only the latter permits another contents page.
        can_continue = True
    if (
        len(rows) < 3
        or max(r.number.x1 for r in rows) - min(r.number.x1 for r in rows)
        > _COLUMN_TOLERANCE
    ):
        return None
    return _PageRun(rows, first_destination, can_continue)


def front_toc(doc, selected: set[int]) -> dict[int, list[ContentsRow]]:
    """Only a heading and continuous positive pages can open a contents region."""
    if not selected or min(selected) >= _FRONT_LIMIT:
        return {}
    try:
        return _front_toc(doc, selected)
    except (
        pymupdf.FileDataError,
        pymupdf.mupdf.FzErrorSyntax,
        pymupdf.mupdf.FzErrorFormat,
    ) as error:
        # An unreadable optional outline or front page must not prevent
        # normal extraction of an otherwise readable selection.
        logging.getLogger(__name__).warning("Skipping front TOC repair: %s", error)
        return {}


def _front_toc(doc, selected: set[int]) -> dict[int, list[ContentsRow]]:
    end = min(len(doc), max(selected) + 1, _FRONT_LIMIT)
    # Outline destinations are 1-based physical pages, NOT printed folios.
    first = next((p for _, _, p in doc.get_toc() if 1 <= p <= len(doc)), None)
    if first is not None:
        end = min(end, first - 1)
    if min(selected) >= end:
        return {}
    result = {}
    opening_edge = None
    link_bound = None
    for number in range(end):
        if link_bound is not None and number >= link_bound:
            break
        run = _page_run(doc[number], opening=opening_edge is None)
        if run is None:
            if opening_edge is None:
                continue  # A heading alone has not opened a contents region.
            break
        edge = run.rows[0].number.x1
        if opening_edge is None:
            opening_edge = edge
        elif (
            first is None
            and link_bound is None
            and abs(edge - opening_edge) > _COLUMN_TOLERANCE
        ):
            break  # No physical destination to distinguish a new numeric table.
        if link_bound is None:
            link_bound = run.first_destination
            if link_bound is not None and number >= link_bound:
                break
        if number in selected:
            result[number] = run.rows
        if not run.can_continue:
            break
    return result


def _subtract(rect, cut):
    overlap = rect & cut
    if overlap.is_empty:
        return [rect]
    return [
        part
        for part in (
            pymupdf.Rect(rect.x0, rect.y0, rect.x1, overlap.y0),
            pymupdf.Rect(rect.x0, overlap.y1, rect.x1, rect.y1),
            pymupdf.Rect(rect.x0, overlap.y0, overlap.x0, overlap.y1),
            pymupdf.Rect(overlap.x1, overlap.y0, rect.x1, overlap.y1),
        )
        if not part.is_empty
    ]


def separate_cells(
    boxes: list[Detection], rows: list[ContentsRow], chars, height: float
) -> list[Detection]:
    """Leave the digits as original page glyphs outside the typesetting stream."""

    def detection(rect, conf, role):
        return tuple((64, v) for v in rect), conf, role

    # The model converts/pads boxes before assigning *native* glyphs. Never
    # mark adjacent title text as fixed on the strength of MuPDF geometry alone.
    ink = [
        (model_rect(c, ceil(height)), c.char_unicode)
        for c in chars
        if (c.char_unicode or "").strip()
    ]
    replacements = []
    cuts = []
    artwork = [
        padded_rect(box)
        for box in boxes
        if box[2] in {"figure", "image", "formula", "isolate_formula"}
    ]
    for row in rows:
        cut = (row.title | row.number) + (-1, -1, 1, 1)
        if any(overlaps(rect, (cut.x0, cut.y0, cut.x1, cut.y1)) for rect in artwork):
            continue  # Do not replace a native formula/figure region with prose.
        # The native `number` class wins over text and keeps its original
        # glyphs. Use only a middle band; an ascender/descender in a wrapped
        # title may overlap the number's full font box on the preceding line.
        band = row.number + (1, row.number.height * 0.35, -1, -row.number.height * 0.35)
        if band.is_empty:
            continue
        number = detection(band, 1.0, "number")
        padded = padded_rect(number)
        selected = sorted((b[0], char) for b, char in ink if overlaps(b, padded))
        if "".join(char for _, char in selected) != row.printed:
            continue
        replacements.extend([detection(row.title, 1.0, "plain text"), number])
        cuts.append(cut)
    if not cuts:
        return boxes
    result = []
    for box in boxes:
        coords, conf, role = box
        rect = pymupdf.Rect([v for _, v in coords])
        pieces = [rect]
        for cut in cuts:
            pieces = [part for piece in pieces for part in _subtract(piece, cut)]
        if pieces == [rect]:
            result.append(box)
        else:
            result.extend(detection(piece, conf, role) for piece in pieces)
    return result + replacements
