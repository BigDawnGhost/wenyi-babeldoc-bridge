"""Schema validation without babeldoc installed."""

from __future__ import annotations

import json
import sys
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

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_paragraphs.json"


class SchemaTests(unittest.TestCase):
    def test_fixture_paragraphs_valid(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        errors = validate_paragraph_document(data)
        self.assertEqual(errors, [])

    def test_id_matches_page_index(self):
        self.assertEqual(make_paragraph_id(14, 130), "14:130")

    def test_skip_layout_role_tokens(self):
        self.assertFalse(is_translatable_unicode("abandon"))
        self.assertFalse(is_translatable_unicode("fallback_line"))
        self.assertTrue(
            is_translatable_unicode(
                "Chapters 14–16 introduce some of the posttranscriptional events."
            )
        )

    def test_paragraph_from_il_filters_noise(self):
        self.assertIsNone(
            paragraph_from_il(
                page_number=0,
                index=1,
                raw={"unicode": "fallback_line", "debug_id": "x"},
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
                ParagraphUnit(id="0:2", page=0, index=2, source="Second paragraph text"),
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
                        {"unicode": "abandon"},
                        {
                            "unicode": "Organization of this textbook for students.",
                            "debug_id": "AhEpw",
                            "layout_label": "title",
                        },
                    ],
                }
            ]
        }
        path = Path(self.id())  # unused placeholder name
        tmp = Path(__file__).resolve().parent / "_tmp_styles.json"
        try:
            tmp.write_text(json.dumps(styles), encoding="utf-8")
            doc = load_paragraphs_from_styles_json(tmp, source_pdf="x.pdf", pages_spec="15")
            self.assertEqual(len(doc.paragraphs), 1)
            self.assertEqual(doc.paragraphs[0].id, "14:1")
            self.assertEqual(validate_paragraph_document(doc), [])
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
