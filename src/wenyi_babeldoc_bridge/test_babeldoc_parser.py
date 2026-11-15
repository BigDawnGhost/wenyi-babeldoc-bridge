"""Exercise native stage wiring without models."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from wenyi_babeldoc_bridge.pipeline import extract_to_session, load_session_docs
from wenyi_babeldoc_bridge.schema import ParagraphDocument, ParagraphUnit
from wenyi_babeldoc_bridge.test_session_snapshot import _FakeDocument


class NativeParserTests(unittest.TestCase):
    def test_mapping_failures_preserve_original_paragraphs_and_stable_sibling_ids(self):
        for stage in ("source_mapping", "object_protection"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source.pdf"
                source.write_bytes(b"%PDF synthetic source")
                cfg = SimpleNamespace(
                    get_working_file_path=lambda _: str(root / "working/input.pdf")
                )
                paras = [
                    SimpleNamespace(
                        unicode=f"Original paragraph {index}.",
                        pdf_paragraph_composition=[object()],
                    )
                    for index in range(3)
                ]
                original = paras[1].pdf_paragraph_composition
                docs = SimpleNamespace(
                    page=[
                        SimpleNamespace(page_number=0, pdf_paragraph=paras, pdf_font=[])
                    ],
                    document=object(),
                )
                paragraphs = ParagraphDocument(
                    source_pdf=str(source),
                    paragraphs=[
                        ParagraphUnit(id=f"0:{i}", page=0, index=i, source=p.unicode)
                        for i, p in enumerate(paras)
                    ],
                )
                hl = MagicMock()
                hl.check_cid_char.return_value = False
                hl.fix_media_box.return_value = {}
                bb = {
                    "hl": hl,
                    "Document": MagicMock(),
                    "parse_prepared_pdf": MagicMock(return_value=docs),
                    "LayoutParser": MagicMock(),
                    "ParagraphFinder": MagicMock(),
                    "StylesAndFormulas": MagicMock(),
                    "XMLConverter": MagicMock(),
                }
                bb["LayoutParser"].return_value.process.return_value = docs

                def offsets(para):
                    if stage == "source_mapping" and para is paras[1]:
                        raise ValueError("synthetic missing source identity")
                    return {}

                def protect(para, *args, **kwargs):
                    if stage == "object_protection" and para is paras[1]:
                        raise ValueError("synthetic unsafe formula boundary")
                    return para.unicode, [], tuple(range(len(para.unicode) + 1))

                with (
                    patch(
                        "wenyi_babeldoc_bridge.pipeline.require_babeldoc",
                        return_value=bb,
                    ),
                    patch(
                        "wenyi_babeldoc_bridge.pipeline._build_translation_config",
                        return_value=(cfg, object()),
                    ),
                    patch(
                        "wenyi_babeldoc_bridge.pipeline.capture_links", return_value=[]
                    ),
                    patch(
                        "wenyi_babeldoc_bridge.pipeline.source_glyph_offsets",
                        side_effect=offsets,
                    ),
                    patch(
                        "wenyi_babeldoc_bridge.pipeline.capture_toc_rows",
                        return_value=[],
                    ),
                    patch(
                        "wenyi_babeldoc_bridge.pipeline.attach_math_marks",
                        return_value={},
                    ),
                    patch(
                        "wenyi_babeldoc_bridge.pipeline.prepare_protected_annotations",
                        side_effect=protect,
                    ),
                    patch(
                        "wenyi_babeldoc_bridge.schema.load_paragraphs_from_styles_json",
                        return_value=paragraphs,
                    ),
                    patch(
                        "wenyi_babeldoc_bridge.pipeline.persist_session_snapshot"
                    ) as freeze,
                    self.assertLogs(
                        "wenyi_babeldoc_bridge.pipeline", level="WARNING"
                    ) as logs,
                ):
                    session = extract_to_session(
                        session_id="a" * 32,
                        pdf_path=source,
                        pages_spec=None,
                        out_dir=root,
                    )
                self.assertEqual(
                    [unit.id for unit in session.paragraphs.paragraphs], ["0:0", "0:2"]
                )
                self.assertIs(paras[1].pdf_paragraph_composition, original)
                self.assertEqual(paras[1].unicode, "Original paragraph 1.")
                freeze.assert_called_once_with(session)
                warnings = json.loads((root / "extraction_warnings.json").read_text())
                self.assertEqual(len(warnings), 1)
                self.assertEqual(warnings[0]["paragraph_id"], "0:1")
                self.assertEqual(warnings[0]["stage"], stage)
                self.assertEqual(warnings[0]["action"], "preserved_original")
                self.assertIn("0:1", logs.output[0])
                self.assertNotIn(paras[1].unicode, logs.output[0])

    def test_extract_uses_prepared_pdf_native_parser_and_freezes_its_il(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF synthetic source")
            working = root / "working" / "input.pdf"
            cfg = SimpleNamespace(get_working_file_path=lambda _: str(working))
            docs = _FakeDocument()
            parser = MagicMock(return_value=docs)
            hl = SimpleNamespace(
                safe_save=lambda _doc, path: Path(path).write_bytes(b"%PDF prepared"),
                fix_null_page_content=MagicMock(),
                fix_filter=MagicMock(),
                fix_null_xref=MagicMock(),
                fix_media_box=MagicMock(return_value={}),
                check_cid_char=MagicMock(return_value=False),
            )
            converter = MagicMock()

            def write_json(_docs, path):
                Path(path).write_text('{"page": []}', encoding="utf-8")

            converter.write_json.side_effect = write_json
            document = MagicMock()
            bb = {
                "hl": hl,
                "Document": MagicMock(return_value=document),
                "parse_prepared_pdf": parser,
                "LayoutParser": MagicMock(),
                "ParagraphFinder": MagicMock(),
                "StylesAndFormulas": MagicMock(),
                "XMLConverter": MagicMock(return_value=converter),
            }
            bb["LayoutParser"].return_value.process.return_value = docs
            with (
                patch(
                    "wenyi_babeldoc_bridge.pipeline.require_babeldoc", return_value=bb
                ),
                patch(
                    "wenyi_babeldoc_bridge.pipeline._build_translation_config",
                    return_value=(cfg, object()),
                ),
                patch("wenyi_babeldoc_bridge.pipeline.capture_links", return_value=[]),
                patch(
                    "wenyi_babeldoc_bridge.native.Document.restore",
                    side_effect=_FakeDocument.restore,
                ),
            ):
                session = extract_to_session(
                    session_id="a" * 32,
                    pdf_path=source,
                    pages_spec="2",
                    out_dir=root,
                )
                restored = load_session_docs(session)
                document.close.assert_called_once()
                document.close.reset_mock()
                parser.side_effect = RuntimeError("synthetic parse failure")
                with self.assertRaisesRegex(RuntimeError, "synthetic parse failure"):
                    extract_to_session(
                        session_id="b" * 32,
                        pdf_path=source,
                        pages_spec="2",
                        out_dir=root,
                    )
                document.close.assert_called_once()

            parser.assert_called_with(str(working), config=cfg, doc_pdf=document)
            self.assertIsNone(session.docs)
            self.assertEqual(restored.page, [])
            self.assertEqual(session.pages_spec, "2")
            self.assertTrue((root / "session.json").is_file())
            self.assertEqual(working.read_bytes(), b"%PDF prepared")


if __name__ == "__main__":
    unittest.main()
