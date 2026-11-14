"""Hard directory boundaries must survive style grouping and annotated fillback."""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from wenyi_babeldoc_bridge.annotations import source_glyph_offsets


def paragraph(lines):
    compositions = []
    for index, text in enumerate(lines):
        y = 700 - index * 14
        box = NS(x=60, y=y, x2=400, y2=y + 12)
        chars = [
            NS(char_unicode=char, box=NS(x=60 + i * 5, y=y, x2=65 + i * 5, y2=y + 12))
            for i, char in enumerate(text)
        ]
        compositions.append(NS(pdf_line=NS(box=box, pdf_character=chars)))
    return NS(
        unicode=" ".join(lines),
        vertical=False,
        pdf_style=NS(font_size=12),
        pdf_paragraph_composition=compositions,
    )


class DirectoryRowTests(unittest.TestCase):
    def test_capture_uses_original_lines_not_later_style_boxes(self):
        from wenyi_babeldoc_bridge.toc import capture_toc_rows

        lines = ["3.1 First . . . 6", "3.2 Real x . . . 8", "3.3 Last . . . 9"]
        para = paragraph(lines)
        para.pdf_style = None  # ParagraphFinder precedes paragraph style assignment.
        rows = capture_toc_rows(para, source_glyph_offsets(para))
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [para.unicode[row["source_start"] : row["source_end"]] for row in rows],
            lines,
        )
        self.assertEqual([row["box"][1] for row in rows], [700, 686, 672])

    def test_body_wrapping_and_ambiguous_lists_stay_unstructured(self):
        from wenyi_babeldoc_bridge.toc import capture_toc_rows

        for lines in (
            ["A paragraph wraps naturally", "onto its next visual line."],
            ["1. The first argument...", "2. The second argument..."],
            ["3.1 First . . . 6", "5.2 Another . . . 8"],
        ):
            with self.subTest(lines=lines):
                para = paragraph(lines)
                self.assertEqual(capture_toc_rows(para, source_glyph_offsets(para)), [])

    def test_protection_remaps_row_offsets_without_changing_boxes_or_ids(self):
        from wenyi_babeldoc_bridge.protected_objects import (
            prepare_protected_annotations,
        )
        from wenyi_babeldoc_bridge.toc import (
            capture_toc_rows,
            partition_row_annotations,
            remap_source_rows,
        )

        para = paragraph(
            ["3.1 当x<1时 . . . 6", "3.2 Use y=2 . . . 8", "3.3 Plain . . . 9"]
        )
        para.pdf_style = NS(font_id="body", font_size=12)
        for composition in para.pdf_paragraph_composition:
            for char in composition.pdf_line.pdf_character:
                char.pdf_style = para.pdf_style
        offsets = source_glyph_offsets(para)
        original_rows = capture_toc_rows(para, offsets)
        original_ranges = [
            (row["source_start"], row["source_end"]) for row in original_rows
        ]
        source, items, boundaries = prepare_protected_annotations(
            para,
            [],
            fonts=[],
            bb={"Box": NS, "PdfFormula": NS, "PdfParagraphComposition": NS},
            offsets=offsets,
        )
        rows = remap_source_rows(source, original_rows, boundaries)
        partitioned = partition_row_annotations(items, rows)
        self.assertEqual(
            [source[row["source_start"] : row["source_end"]] for row in rows],
            ["3.1 当时 . . . 6", "3.2 Use  . . . 8", "3.3 Plain . . . 9"],
        )
        self.assertEqual(
            [row["box"] for row in rows], [row["box"] for row in original_rows]
        )
        self.assertEqual(
            [(row["source_start"], row["source_end"]) for row in original_rows],
            original_ranges,
        )
        self.assertEqual(partitioned, items)
        self.assertEqual(len(items), 2)
        for row, item in zip(rows, items):
            self.assertTrue(item["protected"])
            self.assertLessEqual(row["source_start"], item["source_start"])
            self.assertLessEqual(item["source_end"], row["source_end"])

    def test_collapsed_cross_row_formula_still_prevents_row_partitioning(self):
        from wenyi_babeldoc_bridge.toc import (
            partition_row_annotations,
            remap_source_rows,
        )

        # Removing "X Y" from "FirstX YLast" collapses a cross-row object to one point.
        boundaries = tuple(i - max(0, min(i, 8) - 5) for i in range(13))
        rows = remap_source_rows(
            "FirstLast",
            [
                {"source_start": 0, "source_end": 6},
                {"source_start": 7, "source_end": 12},
            ],
            boundaries,
        )
        with self.assertRaisesRegex(ValueError, "crosses directory rows"):
            partition_row_annotations(
                [
                    {
                        "id": "formula:0",
                        "kind": "formula",
                        "mode": "point",
                        "source_start": 5,
                        "source_end": 5,
                        "protected": True,
                    }
                ],
                rows,
            )
        with self.assertRaisesRegex(ValueError, "Cannot preserve directory rows"):
            remap_source_rows(
                "Last",
                [
                    {"source_start": 0, "source_end": 6},
                    {"source_start": 7, "source_end": 12},
                ],
                tuple(max(0, i - 8) for i in range(13)),
            )

    def test_target_boundaries_are_explicit_not_guessed_from_newlines(self):
        from wenyi_babeldoc_bridge.toc import validate_target_rows

        text = "first\nsoft wrap\nsecond"
        rows = [
            {"target_start": 0, "target_end": 15},
            {"target_start": 16, "target_end": len(text)},
        ]
        validate_target_rows(text, rows, count=2)
        for invalid in (None, rows[:1], list(reversed(rows))):
            with self.subTest(rows=invalid), self.assertRaises(ValueError):
                validate_target_rows(text, invalid, count=2)

    def test_annotation_crossing_rows_is_split_without_changing_composition_identity(
        self,
    ):
        from wenyi_babeldoc_bridge.toc import partition_row_annotations

        items = [
            {
                "id": "style:0",
                "kind": "style",
                "mode": "range",
                "source_start": 0,
                "source_end": 11,
                "composition_index": 0,
            }
        ]
        rows = [
            {"source_start": 0, "source_end": 5},
            {"source_start": 6, "source_end": 11},
        ]
        result = partition_row_annotations(items, rows)
        self.assertEqual([item["composition_index"] for item in result], [0, 0])
        self.assertEqual(len({item["id"] for item in result}), 2)
        self.assertEqual(
            [(item["source_start"], item["source_end"]) for item in result],
            [(0, 5), (6, 11)],
        )

    def test_formula_row_uses_its_own_box_and_target_offsets(self):
        from wenyi_babeldoc_bridge.toc import inject_toc_rows

        formula = NS(pdf_character=[NS(char_unicode="x")])
        original = NS(
            box=NS(x=60, y=680, x2=400, y2=720),
            pdf_style=NS(font_size=12),
            pdf_paragraph_composition=[NS(pdf_formula=formula)],
        )
        item = {
            "id": "formula:0",
            "kind": "formula",
            "source_start": 7,
            "source_end": 8,
            "composition_index": 0,
        }
        unit = NS(
            rows=[
                {"source_start": 0, "source_end": 5, "box": [60, 700, 400, 712]},
                {"source_start": 6, "source_end": 11, "box": [60, 686, 400, 698]},
            ],
            annotations=[item],
        )
        targets = [
            {"target_start": 0, "target_end": 5},
            {"target_start": 6, "target_end": 12},
        ]
        placement = {
            "id": "formula:0",
            "target_start": 7,
            "target_end": 8,
            "status": "aligned",
        }
        bb = {"PdfParagraphComposition": NS, "PdfSameStyleUnicodeCharacters": NS}
        paragraphs, plans = inject_toc_rows(
            bb, original, unit, "first\n x row", targets, [placement], {}
        )
        self.assertEqual([p.box.y for p in paragraphs], [700, 686])
        self.assertEqual([p.unicode for p in paragraphs], ["first", " x row"])
        self.assertIs(paragraphs[1].pdf_paragraph_composition[1].pdf_formula, formula)
        self.assertEqual(plans[1][3][0]["target_start"], 1)
        self.assertEqual(original.box.y, 680)

    def test_split_rows_do_not_interleave_their_pdf_text_streams(self):
        from wenyi_babeldoc_bridge.toc import sequence_row_glyphs

        rows = [
            NS(
                pdf_paragraph_composition=[
                    NS(pdf_character=NS(render_order=100, sub_render_order=index))
                    for index in (1, 2, 3)
                ]
            )
            for _ in range(2)
        ]
        sequence_row_glyphs(rows)
        chars = [c.pdf_character for row in rows for c in row.pdf_paragraph_composition]
        self.assertEqual([c.render_order for c in chars], [100] * 6)
        self.assertEqual([c.sub_render_order for c in chars], list(range(1, 7)))
