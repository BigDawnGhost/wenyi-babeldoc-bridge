"""Synthetic glyph regressions for immutable mathematical objects."""

from __future__ import annotations

import hashlib
import unicodedata
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from wenyi_babeldoc_bridge.annotations import (
    inject_aligned_translation,
    validate_annotation_placements,
)
from wenyi_babeldoc_bridge.protected_objects import prepare_protected_annotations


class ProtectedObjectTests(unittest.TestCase):
    def paragraph(self, text, *, math_letters="g"):
        base = NS(font_id="body", font_size=12)
        chars = [
            NS(
                char_unicode=c,
                box=NS(x=i, y=10, x2=i + 1, y2=22),
                pdf_style=NS(
                    font_id="math" if c in math_letters else "body", font_size=12
                ),
            )
            for i, c in enumerate(text)
        ]
        para = NS(
            unicode=text,
            pdf_style=base,
            pdf_paragraph_composition=[NS(pdf_line=NS(pdf_character=chars))],
        )
        fonts = [NS(font_id="math", name="ABCDEF+AdvPSMP10")]
        bb = {
            "PdfParagraphComposition": NS,
            "PdfSameStyleUnicodeCharacters": NS,
            "PdfFormula": NS,
            "PdfSameStyleCharacters": NS,
            "Box": NS,
        }
        return para, chars, fonts, bb

    def test_math_font_glyph_and_relation_are_one_original_object(self):
        para, chars, fonts, bb = self.paragraph("We wish |g|<1.")
        source, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        objects = [item for item in items if item.get("protected")]
        self.assertEqual(len(objects), 1)
        self.assertEqual(source, "We wish .")
        item = objects[0]
        self.assertEqual(item["object_source"], "|g|<1")
        self.assertEqual(item["mode"], "point")
        rows = [
            dict(
                id=item["id"],
                mode="point",
                target_start=2,
                target_end=2,
                target_order=0,
                status="aligned",
            )
        ]
        plan = inject_aligned_translation(bb, para, "希望。", items, rows)
        frozen = para.pdf_paragraph_composition[1].pdf_formula.pdf_character
        self.assertIs(frozen[1], chars[9])
        self.assertEqual("".join(row[0] for row in plan), "希望|g|<1。")
        self.assertEqual(frozen[1].pdf_style.font_id, "math")

    def test_cjk_prose_adjacent_to_math_remains_translatable(self):
        for text, expected in (
            ("当x<1时继续。", "当时继续。"),
            ("当x<1时，继续。", "当时，继续。"),
            ("値x<1なら進む。", "値なら進む。"),
            ("값x<1이면 계속한다.", "값이면 계속한다."),
        ):
            for math_letters in ("x", ""):
                with self.subTest(text=text, math_letters=math_letters):
                    para, chars, fonts, bb = self.paragraph(
                        text, math_letters=math_letters
                    )
                    para.unicode = unicodedata.normalize("NFKC", text)
                    source, items, boundaries = prepare_protected_annotations(
                        para, [], fonts=fonts, bb=bb
                    )
                    self.assertEqual(source, unicodedata.normalize("NFKC", expected))
                    self.assertEqual(len(boundaries), len(para.unicode) + 1)
                    self.assertEqual(boundaries[1:5], (1, 1, 1, 1))
                    [item] = [item for item in items if item.get("protected")]
                    self.assertEqual(item["source_start"], 1)
                    self.assertEqual(item["object_source"], "x<1")
                    frozen = para.pdf_paragraph_composition[
                        item["composition_index"]
                    ].pdf_formula.pdf_character
                    self.assertEqual(
                        [id(char) for char in frozen],
                        [id(char) for char in chars[1:4]],
                    )
                    plan = inject_aligned_translation(
                        bb,
                        para,
                        "Continue when .",
                        items,
                        [
                            {
                                "id": item["id"],
                                "mode": "point",
                                "target_start": 14,
                                "target_end": 14,
                                "status": "aligned",
                            }
                        ],
                    )
                    self.assertEqual(
                        "".join(row[0] for row in plan), "Continue when x<1."
                    )

    def test_native_formula_seed_does_not_freeze_adjacent_prose(self):
        from wenyi_babeldoc_bridge.annotations import source_glyph_offsets

        para, chars, fonts, bb = self.paragraph("当x<1时继续。", math_letters="")
        offsets = source_glyph_offsets(para)
        original = NS(
            pdf_character=chars[1:4],
            box=NS(x=1, y=10, x2=4, y2=22),
        )
        para.pdf_paragraph_composition = [
            NS(pdf_line=NS(pdf_character=[chars[0], *chars[4:]])),
            NS(pdf_formula=original),
        ]
        source, items, _ = prepare_protected_annotations(
            para, [], fonts=fonts, bb=bb, offsets=offsets
        )
        self.assertEqual(source, "当时继续。")
        [item] = [item for item in items if item.get("protected")]
        self.assertEqual(item["object_source"], "x<1")
        self.assertIs(
            para.pdf_paragraph_composition[item["composition_index"]].pdf_formula,
            original,
        )

    def test_mark_only_carrier_does_not_preserve_a_wide_synthetic_space(self):
        para, chars, fonts, bb = self.paragraph("~ Text", math_letters="")
        chars[1].box.x2 = 100
        original = NS(pdf_character=chars[:2], box=NS(x=0, y=10, x2=100, y2=22))
        para.pdf_paragraph_composition = [
            NS(pdf_formula=original),
            NS(pdf_line=NS(pdf_character=chars[2:])),
        ]
        source, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        self.assertEqual(source, " Text")
        [item] = [a for a in items if a.get("protected")]
        result = para.pdf_paragraph_composition[item["composition_index"]].pdf_formula
        self.assertEqual(result.box.x2 - result.box.x, 1)
        self.assertEqual(result.pdf_character, chars[:1])

    def test_whitespace_does_not_join_math_across_lines_or_columns(self):
        for x, y in ((0, -10), (100, 10)):
            with self.subTest(x=x, y=y):
                para, chars, fonts, bb = self.paragraph("x y", math_letters="xy")
                chars[2].box = NS(x=x, x2=x + 1, y=y, y2=y + 12)
                _, items, _ = prepare_protected_annotations(
                    para, [], fonts=fonts, bb=bb
                )
                self.assertEqual(
                    [item["object_source"] for item in items if item.get("protected")],
                    ["x", "y"],
                )

    def test_existing_multiline_native_formula_and_graphics_are_not_split(self):
        for graphics in (False, True):
            with self.subTest(graphics=graphics):
                para, chars, fonts, bb = self.paragraph("a/b", math_letters="")
                chars[2].box.y -= 30
                chars[2].box.y2 -= 30
                original = NS(
                    pdf_character=chars,
                    box=NS(x=0, y=-20, x2=3, y2=22),
                    pdf_curve=[NS(box=NS(x=0, y=0, x2=3, y2=1))] if graphics else [],
                )
                para.pdf_paragraph_composition = [NS(pdf_formula=original)]
                _, items, _ = prepare_protected_annotations(
                    para, [], fonts=fonts, bb=bb
                )
                [item] = [item for item in items if item.get("protected")]
                self.assertIs(
                    para.pdf_paragraph_composition[
                        item["composition_index"]
                    ].pdf_formula,
                    original,
                )

    def test_seed_splitting_keeps_numbers_and_known_functions_atomic(self):
        for text, math_letters, expected, expression in (
            ("Use 1.5<x.", "15", "Use .", "1.5<x"),
            ("With sin(x)<1.", "s", "With .", "sin(x)<1"),
            ("当sin(x)<1时继续。", "s", "当时继续。", "sin(x)<1"),
        ):
            with self.subTest(text=text):
                para, _, fonts, bb = self.paragraph(text, math_letters=math_letters)
                source, items, _ = prepare_protected_annotations(
                    para, [], fonts=fonts, bb=bb
                )
                self.assertEqual(source, expected)
                [item] = [item for item in items if item.get("protected")]
                frozen = para.pdf_paragraph_composition[
                    item["composition_index"]
                ].pdf_formula.pdf_character
                self.assertEqual(
                    "".join(char.char_unicode for char in frozen), expression
                )

    def test_missing_protected_object_is_not_best_effort(self):
        item = dict(
            id="formula:0",
            kind="formula",
            mode="point",
            source_start=0,
            source_end=0,
            composition_index=0,
            protected=True,
        )
        digest = hashlib.sha256("译文".encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "protected"):
            validate_annotation_placements(
                [item], "译文", {"target_digest": digest, "placements": []}
            )

    def test_does_not_freeze_regular_words_or_an_unmapped_font(self):
        para, _, _, bb = self.paragraph("A normal paragraph.", math_letters="")
        source, items, boundaries = prepare_protected_annotations(
            para, [], fonts=[NS(font_id="body", name="CustomRoman")], bb=bb
        )
        self.assertEqual(source, para.unicode)
        self.assertEqual(boundaries, tuple(range(len(source) + 1)))
        self.assertFalse(any(item.get("protected") for item in items))

    def test_explicit_omission_preserves_prose_and_other_objects(self):
        para, _, fonts, bb = self.paragraph(
            "Let g and h be positive.", math_letters="gh"
        )
        _, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        objects = [item for item in items if item.get("protected")]
        self.assertEqual(len(objects), 2)
        text = "令与为正。"
        payload = {
            "target_digest": hashlib.sha256(text.encode()).hexdigest(),
            "placements": [
                {
                    "id": objects[0]["id"],
                    "mode": "point",
                    "target_start": 1,
                    "target_end": 1,
                    "status": "aligned",
                }
            ],
            "omitted_protected_objects": [objects[1]["id"]],
        }
        skipped = {}
        rows = validate_annotation_placements(items, text, payload, skipped=skipped)
        plan = inject_aligned_translation(bb, para, text, items, rows, skipped=skipped)
        self.assertEqual("".join(row[0] for row in plan), "令g与为正。")
        self.assertEqual(skipped[objects[1]["id"]], "explicit_client_omission")
        for invalid in (["unknown"], [objects[1]["id"]] * 2, "all", [None]):
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(ValueError, "omitted"),
            ):
                validate_annotation_placements(
                    items, text, {**payload, "omitted_protected_objects": invalid}
                )
        with self.assertRaisesRegex(ValueError, "protected"):
            validate_annotation_placements(
                items, text, {**payload, "target_digest": "stale"}
            )

    def test_unicode_math_and_greek_variable_without_freezing_greek_prose(self):
        para, _, fonts, bb = self.paragraph("Όταν η≪1 τότε", math_letters="")
        source, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        self.assertEqual(source, "Όταν  τότε")
        self.assertEqual(sum(bool(item.get("protected")) for item in items), 1)

    def test_prose_parenthesis_is_not_part_of_the_math_object(self):
        para, _, fonts, bb = self.paragraph("case m<k (traveling)", math_letters="")
        source, _, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        self.assertEqual(source, "case  (traveling)")

    def test_math_alphanumeric_glyph_is_not_lost_during_nfkc_projection(self):
        para, _, fonts, bb = self.paragraph("We use 𝜂 in this region.", math_letters="")
        para.unicode = unicodedata.normalize("NFKC", para.unicode)
        source, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        self.assertEqual(source, "We use  in this region.")
        self.assertEqual(sum(bool(item.get("protected")) for item in items), 1)
        self.assertEqual(items[0]["object_source"], "η")

    def test_protection_uses_complete_nfkc_glyph_spans(self):
        from wenyi_babeldoc_bridge.annotations import source_glyph_offsets

        for spelling in ("´", "¨", "¯", "ﬃ", "𝜂", "a+b"):
            with self.subTest(spelling=spelling):
                para, chars, fonts, bb = self.paragraph("A´!", math_letters="´")
                chars[1].char_unicode = spelling
                projected = unicodedata.normalize("NFKC", spelling)
                para.unicode = f"A{projected}!"
                offsets = source_glyph_offsets(para)
                link = {"id": "0:0", "from": [1, 10, 2, 22]}
                source, items, boundaries = prepare_protected_annotations(
                    para, [link], fonts=fonts, bb=bb, offsets=offsets
                )
                self.assertEqual(source, "A!")
                self.assertEqual(boundaries, (0, 1, *([1] * len(projected)), 2))
                [item] = [row for row in items if row.get("protected")]
                self.assertEqual(item["object_source"], projected)
                self.assertEqual(item["source_start"], 1)
                self.assertEqual(item["source_end"], 1)
                self.assertEqual(item["link_ids"], ["0:0"])
                formula = para.pdf_paragraph_composition[
                    item["composition_index"]
                ].pdf_formula
                self.assertEqual(formula.pdf_character, [chars[1]])
                self.assertIs(formula.pdf_character[0], chars[1])

    def test_nfkc_native_formula_keeps_original_glyph_and_attached_graphics(self):
        from wenyi_babeldoc_bridge.annotations import source_glyph_offsets

        para, chars, fonts, bb = self.paragraph("A´!", math_letters="")
        para.unicode = unicodedata.normalize("NFKC", para.unicode)
        offsets = source_glyph_offsets(para)
        curve, form = NS(box=chars[1].box), NS(box=chars[1].box)
        original = NS(
            pdf_character=[chars[1]],
            box=chars[1].box,
            pdf_curve=[curve],
            pdf_form=[form],
        )
        para.pdf_paragraph_composition = [
            NS(pdf_line=NS(pdf_character=[chars[0], chars[2]])),
            NS(pdf_formula=original),
        ]
        source, items, _ = prepare_protected_annotations(
            para, [], fonts=fonts, bb=bb, offsets=offsets
        )
        self.assertEqual(source, "A!")
        [item] = [row for row in items if row.get("protected")]
        self.assertEqual(item["object_source"], " \u0301")
        self.assertIs(
            para.pdf_paragraph_composition[item["composition_index"]].pdf_formula,
            original,
        )
        self.assertIs(original.pdf_curve[0], curve)
        self.assertIs(original.pdf_form[0], form)
        self.assertIs(original.pdf_character[0], chars[1])

    def test_glyph_region_alignment_merges_shared_spans_and_rejects_ambiguity(self):
        from wenyi_babeldoc_bridge.protected_objects import _glyph_regions

        self.assertEqual(
            _glyph_regions([(1, 2), (3, 4)], [(0, 1, 4, object())]), [(1, 4)]
        )
        self.assertEqual(
            _glyph_regions([(2, 3)], [(0, 1, 4, object()), (1, 2, 3, object())]),
            [(1, 4)],
        )
        with self.assertRaisesRegex(ValueError, "overlapping glyph spans"):
            _glyph_regions([(1, 2)], [(0, 1, 3, object()), (1, 2, 4, object())])
        with self.assertRaisesRegex(ValueError, "no original source glyphs"):
            _glyph_regions([(1, 2)], [])

    def test_expanded_regions_do_not_duplicate_a_glyph_or_consume_adjacent_prose(self):
        para, chars, fonts, bb = self.paragraph("A´¨!", math_letters="´¨")
        para.unicode = unicodedata.normalize("NFKC", para.unicode)
        source, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        self.assertEqual(source, "A!")
        frozen = [
            char
            for item in items
            if item.get("protected")
            for char in para.pdf_paragraph_composition[
                item["composition_index"]
            ].pdf_formula.pdf_character
        ]
        self.assertEqual([id(char) for char in frozen], [id(c) for c in chars[1:3]])

    def test_failed_preparation_restores_original_compositions_and_link_bindings(self):
        para, chars, fonts, bb = self.paragraph("Use x<1.", math_letters="x")
        original = para.pdf_paragraph_composition
        links = [
            {"id": "absent", "from": [0, 10, 8, 22]},
            {"id": "false", "from": [0, 10, 8, 22], "text_bound": False},
            {"id": "true", "from": [0, 10, 8, 22], "text_bound": True},
        ]
        before = [dict(link) for link in links]

        def fail_after_regrouping(para, links, **kwargs):
            self.assertIsNot(para.pdf_paragraph_composition, original)
            for link in links:
                link["text_bound"] = True
            raise ValueError("synthetic mapping failure after regrouping")

        with (
            patch(
                "wenyi_babeldoc_bridge.protected_objects.extract_inline_annotations",
                side_effect=fail_after_regrouping,
            ),
            self.assertRaisesRegex(ValueError, "synthetic mapping failure"),
        ):
            prepare_protected_annotations(para, links, fonts=fonts, bb=bb)
        self.assertIs(para.pdf_paragraph_composition, original)
        self.assertEqual(original[0].pdf_line.pdf_character, chars)
        self.assertEqual(links, before)

    def test_math_only_has_no_editable_source_and_retains_frozen_glyphs(self):
        para, chars, fonts, bb = self.paragraph("|g|<1")
        link = {"id": "math", "from": [0, 10, 5, 22]}
        source, items, _ = prepare_protected_annotations(
            para, [link], fonts=fonts, bb=bb
        )
        self.assertEqual(source, "")
        self.assertTrue(items[0]["protected"])
        self.assertFalse(link.get("text_bound"))
        self.assertEqual(
            para.pdf_paragraph_composition[-1].pdf_formula.pdf_character, chars
        )

    def test_coincident_objects_require_unique_target_order(self):
        items = [
            dict(
                id=f"formula:{i}",
                kind="formula",
                mode="point",
                source_start=i,
                source_end=i,
                composition_index=i,
                protected=True,
            )
            for i in range(2)
        ]
        rows = [
            dict(
                id=item["id"],
                mode="point",
                target_start=0,
                target_end=0,
                target_order=0,
                status="aligned",
            )
            for item in items
        ]
        with self.assertRaisesRegex(ValueError, "protected"):
            validate_annotation_placements(
                items,
                "文",
                {
                    "target_digest": hashlib.sha256("文".encode()).hexdigest(),
                    "placements": rows,
                },
            )

    def test_fillback_recovers_baseline_from_original_prose_not_formula_bottom(self):
        from wenyi_babeldoc_bridge.protected_objects import (
            restore_protected_formula_baselines,
        )

        para, chars, fonts, bb = self.paragraph("We use x<1.", math_letters="x")
        chars[9].box.y -= 4
        chars[9].box.y2 -= 4
        _, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        formula = para.pdf_paragraph_composition[-1].pdf_formula
        original_boxes = [vars(char.box).copy() for char in formula.pdf_character]
        self.assertEqual(formula.y_offset, 0)
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, -4)
        self.assertEqual(
            [vars(char.box) for char in formula.pdf_character], original_boxes
        )
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, -4)

    def test_baseline_uses_same_source_line_and_preserves_corner_marks(self):
        from wenyi_babeldoc_bridge.protected_objects import (
            restore_protected_formula_baselines,
        )

        para, chars, fonts, bb = self.paragraph("First x<1. More", math_letters="x")
        for char in chars[11:]:
            char.box.y -= 16
            char.box.y2 -= 16
            char.box.x -= 6
            char.box.x2 -= 6
        chars[8].box.y -= 3
        chars[8].box.y2 -= 3
        _, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        formula = para.pdf_paragraph_composition[-1].pdf_formula
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, -3)
        formula.is_corner_mark = True
        formula.y_offset = 5
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, 5)

    def test_baseline_keeps_tall_glyphs_subscripts_and_graphics_together(self):
        from wenyi_babeldoc_bridge.protected_objects import (
            restore_protected_formula_baselines,
        )

        para, chars, fonts, bb = self.paragraph("Given x+1<2.", math_letters="x")
        chars[6].box.y += 5
        chars[6].box.y2 += 10
        chars[6].pdf_style.font_size = 18
        chars[8].box.y -= 7
        chars[8].box.y2 -= 7
        chars[8].pdf_style.font_size = 8
        _, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        formula = para.pdf_paragraph_composition[-1].pdf_formula
        curve = NS(box=NS(x=6, y=9, x2=9, y2=9), relocation_transform=[])
        form = NS(box=NS(x=6, y=8, x2=9, y2=12))
        formula.pdf_curve = [curve]
        formula.pdf_form = [form]
        frozen = formula.pdf_character[:]
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, -7)
        self.assertEqual(formula.pdf_character, frozen)
        self.assertIs(formula.pdf_curve[0], curve)
        self.assertIs(formula.pdf_form[0], form)

    def test_baseline_does_not_invent_an_anchor_or_change_legacy_objects(self):
        from wenyi_babeldoc_bridge.protected_objects import (
            restore_protected_formula_baselines,
        )

        para, _, fonts, bb = self.paragraph("Given x<1.", math_letters="x")
        _, items, _ = prepare_protected_annotations(para, [], fonts=fonts, bb=bb)
        formula = para.pdf_paragraph_composition[-1].pdf_formula
        formula.y_offset = 2
        for char in formula.pdf_character:
            char.box.y += 40
            char.box.y2 += 40
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, 2)
        for char in formula.pdf_character:
            char.box.y -= 40
            char.box.y2 -= 40
        [item] = [item for item in items if item.get("protected")]
        item["protected"] = False
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, 2)
        item["protected"] = True
        para.vertical = True
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, 2)
        para.vertical = False
        para.pdf_paragraph_composition = [para.pdf_paragraph_composition[-1]]
        item["composition_index"] = 0
        restore_protected_formula_baselines(para, items)
        self.assertEqual(formula.y_offset, 2)
