"""Deterministic inline structure and link tests; no layout or translation service."""

from __future__ import annotations

import hashlib
import unittest
from types import SimpleNamespace as NS

from wenyi_babeldoc_bridge.annotations import (
    extract_inline_annotations,
    inject_aligned_translation,
    layout_link_rectangles,
    prepare_inline_annotations,
    summarize_annotations,
    validate_annotation_placements,
)


def character(text, x):
    return NS(
        char_unicode=text,
        box=NS(x=x, y=10, x2=x + 1, y2=20),
        pdf_style=NS(font_id="body", font_size=12),
    )


def paragraph():
    style = NS(font_id="body", font_size=12)
    formula = NS(
        pdf_character=[character("2", 4)],
        is_corner_mark=True,
        x_offset=0,
        y_offset=5,
    )
    return NS(
        unicode="Ada 2",
        pdf_style=style,
        pdf_paragraph_composition=[
            NS(
                pdf_same_style_characters=NS(
                    pdf_character=[character(c, i) for i, c in enumerate("Ada")],
                    pdf_style=style,
                )
            ),
            NS(pdf_formula=formula),
        ],
    )


def placement(item, start, end):
    return {
        "id": item["id"],
        "mode": item["mode"],
        "target_start": start,
        "target_end": end,
        "status": "aligned",
    }


