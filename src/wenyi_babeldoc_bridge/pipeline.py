"""In-process BabelDOC extract / inject / typeset helpers (AGPL side only)."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import warnings
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

SESSION_SNAPSHOT_SCHEMA = "wenyi-babeldoc-session/v1"
SESSION_MANIFEST_NAME = "session.json"
SESSION_IL_NAME = "styles_and_formulas.pickle"
SESSION_MEDIABOX_NAME = "mediabox.json"


def require_babeldoc() -> dict[str, Any]:
    try:
        # Import high_level first to avoid circular imports.
        from babeldoc.docvision.doclayout import DocLayoutModel
        from babeldoc.format.pdf import high_level as hl
        from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
        from babeldoc.format.pdf.document_il.il_version_1 import Document as ILDocument
        from babeldoc.format.pdf.document_il.il_version_1 import (
            PdfParagraphComposition,
            PdfSameStyleUnicodeCharacters,
        )
        from babeldoc.format.pdf.document_il.midend.layout_parser import LayoutParser
        from babeldoc.format.pdf.document_il.midend.paragraph_finder import (
            ParagraphFinder,
        )
        from babeldoc.format.pdf.document_il.midend.styles_and_formulas import (
            StylesAndFormulas,
        )
        from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
        from babeldoc.format.pdf.document_il.xml_converter import XMLConverter
        from babeldoc.format.pdf.translation_config import (
            TranslationConfig,
            WatermarkOutputMode,
        )
        from babeldoc.translator.translator import BaseTranslator
        from pymupdf import Document
    except ImportError as error:
        raise RuntimeError(
            "babeldoc not importable; use the isolated venv from README.md"
        ) from error

    return {
        "hl": hl,
        "DocLayoutModel": DocLayoutModel,
        "PDFCreater": PDFCreater,
        "PdfParagraphComposition": PdfParagraphComposition,
        "PdfSameStyleUnicodeCharacters": PdfSameStyleUnicodeCharacters,
        "DocumentIL": ILDocument,
        "LayoutParser": LayoutParser,
        "ParagraphFinder": ParagraphFinder,
        "StylesAndFormulas": StylesAndFormulas,
        "Typesetting": Typesetting,
        "XMLConverter": XMLConverter,
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


def _atomic_write_pickle(path: Path, value: Any) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("wb") as handle:
        pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temp_path, path)


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


def _is_debug_overlay_paragraph(para: Any) -> bool:
    """Return whether a paragraph is a BabelDOC layout-class overlay label."""
    for composition in para.pdf_paragraph_composition or []:
        style_run = getattr(composition, "pdf_same_style_unicode_characters", None)
        if style_run is not None and getattr(style_run, "debug_info", False):
            return True
    return False


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
    model = None
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

    _atomic_write_pickle(snapshot_path, session.docs)
    _atomic_write_json(mediabox_path, session.mediabox_data or {})

    files = {
        "source_pdf": pdf_path.relative_to(out_dir).as_posix(),
        "working_pdf": temp_pdf_path.relative_to(out_dir).as_posix(),
        "il_snapshot": snapshot_path.name,
        "mediabox": mediabox_path.name,
        "paragraphs": paragraphs_path.name,
    }
    hashes = {
        name: _sha256(out_dir / relative_path) for name, relative_path in files.items()
    }
    manifest = {
        "schema": SESSION_SNAPSHOT_SCHEMA,
        "session_id": session.session_id,
        "pages_spec": session.pages_spec,
        "babeldoc_version": _babeldoc_version(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "files": files,
        "sha256": hashes,
    }
    _atomic_write_json(out_dir / SESSION_MANIFEST_NAME, manifest)
    session.snapshot_path = snapshot_path
    session.snapshot_sha256 = hashes["il_snapshot"]


def load_session_docs(session: ExtractSession) -> Any:
    """Load a fresh copy of the pristine IL so repeated fillback is idempotent."""
    if not session.snapshot_path.is_file():
        raise RuntimeError(f"session IL snapshot missing: {session.snapshot_path}")
    actual = _sha256(session.snapshot_path)
    if actual != session.snapshot_sha256:
        raise RuntimeError("session IL snapshot checksum mismatch")
    with session.snapshot_path.open("rb") as handle:
        docs = pickle.load(handle)  # noqa: S301 - trusted bridge-owned state only
    if not hasattr(docs, "page"):
        raise RuntimeError("session IL snapshot is not a BabelDOC document")
    return docs


def _resolve_session_file(out_dir: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise RuntimeError("session snapshot contains an invalid file path")
    resolved = (out_dir / relative_path).resolve()
    if resolved != out_dir and out_dir not in resolved.parents:
        raise RuntimeError("session snapshot file escapes its session directory")
    return resolved


def _paragraph_pairs_from_docs(docs: Any) -> list[tuple[str, str]]:
    from wenyi_babeldoc_bridge.schema import (  # type: ignore
        is_translatable_unicode,
        make_paragraph_id,
    )

    pairs: list[tuple[str, str]] = []
    for page in docs.page:
        for index, para in enumerate(page.pdf_paragraph or []):
            source = para.unicode or ""
            if is_translatable_unicode(source):
                pairs.append(
                    (make_paragraph_id(int(page.page_number), index), str(source))
                )
    return pairs


def _validate_docs_against_paragraphs(docs: Any, paragraphs: Any) -> None:
    from wenyi_babeldoc_bridge.schema import is_translatable_unicode  # type: ignore

    # Older extracts recorded layout-role overlay tokens (figure_caption, …)
    # as translatable units. Current skip rules ignore them on the IL side.
    expected = [
        (unit.id, unit.source)
        for unit in paragraphs.paragraphs
        if is_translatable_unicode(unit.source)
    ]
    actual = _paragraph_pairs_from_docs(docs)
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


def _load_snake_case_il_json(path: Path, document_class: type) -> Any:
    """Read legacy XMLConverter JSON whose keys use dataclass field names."""
    from xsdata.formats.dataclass.parsers import JsonParser
    from xsdata.utils import collections

    class SnakeCaseJsonParser(JsonParser):
        @classmethod
        def find_var(cls, xml_vars, key, value):
            found = super().find_var(xml_vars, key, value)
            if found is not None:
                return found
            for var in xml_vars:
                if var.name == key and collections.is_array(value) == (
                    var.list_element or var.tokens
                ):
                    return var
            return None

        def bind_dataclass(self, data, clazz):
            instance = super().bind_dataclass(data, clazz)
            xml_vars = self.context.build(clazz).get_all_vars()
            for key, value in data.items():
                var = self.find_var(xml_vars, key, value)
                if var is None or not var.init:
                    continue
                is_primitive_list = isinstance(value, list) and all(
                    not isinstance(item, (dict, list)) for item in value
                )
                if not isinstance(value, (dict, list)) or is_primitive_list:
                    # XML metadata types do not always match the values emitted
                    # by XMLConverter.to_json (for example float CTMs typed as
                    # strings). Preserve the exact frozen JSON scalar values.
                    setattr(instance, var.name, value)
            return instance

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return SnakeCaseJsonParser().from_path(path, document_class)


def _legacy_session(
    *,
    session_id: str,
    out_dir: Path,
) -> ExtractSession:
    """Migrate a completed pre-snapshot session after validating every paragraph."""
    from wenyi_babeldoc_bridge.schema import ParagraphDocument  # type: ignore

    styles_path = out_dir / "styles_and_formulas.json"
    paragraphs_path = out_dir / "paragraphs.json"
    pdf_candidates = [
        path for path in out_dir.glob("*.pdf") if path.name not in {"fillback.mono.pdf"}
    ]
    working_candidates = list(out_dir.glob("working/**/input.pdf"))
    if (
        not styles_path.is_file()
        or not paragraphs_path.is_file()
        or len(pdf_candidates) != 1
        or len(working_candidates) != 1
    ):
        raise FileNotFoundError(f"durable session not found: {session_id}")

    bb = require_babeldoc()
    paragraphs = ParagraphDocument.read_json(paragraphs_path)
    docs = _load_snake_case_il_json(styles_path, bb["DocumentIL"])
    _validate_docs_against_paragraphs(docs, paragraphs)

    pdf_path = pdf_candidates[0].resolve()
    temp_pdf_path = working_candidates[0].resolve()
    work_dir = out_dir / "working"
    cfg, pm = _build_translation_config(
        bb,
        pdf_path=pdf_path,
        pages_spec=paragraphs.pages_spec,
        out_dir=out_dir,
        work_dir=work_dir,
        load_layout_model=False,
    )
    original = bb["Document"](str(pdf_path))
    try:
        mediabox_data = bb["hl"].fix_media_box(original)
    finally:
        original.close()

    session = ExtractSession(
        session_id=session_id,
        pdf_path=str(pdf_path),
        pages_spec=paragraphs.pages_spec,
        work_dir=work_dir,
        out_dir=out_dir,
        bb=bb,
        cfg=cfg,
        docs=docs,
        temp_pdf_path=str(temp_pdf_path),
        mediabox_data=mediabox_data,
        pm=pm,
        paragraphs=paragraphs,
        styles_path=styles_path,
        snapshot_path=out_dir / SESSION_IL_NAME,
        snapshot_sha256="",
        restored=True,
    )
    persist_session_snapshot(session)
    session.docs = None
    return session


def restore_session(*, session_id: str, out_dir: Path) -> ExtractSession:
    """Restore a frozen session without rerunning BabelDOC layout analysis."""
    from wenyi_babeldoc_bridge.schema import ParagraphDocument  # type: ignore

    out_dir = out_dir.resolve()
    manifest_path = out_dir / SESSION_MANIFEST_NAME
    if not manifest_path.is_file():
        return _legacy_session(session_id=session_id, out_dir=out_dir)

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != SESSION_SNAPSHOT_SCHEMA
    ):
        raise RuntimeError("unsupported session snapshot schema")
    if payload.get("session_id") != session_id:
        raise RuntimeError("session snapshot id mismatch")
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
        if _sha256(path) != expected_hash:
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
    )
    docs = load_session_docs(session)
    _validate_docs_against_paragraphs(docs, paragraphs)
    return session


def extract_to_session(
    *,
    session_id: str,
    pdf_path: Path,
    pages_spec: str | None,
    out_dir: Path,
) -> ExtractSession:
    from wenyi_babeldoc_bridge.schema import (  # type: ignore
        load_paragraphs_from_styles_json,
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
    hl.safe_save(doc_pdf2zh, temp_pdf_path)
    try:
        hl.fix_null_page_content(doc_pdf2zh)
        hl.fix_filter(doc_pdf2zh)
        hl.fix_null_xref(doc_pdf2zh)
    except Exception:
        pass
    mediabox_data = hl.fix_media_box(doc_pdf2zh)
    hl.safe_save(doc_pdf2zh, temp_pdf_path)

    il_creater = hl.ILCreater(cfg)
    il_creater.mupdf = doc_pdf2zh
    with Path(temp_pdf_path).open("rb") as handle:
        hl.start_parse_il(
            handle,
            doc_zh=doc_pdf2zh,
            resfont=None,
            il_creater=il_creater,
            translation_config=cfg,
        )
    docs = il_creater.create_il()
    del il_creater
    if hl.check_cid_char(docs):
        raise RuntimeError("too many CID chars")

    docs = bb["LayoutParser"](cfg).process(docs, doc_pdf2zh)
    hl.close_process_pool()
    bb["ParagraphFinder"](cfg).process(docs)
    bb["StylesAndFormulas"](cfg).process(docs)

    styles_path = out_dir / "styles_and_formulas.json"
    bb["XMLConverter"]().write_json(docs, str(styles_path))
    paragraphs = load_paragraphs_from_styles_json(
        styles_path, source_pdf=str(pdf_path), pages_spec=pages_spec
    )
    errors = validate_paragraph_document(paragraphs)
    if errors:
        raise RuntimeError("paragraph export invalid: " + "; ".join(errors))
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
) -> Path:
    from wenyi_babeldoc_bridge.schema import (  # type: ignore
        TranslationDocument,
        is_translatable_unicode,
        make_paragraph_id,
        validate_translations_against_paragraphs,
    )

    trans_doc = TranslationDocument(
        source_pdf=session.pdf_path, translations=translations
    )
    errors = validate_translations_against_paragraphs(session.paragraphs, trans_doc)
    if errors:
        raise ValueError("translations invalid: " + "; ".join(errors))
    trans_doc.write_json(session.out_dir / "translations.json")

    bb = session.bb
    # Typesetting mutates the document. Reloading the frozen post-extraction IL
    # makes a failed or repeated fillback deterministic and idempotent.
    docs = load_session_docs(session)
    missing: list[str] = []
    injected = 0
    split_paragraphs = 0
    for page in docs.page:
        # Build replacements against original indices, then apply in reverse.
        replacements: list[tuple[int, list]] = []
        for index, para in enumerate(list(page.pdf_paragraph or [])):
            pid = make_paragraph_id(int(page.page_number), index)
            src = para.unicode or ""
            if _is_debug_overlay_paragraph(para):
                continue
            if not is_translatable_unicode(src):
                continue
            zh = translations.get(pid)
            if zh is None:
                missing.append(pid)
                continue
            new_paras = inject_paragraph_translation(bb, para, zh)
            replacements.append((index, new_paras))
            injected += 1
            if len(new_paras) > 1:
                split_paragraphs += 1
        for index, new_paras in sorted(
            replacements, key=lambda row: row[0], reverse=True
        ):
            page.pdf_paragraph[index : index + 1] = new_paras
    if missing:
        raise ValueError(f"missing translation ids: {missing[:5]}")
    if injected == 0:
        raise ValueError("no paragraphs injected")

    (session.out_dir / "inject_stats.json").write_text(
        json.dumps(
            {
                "injected": injected,
                "split_into_line_paragraphs": split_paragraphs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Honour the current env even if this session was extracted with debug on.
    session.cfg.debug = _debug_enabled()
    if not session.cfg.debug:
        _strip_debug_overlays(docs)
    bb["Typesetting"](session.cfg).typesetting_document(docs)
    result = bb["PDFCreater"](
        session.temp_pdf_path, docs, session.cfg, session.mediabox_data
    ).write(session.cfg)
    mono = result.no_watermark_mono_pdf_path or result.mono_pdf_path
    if mono is None:
        raise RuntimeError("no mono PDF produced")
    out_pdf = session.out_dir / "fillback.mono.pdf"
    out_pdf.write_bytes(Path(mono).read_bytes())
    try:
        session.pm.translate_done(result)
    except Exception:
        pass
    return out_pdf
