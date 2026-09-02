from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from wenyi_babeldoc_bridge.pipeline import (
    ExtractSession,
    _load_snake_case_il_json,
    load_session_docs,
    persist_session_snapshot,
    restore_session,
)
from wenyi_babeldoc_bridge.schema import ParagraphDocument, ParagraphUnit


@dataclass
class _FakeParagraph:
    unicode: str


@dataclass
class _FakePage:
    page_number: int
    pdf_paragraph: list[_FakeParagraph] = field(default_factory=list)


@dataclass
class _FakeDocument:
    page: list[_FakePage] = field(default_factory=list)


@dataclass
class _LegacyScalarDocument:
    ctm: list[str] = field(
        default_factory=list,
        metadata={"type": "Element", "tokens": True},
    )
    bold: bool = field(default=False, metadata={"type": "Attribute"})
    page_number: int = field(
        default=0,
        metadata={"name": "pageNumber", "type": "Attribute"},
    )


class SessionSnapshotTests(unittest.TestCase):
    def _make_session(self, root: Path) -> ExtractSession:
        source = root / "book.pdf"
        source.write_bytes(b"%PDF-1.4 source")
        working = root / "working" / "book" / "input.pdf"
        working.parent.mkdir(parents=True)
        working.write_bytes(b"%PDF-1.4 fixed")
        paragraphs = ParagraphDocument(
            source_pdf=str(source),
            paragraphs=[
                ParagraphUnit(
                    id="0:0",
                    page=0,
                    index=0,
                    source="Original paragraph text.",
                )
            ],
        )
        paragraphs.write_json(root / "paragraphs.json")
        return ExtractSession(
            session_id="a" * 32,
            pdf_path=str(source),
            pages_spec=None,
            work_dir=root / "working",
            out_dir=root,
            bb={},
            cfg=object(),
            docs=_FakeDocument(
                page=[
                    _FakePage(
                        page_number=0,
                        pdf_paragraph=[_FakeParagraph("Original paragraph text.")],
                    )
                ]
            ),
            temp_pdf_path=str(working),
            mediabox_data={1: {"MediaBox": "[0 0 100 100]"}},
            pm=object(),
            paragraphs=paragraphs,
            styles_path=root / "styles_and_formulas.json",
            snapshot_path=root / "styles_and_formulas.pickle",
            snapshot_sha256="",
        )

    def test_snapshot_loads_a_fresh_pristine_document_each_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._make_session(root)
            persist_session_snapshot(session)
            session.docs = None

            first = load_session_docs(session)
            first.page[0].pdf_paragraph[0].unicode = "Modified"
            second = load_session_docs(session)

            self.assertEqual(
                second.page[0].pdf_paragraph[0].unicode,
                "Original paragraph text.",
            )
            manifest = json.loads((root / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["session_id"], "a" * 32)
            self.assertIn("il_snapshot", manifest["sha256"])

    def test_legacy_json_migration_preserves_original_scalar_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(
                json.dumps({"ctm": [1.25, 0], "bold": 1, "page_number": 7}),
                encoding="utf-8",
            )

            restored = _load_snake_case_il_json(path, _LegacyScalarDocument)

            self.assertEqual(restored.ctm, [1.25, 0])
            self.assertIs(type(restored.ctm[0]), float)
            self.assertIs(type(restored.ctm[1]), int)
            self.assertEqual(restored.bold, 1)
            self.assertIs(type(restored.bold), int)
            self.assertEqual(restored.page_number, 7)

    def test_restore_reuses_the_same_session_without_layout_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._make_session(root)
            persist_session_snapshot(session)

            with (
                patch(
                    "wenyi_babeldoc_bridge.pipeline.require_babeldoc", return_value={}
                ),
                patch(
                    "wenyi_babeldoc_bridge.pipeline._build_translation_config",
                    return_value=("cfg", "pm"),
                ) as build_config,
            ):
                restored = restore_session(session_id="a" * 32, out_dir=root)

            self.assertTrue(restored.restored)
            self.assertEqual(restored.session_id, session.session_id)
            self.assertEqual(len(restored.paragraphs.paragraphs), 1)
            self.assertEqual(
                load_session_docs(restored).page[0].pdf_paragraph[0].unicode,
                "Original paragraph text.",
            )
            build_config.assert_called_once()
            self.assertFalse(build_config.call_args.kwargs["load_layout_model"])


if __name__ == "__main__":
    unittest.main()
