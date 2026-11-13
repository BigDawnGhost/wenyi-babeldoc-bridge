"""Exercise native stage wiring without models."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from wenyi_babeldoc_bridge.pipeline import extract_to_session, load_session_docs
from wenyi_babeldoc_bridge.test_session_snapshot import _FakeDocument


class NativeParserTests(unittest.TestCase):
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
