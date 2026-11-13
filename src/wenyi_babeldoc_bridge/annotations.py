"""Preserve inline IL objects and rebuild PDF links from Wenyi's target offsets."""

from __future__ import annotations

import hashlib
import unicodedata
from contextlib import contextmanager
from typing import Any, Iterator

GlyphPlan = tuple[str, int, int, str | None]


def _characters(composition: Any) -> list[Any]:
    for name in ("pdf_formula", "pdf_same_style_characters", "pdf_line"):
        value = getattr(composition, name, None)
        if value is not None:
            return list(value.pdf_character or [])
    char = getattr(composition, "pdf_character", None)
    return [char] if char is not None else []


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _source_characters(
    para: Any, offsets: dict[int, tuple[int, int]] | None = None
) -> list[tuple[int, int, int, Any]]:
    """Map original glyphs to the exact exported Unicode, allowing inferred spaces only."""
    source = para.unicode or ""
    cursor = 0
    result = []
    for index, composition in enumerate(para.pdf_paragraph_composition or []):
        for char in _characters(composition):
            text = _normalized(char.char_unicode or "")
            if not text.strip():
                continue
            if offsets is not None:
                if id(char) not in offsets:
                    raise ValueError(
                        "PDF inline glyph lost its original source identity"
                    )
                start, end = offsets[id(char)]
                result.append((index, start, end, char))
                continue
            start = source.find(text, cursor)
            if start < 0 or source[cursor:start].strip():
                raise ValueError(
                    "Cannot map PDF inline objects to paragraph source; "
                    "the original IL and source text disagree"
                )
            end = start + len(text)
            result.append((index, start, end, char))
            cursor = end
    if offsets is None and result and source[cursor:].strip():
        raise ValueError("Unmapped PDF paragraph source after the last original glyph")
    return result


def source_glyph_offsets(para: Any) -> dict[int, tuple[int, int]]:
    """Capture reading-order offsets before StylesAndFormulas regroups glyphs."""
    return {id(char): (start, end) for _, start, end, char in _source_characters(para)}


