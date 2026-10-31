"""Schema validation without babeldoc installed."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wenyi_babeldoc_bridge.schema import (  # noqa: E402
    ParagraphDocument,
    ParagraphUnit,
    TranslationDocument,
    is_translatable_unicode,
    load_paragraphs_from_styles_json,
    make_paragraph_id,
    paragraph_from_il,
    validate_paragraph_document,
    validate_translations_against_paragraphs,
)


class SchemaTests(unittest.TestCase):
    def test_short_paragraph_document_round_trip(self):
        doc = ParagraphDocument(
            paragraphs=[ParagraphUnit(id="4:3", page=4, index=3, source="Cis man")]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = doc.write_json(Path(directory) / "paragraphs.json")
            self.assertEqual(ParagraphDocument.read_json(path), doc)
        self.assertEqual(validate_paragraph_document(doc), [])

    def test_id_matches_page_index(self):
        self.assertEqual(make_paragraph_id(14, 130), "14:130")

    def test_nonempty_text_is_not_filtered_by_content(self):
        for text in (
            "Cis man",
            "Gender",
            "Percent",
            "N",
            "15",
            "22.0",
            "中",
            "table",
            "title",
            "plain text",
            "figure_caption",
            "abandon",
            "fallback_line",
            "isolate_formula",
            "table_caption",
            "/Volume/example",
            "wea25324_fm",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_translatable_unicode(text))
                unit = paragraph_from_il(page_number=4, index=3, raw={"unicode": text})
                self.assertIsNotNone(unit)
                self.assertEqual(unit.source, text)
                self.assertEqual(unit.id, "4:3")

    def test_short_table_cells_keep_indices_and_ignore_debug_overlays(self):
        styles = {
            "page": [
                {
                    "page_number": 4,
                    "pdf_paragraph": [
                        {"unicode": "Cis man", "layout_label": "table"},
                        {"unicode": " \n"},
                        {
                            "unicode": "figure_caption",
                            "pdf_paragraph_composition": [
                                {
                                    "pdf_same_style_unicode_characters": {
                                        "unicode": "figure_caption",
                                        "debug_info": True,
                                    }
                                }
                            ],
                        },
                        {"unicode": "Gender"},
                        {"unicode": "N"},
                        {"unicode": "15"},
                        {"unicode": "22.0"},
                        {"unicode": "table", "debug_id": "real-content"},
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "styles.json"
            path.write_text(json.dumps(styles), encoding="utf-8")
            doc = load_paragraphs_from_styles_json(path)

        self.assertEqual(
            [(unit.id, unit.source) for unit in doc.paragraphs],
            [
                ("4:0", "Cis man"),
                ("4:3", "Gender"),
                ("4:4", "N"),
                ("4:5", "15"),
                ("4:6", "22.0"),
                ("4:7", "table"),
            ],
        )
        self.assertEqual(validate_paragraph_document(doc), [])

    def test_skip_only_empty_text(self):
        for text in (None, "", " ", "\t\n"):
            with self.subTest(text=text):
                self.assertFalse(is_translatable_unicode(text))
                self.assertIsNone(
                    paragraph_from_il(page_number=0, index=0, raw={"unicode": text})
                )

    def test_debug_overlay_filter_uses_metadata_not_text(self):
        for text in ("figure_caption", "An arbitrary debug label"):
            with self.subTest(text=text):
                raw = {
                    "unicode": text,
                    "pdf_paragraph_composition": [
                        {
                            "pdf_same_style_unicode_characters": {
                                "unicode": text,
                                "debug_info": False,
                            }
                        }
                    ],
                }
                self.assertIsNotNone(paragraph_from_il(page_number=0, index=0, raw=raw))
                raw["pdf_paragraph_composition"][0][
                    "pdf_same_style_unicode_characters"
                ]["debug_info"] = True
                self.assertIsNone(paragraph_from_il(page_number=0, index=0, raw=raw))

    def test_paragraph_from_il_filters_noise(self):
        self.assertIsNone(
            paragraph_from_il(
                page_number=0,
                index=1,
                raw={
                    "unicode": "fallback_line",
                    "debug_id": "x",
                    "pdf_paragraph_composition": [
                        {"pdf_same_style_unicode_characters": {"debug_info": True}}
                    ],
                },
            )
        )
        unit = paragraph_from_il(
            page_number=14,
            index=130,
            raw={
                "unicode": "Control of transposons by Piwi-interacting RNAs (piRNAs).",
                "debug_id": "M7NN9",
                "layout_label": "plain text",
                "box": {"x": 1, "y": 2, "x2": 3, "y2": 4},
            },
        )
        assert unit is not None
        self.assertEqual(unit.id, "14:130")
        self.assertEqual(unit.debug_id, "M7NN9")
        self.assertEqual(unit.box, [1.0, 2.0, 3.0, 4.0])

    def test_placeholder_flag(self):
        unit = paragraph_from_il(
            page_number=1,
            index=0,
            raw={"unicode": "Energy is E={v1} in this formula."},
        )
        assert unit is not None
        self.assertTrue(unit.has_placeholders)

    def test_translations_must_cover_all_ids(self):
        doc = ParagraphDocument(
            source_pdf="sample.pdf",
            paragraphs=[
                ParagraphUnit(id="0:1", page=0, index=1, source="Hello world here"),
                ParagraphUnit(
                    id="0:2", page=0, index=2, source="Second paragraph text"
                ),
            ],
        )
        partial = TranslationDocument(
            source_pdf="sample.pdf",
            translations={"0:1": "你好世界"},
        )
        errors = validate_translations_against_paragraphs(doc, partial)
        self.assertTrue(any("missing translations" in e for e in errors))

        complete = TranslationDocument(
            source_pdf="sample.pdf",
            translations={"0:1": "你好世界", "0:2": "第二段"},
        )
        self.assertEqual(validate_translations_against_paragraphs(doc, complete), [])

    def test_load_from_minimal_styles_json(self):
        styles = {
            "page": [
                {
                    "page_number": 14,
                    "pdf_paragraph": [
                        {"unicode": " \t\n"},
                        {
                            "unicode": "Organization of this textbook for students.",
                            "debug_id": "AhEpw",
                            "layout_label": "title",
                        },
                    ],
                }
            ]
        }
        tmp = Path(__file__).resolve().parent / "_tmp_styles.json"
        try:
            tmp.write_text(json.dumps(styles), encoding="utf-8")
            doc = load_paragraphs_from_styles_json(
                tmp, source_pdf="x.pdf", pages_spec="15"
            )
            self.assertEqual(len(doc.paragraphs), 1)
            self.assertEqual(doc.paragraphs[0].id, "14:1")
            self.assertEqual(validate_paragraph_document(doc), [])
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
