from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from wenyi_babeldoc_bridge.pipeline import (
    ExtractSession,
    _debug_enabled,
    _is_debug_overlay_paragraph,
    _load_snake_case_il_json,
    _strip_debug_overlays,
    _validate_docs_against_paragraphs,
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


@dataclass
class _FakeStyleRun:
    debug_info: bool = False
    unicode: str = "plain text"


@dataclass
class _FakeComposition:
    pdf_same_style_unicode_characters: _FakeStyleRun | None = None


@dataclass
class _FakeOverlayParagraph:
    unicode: str = "plain text"
    xobj_id: int = -1
    pdf_paragraph_composition: list[_FakeComposition] = field(default_factory=list)


@dataclass
class _FakeOverlayPage:
    pdf_paragraph: list[_FakeOverlayParagraph] = field(default_factory=list)
    pdf_rectangle: list[object] = field(default_factory=list)


@dataclass
class _FakeOverlayDocument:
    page: list[_FakeOverlayPage] = field(default_factory=list)


@dataclass
class _FakeDebugRect:
    debug_info: bool = True


class DebugFlagTests(unittest.TestCase):
    def test_debug_overlay_is_off_by_default(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if key != "WENYI_BABELDOC_DEBUG"
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(_debug_enabled())

    def test_debug_overlay_can_be_opted_in(self):
        with patch.dict(os.environ, {"WENYI_BABELDOC_DEBUG": "1"}):
            self.assertTrue(_debug_enabled())
        with patch.dict(os.environ, {"WENYI_BABELDOC_DEBUG": "true"}):
            self.assertTrue(_debug_enabled())
        with patch.dict(os.environ, {"WENYI_BABELDOC_DEBUG": "0"}):
            self.assertFalse(_debug_enabled())

    def test_debug_overlay_paragraphs_are_stripped(self):
        overlay = _FakeOverlayParagraph(
            unicode="plain text",
            pdf_paragraph_composition=[
                _FakeComposition(_FakeStyleRun(debug_info=True, unicode="plain text"))
            ],
        )
        body = _FakeOverlayParagraph(
            unicode="Long-term LLM agents need persistent memory.",
            xobj_id=0,
            pdf_paragraph_composition=[
                _FakeComposition(_FakeStyleRun(debug_info=False, unicode="body"))
            ],
        )
        docs = _FakeOverlayDocument(
            page=[
                _FakeOverlayPage(
                    pdf_paragraph=[overlay, body],
                    pdf_rectangle=[_FakeDebugRect(), _FakeDebugRect(debug_info=False)],
                )
            ]
        )

        self.assertTrue(_is_debug_overlay_paragraph(overlay))
        self.assertFalse(_is_debug_overlay_paragraph(body))
        self.assertEqual(_strip_debug_overlays(docs), 1)
        self.assertEqual(docs.page[0].pdf_paragraph, [body])
        self.assertEqual(len(docs.page[0].pdf_rectangle), 1)
        self.assertFalse(docs.page[0].pdf_rectangle[0].debug_info)

    def test_restore_validation_ignores_legacy_layout_role_units(self):
        docs = _FakeDocument(
            page=[
                _FakePage(
                    page_number=0,
                    pdf_paragraph=[_FakeParagraph("Original paragraph text.")],
                )
            ]
        )
        paragraphs = ParagraphDocument(
            paragraphs=[
                ParagraphUnit(
                    id="0:0",
                    page=0,
                    index=0,
                    source="Original paragraph text.",
                ),
                ParagraphUnit(
                    id="0:1",
                    page=0,
                    index=1,
                    source="figure_caption",
                ),
            ]
        )
        _validate_docs_against_paragraphs(docs, paragraphs)


if __name__ == "__main__":
    unittest.main()