class InlineAnnotationTests(unittest.TestCase):
    def test_style_regrouping_uses_original_reading_order_and_separate_ranges(self):
        from wenyi_babeldoc_bridge.annotations import source_glyph_offsets

        text = "Part 3: 309."
        glyphs = [character(char, index) for index, char in enumerate(text)]
        base = NS(font_id="body", font_size=12)
        styled = NS(font_id="other", font_size=12)
        para = NS(
            unicode=text,
            pdf_style=base,
            pdf_paragraph_composition=[NS(pdf_line=NS(pdf_character=glyphs))],
        )
        offsets = source_glyph_offsets(para)
        digits = [char for char in glyphs if char.char_unicode.isdigit()]
        others = [char for char in glyphs if not char.char_unicode.isdigit()]
        para.pdf_paragraph_composition = [
            NS(pdf_same_style_characters=NS(pdf_character=digits, pdf_style=styled)),
            NS(pdf_same_style_characters=NS(pdf_character=others, pdf_style=base)),
        ]
        items = extract_inline_annotations(para, [], offsets=offsets)
        self.assertEqual(
            [text[item["source_start"] : item["source_end"]] for item in items],
            ["3", "309"],
        )
        self.assertEqual(len({item["id"] for item in items}), 2)

    def test_corner_mark_is_a_point_outside_translatable_prose(self):
        para = paragraph()
        original = para.pdf_paragraph_composition[1].pdf_formula
        original.pdf_character[0].pdf_style.font_size = 8
        text, items = prepare_inline_annotations(
            para, [{"id": "0:0", "from": [4, 10, 5, 20]}]
        )
        self.assertEqual(text, "Ada ")
        self.assertEqual(para.unicode, "Ada 2")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["mode"], "point")
        self.assertEqual((item["source_start"], item["source_end"]), (4, 4))
        self.assertEqual(item["link_ids"], ["0:0"])
        rows = [placement(item, 2, 2)]
        digest = hashlib.sha256("阿达".encode()).hexdigest()
        validate_annotation_placements(
            items, "阿达", {"target_digest": digest, "placements": rows}
        )
        plan = inject_aligned_translation(
            {"PdfParagraphComposition": NS, "PdfSameStyleUnicodeCharacters": NS},
            para,
            "阿达",
            items,
            rows,
        )
        self.assertEqual([row[0] for row in plan], ["阿", "达", "2"])
        self.assertIs(para.pdf_paragraph_composition[-1].pdf_formula, original)
        self.assertEqual(plan[-1][1:3], (2, 2))

    def test_extract_retains_composition_identity_and_link_ranges(self):
        para = paragraph()
        items = extract_inline_annotations(
            para,
            [{"id": "0:0", "from": [0, 10, 3, 20]}],
        )
        formula = next(item for item in items if item["kind"] == "formula")
        link = next(item for item in items if item["kind"] == "link")
        self.assertEqual((formula["source_start"], formula["source_end"]), (4, 5))
        self.assertEqual(formula["composition_index"], 1)
        self.assertEqual((link["source_start"], link["source_end"]), (0, 3))
        self.assertEqual(link["link_id"], "0:0")

    def test_tall_link_rect_does_not_capture_words_on_the_adjacent_line(self):
        style = NS(font_id="body", font_size=12)
        glyphs = [character(char, index) for index, char in enumerate("2014")]
        for index, char in enumerate("can"):
            glyph = character(char, index)
            glyph.box.y, glyph.box.y2 = 0, 10
            glyphs.append(glyph)
        para = NS(
            unicode="2014 can",
            pdf_style=style,
            pdf_paragraph_composition=[
                NS(pdf_same_style_characters=NS(pdf_character=glyphs, pdf_style=style))
            ],
        )
        [link] = extract_inline_annotations(
            para, [{"id": "0:0", "from": [0, 8, 4, 22]}]
        )
        self.assertEqual((link["source_start"], link["source_end"]), (0, 4))

    def test_injection_reuses_original_formula_instead_of_plain_text(self):
        para = paragraph()
        original = para.pdf_paragraph_composition[1].pdf_formula
        items = extract_inline_annotations(para, [])
        rows = [placement(items[0], 2, 3)]
        plan = inject_aligned_translation(
            {"PdfParagraphComposition": NS, "PdfSameStyleUnicodeCharacters": NS},
            para,
            "阿达2",
            items,
            rows,
        )
        formulas = [
            comp.pdf_formula
            for comp in para.pdf_paragraph_composition
            if getattr(comp, "pdf_formula", None) is not None
        ]
        self.assertEqual(formulas, [original])
        self.assertEqual(original.y_offset, 5)
        self.assertEqual([row[0] for row in plan], ["阿", "达", "2"])
        self.assertEqual(para.unicode, "阿达2")

    def test_invalid_positions_are_skipped_without_discarding_valid_siblings(self):
        item = extract_inline_annotations(paragraph(), [])[0]
        text = "阿达2"
        row = placement(item, 2, 3)
        digest = hashlib.sha256(text.encode()).hexdigest()
        for invalid in (
            {},
            {"target_digest": "stale", "placements": [row]},
            {"target_digest": digest, "placements": []},
            {"target_digest": digest, "placements": [row, row]},
            {"target_digest": digest, "placements": [{**row, "status": "fallback"}]},
            {"target_digest": digest, "placements": [{**row, "target_end": 50}]},
            {"target_digest": digest, "placements": [{**row, "id": "unknown"}]},
        ):
            sibling = {
                "id": "link:valid",
                "kind": "link",
                "mode": "range",
                "link_id": "0:1",
            }
            valid = placement(sibling, 0, 2)
            payload = dict(invalid)
            payload["placements"] = [*payload.get("placements", []), valid]
            skipped = {}
            with self.subTest(invalid=invalid):
                accepted = validate_annotation_placements(
                    [item, sibling], text, payload, skipped=skipped
                )
                self.assertIn(item["id"], skipped)
                if invalid.get("target_digest") == digest:
                    self.assertEqual(accepted, [valid])
                else:
                    self.assertEqual(accepted, [])
        self.assertEqual(
            validate_annotation_placements(
                [item], text, {"target_digest": digest, "placements": [row]}
            ),
            [row],
        )

    def test_failed_formula_keeps_translated_text_and_a_valid_link(self):
        para = paragraph()
        formula = extract_inline_annotations(para, [])[0]
        link = {"id": "link:valid", "kind": "link", "mode": "range", "link_id": "0:0"}
        items = [formula, link]
        text = "阿达2"
        rows = [
            {**placement(formula, 3, 3), "status": "fallback"},
            placement(link, 0, 2),
        ]
        skipped = {}
        accepted = validate_annotation_placements(
            items,
            text,
            {
                "target_digest": hashlib.sha256(text.encode()).hexdigest(),
                "placements": rows,
            },
            skipped=skipped,
        )
        plan = inject_aligned_translation(
            {"PdfParagraphComposition": NS, "PdfSameStyleUnicodeCharacters": NS},
            para,
            text,
            items,
            accepted,
            skipped=skipped,
        )
        self.assertEqual(para.unicode, text)
        self.assertEqual([row[0] for row in plan], ["阿", "达", "2"])
        self.assertTrue(
            all(
                getattr(c, "pdf_formula", None) is None
                for c in para.pdf_paragraph_composition
            )
        )
        para.pdf_paragraph_composition = [
            NS(pdf_character=character(char, index)) for index, char in enumerate(text)
        ]
        boxes = layout_link_rectangles(para, plan, items, accepted, skipped=skipped)
        self.assertEqual(set(boxes), {"0:0"})
        self.assertIn(formula["id"], skipped)
        self.assertNotIn(link["id"], skipped)

    def test_conflicting_styles_do_not_drop_other_styles_or_links(self):
        para = paragraph()
        styles = [
            NS(font_id="bold", font_size=12),
            NS(font_id="italic", font_size=12),
            NS(font_id="small", font_size=10),
        ]
        para.pdf_paragraph_composition = [
            NS(pdf_same_style_characters=NS(pdf_style=style)) for style in styles
        ]
        items = [
            {
                "id": f"style:{index}",
                "kind": "style",
                "mode": "range",
                "composition_index": index,
            }
            for index in range(3)
        ]
        link = {"id": "link:valid", "kind": "link", "mode": "range", "link_id": "0:0"}
        items.append(link)
        rows = [
            placement(items[0], 0, 2),
            placement(items[1], 1, 3),
            placement(items[2], 3, 4),
            placement(link, 0, 4),
        ]
        skipped = {}
        plan = inject_aligned_translation(
            {"PdfParagraphComposition": NS, "PdfSameStyleUnicodeCharacters": NS},
            para,
            "中文测试",
            items,
            rows,
            skipped=skipped,
        )
        self.assertEqual(para.unicode, "中文测试")
        self.assertEqual("".join(row[0] for row in plan), "中文测试")
        self.assertEqual(set(skipped), {"style:0", "style:1"})
        runs = [
            c.pdf_same_style_unicode_characters for c in para.pdf_paragraph_composition
        ]
        self.assertEqual(runs[-1].pdf_style, styles[2])
        self.assertEqual(runs[0].pdf_style, para.pdf_style)

    def test_formula_overlap_skips_only_conflict_participants(self):
        para = paragraph()
        original = para.pdf_paragraph_composition[1]
        para.pdf_paragraph_composition = [original, original, original]
        items = [
            {
                "id": f"formula:{index}",
                "kind": "formula",
                "mode": "range",
                "composition_index": index,
            }
            for index in range(3)
        ]
        rows = [
            placement(items[0], 0, 2),
            placement(items[1], 1, 3),
            placement(items[2], 3, 4),
        ]
        skipped = {}
        plan = inject_aligned_translation(
            {"PdfParagraphComposition": NS, "PdfSameStyleUnicodeCharacters": NS},
            para,
            "甲乙丙2",
            items,
            rows,
            skipped=skipped,
        )
        self.assertEqual(para.unicode, "甲乙丙2")
        self.assertEqual("".join(row[0] for row in plan), "甲乙丙2")
        self.assertEqual(
            skipped,
            {"formula:0": "conflicting_formulas", "formula:1": "conflicting_formulas"},
        )
        self.assertIs(
            para.pdf_paragraph_composition[-1].pdf_formula, original.pdf_formula
        )

    def test_statistics_separate_identity_and_translated_annotations(self):
        summary = summarize_annotations(
            [
                {
                    "kind": "link",
                    "source_identity": False,
                    "aligned": True,
                    "reason": None,
                },
                {
                    "kind": "style",
                    "source_identity": False,
                    "aligned": True,
                    "reason": "conflicting_styles",
                },
                {
                    "kind": "link",
                    "source_identity": False,
                    "aligned": False,
                    "reason": "alignment_failed",
                },
                {
                    "kind": "formula",
                    "source_identity": True,
                    "aligned": True,
                    "reason": None,
                },
            ]
        )
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["applied"], 2)
        self.assertEqual(summary["translated"]["aligned"], 2)
        self.assertEqual(summary["translated"]["alignment_pass_rate"], 2 / 3)
        self.assertEqual(summary["translated"]["application_rate"], 1 / 3)
        self.assertEqual(summary["source_identity"]["applied"], 1)
        self.assertEqual(summary["by_kind"]["link"]["skipped"], 1)
        self.assertEqual(
            summary["reasons"], {"conflicting_styles": 1, "alignment_failed": 1}
        )
        self.assertIsNone(summarize_annotations([])["application_rate"])

    def test_formula_whose_source_cannot_be_mapped_fails_instead_of_flattening(self):
        para = paragraph()
        para.unicode = "Not the same source"
        with self.assertRaisesRegex(ValueError, "source"):
            extract_inline_annotations(para, [])

    def test_link_rectangles_follow_rendered_lines_not_original_coordinates(self):
        first, second = character("甲", 30), character("乙", 40)
        second.box.y, second.box.y2 = 30, 40
        para = NS(
            pdf_paragraph_composition=[
                NS(pdf_character=first),
                NS(pdf_character=second),
            ]
        )
        item = {"id": "link:0", "kind": "link", "mode": "range", "link_id": "0:0"}
        result = layout_link_rectangles(
            para,
            [("甲", 0, 1, None), ("乙", 1, 2, None)],
            [item],
            [placement(item, 0, 2)],
        )
        self.assertEqual(result, {"0:0": [[30, 10, 31, 20], [40, 30, 41, 40]]})
        skipped = {}
        self.assertEqual(
            layout_link_rectangles(
                para,
                [("甲", 0, 1, None)],
                [item],
                [placement(item, 0, 1)],
                skipped=skipped,
            ),
            {},
        )
        self.assertEqual(skipped, {item["id"]: "glyph_stream_changed"})

    def test_link_rectangles_allow_typesetting_to_drop_boundary_spaces(self):
        para = NS(
            pdf_paragraph_composition=[
                NS(pdf_character=character("A", 30)),
                NS(pdf_character=character("B", 40)),
            ]
        )
        item = {"id": "link:0", "kind": "link", "mode": "range", "link_id": "0:0"}
        result = layout_link_rectangles(
            para,
            [("A", 0, 1, None), (" ", 1, 2, None), ("B", 2, 3, None)],
            [item],
            [placement(item, 2, 3)],
        )
        self.assertEqual(result, {"0:0": [[40, 10, 41, 20]]})
        para.pdf_paragraph_composition[-1].pdf_character.char_unicode = "C"
        self.assertEqual(
            layout_link_rectangles(
                para,
                [("A", 0, 1, None), (" ", 1, 2, None), ("B", 2, 3, None)],
                [item],
                [placement(item, 2, 3)],
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
