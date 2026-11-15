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

    def test_restore_rejects_missing_or_null_required_fields(self):
        for key in ("id", "page", "index", "source"):
            for missing in (True, False):
                with self.subTest(key=key, missing=missing):
                    data = ParagraphDocument(
                        paragraphs=[
                            ParagraphUnit(id="0:0", page=0, index=0, source="Text")
                        ]
                    ).to_dict()
                    raw = data["paragraphs"][0]
                    if missing:
                        del raw[key]
                    else:
                        raw[key] = None
                    with self.assertRaisesRegex(
                        ValueError, "paragraph document invalid"
                    ):
                        ParagraphDocument.from_dict(data)

    def test_protected_formula_reference_survives_client_and_session_round_trip(self):
        unit = ParagraphUnit(
            id="0:0",
            page=0,
            index=0,
            source="If  then proceed.",
            original_source="If x<1 then proceed.",
            annotations=[
                {
                    "id": "formula:1",
                    "kind": "formula",
                    "mode": "point",
                    "source_start": 3,
                    "source_end": 3,
                    "composition_index": 1,
                    "protected": True,
                    "object_source": "x<1",
                }
            ],
        )
        doc = ParagraphDocument(paragraphs=[unit])
        self.assertEqual(validate_paragraph_document(doc), [])
        public = doc.to_dict(for_client=True)["paragraphs"][0]
        self.assertNotIn("original_source", public)
        self.assertEqual(public["source"], unit.source)
        self.assertEqual(public["annotations"][0]["object_source"], "x<1")
        with tempfile.TemporaryDirectory() as directory:
            path = doc.write_json(Path(directory) / "paragraphs.json")
            self.assertEqual(ParagraphDocument.read_json(path), doc)
        unit.annotations[0]["object_source"] = ["x<1"]
        self.assertTrue(
            any("object_source" in error for error in validate_paragraph_document(doc))
        )

    def test_id_matches_page_index(self):
        self.assertEqual(make_paragraph_id(14, 130), "14:130")

    def test_non_numeric_text_keeps_short_words_and_layout_labels(self):
        for text in (
            "Cis man",
            "Gender",
            "Percent",
            "N",
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
                assert unit is not None
                self.assertEqual(unit.source, text)
                self.assertEqual(unit.id, "4:3")

    def test_numeric_paragraphs_stay_outside_translation_inputs(self):
        for text in (
            "0",
            "15",
            "22.0",
            "12,823",
            "116,744",
            "-12,823.5",
            "+0.25",
            "−0.25",
            ".5",
            " 16 351 877 ",
            "16\n351\t877",
            "１２３",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_translatable_unicode(text))
                self.assertIsNone(
                    paragraph_from_il(page_number=4, index=3, raw={"unicode": text})
                )

    def test_isolated_numeric_separators_keep_original_glyphs(self):
        for text in (",", ".", " , ", "\n.\t"):
            with self.subTest(text=text):
                self.assertIsNone(
                    paragraph_from_il(page_number=4, index=3, raw={"unicode": text})
                )

    def test_numeric_filter_does_not_consume_mixed_text_or_guess_number_formats(self):
        for text in (
            "N 16 351",
            "With diagonal scaling 351",
            "3 kg",
            "95%",
            "1e3",
            "1,2",
            "1.2.3",
            "1/2",
            "-",
            "a,b",
            "2026-11-15",
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(
                    paragraph_from_il(page_number=4, index=3, raw={"unicode": text})
                )

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
                ("4:7", "table"),
            ],
        )
        self.assertEqual(validate_paragraph_document(doc), [])

    def test_vertical_paragraphs_are_not_exported_or_renumbered(self):
        for label in ("abandon", "plain text", "title", None):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "styles.json"
                path.write_text(
                    json.dumps(
                        {
                            "page": [
                                {
                                    "page_number": 4,
                                    "pdf_paragraph": [
                                        {
                                            "unicode": "Rotated sidebar",
                                            "vertical": True,
                                            "layout_label": label,
                                        },
                                        {
                                            "unicode": "15",
                                            "vertical": False,
                                            "layout_label": label,
                                        },
                                        {
                                            "unicode": "Another sidebar",
                                            "vertical": True,
                                        },
                                        {"unicode": "Body text", "layout_label": label},
                                    ],
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                doc = load_paragraphs_from_styles_json(path)
                self.assertEqual(
                    [(unit.id, unit.source) for unit in doc.paragraphs],
                    [("4:3", "Body text")],
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
