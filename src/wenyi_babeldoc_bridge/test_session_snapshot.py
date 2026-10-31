from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from wenyi_babeldoc_bridge.pipeline import (
    ExtractSession,
    _debug_enabled,
    _is_debug_overlay_paragraph,
    _load_snake_case_il_json,
    _strip_debug_overlays,
    _validate_docs_against_paragraphs,
    fillback_session,
    load_session_docs,
    persist_session_snapshot,
    restore_session,
)
from wenyi_babeldoc_bridge.schema import ParagraphDocument, ParagraphUnit


@dataclass
class _FakeParagraph:
    unicode: str
    pdf_paragraph_composition: list[object] = field(default_factory=list)


@dataclass
class _FakePage:
    page_number: int
    pdf_paragraph: list[_FakeParagraph] = field(default_factory=list)
    pdf_rectangle: list[object] = field(default_factory=list)


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

    def _configure_fillback(self, session: ExtractSession) -> MagicMock:
        rendered = session.out_dir / "rendered.pdf"
        rendered.write_bytes(b"%PDF-1.4 synthetic renderer output")
        session.cfg = SimpleNamespace(debug=False)
        session.pm = MagicMock()
        typesetting = MagicMock()
        creator = MagicMock()
        creator.return_value.write.return_value = SimpleNamespace(
            no_watermark_mono_pdf_path=rendered
        )
        session.bb = {"Typesetting": typesetting, "PDFCreater": creator}
        return typesetting.return_value.typesetting_document

    def test_fillback_injects_short_cells_and_reloads_pristine_il(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self._make_session(Path(directory))
            texts = ["Cis man", "Gender", "Percent", "N", "15", "22.0", "table"]
            overlay = _FakeParagraph(
                "figure_caption",
                [_FakeComposition(_FakeStyleRun(debug_info=True))],
            )
            session.docs.page[0].pdf_paragraph = [
                overlay,
                *[_FakeParagraph(text) for text in texts],
            ]
            session.paragraphs = ParagraphDocument(
                paragraphs=[
                    ParagraphUnit(id=f"0:{index}", page=0, index=index, source=text)
                    for index, text in enumerate(texts, 1)
                ]
            )
            session.paragraphs.write_json(session.out_dir / "paragraphs.json")
            persist_session_snapshot(session)
            typeset = self._configure_fillback(session)
            translations = {
                unit.id: f"translated {unit.source}"
                for unit in session.paragraphs.paragraphs
            }
            seen_sources = []

            def inject(_bb, para, text):
                seen_sources.append(para.unicode)
                para.unicode = text
                return [para]

            with (
                patch(
                    "wenyi_babeldoc_bridge.pipeline.inject_paragraph_translation",
                    inject,
                ),
                patch.dict(os.environ, {"WENYI_BABELDOC_DEBUG": "0"}),
            ):
                for _attempt in range(2):
                    result = fillback_session(session, translations)
                    self.assertEqual(
                        result.read_bytes(), b"%PDF-1.4 synthetic renderer output"
                    )
                    rendered_docs = typeset.call_args.args[0]
                    self.assertEqual(
                        [para.unicode for para in rendered_docs.page[0].pdf_paragraph],
                        list(translations.values()),
                    )

            self.assertEqual(seen_sources, texts * 2)
            self.assertEqual(
                [
                    para.unicode
                    for para in load_session_docs(session).page[0].pdf_paragraph
                ],
                ["figure_caption", *texts],
            )

    def test_fillback_rejects_missing_unknown_and_empty_short_cell_translations(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self._make_session(Path(directory))
            session.paragraphs = ParagraphDocument(
                paragraphs=[ParagraphUnit(id="0:0", page=0, index=0, source="Cis man")]
            )
            for translations, message in (
                ({}, "missing translations"),
                ({"0:0": "译文", "0:1": "15"}, "unknown translation id"),
                ({"0:0": " "}, "empty translation"),
            ):
                with self.subTest(translations=translations):
                    with self.assertRaisesRegex(ValueError, message):
                        fillback_session(session, translations)


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

    def test_restore_validation_ignores_debug_overlays(self):
        docs = _FakeDocument(
            page=[
                _FakePage(
                    page_number=0,
                    pdf_paragraph=[
                        _FakeParagraph("Original paragraph text."),
                        _FakeParagraph(
                            "figure_caption",
                            [_FakeComposition(_FakeStyleRun(debug_info=True))],
                        ),
                    ],
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
            ]
        )
        _validate_docs_against_paragraphs(docs, paragraphs)

    def test_restore_validation_preserves_real_layout_role_text(self):
        docs = _FakeDocument(
            page=[
                _FakePage(
                    page_number=0, pdf_paragraph=[_FakeParagraph("figure_caption")]
                )
            ]
        )
        paragraphs = ParagraphDocument(
            paragraphs=[
                ParagraphUnit(id="0:0", page=0, index=0, source="figure_caption")
            ]
        )
        _validate_docs_against_paragraphs(docs, paragraphs)

    def test_restore_validation_rejects_missing_or_changed_exported_cells(self):
        paragraphs = ParagraphDocument(
            paragraphs=[ParagraphUnit(id="0:0", page=0, index=0, source="Cis man")]
        )
        for cells in ([], [_FakeParagraph("Gender")], [_FakeParagraph(" ")]):
            with self.subTest(cells=cells):
                docs = _FakeDocument(
                    page=[_FakePage(page_number=0, pdf_paragraph=cells)]
                )
                with self.assertRaisesRegex(
                    RuntimeError, "IL does not match paragraphs"
                ):
                    _validate_docs_against_paragraphs(docs, paragraphs)


if __name__ == "__main__":
    unittest.main()
