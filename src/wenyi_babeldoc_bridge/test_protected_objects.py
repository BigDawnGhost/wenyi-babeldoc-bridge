"""Synthetic glyph regressions for immutable mathematical objects."""

from __future__ import annotations

import hashlib
import unicodedata
import unittest
from types import SimpleNamespace as NS

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
        self.assertNotIn("object_source", item)
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
        self.assertIs(
            para.pdf_paragraph_composition[item["composition_index"]].pdf_formula,
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
