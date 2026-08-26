#!/usr/bin/env python3
"""Run BabelDOC up to styles/formulas (skip translation) and export paragraphs.json.

Requires an isolated venv with babeldoc installed. See README.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _require_babeldoc():
    try:
        import babeldoc  # noqa: F401
        from babeldoc.docvision.doclayout import DocLayoutModel
        from babeldoc.format.pdf.high_level import translate
        from babeldoc.format.pdf.translation_config import TranslationConfig, WatermarkOutputMode
        from babeldoc.translator.translator import BaseTranslator
    except ImportError as error:
        raise SystemExit(
            "babeldoc is not importable in this interpreter.\n"
            "Create an isolated venv (do not use Wenyi's main .venv):\n"
            "  uv venv /tmp/wenyi-babeldoc-venv --python 3.12\n"
            "  uv pip install --python /tmp/wenyi-babeldoc-venv/bin/python "
            "'babeldoc>=0.5.20,<0.6.0'\n"
            "Then rerun with that python."
        ) from error
    return DocLayoutModel, translate, TranslationConfig, WatermarkOutputMode, BaseTranslator


def _identity_translator(BaseTranslator):
    class IdentityTranslator(BaseTranslator):
        name = "identity"

        def __init__(self):
            super().__init__("en", "zh-CN", ignore_cache=True)

        def do_translate(self, text, rate_limit_params=None):
            return text

        def do_llm_translate(self, text, rate_limit_params=None):
            return text

    return IdentityTranslator()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path, help="Input PDF path")
    parser.add_argument(
        "--pages",
        default=None,
        help="BabelDOC pages spec (1-based), e.g. 15 or 14-16",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output directory for paragraphs.json + frozen IL",
    )
    args = parser.parse_args(argv)

    pdf = args.pdf.expanduser().resolve()
    if not pdf.is_file():
        raise SystemExit(f"PDF not found: {pdf}")

    (
        DocLayoutModel,
        translate,
        TranslationConfig,
        WatermarkOutputMode,
        BaseTranslator,
    ) = _require_babeldoc()

    # Import schema from this package directory without installing.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wenyi_babeldoc_bridge.schema import (  # type: ignore
        load_paragraphs_from_styles_json,
        validate_paragraph_document,
    )

    out_dir = args.out.expanduser().resolve()
    work_dir = out_dir / "working"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        model = DocLayoutModel.load_onnx()
    except Exception:
        model = DocLayoutModel.load_available()

    config_kwargs = dict(
        translator=_identity_translator(BaseTranslator),
        input_file=pdf,
        lang_in="en",
        lang_out="zh-CN",
        doc_layout_model=model,
        output_dir=out_dir,
        working_dir=work_dir,
        debug=True,
        skip_translation=True,
        no_dual=True,
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        skip_scanned_detection=True,
        auto_extract_glossary=False,
    )
    if args.pages:
        config_kwargs["pages"] = args.pages

    print(f"[probe] pdf={pdf}", flush=True)
    print(f"[probe] pages={args.pages!r} out={out_dir}", flush=True)
    translate(TranslationConfig(**config_kwargs))

    styles_hits = list(work_dir.rglob("styles_and_formulas.json"))
    if not styles_hits:
        raise SystemExit("styles_and_formulas.json not found; debug dump missing")
    styles_path = styles_hits[0]
    frozen = out_dir / "styles_and_formulas.json"
    frozen.write_bytes(styles_path.read_bytes())

    doc = load_paragraphs_from_styles_json(
        frozen,
        source_pdf=str(pdf),
        pages_spec=args.pages,
    )
    errors = validate_paragraph_document(doc)
    if errors:
        raise SystemExit("paragraphs.json validation failed:\n- " + "\n- ".join(errors))

    paragraphs_path = doc.write_json(out_dir / "paragraphs.json")
    summary = {
        "source_pdf": str(pdf),
        "pages_spec": args.pages,
        "paragraph_count": len(doc.paragraphs),
        "with_debug_id": sum(1 for p in doc.paragraphs if p.debug_id),
        "with_placeholders": sum(1 for p in doc.paragraphs if p.has_placeholders),
        "sample": [
            {
                "id": p.id,
                "debug_id": p.debug_id,
                "layout_label": p.layout_label,
                "source_preview": p.source[:120],
            }
            for p in doc.paragraphs[:8]
        ],
        "styles_and_formulas": str(frozen),
        "paragraphs_json": str(paragraphs_path),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