def _source_ranges(source: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Keep discontinuous style/link runs from swallowing intervening source text."""
    ranges: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if ranges and not source[ranges[-1][1] : start].strip():
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


def _contains_glyph_center(box: Any, rect: list[float]) -> bool:
    # Tall link rectangles can touch glyph bounds on adjacent lines. Such an
    # overlap does not make those neighboring words part of the linked text.
    return (
        rect[0] <= (box.x + box.x2) / 2 <= rect[2]
        and rect[1] <= (box.y + box.y2) / 2 <= rect[3]
    )


def extract_inline_annotations(
    para: Any,
    links: list[dict[str, Any]],
    *,
    offsets: dict[int, tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    """Export source ranges and stable composition references, never raw IL over HTTP."""
    compositions = list(para.pdf_paragraph_composition or [])
    if not compositions:
        return []
    if not links and not any(
        getattr(comp, "pdf_formula", None) is not None
        or (
            getattr(comp, "pdf_same_style_characters", None) is not None
            and comp.pdf_same_style_characters.pdf_style != para.pdf_style
        )
        for comp in compositions
    ):
        return []
    chars = _source_characters(para, offsets)
    items: list[dict[str, Any]] = []
    for index, composition in enumerate(compositions):
        formula = getattr(composition, "pdf_formula", None)
        run = getattr(composition, "pdf_same_style_characters", None)
        kind = "formula" if formula is not None else "style"
        if formula is None and (run is None or run.pdf_style == para.pdf_style):
            continue
        spans = [(start, end) for ci, start, end, _ in chars if ci == index]
        if not spans:
            if kind == "style":
                continue
            raise ValueError(f"Cannot locate PDF {kind} in paragraph source")
        ranges = (
            [(min(start for start, _ in spans), max(end for _, end in spans))]
            if kind == "formula"
            else _source_ranges(para.unicode, spans)
        )
        for ordinal, (start, end) in enumerate(ranges):
            suffix = f":{ordinal}" if len(ranges) > 1 else ""
            items.append(
                {
                    "id": f"{kind}:{index}{suffix}",
                    "kind": kind,
                    "mode": "range",
                    "source_start": start,
                    "source_end": end,
                    "composition_index": index,
                }
            )
    for link in links:
        spans = [
            (start, end)
            for _, start, end, char in chars
            if _contains_glyph_center(char.box, link["from"])
        ]
        if spans:
            ranges = _source_ranges(para.unicode, spans)
            for ordinal, (start, end) in enumerate(ranges):
                suffix = f":{ordinal}" if len(ranges) > 1 else ""
                items.append(
                    {
                        "id": f"link:{link['id']}{suffix}",
                        "kind": "link",
                        "mode": "range",
                        "source_start": start,
                        "source_end": end,
                        "link_id": link["id"],
                    }
                )
            link["text_bound"] = True
    return items


def prepare_inline_annotations(
    para: Any,
    links: list[dict[str, Any]],
    *,
    offsets: dict[int, tuple[int, int]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Keep small corner markers out of translatable prose and align their anchor points."""
    items = extract_inline_annotations(para, links, offsets=offsets)
    source = para.unicode or ""
    markers = []
    base_size = getattr(para.pdf_style, "font_size", 0) or 0
    for item in items:
        if item["kind"] != "formula":
            continue
        formula = para.pdf_paragraph_composition[item["composition_index"]].pdf_formula
        if getattr(formula, "is_corner_mark", False) and all(
            char.pdf_style.font_size < base_size * 0.9
            for char in formula.pdf_character or []
        ):
            markers.append(item)
    if not markers:
        return source, items
    marker_spans = [
        (item["source_start"], item["source_end"], item) for item in markers
    ]
    marker_ids = {item["id"] for item in markers}
    spans = sorted((start, end) for start, end, _ in marker_spans)
    kept = []
    cursor = 0
    for start, end in spans:
        kept.append(source[cursor:start])
        cursor = end
    kept.append(source[cursor:])
    cleaned = "".join(kept)
    if not cleaned.strip():
        # A standalone marker still needs its stable paragraph ID and a nonempty source.
        return source, items

    def offset(position: int) -> int:
        return position - sum(
            max(0, min(position, end) - start) for start, end in spans
        )

    result = []
    for item in items:
        start, end = item["source_start"], item["source_end"]
        covered = [
            marker
            for marker_start, marker_end, marker in marker_spans
            if start < marker_end and marker_start < end
        ]
        if item["kind"] == "link" and offset(start) == offset(end):
            for marker in covered:
                marker.setdefault("link_ids", []).append(item["link_id"])
            continue
        if item["kind"] == "link" and covered:
            item["object_ids"] = [marker["id"] for marker in covered]
        item["source_start"], item["source_end"] = offset(start), offset(end)
        if item["id"] in marker_ids:
            item["mode"] = "point"
        result.append(item)
    return cleaned, result


def validate_annotation_placements(
    items: list[dict[str, Any]],
    text: str,
    payload: dict[str, Any],
    *,
    skipped: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Select trustworthy items independently, without changing or replacing the text."""
    skipped = skipped if skipped is not None else {}
    rows = payload.get("placements")
    digest = payload.get("target_digest")
    if digest != hashlib.sha256(text.encode("utf-8")).hexdigest():
        reason = "stale_alignment" if digest else "missing_alignment"
        skipped.update((item["id"], reason) for item in items)
        return []
    if not isinstance(rows, list):
        skipped.update((item["id"], "invalid_placements") for item in items)
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            grouped.setdefault(row["id"], []).append(row)
    accepted = []
    for item in items:
        item_id = item["id"]
        candidates = grouped.get(item_id, [])
        if len(candidates) != 1:
            skipped[item_id] = (
                "duplicate_placement" if candidates else "missing_placement"
            )
            continue
        row = candidates[0]
        if row.get("status") != "aligned":
            skipped[item_id] = "alignment_failed"
            continue
        start, end = row.get("target_start"), row.get("target_end")
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start <= end <= len(text)
            or row.get("mode") != item["mode"]
            or (row["mode"] == "point") != (start == end)
        ):
            skipped[item_id] = "invalid_placement"
            continue
        accepted.append(row)
    return accepted


def _skip_conflicts(
    para: Any,
    items: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    skipped: dict[str, str],
) -> None:
    """Discard only the participants of ambiguous style/formula overlaps."""
    candidates = [
        item
        for item in items
        if item["id"] in rows and item["kind"] in ("style", "formula")
    ]
    for index, item in enumerate(candidates):
        row = rows[item["id"]]
        start, end = row["target_start"], row["target_end"]
        for other in candidates[index + 1 :]:
            if item["kind"] != other["kind"]:
                continue
            peer = rows[other["id"]]
            left, right = peer["target_start"], peer["target_end"]
            overlaps = max(start, left) < min(end, right)
            if item["kind"] == "formula":
                overlaps |= start == end and left < start < right
                overlaps |= left == right and start < left < end
                reason = "conflicting_formulas"
            else:
                compositions = para.pdf_paragraph_composition
                style = compositions[
                    item["composition_index"]
                ].pdf_same_style_characters.pdf_style
                other_style = compositions[
                    other["composition_index"]
                ].pdf_same_style_characters.pdf_style
                overlaps &= style != other_style
                reason = "conflicting_styles"
            if overlaps:
                skipped[item["id"]] = reason
                skipped[other["id"]] = reason


def inject_aligned_translation(
    bb: dict[str, Any],
    para: Any,
    text: str,
    items: list[dict[str, Any]],
    placements: list[dict[str, Any]],
    *,
    skipped: dict[str, str] | None = None,
) -> list[GlyphPlan]:
    """Restore formulas/styles and record each future glyph's target interval."""
    skipped = skipped if skipped is not None else {}
    rows = {row["id"]: row for row in placements}
    _skip_conflicts(para, items, rows, skipped)
    original = list(para.pdf_paragraph_composition or [])
    formulas: dict[int, list[tuple[int, Any, str]]] = {}
    styles: list[tuple[int, int, Any]] = []
    for item in items:
        if item["id"] not in rows or item["id"] in skipped:
            continue
        row = rows[item["id"]]
        start, end = row["target_start"], row["target_end"]
        if item["kind"] == "formula":
            formulas.setdefault(start, []).append(
                (end, original[item["composition_index"]].pdf_formula, item["id"])
            )
        elif item["kind"] == "style":
            run = original[item["composition_index"]].pdf_same_style_characters
            styles.append((start, end, run.pdf_style))
    boundaries = {0, len(text), *formulas}
    boundaries.update(end for entries in formulas.values() for end, _, _ in entries)
    for start, end, _ in styles:
        boundaries.update((start, end))
    ordered = sorted(boundaries)
    compositions = []
    plan: list[GlyphPlan] = []
    cursor = 0
    while cursor <= len(text):
        entries = sorted(formulas.get(cursor, []), key=lambda entry: entry[0])
        end = cursor
        for end, formula, item_id in entries:
            compositions.append(bb["PdfParagraphComposition"](pdf_formula=formula))
            plan.extend(
                (char.char_unicode or "", cursor, end, item_id)
                for char in formula.pdf_character or []
            )
        if end > cursor:
            cursor = end
            continue
        if cursor == len(text):
            break
        end = next(boundary for boundary in ordered if boundary > cursor)
        active = [style for start, stop, style in styles if start <= cursor < stop]
        style = active[0] if active else para.pdf_style
        compositions.append(
            bb["PdfParagraphComposition"](
                pdf_same_style_unicode_characters=bb["PdfSameStyleUnicodeCharacters"](
                    unicode=text[cursor:end], pdf_style=style
                )
            )
        )
        plan.extend(
            (char, i, i + 1, None)
            for i, char in enumerate(text[cursor:end], cursor)
            if char != "\n"
        )
        cursor = end
    para.unicode = text
    para.pdf_paragraph_composition = compositions
    return plan


def _glyph_rectangles(chars: Iterator[Any]) -> list[list[float]]:
    """Merge visible glyph bounds into one clickable rectangle per visual line."""
    boxes: list[list[float]] = []
    for char in chars:
        box = getattr(getattr(char, "visual_bbox", None), "box", None) or char.box
        rect = [float(box.x), float(box.y), float(box.x2), float(box.y2)]
        if rect[0] >= rect[2] or rect[1] >= rect[3]:
            continue
        line = next(
            (
                old
                for old in boxes
                if min(old[3], rect[3]) - max(old[1], rect[1])
                > min(old[3] - old[1], rect[3] - rect[1]) * 0.5
            ),
            None,
        )
        if line is None:
            boxes.append(rect)
        else:
            line[:] = [
                min(line[0], rect[0]),
                min(line[1], rect[1]),
                max(line[2], rect[2]),
                max(line[3], rect[3]),
            ]
    return boxes


def original_link_rectangles(
    para: Any,
    items: list[dict[str, Any]],
    links: dict[str, dict[str, Any]],
    *,
    skipped: dict[str, str],
) -> dict[str, list[list[float]]]:
    """Recover links from unchanged glyph geometry, including linked corner marks."""
    by_link: dict[str, list[str]] = {}
    for item in items:
        link_ids = (
            [item["link_id"]] if item["kind"] == "link" else item.get("link_ids", [])
        )
        for link_id in link_ids:
            by_link.setdefault(link_id, []).append(item["id"])
    chars = [
        char
        for composition in para.pdf_paragraph_composition or []
        for char in _characters(composition)
        if _normalized(char.char_unicode or "").strip()
    ]
    result = {}
    for link_id, item_ids in by_link.items():
        link = links[link_id]
        boxes = _glyph_rectangles(
            char for char in chars if _contains_glyph_center(char.box, link["from"])
        )
        if boxes:
            result[link_id] = boxes
        else:
            skipped.update((item_id, "no_rendered_glyphs") for item_id in item_ids)
    return result


def layout_link_rectangles(
    para: Any,
    plan: list[GlyphPlan],
    items: list[dict[str, Any]],
    placements: list[dict[str, Any]],
    *,
    skipped: dict[str, str] | None = None,
) -> dict[str, list[list[float]]]:
    """Resolve target ranges against actual rendered glyphs, separately for every line."""
    skipped = skipped if skipped is not None else {}
    rows = {row["id"]: row for row in placements}
    linked_items = [
        item
        for item in items
        if item["id"] in rows
        and item["id"] not in skipped
        and (item["kind"] == "link" or item.get("link_ids"))
    ]
    if not linked_items:
        return {}
    chars = [
        char
        for composition in para.pdf_paragraph_composition or []
        for char in _characters(composition)
        if _normalized(char.char_unicode or "").strip()
    ]
    # BabelDOC may drop spaces at line boundaries. Match only visible glyphs;
    # their original target intervals still identify the precise linked text.
    plan = [entry for entry in plan if _normalized(entry[0]).strip()]
    if len(chars) != len(plan) or any(
        _normalized(char.char_unicode or "") != _normalized(expected)
        for char, (expected, _, _, _) in zip(chars, plan)
    ):
        skipped.update((item["id"], "glyph_stream_changed") for item in linked_items)
        return {}
    result: dict[str, list[list[float]]] = {}
    for item in linked_items:
        link_ids = (
            [item["link_id"]] if item["kind"] == "link" else item.get("link_ids", [])
        )
        if not link_ids:
            continue
        row = rows[item["id"]]
        object_ids = (
            set(item.get("object_ids", [])) if item["kind"] == "link" else {item["id"]}
        )
        boxes = _glyph_rectangles(
            char
            for char, (_, start, end, object_id) in zip(chars, plan)
            if object_id in object_ids
            or (start < row["target_end"] and end > row["target_start"])
        )
        if not boxes:
            skipped[item["id"]] = "no_rendered_glyphs"
            continue
        for link_id in link_ids:
            result.setdefault(link_id, []).extend(boxes)
    return result


def summarize_annotations(details: list[dict[str, Any]]) -> dict[str, Any]:
    """Count validation and application separately; neither proves semantic correctness."""

    def bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows)
        aligned = sum(row["aligned"] for row in rows)
        applied = sum(row["reason"] is None for row in rows)
        return {
            "total": total,
            "aligned": aligned,
            "applied": applied,
            "skipped": total - applied,
            "alignment_pass_rate": aligned / total if total else None,
            "application_rate": applied / total if total else None,
        }

    reasons: dict[str, int] = {}
    for row in details:
        if row["reason"]:
            reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    return {
        **bucket(details),
        "translated": bucket([row for row in details if not row["source_identity"]]),
        "source_identity": bucket([row for row in details if row["source_identity"]]),
        "by_kind": {
            kind: bucket([row for row in details if row["kind"] == kind])
            for kind in ("formula", "style", "link")
        },
        "reasons": reasons,
    }


@contextmanager
def _unrotated_pages(doc: Any) -> Iterator[None]:
    """Use one coordinate frame for PyMuPDF link reads/writes, including cropped pages."""
    rotations = [(page.number, page.rotation) for page in doc if page.rotation]
    try:
        for number, _ in rotations:
            doc[number].set_rotation(0)
        yield
    finally:
        for number, rotation in rotations:
            doc[number].set_rotation(rotation)


def capture_links(doc: Any) -> list[dict[str, Any]]:
    """Capture URI/page destinations before BabelDOC clears page annotations."""
    import pymupdf

    records = []
    with _unrotated_pages(doc):
        for page in doc:
            for index, link in enumerate(page.get_links()):
                if link["kind"] not in (
                    pymupdf.LINK_URI,
                    pymupdf.LINK_GOTO,
                    pymupdf.LINK_NAMED,
                ):
                    continue
                # Resolved named destinations expose page/to but report LINK_NAMED.
                # Direct page jumps avoid depending on the original name tree.
                action: dict[str, Any] = {
                    "kind": (
                        pymupdf.LINK_URI
                        if link["kind"] == pymupdf.LINK_URI
                        else pymupdf.LINK_GOTO
                    )
                }
                if link["kind"] == pymupdf.LINK_URI:
                    action["uri"] = link["uri"]
                else:
                    target = link.get("page", -1)
                    if not 0 <= target < len(doc):
                        continue
                    point = link.get("to", pymupdf.Point(0, 0))
                    # Resolved named destinations already use PDF coordinates.
                    if link["kind"] != pymupdf.LINK_NAMED:
                        point = point * ~doc[target].transformation_matrix
                    action.update(page=target, to=list(point), zoom=link.get("zoom", 0))
                records.append(
                    {
                        "id": f"{page.number}:{index}",
                        "page": page.number,
                        "from": list(link["from"] * ~page.transformation_matrix),
                        "action": action,
                    }
                )
    return records


def restore_links(
    path: Any,
    links: list[dict[str, Any]],
    page_numbers: list[int],
    rectangles: dict[str, list[list[float]]],
) -> None:
    """Rebuild supported links with selected-page mapping and post-layout rectangles."""
    if not links:
        return
    import pymupdf

    page_map = {source: output for output, source in enumerate(page_numbers)}
    with pymupdf.open(path) as doc:
        with _unrotated_pages(doc):
            for link in links:
                if link["page"] not in page_map:
                    continue
                action = dict(link["action"])
                if action["kind"] == pymupdf.LINK_GOTO:
                    if action["page"] not in page_map:
                        # A destination omitted from the exported page selection cannot be linked.
                        continue
                    action["page"] = page_map[action["page"]]
                    action["to"] = (
                        pymupdf.Point(action["to"])
                        * doc[action["page"]].transformation_matrix
                    )
                page = doc[page_map[link["page"]]]
                boxes = rectangles.get(link["id"])
                if not boxes:
                    if link.get("text_bound"):
                        # Failed text annotations must not become stale clickable boxes.
                        continue
                    boxes = [link["from"]]
                for box in boxes:
                    page.insert_link(
                        {
                            **action,
                            "from": pymupdf.Rect(box) * page.transformation_matrix,
                        }
                    )
        doc.saveIncr()
