#!/usr/bin/env python3
"""Round-trip probe: extract paragraphs → apply translations by id → typeset PDF.

This validates the core claim for Wenyi integration:

- BabelDOC can expose paragraph units before translation
- Translations keyed by ``page:index`` can be injected into the *same* in-memory IL
- Typesetting/PDFCreater can emit a PDF containing those translations

Requires an isolated babeldoc venv. See README.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _require_babeldoc():
    try:
        # Import high_level first to avoid babeldoc circular imports.
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
        raise SystemExit(
            "babeldoc/pymupdf not importable. Use the isolated venv from README.md."
        ) from error

    return {
        "DocLayoutModel": DocLayoutModel,
        "PDFCreater": PDFCreater,
        "PdfParagraphComposition": PdfParagraphComposition,
        "PdfSameStyleUnicodeCharacters": PdfSameStyleUnicodeCharacters,
        "LayoutParser": LayoutParser,
        "ParagraphFinder": ParagraphFinder,
        "StylesAndFormulas": StylesAndFormulas,
        "Typesetting": Typesetting,
        "XMLConverter": XMLConverter,
        "ILCreater": hl.ILCreater,
        "ProgressMonitor": hl.ProgressMonitor,
        "check_cid_char": hl.check_cid_char,
        "close_process_pool": hl.close_process_pool,
        "fix_filter": hl.fix_filter,
        "fix_media_box": hl.fix_media_box,
        "fix_null_page_content": hl.fix_null_page_content,
        "fix_null_xref": hl.fix_null_xref,
        "get_translation_stage": hl.get_translation_stage,
        "safe_save": hl.safe_save,
        "start_parse_il": hl.start_parse_il,
        "TranslationConfig": TranslationConfig,
        "WatermarkOutputMode": WatermarkOutputMode,
        "BaseTranslator": BaseTranslator,
        "Document": Document,
    }


def _identity_translator(BaseTranslator):
    class IdentityTranslator(BaseTranslator):
        name = "identity"

        def __init__(self):
            super().__init__("en", "zh-CN", ignore_cache=True)

        def do_translate(self, text, rate_limit_params=None):
            return text

        def do_llm_translate(self, text, rate_limit_params=None):
            raise NotImplementedError

    return IdentityTranslator()


def _fake_translation(index: int, source: str) -> str:
    # Keep enough source for visual spot-check; prefix proves injection.
    return f"[假回填{index}]{source[:80]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--pages", default="15", help="BabelDOC 1-based pages spec")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--translations",
        type=Path,
        default=None,
        help="Optional translations.json; default = synthetic markers",
    )
    args = parser.parse_args(argv)

    pdf = args.pdf.expanduser().resolve()
    if not pdf.is_file():
        raise SystemExit(f"PDF not found: {pdf}")

    bb = _require_babeldoc()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wenyi_babeldoc_bridge.schema import (  # type: ignore
        TranslationDocument,
        is_translatable_unicode,
        load_paragraphs_from_styles_json,
        make_paragraph_id,
        validate_paragraph_document,
        validate_translations_against_paragraphs,
    )

    out_dir = args.out.expanduser().resolve()
    work_dir = out_dir / "working"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        model = bb["DocLayoutModel"].load_onnx()
    except Exception:
        model = bb["DocLayoutModel"].load_available()

    cfg = bb["TranslationConfig"](
        translator=_identity_translator(bb["BaseTranslator"]),
        input_file=pdf,
        lang_in="en",
        lang_out="zh-CN",
        doc_layout_model=model,
        output_dir=out_dir,
        working_dir=work_dir,
        debug=True,
        skip_translation=True,
        pages=args.pages,
        no_dual=True,
        watermark_output_mode=bb["WatermarkOutputMode"].NoWatermark,
        skip_scanned_detection=True,
        auto_extract_glossary=False,
        only_include_translated_page=True,
    )
    pm = bb["ProgressMonitor"](bb["get_translation_stage"](cfg))
    cfg.progress_monitor = pm

    print(f"[fillback] parse+layout pdf={pdf} pages={args.pages!r}", flush=True)
    temp_pdf_path = cfg.get_working_file_path("input.pdf")
    doc_pdf2zh = bb["Document"](str(pdf))
    bb["safe_save"](doc_pdf2zh, temp_pdf_path)
    try:
        bb["fix_null_page_content"](doc_pdf2zh)
        bb["fix_filter"](doc_pdf2zh)
        bb["fix_null_xref"](doc_pdf2zh)
    except Exception:
        pass
    mediabox_data = bb["fix_media_box"](doc_pdf2zh)
    bb["safe_save"](doc_pdf2zh, temp_pdf_path)

    il_creater = bb["ILCreater"](cfg)
    il_creater.mupdf = doc_pdf2zh
    with Path(temp_pdf_path).open("rb") as handle:
        bb["start_parse_il"](
            handle,
            doc_zh=doc_pdf2zh,
            resfont=None,
            il_creater=il_creater,
            translation_config=cfg,
        )
    docs = il_creater.create_il()
    del il_creater
    if bb["check_cid_char"](docs):
        raise SystemExit("too many CID chars")

    docs = bb["LayoutParser"](cfg).process(docs, doc_pdf2zh)
    bb["close_process_pool"]()
    bb["ParagraphFinder"](cfg).process(docs)
    bb["StylesAndFormulas"](cfg).process(docs)

    xml = bb["XMLConverter"]()
    styles_path = out_dir / "styles_and_formulas.json"
    xml.write_json(docs, str(styles_path))

    para_doc = load_paragraphs_from_styles_json(
        styles_path, source_pdf=str(pdf), pages_spec=args.pages
    )
    errors = validate_paragraph_document(para_doc)
    if errors:
        raise SystemExit("paragraph export invalid:\n- " + "\n- ".join(errors))
    para_doc.write_json(out_dir / "paragraphs.json")

    if args.translations:
        raw = json.loads(args.translations.read_text(encoding="utf-8"))
        mapping = raw.get("translations") or raw
        if not isinstance(mapping, dict):
            raise SystemExit("translations file must be {id: text} or wrapped object")
        trans_doc = TranslationDocument(source_pdf=str(pdf), translations=mapping)
    else:
        mapping = {
            unit.id: _fake_translation(i + 1, unit.source)
            for i, unit in enumerate(para_doc.paragraphs)
        }
        trans_doc = TranslationDocument(source_pdf=str(pdf), translations=mapping)
    trans_doc.write_json(out_dir / "translations.json")
    terrors = validate_translations_against_paragraphs(para_doc, trans_doc)
    if terrors:
        raise SystemExit("translations invalid:\n- " + "\n- ".join(terrors))

    injected = 0
    missing = []
    for page in docs.page:
        for index, para in enumerate(page.pdf_paragraph or []):
            pid = make_paragraph_id(int(page.page_number), index)
            src = para.unicode or ""
            if not is_translatable_unicode(src):
                continue
            zh = mapping.get(pid)
            if zh is None:
                missing.append(pid)
                continue
            para.unicode = zh
            comp = bb["PdfParagraphComposition"]()
            style_run = bb["PdfSameStyleUnicodeCharacters"]()
            style_run.unicode = zh
            style_run.pdf_style = para.pdf_style
            comp.pdf_same_style_unicode_characters = style_run
            para.pdf_paragraph_composition = [comp]
            injected += 1
    if missing:
        raise SystemExit(f"missing translation ids during inject: {missing[:5]}")

    print(f"[fillback] injected {injected} paragraphs; typesetting...", flush=True)
    bb["Typesetting"](cfg).typesetting_document(docs)
    result = bb["PDFCreater"](temp_pdf_path, docs, cfg, mediabox_data).write(cfg)
    mono = result.no_watermark_mono_pdf_path or result.mono_pdf_path
    if mono is None:
        raise SystemExit("no mono PDF produced")

    import pymupdf

    out_pdf = out_dir / "fillback.mono.pdf"
    out_pdf.write_bytes(Path(mono).read_bytes())

    doc = pymupdf.open(str(out_pdf))
    hit_pages = []
    marker_hits = 0
    for i, page in enumerate(doc):
        text = page.get_text()
        count = text.count("假回填")
        if count:
            hit_pages.append(i)
            marker_hits += count
    sample_lines = []
    if hit_pages:
        for line in doc[hit_pages[0]].get_text().splitlines():
            if "假回填" in line:
                sample_lines.append(line[:160])
            if len(sample_lines) >= 8:
                break

    summary = {
        "ok": marker_hits > 0,
        "paragraph_count": len(para_doc.paragraphs),
        "injected": injected,
        "output_pdf": str(out_pdf),
        "output_pages": doc.page_count,
        "marker_hits": marker_hits,
        "hit_pages": hit_pages,
        "sample_lines": sample_lines,
        "paragraphs_json": str(out_dir / "paragraphs.json"),
        "translations_json": str(out_dir / "translations.json"),
        "styles_and_formulas": str(styles_path),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    try:
        pm.translate_done(result)
    except Exception:
        pass
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
