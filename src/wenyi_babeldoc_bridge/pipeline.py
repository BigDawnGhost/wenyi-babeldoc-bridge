"""In-process BabelDOC extract / inject / typeset helpers (AGPL side only)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from wenyi_babeldoc_bridge.annotations import (
    capture_links,
    inject_aligned_translation,
    layout_link_rectangles,
    original_link_rectangles,
    restore_links,
    source_glyph_offsets,
    summarize_annotations,
    validate_annotation_placements,
)
from wenyi_babeldoc_bridge.math_attachments import attach_math_marks
from wenyi_babeldoc_bridge.native import can_chain_layout, can_chain_write
from wenyi_babeldoc_bridge.protected_objects import (
    prepare_protected_annotations,
    restore_protected_formula_baselines,
)
from wenyi_babeldoc_bridge.rows import (
    anchor_row_markers,
    capture_rows,
    inject_rows,
    partition_row_annotations,
    remap_source_rows,
    sequence_row_glyphs,
    validate_target_rows,
)
from wenyi_babeldoc_bridge.schema import (
    is_debug_overlay_paragraph as _is_debug_overlay_paragraph,
)
from wenyi_babeldoc_bridge.schema import (
    is_numeric_text,
    is_passthrough_paragraph,
    is_translatable_paragraph,
    make_paragraph_id,
)

SESSION_SNAPSHOT_SCHEMA = "wenyi-babeldoc-session/v2"
SESSION_MANIFEST_NAME = "session.json"
SESSION_IL_NAME = "styles_and_formulas.native.json.gz"
SESSION_MEDIABOX_NAME = "mediabox.json"
logger = logging.getLogger(__name__)


def require_babeldoc() -> dict[str, Any]:
    if _babeldoc_version() != "0.7.1":
        raise RuntimeError("This bridge requires BabelDOC 0.7.1; reinstall the bridge")
    try:
        # Initialize high_level before the IL helpers to avoid circular imports.
        from babeldoc.docvision.doclayout import DocLayoutModel
        from babeldoc.format.pdf import high_level as hl
        from babeldoc.format.pdf.document_il.il_version_1 import (
            Box,
            PdfFormula,
            PdfParagraphComposition,
            PdfSameStyleUnicodeCharacters,
        )
        from babeldoc.format.pdf.document_il.il_version_1 import Document as ILDocument
        from babeldoc.format.pdf.document_il.xml_converter import XMLConverter
        from babeldoc.format.pdf.translation_config import (
            TranslationConfig,
            WatermarkOutputMode,
        )
        from babeldoc.translator.translator import BaseTranslator
        from pymupdf import Document

        from wenyi_babeldoc_bridge import _native
        from wenyi_babeldoc_bridge.native import (
            LayoutParser,
            ParagraphFinder,
            PDFCreater,
            StylesAndFormulas,
            Typesetting,
            parse_prepared_pdf,
        )
    except ImportError as error:
        raise RuntimeError(
            "BabelDOC or the bridge native extension is missing; "
            "install a platform wheel or build with Rust from source"
        ) from error
    if _native.BABELDOC_VERSION != _babeldoc_version():
        raise RuntimeError("Bridge native extension and BabelDOC versions disagree")

    return {
        "hl": hl,
        "DocLayoutModel": DocLayoutModel,
        "PDFCreater": PDFCreater,
        "Box": Box,
        "PdfFormula": PdfFormula,
        "PdfParagraphComposition": PdfParagraphComposition,
        "PdfSameStyleUnicodeCharacters": PdfSameStyleUnicodeCharacters,
        "DocumentIL": ILDocument,
        "LayoutParser": LayoutParser,
        "ParagraphFinder": ParagraphFinder,
        "StylesAndFormulas": StylesAndFormulas,
        "Typesetting": Typesetting,
        "XMLConverter": XMLConverter,
        "parse_prepared_pdf": parse_prepared_pdf,
        "TranslationConfig": TranslationConfig,
        "WatermarkOutputMode": WatermarkOutputMode,
        "BaseTranslator": BaseTranslator,
        "Document": Document,
    }


def identity_translator(BaseTranslator):
    class IdentityTranslator(BaseTranslator):
        name = "identity"

        def __init__(self):
            super().__init__("en", "zh-CN", ignore_cache=True)

        def do_translate(self, text, rate_limit_params=None):
            return text

        def do_llm_translate(self, text, rate_limit_params=None):
            raise NotImplementedError

    return IdentityTranslator()


@dataclass
class ExtractSession:
    """Holds one durable frozen IL snapshot for later fillback."""

    session_id: str
    pdf_path: str
    pages_spec: str | None
    work_dir: Path
    out_dir: Path
    bb: dict[str, Any]
    cfg: Any
    docs: Any | None
    temp_pdf_path: str
    mediabox_data: Any
    pm: Any
    paragraphs: Any
    styles_path: Path
    snapshot_path: Path
    snapshot_sha256: str
    restored: bool = False
    preserved_paragraph_ids: tuple[str, ...] = ()


def _babeldoc_version() -> str:
    try:
        return version("babeldoc")
    except PackageNotFoundError:
        return "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def _atomic_write_native(path: Path, value: Any) -> str:
    temp_path = path.with_name(path.name + ".tmp")
    try:
        digest = value.write_checkpoint(temp_path)
        os.replace(temp_path, path)
        return digest
    finally:
        temp_path.unlink(missing_ok=True)


def _debug_enabled() -> bool:
    """Return whether BabelDOC should paint layout overlay boxes.

    LayoutParser stores debug rectangles and class-name labels (``plain text``,
    ``title``, ``figure_caption``, …) on the IL when extract ran with debug on.
    PDFCreater still typesets those labels unless we strip them. Shipped
    fillback PDFs keep this off. Set ``WENYI_BABELDOC_DEBUG=1`` to show
    paragraph/layout boxes and role labels while diagnosing typesetting.
    """
    raw = os.environ.get("WENYI_BABELDOC_DEBUG", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _strip_debug_overlays(docs: Any) -> int:
    """Remove layout-role labels and debug rectangles from a loaded IL copy."""
    removed = 0
    for page in docs.page:
        paragraphs = list(page.pdf_paragraph or [])
        kept = [para for para in paragraphs if not _is_debug_overlay_paragraph(para)]
        removed += len(paragraphs) - len(kept)
        page.pdf_paragraph = kept
        rectangles = list(page.pdf_rectangle or [])
        page.pdf_rectangle = [
            rect for rect in rectangles if not getattr(rect, "debug_info", False)
        ]
    return removed


def _build_translation_config(
    bb: dict[str, Any],
    *,
    pdf_path: Path,
    pages_spec: str | None,
    out_dir: Path,
    work_dir: Path,
    load_layout_model: bool,
) -> tuple[Any, Any]:
    # TranslationConfig auto-loads a model when passed None, including recovery.
    # A truthy sentinel keeps restored sessions independent of model availability.
    model = object()
    if load_layout_model:
        try:
            model = bb["DocLayoutModel"].load_onnx()
        except Exception:
            model = bb["DocLayoutModel"].load_available()

    cfg = bb["TranslationConfig"](
        translator=identity_translator(bb["BaseTranslator"]),
        input_file=pdf_path,
        lang_in="en",
        lang_out="zh-CN",
        doc_layout_model=model,
        output_dir=out_dir,
        working_dir=work_dir,
        debug=_debug_enabled(),
        skip_translation=True,
        pages=pages_spec,
        no_dual=True,
        watermark_output_mode=bb["WatermarkOutputMode"].NoWatermark,
        skip_scanned_detection=True,
        auto_extract_glossary=False,
        only_include_translated_page=True,
    )
    pm = bb["hl"].ProgressMonitor(bb["hl"].get_translation_stage(cfg))
    cfg.progress_monitor = pm
    return cfg, pm


def persist_session_snapshot(session: ExtractSession) -> None:
    """Atomically publish the immutable IL and metadata needed after restart."""
    if session.docs is None:
        raise RuntimeError("cannot snapshot a session without IL")

    out_dir = session.out_dir.resolve()
    snapshot_path = out_dir / SESSION_IL_NAME
    mediabox_path = out_dir / SESSION_MEDIABOX_NAME
    paragraphs_path = out_dir / "paragraphs.json"
    pdf_path = Path(session.pdf_path).resolve()
    temp_pdf_path = Path(session.temp_pdf_path).resolve()

    snapshot_digest = _atomic_write_native(snapshot_path, session.docs)
    _atomic_write_json(mediabox_path, session.mediabox_data or {})

    files = {
        "source_pdf": pdf_path.relative_to(out_dir).as_posix(),
        "working_pdf": temp_pdf_path.relative_to(out_dir).as_posix(),
        "il_snapshot": snapshot_path.name,
        "mediabox": mediabox_path.name,
        "paragraphs": paragraphs_path.name,
    }
    hashes = {
        name: snapshot_digest
        if name == "il_snapshot"
        else _sha256(out_dir / relative_path)
        for name, relative_path in files.items()
    }
    manifest = {
        "schema": SESSION_SNAPSHOT_SCHEMA,
        "session_id": session.session_id,
        "pages_spec": session.pages_spec,
        "babeldoc_version": _babeldoc_version(),
        "preserved_paragraph_ids": list(session.preserved_paragraph_ids),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "files": files,
        "sha256": hashes,
    }
    _atomic_write_json(out_dir / SESSION_MANIFEST_NAME, manifest)
    session.snapshot_path = snapshot_path
    session.snapshot_sha256 = hashes["il_snapshot"]


def load_session_docs(session: ExtractSession) -> Any:
    """Load a fresh copy of the pristine IL so repeated fillback is idempotent."""
    from wenyi_babeldoc_bridge.native import Document

    if not session.snapshot_path.is_file():
        raise RuntimeError(f"session IL snapshot missing: {session.snapshot_path}")
    return Document.restore_checkpoint(session.snapshot_path, session.snapshot_sha256)


def _resolve_session_file(out_dir: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise RuntimeError("session snapshot contains an invalid file path")
    resolved = (out_dir / relative_path).resolve()
    if resolved != out_dir and out_dir not in resolved.parents:
        raise RuntimeError("session snapshot file escapes its session directory")
    return resolved


def _paragraph_pairs_from_docs(
    docs: Any, *, exported_ids: set[str]
) -> list[tuple[str, str]]:
    from wenyi_babeldoc_bridge.schema import (  # type: ignore
        is_translatable_unicode,
        make_paragraph_id,
    )

    pairs: list[tuple[str, str]] = []
    for page in docs.page:
        for index, para in enumerate(page.pdf_paragraph or []):
            pid = make_paragraph_id(int(page.page_number), index)
            # Older sessions exported fixed glyphs too. Validate those entries,
            # but allow new sessions to omit them without renumbering the IL.
            if is_passthrough_paragraph(para) and pid not in exported_ids:
                continue
            if (
                pid not in exported_ids
                and para.pdf_paragraph_composition
                and all(
                    getattr(comp, "pdf_formula", None) is not None
                    for comp in para.pdf_paragraph_composition
                )
            ):
                continue
            source = para.unicode or ""
            if not _is_debug_overlay_paragraph(para) and is_translatable_unicode(
                source
            ):
                pairs.append((pid, str(source)))
    return pairs


def _validate_docs_against_paragraphs(
    docs: Any, paragraphs: Any, preserved_ids: tuple[str, ...] = ()
) -> None:
    exported_ids = {unit.id for unit in paragraphs.paragraphs}
    original_ids = {
        make_paragraph_id(int(page.page_number), index)
        for page in docs.page
        for index, _ in enumerate(page.pdf_paragraph or [])
    }
    preserved = set(preserved_ids)
    if (
        len(preserved) != len(preserved_ids)
        or preserved - original_ids
        or preserved & exported_ids
    ):
        raise RuntimeError("session preserved paragraph inventory is invalid")
    expected = [
        (
            unit.id,
            unit.original_source if unit.original_source is not None else unit.source,
        )
        for unit in paragraphs.paragraphs
    ]
    actual = [
        pair
        for pair in _paragraph_pairs_from_docs(docs, exported_ids=exported_ids)
        if pair[0] not in preserved
    ]
    if actual == expected:
        return
    mismatch = next(
        (
            index
            for index, (left, right) in enumerate(zip(actual, expected))
            if left != right
        ),
        min(len(actual), len(expected)),
    )
    raise RuntimeError(
        "session IL does not match paragraphs.json "
        f"(IL={len(actual)}, paragraphs={len(expected)}, first mismatch={mismatch})"
    )


def restore_session(*, session_id: str, out_dir: Path) -> ExtractSession:
    """Restore a frozen session without rerunning BabelDOC layout analysis."""
    session, _ = restore_session_with_docs(session_id=session_id, out_dir=out_dir)
    return session


def restore_session_with_docs(
    *, session_id: str, out_dir: Path
) -> tuple[ExtractSession, Any]:
    """Return metadata and the validated graph separately; only cache metadata."""
    from wenyi_babeldoc_bridge.schema import ParagraphDocument  # type: ignore

    out_dir = out_dir.resolve()
    manifest_path = out_dir / SESSION_MANIFEST_NAME
    if not manifest_path.is_file():
        if (out_dir / "styles_and_formulas.json").exists():
            raise RuntimeError(
                "Legacy BabelDOC session is incompatible; extract the PDF again"
            )
        raise FileNotFoundError(f"durable session not found: {session_id}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != SESSION_SNAPSHOT_SCHEMA
    ):
        raise RuntimeError("unsupported session snapshot schema; extract the PDF again")
    if payload.get("session_id") != session_id:
        raise RuntimeError("session snapshot id mismatch")
    preserved_ids = payload.get("preserved_paragraph_ids", [])
    if not isinstance(preserved_ids, list) or any(
        not isinstance(pid, str) for pid in preserved_ids
    ):
        raise RuntimeError("session preserved paragraph inventory is invalid")
    if payload.get("babeldoc_version") != _babeldoc_version():
        raise RuntimeError(
            "session BabelDOC version mismatch: "
            f"snapshot={payload.get('babeldoc_version')}, current={_babeldoc_version()}"
        )
    current_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if payload.get("python_version") != current_python:
        raise RuntimeError(
            "session Python version mismatch: "
            f"snapshot={payload.get('python_version')}, current={current_python}"
        )

    files = payload.get("files")
    hashes = payload.get("sha256")
    if not isinstance(files, dict) or not isinstance(hashes, dict):
        raise RuntimeError("session snapshot file manifest is invalid")
    resolved = {
        name: _resolve_session_file(out_dir, path) for name, path in files.items()
    }
    required = {"source_pdf", "working_pdf", "il_snapshot", "mediabox", "paragraphs"}
    if set(resolved) != required:
        raise RuntimeError("session snapshot file manifest is incomplete")
    for name, path in resolved.items():
        expected_hash = hashes.get(name)
        if not path.is_file() or not isinstance(expected_hash, str):
            raise RuntimeError(f"session snapshot file missing: {name}")
        # Native restore checks the IL before decompressing it.
        if name != "il_snapshot" and _sha256(path) != expected_hash:
            raise RuntimeError(f"session snapshot checksum mismatch: {name}")

    paragraphs = ParagraphDocument.read_json(resolved["paragraphs"])
    raw_mediabox = json.loads(resolved["mediabox"].read_text(encoding="utf-8"))
    if not isinstance(raw_mediabox, dict):
        raise RuntimeError("session mediabox snapshot is invalid")
    mediabox_data = {int(key): value for key, value in raw_mediabox.items()}
    bb = require_babeldoc()
    work_dir = out_dir / "working"
    cfg, pm = _build_translation_config(
        bb,
        pdf_path=resolved["source_pdf"],
        pages_spec=payload.get("pages_spec"),
        out_dir=out_dir,
        work_dir=work_dir,
        load_layout_model=False,
    )
    session = ExtractSession(
        session_id=session_id,
        pdf_path=str(resolved["source_pdf"]),
        pages_spec=payload.get("pages_spec"),
        work_dir=work_dir,
        out_dir=out_dir,
        bb=bb,
        cfg=cfg,
        docs=None,
        temp_pdf_path=str(resolved["working_pdf"]),
        mediabox_data=mediabox_data,
        pm=pm,
        paragraphs=paragraphs,
        styles_path=out_dir / "styles_and_formulas.json",
        snapshot_path=resolved["il_snapshot"],
        snapshot_sha256=hashes["il_snapshot"],
        restored=True,
        preserved_paragraph_ids=tuple(preserved_ids),
    )
    try:
        docs = load_session_docs(session)
    except RuntimeError as error:
        if str(error) == "session IL snapshot checksum mismatch":
            raise RuntimeError(
                "session snapshot checksum mismatch: il_snapshot"
            ) from error
        raise
    _validate_docs_against_paragraphs(docs, paragraphs, session.preserved_paragraph_ids)
    return session, docs


def _record_preserved_paragraph(
    warnings: list[dict[str, str]], paragraph_id: str, stage: str, error: ValueError
) -> None:
    warnings.append(
        {
            "paragraph_id": paragraph_id,
            "stage": stage,
            "reason": str(error),
            "action": "preserved_original",
        }
    )
    logger.warning(
        "PDF paragraph %s kept in its original language and layout after %s failed: %s",
        paragraph_id,
        stage,
        error,
    )


def extract_to_session(
    *,
    session_id: str,
    pdf_path: Path,
    pages_spec: str | None,
    out_dir: Path,
) -> ExtractSession:
    from wenyi_babeldoc_bridge.schema import (  # type: ignore
        paragraphs_from_projected_il,
        validate_paragraph_document,
    )

    bb = require_babeldoc()
    out_dir = out_dir.resolve()
    work_dir = out_dir / "working"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    cfg, pm = _build_translation_config(
        bb,
        pdf_path=pdf_path,
        pages_spec=pages_spec,
        out_dir=out_dir,
        work_dir=work_dir,
        load_layout_model=True,
    )
    hl = bb["hl"]

    temp_pdf_path = cfg.get_working_file_path("input.pdf")
    doc_pdf2zh = bb["Document"](str(pdf_path))
    try:
        links = capture_links(doc_pdf2zh)
        hl.safe_save(doc_pdf2zh, temp_pdf_path)
        try:
            hl.fix_null_page_content(doc_pdf2zh)
            hl.fix_filter(doc_pdf2zh)
            hl.fix_null_xref(doc_pdf2zh)
        except Exception:
            logger.debug("Optional PDF repair failed", exc_info=True)
        mediabox_data = hl.fix_media_box(doc_pdf2zh)
        hl.safe_save(doc_pdf2zh, temp_pdf_path)

        docs = bb["parse_prepared_pdf"](temp_pdf_path, config=cfg, doc_pdf=doc_pdf2zh)
        if hl.check_cid_char(docs):
            raise RuntimeError("too many CID chars")

        layout = bb["LayoutParser"](cfg)
        chain_layout = can_chain_layout(docs, layout, bb["ParagraphFinder"])
        if chain_layout:
            docs = layout.process(docs, doc_pdf2zh, _refresh=False)
        else:
            docs = layout.process(docs, doc_pdf2zh)
    finally:
        doc_pdf2zh.close()
    finder = bb["ParagraphFinder"](cfg)
    if chain_layout:
        finder.process(docs, _sync=False)
    else:
        finder.process(docs)
    warnings: list[dict[str, str]] = []
    preserved_ids: set[str] = set()
    source_offsets = {}
    row_structures = {}
    for page in docs.page:
        number = int(page.page_number)
        offsets = source_offsets.setdefault(number, {})
        structures = row_structures.setdefault(number, {})
        for index, para in enumerate(page.pdf_paragraph or []):
            if not is_translatable_paragraph(para):
                continue
            try:
                mapping = source_glyph_offsets(para)
            except ValueError as error:
                pid = make_paragraph_id(number, index)
                preserved_ids.add(pid)
                _record_preserved_paragraph(warnings, pid, "source_mapping", error)
                continue
            offsets[index] = mapping
            structures[index] = capture_rows(para, mapping)
    bb["StylesAndFormulas"](cfg).process(docs)

    pages_by_number = {int(page.page_number): page for page in docs.page}
    attachments = {
        number: attach_math_marks(
            page,
            source_offsets[number],
            bb=bb,
            excluded={
                index
                for index, structure in row_structures[number].items()
                if structure.rows
            },
        )
        for number, page in pages_by_number.items()
    }

    styles_path = out_dir / "styles_and_formulas.json"
    if _debug_enabled():
        bb["XMLConverter"]().write_json(docs.document, str(styles_path))
    paragraphs = paragraphs_from_projected_il(
        docs.page, source_pdf=str(pdf_path), pages_spec=pages_spec
    )
    paragraphs.links = links
    links_by_page: dict[int, list[dict[str, Any]]] = {}
    for link in links:
        links_by_page.setdefault(link["page"], []).append(link)
    for unit in paragraphs.paragraphs:
        if unit.id in preserved_ids:
            continue
        para = pages_by_number[unit.page].pdf_paragraph[unit.index]
        try:
            source, unit.annotations, boundaries = prepare_protected_annotations(
                para,
                links_by_page.get(unit.page, []),
                fonts=pages_by_number[unit.page].pdf_font,
                bb=bb,
                offsets=source_offsets[unit.page][unit.index],
                attachments=attachments[unit.page].get(unit.index, ()),
                fixed_glyphs=row_structures[unit.page][unit.index].markers,
            )
        except ValueError as error:
            preserved_ids.add(unit.id)
            _record_preserved_paragraph(warnings, unit.id, "object_protection", error)
            continue
        if source != unit.source:
            # Editable prose omits formulas; annotations carry read-only references.
            # Keep the full source internally for frozen-graph recovery validation.
            unit.original_source, unit.source = unit.source, source
        rows = row_structures[unit.page][unit.index].rows
        if rows:
            try:
                rows = remap_source_rows(source, rows, boundaries)
                items = unit.annotations
                markers = row_structures[unit.page][unit.index].markers
                if markers:
                    items = anchor_row_markers(para, items, rows, markers)
                items = partition_row_annotations(items, rows)
            except ValueError as error:
                logger.info(
                    "Structured rows are ambiguous after object protection; "
                    "keep paragraph %s: %s",
                    unit.id,
                    error,
                )
            else:
                unit.rows, unit.annotations = rows, items
    # A formula-only paragraph has no translatable prose. Keep its frozen IL,
    # like display equations already omitted by the native paragraph selector.
    # Original paragraph positions/IDs are never renumbered.
    paragraphs.paragraphs = [
        unit
        for unit in paragraphs.paragraphs
        if unit.source.strip() and unit.id not in preserved_ids
    ]
    errors = validate_paragraph_document(paragraphs)
    if errors:
        raise RuntimeError("paragraph export invalid: " + "; ".join(errors))
    (out_dir / "extraction_warnings.json").write_text(
        json.dumps(warnings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    paragraphs.write_json(out_dir / "paragraphs.json")

    session = ExtractSession(
        session_id=session_id,
        pdf_path=str(pdf_path),
        pages_spec=pages_spec,
        work_dir=work_dir,
        out_dir=out_dir,
        bb=bb,
        cfg=cfg,
        docs=docs,
        temp_pdf_path=temp_pdf_path,
        mediabox_data=mediabox_data,
        pm=pm,
        paragraphs=paragraphs,
        styles_path=styles_path,
        snapshot_path=out_dir / SESSION_IL_NAME,
        snapshot_sha256="",
        preserved_paragraph_ids=tuple(sorted(preserved_ids)),
    )
    persist_session_snapshot(session)
    session.docs = None
    return session


def _composition_line_groups(para) -> list[list]:
    """Group paragraph compositions into visual lines by vertical position."""
    comps = list(para.pdf_paragraph_composition or [])
    if not comps:
        return []

    def _y_center(comp) -> float | None:
        ssc = getattr(comp, "pdf_same_style_characters", None) or getattr(
            comp, "pdf_same_style_unicode_characters", None
        )
        box = getattr(ssc, "box", None) if ssc is not None else None
        if box is None:
            return None
        return (float(box.y) + float(box.y2)) / 2.0

    # Sort top-to-bottom in PDF coords (larger y first).
    indexed = [(i, comp, _y_center(comp)) for i, comp in enumerate(comps)]
    indexed.sort(key=lambda row: (-(row[2] if row[2] is not None else 0.0), row[0]))

    groups: list[list] = []
    current: list = []
    current_y: float | None = None
    for _i, comp, y in indexed:
        if y is None:
            if current:
                groups.append(current)
                current = []
                current_y = None
            groups.append([comp])
            continue
        if current_y is None or abs(y - current_y) <= 6.0:
            current.append(comp)
            current_y = y if current_y is None else (current_y + y) / 2.0
        else:
            groups.append(current)
            current = [comp]
            current_y = y
    if current:
        groups.append(current)
    return groups


def _style_from_group(group, para):
    for comp in group:
        ssc = getattr(comp, "pdf_same_style_characters", None)
        if ssc is not None and getattr(ssc, "pdf_style", None) is not None:
            return ssc.pdf_style
        uni = getattr(comp, "pdf_same_style_unicode_characters", None)
        if uni is not None and getattr(uni, "pdf_style", None) is not None:
            return uni.pdf_style
    return para.pdf_style


def _merge_group_box(group, fallback_box):
    from babeldoc.format.pdf.document_il.il_version_1 import Box

    xs0, ys0, xs1, ys1 = [], [], [], []
    for comp in group:
        ssc = getattr(comp, "pdf_same_style_characters", None) or getattr(
            comp, "pdf_same_style_unicode_characters", None
        )
        box = getattr(ssc, "box", None) if ssc is not None else None
        if box is None:
            continue
        xs0.append(float(box.x))
        ys0.append(float(box.y))
        xs1.append(float(box.x2))
        ys1.append(float(box.y2))
    if not xs0:
        return fallback_box
    return Box(x=min(xs0), y=min(ys0), x2=max(xs1), y2=max(ys1))


def inject_paragraph_translation(bb: dict, para, text: str) -> list:
    """Write translation into one or more paragraphs.

    Typesetting flattens all compositions in a paragraph into one reflow stream.
    So newline-separated TOC lines must become **separate PdfParagraph**s (each
    with its original visual-line box), not multiple compositions in one para.
    Returns the paragraph list to splice in place of ``para`` (length >= 1).
    """
    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraph

    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        lines = [text]

    groups = _composition_line_groups(para)
    PdfParagraphComposition = bb["PdfParagraphComposition"]
    PdfSameStyleUnicodeCharacters = bb["PdfSameStyleUnicodeCharacters"]

    def _one(line: str, style, box) -> object:
        new_para = PdfParagraph(
            box=box,
            pdf_style=style or para.pdf_style,
            pdf_paragraph_composition=[],
            xobj_id=para.xobj_id,
            unicode=line,
            scale=para.scale,
            optimal_scale=None,
            vertical=para.vertical,
            first_line_indent=False,
            debug_id=para.debug_id,
            layout_label=para.layout_label,
            layout_id=para.layout_id,
            render_order=para.render_order,
        )
        comp = PdfParagraphComposition()
        style_run = PdfSameStyleUnicodeCharacters()
        style_run.unicode = line
        style_run.pdf_style = style or para.pdf_style
        comp.pdf_same_style_unicode_characters = style_run
        new_para.pdf_paragraph_composition = [comp]
        return new_para

    if len(groups) == len(lines) and len(groups) > 1:
        return [
            _one(
                line, _style_from_group(group, para), _merge_group_box(group, para.box)
            )
            for group, line in zip(groups, lines, strict=True)
        ]

    # Fallback: single paragraph, may reflow inside original box.
    para.unicode = "\n".join(lines)
    comp = PdfParagraphComposition()
    style_run = PdfSameStyleUnicodeCharacters()
    style_run.unicode = "\n".join(lines)
    style_run.pdf_style = para.pdf_style
    comp.pdf_same_style_unicode_characters = style_run
    para.pdf_paragraph_composition = [comp]
    return [para]


def fillback_session(
    session: ExtractSession,
    translations: dict[str, str],
    annotations: dict[str, dict[str, Any]] | None = None,
    *,
    rows: dict[str, list[dict[str, int]]] | None = None,
    statistics: dict[str, Any] | None = None,
    _pristine_docs: Any | None = None,
    _render_dir: Path | None = None,
) -> Path:
    """Fill back a fresh graph, optionally just validated by this operation."""
    from wenyi_babeldoc_bridge.schema import (  # type: ignore
        TranslationDocument,
        validate_translations_against_paragraphs,
    )

    trans_doc = TranslationDocument(
        source_pdf=session.pdf_path, translations=translations
    )
    errors = validate_translations_against_paragraphs(session.paragraphs, trans_doc)
    if errors:
        raise ValueError("translations invalid: " + "; ".join(errors))
    # A cold HTTP restore already loaded and validated this request's pristine
    # copy. Otherwise read the frozen IL here. Never mutate a cached projection.
    docs = load_session_docs(session) if _pristine_docs is None else _pristine_docs
    out_dir = session.out_dir if _render_dir is None else _render_dir
    units = {unit.id: unit for unit in session.paragraphs.paragraphs}
    preserved_ids = set(session.preserved_paragraph_ids)
    preserved = {
        make_paragraph_id(int(page.page_number), index): para
        for page in docs.page
        for index, para in enumerate(page.pdf_paragraph or [])
        if is_passthrough_paragraph(para)
        or make_paragraph_id(int(page.page_number), index) in preserved_ids
    }
    annotations = annotations or {}
    if set(annotations) - set(units):
        raise ValueError("unknown paragraph ids in PDF annotations")
    target_rows = rows or {}
    if any(
        pid not in units or (pid not in preserved and not units[pid].rows)
        for pid in target_rows
    ):
        raise ValueError("unknown structured paragraph ids in PDF rows")
    for pid, unit in units.items():
        if pid not in preserved and unit.rows:
            validate_target_rows(
                translations[pid], target_rows.get(pid), count=len(unit.rows)
            )
    trans_doc.rows = target_rows
    aligned: dict[str, list[dict[str, Any]]] = {}
    skipped: dict[str, dict[str, str]] = {pid: {} for pid in units}
    for pid, unit in units.items():
        if pid in preserved:
            continue
        if not unit.annotations and pid not in annotations:
            continue
        text = translations[pid]
        payload = annotations.get(pid, {})
        if not payload and text == unit.source:
            payload = {
                "target_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "placements": [
                    {
                        "id": item["id"],
                        "mode": item["mode"],
                        "target_start": item["source_start"],
                        "target_end": item["source_end"],
                        "target_order": order,
                        "status": "aligned",
                    }
                    for order, item in enumerate(unit.annotations)
                ],
            }
        skipped[pid] = {}
        aligned[pid] = validate_annotation_placements(
            unit.annotations, text, payload, skipped=skipped[pid]
        )
        trans_doc.annotations[pid] = payload
    trans_doc.write_json(out_dir / "translations.json")

    bb = session.bb
    missing: list[str] = []
    injected = 0
    split_paragraphs = 0
    split_groups = []
    render_plans = []
    for page in docs.page:
        # Build replacements against original indices, then apply in reverse.
        replacements: list[tuple[int, list]] = []
        for index, para in enumerate(list(page.pdf_paragraph or [])):
            pid = make_paragraph_id(int(page.page_number), index)
            if not is_translatable_paragraph(para):
                continue
            if pid not in units:
                continue
            zh = translations.get(pid)
            if zh is None:
                missing.append(pid)
                continue
            unit = units[pid]
            restore_protected_formula_baselines(para, unit.annotations)
            if unit.rows:
                new_paras, plans = inject_rows(
                    bb,
                    para,
                    unit,
                    zh,
                    target_rows[pid],
                    aligned.get(pid, []),
                    skipped[pid],
                )
                render_plans.extend((pid, *plan) for plan in plans)
            elif unit.annotations:
                placements = aligned[pid]
                plan = inject_aligned_translation(
                    bb, para, zh, unit.annotations, placements, skipped=skipped[pid]
                )
                render_plans.append((pid, para, plan, unit.annotations, placements))
                new_paras = [para]
            else:
                new_paras = inject_paragraph_translation(bb, para, zh)
            replacements.append((index, new_paras))
            injected += 1
            if len(new_paras) > 1:
                split_paragraphs += 1
                split_groups.append(new_paras)
        for index, new_paras in sorted(
            replacements, key=lambda row: row[0], reverse=True
        ):
            page.pdf_paragraph[index : index + 1] = new_paras
    if missing:
        raise ValueError(f"missing translation ids: {missing[:5]}")
    if injected == 0 and not preserved:
        raise ValueError("no paragraphs to fill back")

    (out_dir / "inject_stats.json").write_text(
        json.dumps(
            {
                "injected": injected,
                "preserved_vertical": sum(
                    bool(getattr(para, "vertical", False))
                    for para in preserved.values()
                ),
                "preserved_numeric": sum(
                    is_numeric_text(para.unicode) for para in preserved.values()
                ),
                "split_into_line_paragraphs": split_paragraphs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if _render_dir is None:
        cfg, pm = session.cfg, session.pm
        # Honour the current env even if the probe extracted with debug on.
        cfg.debug = _debug_enabled()
    else:
        cfg, pm = _build_translation_config(
            bb,
            pdf_path=Path(session.pdf_path),
            pages_spec=session.pages_spec,
            out_dir=out_dir,
            work_dir=out_dir / "working",
            load_layout_model=False,
        )
    if not cfg.debug:
        _strip_debug_overlays(docs)

    def has_link_bindings(items):
        return any(item["kind"] == "link" or item.get("link_ids") for item in items)

    # Only link geometry consumes a rendered projection. Style/formula plans
    # without links have nothing to resolve. Row draw order is a separate edit.
    render_links = [
        (pid, para, plan, items, placements)
        for pid, para, plan, items, placements in render_plans
        if has_link_bindings(items)
    ]
    legacy_links = [
        (para, units[pid].annotations)
        for pid, para in preserved.items()
        if pid in units and has_link_bindings(units[pid].annotations)
    ]
    typesetter = bb["Typesetting"](cfg)
    chain_write = can_chain_write(docs, typesetter, bb["PDFCreater"])
    native_pages = None
    if chain_write:
        # Native typesetting changes glyphs/paragraphs, not the selected pages.
        native_pages = [int(page.page_number) for page in docs.page]
        typesetter.typesetting_document(
            docs, _refresh=bool(split_groups or render_links or legacy_links)
        )
    else:
        typesetter.typesetting_document(docs)
    for group in split_groups:
        sequence_row_glyphs(group)
    link_rectangles: dict[str, list[list[float]]] = {}
    original_links = {link["id"]: link for link in session.paragraphs.links}
    for para, items in legacy_links:
        # Legacy sessions marked fixed-glyph links as text-bound. Restore their
        # original geometry even if the client supplied changed or failed alignment.
        for link_id, boxes in original_link_rectangles(
            para, items, original_links, skipped={}
        ).items():
            link_rectangles.setdefault(link_id, []).extend(boxes)
    for pid, para, plan, items, placements in render_links:
        for link_id, boxes in layout_link_rectangles(
            para, plan, items, placements, skipped=skipped[pid]
        ).items():
            link_rectangles.setdefault(link_id, []).extend(boxes)
    creator = bb["PDFCreater"](session.temp_pdf_path, docs, cfg, session.mediabox_data)
    # Link lookup was read-only. Row sequencing, unlike link lookup, changed
    # the projection and still needs to be imported by the writer.
    if native_pages is not None and not split_groups:
        result = creator.write(cfg, _native_pages=native_pages)
    else:
        result = creator.write(cfg)
    mono = result.no_watermark_mono_pdf_path or result.mono_pdf_path
    if mono is None:
        raise RuntimeError("no mono PDF produced")
    out_pdf = out_dir / "fillback.mono.pdf"
    with tempfile.NamedTemporaryFile(
        dir=out_dir, prefix=".fillback-", suffix=".pdf", delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(mono, temporary)
        if session.paragraphs.links:
            page_numbers = sorted(
                number
                for number in (
                    native_pages
                    if native_pages is not None
                    else (int(page.page_number) for page in docs.page)
                )
                if cfg.should_translate_page(number + 1)
            )
            restore_links(
                temporary, session.paragraphs.links, page_numbers, link_rectangles
            )
        os.replace(temporary, out_pdf)
    finally:
        temporary.unlink(missing_ok=True)
    details = []
    for pid, placements in aligned.items():
        accepted_ids = {placement["id"] for placement in placements}
        for item in units[pid].annotations:
            reason = skipped[pid].get(item["id"])
            details.append(
                {
                    "paragraph_id": pid,
                    "id": item["id"],
                    "kind": item["kind"],
                    "source_identity": translations[pid] == units[pid].source,
                    "aligned": item["id"] in accepted_ids,
                    "reason": reason,
                }
            )
            if reason:
                logger.info(
                    "PDF annotation skipped: paragraph=%s item=%s kind=%s reason=%s",
                    pid,
                    item["id"],
                    item["kind"],
                    reason,
                )
    summary = summarize_annotations(details)
    _atomic_write_json(
        out_dir / "annotation_stats.json",
        {"summary": summary, "items": details},
    )
    logger.info("PDF annotation statistics: %s", json.dumps(summary, sort_keys=True))
    if statistics is not None:
        statistics.clear()
        statistics.update(summary)
    try:
        pm.translate_done(result)
    except Exception:
        pass
    return out_pdf
