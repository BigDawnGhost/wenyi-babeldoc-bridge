"""In-process BabelDOC extract / inject / typeset helpers (AGPL side only)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def require_babeldoc() -> dict[str, Any]:
    try:
        # Import high_level first to avoid circular imports.
        from babeldoc.docvision.doclayout import DocLayoutModel
        from babeldoc.format.pdf import high_level as hl
        from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
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
    """Holds one frozen IL in memory for later fillback."""

    session_id: str
    pdf_path: str
    pages_spec: str | None
    work_dir: Path
    out_dir: Path
    bb: dict[str, Any]
    cfg: Any
    docs: Any
    temp_pdf_path: str
    mediabox_data: Any
    pm: Any
    paragraphs: Any
    styles_path: Path


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
        debug=True,
        skip_translation=True,
        pages=pages_spec,
        no_dual=True,
        watermark_output_mode=bb["WatermarkOutputMode"].NoWatermark,
        skip_scanned_detection=True,
        auto_extract_glossary=False,
        only_include_translated_page=True,
    )
    hl = bb["hl"]
    pm = hl.ProgressMonitor(hl.get_translation_stage(cfg))
    cfg.progress_monitor = pm

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

    return ExtractSession(
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
    )


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
    docs = session.docs
    missing: list[str] = []
    injected = 0
    split_paragraphs = 0
    for page in docs.page:
        # Build replacements against original indices, then apply in reverse.
        replacements: list[tuple[int, list]] = []
        for index, para in enumerate(list(page.pdf_paragraph or [])):
            pid = make_paragraph_id(int(page.page_number), index)
            src = para.unicode or ""
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
