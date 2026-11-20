"""Preserve inline IL objects and rebuild PDF links from Wenyi's target offsets."""

from __future__ import annotations

import hashlib
import unicodedata
from contextlib import contextmanager
from typing import Any, Iterator

from . import _native

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


def _rect(box: Any) -> tuple[float, float, float, float]:
    return box.x, box.y, box.x2, box.y2


def _visible_rect(char: Any) -> tuple[float, float, float, float]:
    return _rect(getattr(getattr(char, "visual_bbox", None), "box", None) or char.box)


def extract_inline_annotations(
    para: Any,
    links: list[dict[str, Any]],
    *,
    offsets: dict[int, tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    """Export source ranges and stable composition references, never raw IL over HTTP."""
    compositions = list(para.pdf_paragraph_composition or [])
    kinds: list[bool | None] = []
    for composition in compositions:
        formula = getattr(composition, "pdf_formula", None)
        run = getattr(composition, "pdf_same_style_characters", None)
        kinds.append(
            True
            if formula is not None
            else False
            if run is not None and run.pdf_style != para.pdf_style
            else None
        )
    if not compositions or (not links and all(kind is None for kind in kinds)):
        return []
    composition_ranges, link_ranges = _native.inline_source_ranges(
        para.unicode or "",
        kinds,
        [
            (ci, (start, end), _rect(char.box) if links else None)
            for ci, start, end, char in _source_characters(para, offsets)
        ],
        [link["from"] for link in links],
    )
    items: list[dict[str, Any]] = []
    for index, (is_formula, ranges) in enumerate(zip(kinds, composition_ranges)):
        if is_formula is None:
            continue
        kind = "formula" if is_formula else "style"
        if is_formula and not ranges:
            raise ValueError("Cannot locate PDF formula in paragraph source")
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
    for link, ranges in zip(links, link_ranges):
        if ranges:
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
        _require_protected(items, [], skipped)
        return []
    if not isinstance(rows, list):
        skipped.update((item["id"], "invalid_placements") for item in items)
        _require_protected(items, [], skipped)
        return []
    omitted = payload.get("omitted_protected_objects", [])
    protected = {item["id"] for item in items if item.get("protected")}
    if (
        not isinstance(omitted, list)
        or any(not isinstance(item_id, str) for item_id in omitted)
        or len(set(omitted)) != len(omitted)
        or not set(omitted) <= protected
    ):
        raise ValueError(
            "Invalid omitted_protected_objects: expected unique protected IDs"
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            grouped.setdefault(row["id"], []).append(row)
    accepted = []
    for item in items:
        item_id = item["id"]
        if item_id in omitted:
            skipped[item_id] = "explicit_client_omission"
            continue
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
    _require_protected(items, accepted, skipped)
    return accepted


def _require_protected(
    items: list[dict[str, Any]],
    placements: list[dict[str, Any]],
    skipped: dict[str, str],
) -> None:
    """Require every protected object unless the client explicitly omitted that ID."""
    protected = {
        item["id"]
        for item in items
        if item.get("protected")
        and skipped.get(item["id"]) != "explicit_client_omission"
    }
    failures = protected & skipped.keys()
    failures.update(
        item_id
        for item_id in protected
        if sum(row["id"] == item_id for row in placements) != 1
    )
    orders: set[tuple[int, int]] = set()
    for row in placements:
        if row["id"] not in protected:
            continue
        order = row.get("target_order", 0)
        if type(order) is not int or order < 0:
            failures.add(row["id"])
            continue
        key = (row["target_start"], order)
        if key in orders:
            failures.add(row["id"])
        orders.add(key)
    if failures:
        raise ValueError(
            "Cannot restore protected PDF objects: "
            + ", ".join(sorted(failures))
            + ". Repair annotation alignment before exporting."
        )


def _link_backed_styles(
    items: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    skipped: dict[str, str],
) -> set[str]:
    """Recognize style runs covering exactly the same source and target as a link."""
    ranges = [
        (
            item["kind"],
            item["id"],
            (
                (item["source_start"], item["source_end"]),
                (rows[item["id"]]["target_start"], rows[item["id"]]["target_end"]),
            ),
        )
        for item in items
        if item["kind"] in ("style", "link")
        and item["id"] in rows
        and item["id"] not in skipped
        and item.get("mode") == "range"
        and "source_start" in item
        and "source_end" in item
    ]
    styles = [(item_id, span) for kind, item_id, span in ranges if kind == "style"]
    links = [span for kind, _, span in ranges if kind == "link"]
    if not styles or not links:
        return set()
    precise = _native.exact_link_styles([span for _, span in styles], links)
    return {item_id for (item_id, _), linked in zip(styles, precise) if linked}


def _skip_conflicts(
    para: Any,
    items: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    skipped: dict[str, str],
    linked_styles: set[str],
) -> None:
    """Discard only the participants of ambiguous style/formula overlaps."""
    candidates = [
        item
        for item in items
        if item["id"] in rows and item["kind"] in ("style", "formula")
    ]
    # A lone style cannot conflict and does not need an IL lookup.
    if sum(item["kind"] == "style" for item in candidates) == 1:
        candidates = [item for item in candidates if item["kind"] == "formula"]
    if len(candidates) < 2:
        return
    spans = []
    for item in candidates:
        row = rows[item["id"]]
        style = None
        if item["kind"] == "style":
            style = (
                para.pdf_paragraph_composition[
                    item["composition_index"]
                ].pdf_same_style_characters.pdf_style,
                item["id"] in linked_styles,
            )
        spans.append(((row["target_start"], row["target_end"]), style))
    for index in _native.annotation_conflicts(spans):
        item = candidates[index]
        skipped[item["id"]] = (
            "conflicting_styles" if item["kind"] == "style" else "conflicting_formulas"
        )


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
    linked_styles = _link_backed_styles(items, rows, skipped)
    _skip_conflicts(para, items, rows, skipped, linked_styles)
    _require_protected(items, placements, skipped)
    original = list(para.pdf_paragraph_composition or [])
    formulas = []
    styles = []
    for index, item in enumerate(items):
        if item["id"] not in rows or item["id"] in skipped:
            continue
        row = rows[item["id"]]
        start, end = row["target_start"], row["target_end"]
        if item["kind"] == "formula":
            formulas.append((start, end, row.get("target_order", 0), index))
        elif item["kind"] == "style":
            styles.append((index, (start, end), item["id"] in linked_styles))
    formulas.sort(key=lambda entry: entry[:3])
    compositions = []
    plan: list[GlyphPlan] = []
    for is_formula, index, (start, end) in _native.target_runs(
        len(text), [(index, (start, end)) for start, end, _, index in formulas], styles
    ):
        if is_formula:
            assert index is not None
            item = items[index]
            formula = original[item["composition_index"]].pdf_formula
            compositions.append(bb["PdfParagraphComposition"](pdf_formula=formula))
            plan.extend(
                (char.char_unicode or "", start, end, item["id"])
                for char in formula.pdf_character or []
            )
            continue
        style = para.pdf_style
        if index is not None:
            run = original[items[index]["composition_index"]].pdf_same_style_characters
            style = run.pdf_style
        compositions.append(
            bb["PdfParagraphComposition"](
                pdf_same_style_unicode_characters=bb["PdfSameStyleUnicodeCharacters"](
                    unicode=text[start:end], pdf_style=style
                )
            )
        )
        plan.extend(
            (char, i, i + 1, None)
            for i, char in enumerate(text[start:end], start)
            if char != "\n"
        )
    para.unicode = text
    para.pdf_paragraph_composition = compositions
    return plan


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
    if not by_link:
        return {}
    glyphs = [
        (_rect(char.box), _visible_rect(char))
        for composition in para.pdf_paragraph_composition or []
        for char in _characters(composition)
        if _normalized(char.char_unicode or "").strip()
    ]
    all_boxes = _native.original_link_boxes(
        glyphs, [links[link_id]["from"] for link_id in by_link]
    )
    result = {}
    for (link_id, item_ids), boxes in zip(by_link.items(), all_boxes):
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
    visible = [
        (text, _visible_rect(char))
        for composition in para.pdf_paragraph_composition or []
        for char in _characters(composition)
        if (text := _normalized(char.char_unicode or "")).strip()
    ]
    # BabelDOC may drop spaces at line boundaries. Match only visible glyphs;
    # their original target intervals still identify the precise linked text.
    normalized_plan = [
        (text, start, end, object_id)
        for expected, start, end, object_id in plan
        if (text := _normalized(expected)).strip()
    ]
    all_boxes = _native.rendered_link_boxes(
        visible,
        normalized_plan,
        [
            (
                (rows[item["id"]]["target_start"], rows[item["id"]]["target_end"]),
                item.get("object_ids", []) if item["kind"] == "link" else [item["id"]],
            )
            for item in linked_items
        ],
    )
    if all_boxes is None:
        skipped.update((item["id"], "glyph_stream_changed") for item in linked_items)
        return {}
    result: dict[str, list[list[float]]] = {}
    for item, boxes in zip(linked_items, all_boxes):
        link_ids = (
            [item["link_id"]] if item["kind"] == "link" else item.get("link_ids", [])
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

    selected = _native.select_output_links(
        page_numbers,
        [
            (
                link["page"],
                link["action"]["page"]
                if link["action"]["kind"] == pymupdf.LINK_GOTO
                else None,
                bool(link.get("text_bound")),
                link["from"],
                rectangles.get(link["id"]) or [],
            )
            for link in links
        ],
    )
    with pymupdf.open(path) as doc:
        with _unrotated_pages(doc):
            for index, output_page, target, boxes in selected:
                action = dict(links[index]["action"])
                if target is not None:
                    action["page"] = target
                    action["to"] = (
                        pymupdf.Point(action["to"]) * doc[target].transformation_matrix
                    )
                page = doc[output_page]
                for box in boxes:
                    page.insert_link(
                        {
                            **action,
                            "from": pymupdf.Rect(box) * page.transformation_matrix,
                        }
                    )
        doc.saveIncr()
