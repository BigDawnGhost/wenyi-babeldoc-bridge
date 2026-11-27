"""Conservative geometry regressions for detached mathematical marks."""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from wenyi_babeldoc_bridge.annotations import _characters, source_glyph_offsets
from wenyi_babeldoc_bridge.math_attachments import (
    attach_math_marks,
    encoded_math_accents,
    math_accent_checker,
)
from wenyi_babeldoc_bridge.protected_objects import prepare_protected_annotations


def glyph(text, x, y=20, size=12, *, font="math", xobj=0):
    return NS(
        char_unicode=text,
        box=NS(x=x, y=y, x2=x + size / 2, y2=y + size),
        pdf_style=NS(font_id=font, font_size=size),
        xobj_id=xobj,
        vertical=False,
    )


def paragraph(chars):
    return NS(
        unicode="".join(char.char_unicode for char in chars),
        pdf_style=NS(font_id="body", font_size=12),
        pdf_paragraph_composition=[NS(pdf_line=NS(pdf_character=chars))],
        vertical=False,
    )


BB = {key: NS for key in ("Box", "PdfFormula", "PdfParagraphComposition")}
FONTS = [
    NS(font_id="math", name="AdvPSMI", xref_id=None),
    NS(font_id="body", name="TimesRoman", xref_id=None),
]


class MathAttachmentTests(unittest.TestCase):
    def normalize(self, para, loose=()):
        page = NS(pdf_paragraph=[para], pdf_character=list(loose), pdf_font=FONTS)
        offsets = {0: source_glyph_offsets(para)}
        groups = attach_math_marks(page, offsets, bb=BB)
        return page, offsets, groups

    def test_separate_accents_rejoin_their_unique_bases_without_moving_glyphs(self):
        hat, tilde = glyph("^", 30, 23), glyph("~", 90, 23)
        left, right = glyph("M", 30), glyph("k", 90)
        para = paragraph([hat, tilde, glyph(" ", 0), left, glyph(" ", 50), right])
        boxes = [vars(char.box).copy() for char in (hat, tilde, left, right)]
        page, offsets, groups = self.normalize(para)
        self.assertEqual(para.unicode, " M^ k~")
        self.assertEqual([vars(char.box) for char in (hat, tilde, left, right)], boxes)
        # Emulate native regrouping after the original reading offsets were captured.
        para.pdf_paragraph_composition = [
            NS(
                pdf_formula=NS(
                    pdf_character=[hat, tilde], box=NS(x=30, y=23, x2=96, y2=35)
                )
            ),
            NS(pdf_line=NS(pdf_character=[left, right])),
        ]
        source, items, _ = prepare_protected_annotations(
            para,
            [],
            fonts=FONTS,
            bb=BB,
            offsets=offsets[0],
            attachments=groups[0],
        )
        self.assertEqual(source.strip(), "")
        self.assertEqual(
            [item["object_source"] for item in items if item.get("protected")],
            ["M^", "k~"],
        )
        frozen = [
            comp.pdf_formula
            for comp in para.pdf_paragraph_composition
            if getattr(comp, "pdf_formula", None)
        ]
        self.assertTrue(all(formula.box.x2 - formula.box.x <= 6 for formula in frozen))
        self.assertEqual(len(page.pdf_paragraph), 1)

    def test_loose_script_in_each_corner_is_transferred_once_into_the_expression(self):
        for side in ("left", "right"):
            for vertical in ("upper", "lower"):
                with self.subTest(side=side, vertical=vertical):
                    base = glyph("k", 40)
                    script = glyph(
                        "2",
                        36 if side == "left" else 46,
                        26 if vertical == "upper" else 16,
                        7,
                        font="body",
                    )
                    para = paragraph(
                        [glyph("C", 24), glyph("=", 32), base, glyph("S", 53.5)]
                    )
                    page, offsets, groups = self.normalize(para, [script])
                    self.assertEqual(page.pdf_character, [])
                    self.assertEqual(
                        para.unicode, "C=2kS" if side == "left" else "C=k2S"
                    )
                    source, items, _ = prepare_protected_annotations(
                        para,
                        [],
                        fonts=FONTS,
                        bb=BB,
                        offsets=offsets[0],
                        attachments=groups[0],
                    )
                    self.assertEqual(source, "")
                    [item] = [item for item in items if item.get("protected")]
                    formula = para.pdf_paragraph_composition[
                        item["composition_index"]
                    ].pdf_formula
                    self.assertEqual(
                        sum(char is script for char in formula.pdf_character), 1
                    )

    def test_script_between_math_bases_preserves_geometry_in_the_whole_expression(self):
        para = paragraph(
            [glyph("C", 24), glyph("=", 32), glyph("k", 40), glyph("S", 50)]
        )
        script = glyph("2", 46, 26, 7, font="body")
        before = vars(script.box).copy()
        page, offsets, groups = self.normalize(para, [script])
        self.assertEqual(page.pdf_character, [])
        self.assertEqual(para.unicode, "C=k2S")
        source, items, _ = prepare_protected_annotations(
            para, [], fonts=FONTS, bb=BB, offsets=offsets[0], attachments=groups[0]
        )
        self.assertEqual(source, "")
        self.assertEqual(len([a for a in items if a.get("protected")]), 1)
        self.assertEqual(vars(script.box), before)

    def test_ambiguous_base_and_different_drawing_context_are_not_guessed(self):
        for other in (glyph("n", 41), glyph("n", 40, xobj=1)):
            with self.subTest(other=other):
                mark = glyph("~", 40, 23, xobj=1 if other.xobj_id == 1 else 0)
                base = glyph("k", 40)
                chars = [mark, base, other] if other.xobj_id == 0 else [mark, base]
                para = paragraph(chars)
                original = para.unicode
                _, _, groups = self.normalize(para)
                self.assertEqual(para.unicode, original)
                self.assertFalse(groups)

    def test_prose_footnote_and_operator_are_not_attachments(self):
        for mark in (glyph("2", 64, 26, 7, font="body"), glyph("^", 64, 20)):
            para = paragraph(
                [glyph(c, 40 + i * 6, font="body") for i, c in enumerate("word")]
            )
            page, _, groups = self.normalize(para, [mark])
            self.assertEqual(page.pdf_character, [mark])
            self.assertFalse(groups)
        para = paragraph([glyph("k", 40), glyph("^", 46), glyph("2", 52)])
        _, _, groups = self.normalize(para)
        self.assertFalse(groups)

    def test_inline_reference_at_expression_end_is_not_claimed_from_the_page(self):
        para = paragraph([glyph("x", 20), glyph("=", 28), glyph("k", 40)])
        footnote = glyph("2", 46, 26, 7, font="body")
        page, _, groups = self.normalize(para, [footnote])
        self.assertFalse(groups)
        self.assertEqual(page.pdf_character, [footnote])

    def test_unique_accent_can_bind_an_isolated_variable_in_an_ordinary_font(self):
        mark, base = glyph("ˆ", 42, 23, font="body"), glyph("M", 40, font="body")
        mark.box.x2 = 45
        para = paragraph([mark, glyph(" ", 20), base])
        _, offsets, groups = self.normalize(para)
        self.assertEqual(para.unicode, " Mˆ")
        _, items, _ = prepare_protected_annotations(
            para, [], fonts=FONTS, bb=BB, offsets=offsets[0], attachments=groups[0]
        )
        self.assertEqual(
            [a["object_source"] for a in items if a.get("protected")], ["Mˆ"]
        )

    def test_pdf_encoded_accent_leaves_a_distant_native_formula_and_rejoins_its_base(
        self,
    ):
        for indirect in (False, True):
            with self.subTest(indirect=indirect):
                self._assert_pdf_encoded_accent_attachment(indirect=indirect)

    def _assert_pdf_encoded_accent_attachment(self, *, indirect):
        import pymupdf

        with pymupdf.open() as pdf:
            accent_font = pdf.new_page().insert_font(fontname="helv")
            assert isinstance(accent_font, int)
            differences = "[100 /d /tildewide /f 120 /hatwider 120 /x]"
            if indirect:
                xref = pdf.get_new_xref()
                pdf.update_object(xref, differences)
                differences = f"{xref} 0 R"
            encoding = pdf.get_new_xref()
            pdf.update_object(
                encoding,
                f"<< /BaseEncoding /WinAnsiEncoding /Differences {differences} >>",
            )
            pdf.xref_set_key(accent_font, "Encoding", f"{encoding} 0 R")
            self.assertEqual(
                pdf.xref_get_key(accent_font, "Encoding/Differences")[0],
                "xref" if indirect else "array",
            )
            font = NS(font_id="accent", name="Helvetica", xref_id=accent_font)
            page = NS(
                pdf_font=[*FONTS, font],
                pdf_xobject=[
                    NS(xobj_id=2, pdf_font=[NS(font_id="accent", xref_id=None)])
                ],
            )
            accents = encoded_math_accents(pdf, [page])
            self.assertEqual(accents, {accent_font: {101: "~"}})

            mark = glyph("e", 41, y=23, font="accent")
            mark.pdf_character_id = 101
            foreign = glyph("e", 41, y=23, font="accent", xobj=2)
            foreign.pdf_character_id = 101
            is_accent = math_accent_checker(pdf, page)
            self.assertTrue(is_accent(mark))
            self.assertFalse(is_accent(foreign))
            is_xobject_accent = math_accent_checker(
                pdf,
                NS(
                    pdf_font=FONTS,
                    pdf_xobject=[NS(xobj_id=2, pdf_font=[font])],
                ),
            )
            self.assertFalse(is_xobject_accent(mark))
            self.assertTrue(is_xobject_accent(foreign))

        sigma = glyph("σ", 150, y=36)
        original_box = vars(mark.box).copy()
        base = glyph("M", 40, font="body")
        prose = [glyph(c, 10 + i * 6, font="body") for i, c in enumerate("and ")]
        para = paragraph([sigma, *prose, mark, base])
        offsets = {0: source_glyph_offsets(para)}
        para.pdf_paragraph_composition = [
            NS(pdf_formula=NS(pdf_character=[sigma, mark])),
            NS(pdf_line=NS(pdf_character=[*prose, base])),
        ]
        page.pdf_paragraph = [para]
        page.pdf_character = []
        groups = attach_math_marks(page, offsets, bb=BB, encoded_accents=accents)
        self.assertEqual(groups[0], [(base, mark)])
        source, items, _ = prepare_protected_annotations(
            para,
            [],
            fonts=page.pdf_font,
            bb=BB,
            offsets=offsets[0],
            attachments=groups[0],
        )
        self.assertEqual(source.strip(), "and")
        self.assertEqual([a["object_source"] for a in items], ["σ", "M~"])
        formula = para.pdf_paragraph_composition[
            items[-1]["composition_index"]
        ].pdf_formula
        self.assertEqual(formula.pdf_character, [base, mark])
        self.assertIs(formula.pdf_character[1], mark)
        self.assertEqual((mark.char_unicode, mark.pdf_character_id), ("e", 101))
        self.assertEqual(vars(mark.box), original_box)

    def test_invalid_differences_do_not_produce_accent_codes(self):
        import pymupdf

        with pymupdf.open() as pdf:
            font_xref = pdf.new_page().insert_font(fontname="helv")
            target = pdf.get_new_xref()
            page = NS(
                pdf_font=[NS(font_id="F1", xref_id=font_xref)],
                pdf_xobject=[],
            )
            for value in (
                "<< /Entry [101 /tildewide] >>",
                "([101 /tildewide])",
                "[101 /tildewide [/hatwide]]",
                "[101.25 /tildewide]",
                "[101 3 0 R /tildewide]",
                "[/tildewide]",
                "[256 /tildewide]",
                "[255 /x /tildewide]",
                "null",
            ):
                with self.subTest(target=value):
                    pdf.update_object(target, value)
                    pdf.xref_set_key(
                        font_xref, "Encoding", f"<< /Differences {target} 0 R >>"
                    )
                    self.assertEqual(encoded_math_accents(pdf, [page]), {})
            pdf.xref_set_key(
                font_xref, "Encoding", f"<< /Differences {pdf.xref_length()} 0 R >>"
            )
            self.assertEqual(encoded_math_accents(pdf, [page]), {})

    def test_accent_encoding_does_not_apply_to_same_font_alias_in_another_scope(self):
        mark = glyph("e", 41, y=23, font="F1", xobj=2)
        mark.pdf_character_id = 101
        base = glyph("M", 40, font="body", xobj=2)
        para = paragraph([mark, base])
        page = NS(
            pdf_paragraph=[para],
            pdf_character=[],
            pdf_font=[NS(font_id="F1", name="CMEX10", xref_id=8)],
            pdf_xobject=[NS(xobj_id=2, pdf_font=[NS(font_id="F1", xref_id=9)])],
        )
        offsets = {0: source_glyph_offsets(para)}
        groups = attach_math_marks(
            page, offsets, bb=BB, encoded_accents={8: {101: "~"}}
        )
        self.assertFalse(groups)
        self.assertEqual(para.unicode, "eM")

    def test_two_marks_in_one_slot_and_cross_paragraph_candidates_are_not_guessed(self):
        base = glyph("k", 40)
        first, second = glyph("~", 40, 23), glyph("^", 40, 23)
        para = paragraph([first, second, base])
        _, _, groups = self.normalize(para)
        self.assertFalse(groups)
        other = paragraph([glyph("n", 40)])
        page = NS(
            pdf_paragraph=[para, other],
            pdf_character=[glyph("2", 46, 26, 7)],
            pdf_font=FONTS,
        )
        offsets = {i: source_glyph_offsets(p) for i, p in enumerate(page.pdf_paragraph)}
        self.assertFalse(attach_math_marks(page, offsets, bb=BB))
        self.assertEqual(len(page.pdf_character), 1)

    def test_nested_marks_do_not_consume_each_others_anchors(self):
        base = glyph("k", 40)
        script = glyph("i", 46, 26, 7)
        accent = glyph("~", 46, 28, 7)
        para = paragraph([accent, script, base, glyph("S", 53.5)])
        original = para.unicode
        _, offsets, groups = self.normalize(para)
        self.assertFalse(groups)
        self.assertEqual(para.unicode, original)
        self.assertEqual(
            set(offsets[0]),
            {
                id(c)
                for comp in para.pdf_paragraph_composition
                for c in _characters(comp)
                if c.char_unicode.strip()
            },
        )

    def test_accepted_upper_script_stays_in_the_same_object_at_the_height_limit(self):
        para = paragraph(
            [glyph("C", 24), glyph("=", 32), glyph("k", 40), glyph("S", 53.5)]
        )
        script = glyph("2", 46, 30, 7, font="body")
        _, offsets, groups = self.normalize(para, [script])
        self.assertTrue(groups)
        _, items, _ = prepare_protected_annotations(
            para, [], fonts=FONTS, bb=BB, offsets=offsets[0], attachments=groups[0]
        )
        self.assertTrue(any("k2" in a.get("object_source", "") for a in items))

    def test_native_reference_marker_is_not_reassigned_even_inside_math(self):
        base = glyph("k", 40)
        following = glyph("S", 50)
        mark = glyph("2", 46, 26, 7, font="body")
        para = paragraph([base, mark, following])
        offsets = {0: source_glyph_offsets(para)}
        reference = NS(pdf_character=[mark], is_corner_mark=True)
        para.pdf_paragraph_composition = [
            NS(pdf_line=NS(pdf_character=[base, following])),
            NS(pdf_formula=reference),
        ]
        page = NS(pdf_paragraph=[para], pdf_character=[], pdf_font=FONTS)
        self.assertFalse(attach_math_marks(page, offsets, bb=BB))
        self.assertIs(para.pdf_paragraph_composition[1].pdf_formula, reference)

    def opposed_scripts(self, exponent):
        base = glyph("f", 40, font="italic")
        lower = glyph("Q", 46, 16, 9, font="italic")
        upper = [
            glyph(c, 46 + 4.5 * i, 25, 9, font="math" if c == "−" else "italic")
            for i, c in enumerate(exponent)
        ]
        gap = glyph(" ", 0)
        prose = [
            glyph(" ", 0),
            *[
                glyph(c, 46 + len(upper) * 4.5 + 7 + 6 * i, font="body")
                for i, c in enumerate("grows.")
            ],
        ]
        glyphs = [base, *upper, lower]
        for i, char in enumerate(glyphs):
            char.pdf_character_id = ord(char.char_unicode)
            char.render_order = 20 + i
            char.sub_render_order = 0
        para = paragraph([base, *upper, gap, lower, *prose])
        offsets = {0: source_glyph_offsets(para)}
        formula = NS(pdf_character=upper, is_corner_mark=True)
        # Native composition order is not source order.
        para.pdf_paragraph_composition = [
            NS(pdf_formula=formula),
            NS(pdf_line=NS(pdf_character=[base, gap, lower, *prose])),
        ]
        page = NS(pdf_paragraph=[para], pdf_character=[], pdf_font=FONTS)
        return para, page, offsets, glyphs

    def test_lower_letter_joins_its_opposite_native_exponent_without_rewriting(self):
        def draw_fields(char):
            return (
                vars(char.box).copy(),
                char.pdf_character_id,
                char.render_order,
                char.sub_render_order,
            )

        for exponent in ("n−1", "n−5/2"):
            with self.subTest(exponent=exponent):
                para, page, offsets, glyphs = self.opposed_scripts(exponent)
                original = para.unicode, offsets[0].copy()
                fields = [draw_fields(c) for c in glyphs]
                groups = attach_math_marks(page, offsets, bb=BB)
                self.assertEqual(groups, {0: [(glyphs[0], glyphs[-1])]})
                self.assertEqual((para.unicode, offsets[0]), original)
                source, items, _ = prepare_protected_annotations(
                    para,
                    [],
                    fonts=FONTS,
                    bb=BB,
                    offsets=offsets[0],
                    attachments=groups[0],
                )
                self.assertEqual(source, " grows.")
                [item] = [a for a in items if a.get("protected")]
                self.assertEqual(item["object_source"], f"f{exponent} Q")
                formula = para.pdf_paragraph_composition[
                    item["composition_index"]
                ].pdf_formula
                self.assertEqual(
                    [id(c) for c in formula.pdf_character], [id(c) for c in glyphs]
                )
                self.assertEqual(
                    [draw_fields(c) for c in formula.pdf_character], fields
                )

    def test_opposed_scripts_do_not_claim_a_citation_or_incompatible_letter(self):
        for exponent, field, value in (
            ("12", None, None),
            ("n−1", "xobj_id", 1),
            ("n−1", "vertical", True),
            ("n−1", "pdf_style", NS(font_id="body", font_size=9)),
            ("n−1", "box", NS(x=46, x2=50.5, y=20, y2=29)),
        ):
            with self.subTest(exponent=exponent, field=field):
                _, page, offsets, glyphs = self.opposed_scripts(exponent)
                if field:
                    setattr(glyphs[-1], field, value)
                self.assertFalse(attach_math_marks(page, offsets, bb=BB))

    def test_mark_carrier_with_an_operator_is_not_a_complete_native_formula(self):
        accent = glyph("~", 40, 23)
        script = glyph("2", 46, 16, 7, font="body")
        equals, base, following = glyph("=", 32), glyph("k", 40), glyph("S", 53.5)
        para = paragraph([accent, script, equals, base, following])
        offsets = {0: source_glyph_offsets(para)}
        para.pdf_paragraph_composition = [
            NS(pdf_formula=NS(pdf_character=[accent, script, equals])),
            NS(pdf_line=NS(pdf_character=[base, following])),
        ]
        page = NS(pdf_paragraph=[para], pdf_character=[], pdf_font=FONTS)
        groups = attach_math_marks(page, offsets, bb=BB)
        self.assertEqual(para.unicode, "=k~2S")
        self.assertEqual(groups[0], [(base, accent), (base, script)])
        source, items, _ = prepare_protected_annotations(
            para, [], fonts=FONTS, bb=BB, offsets=offsets[0], attachments=groups[0]
        )
        self.assertEqual(source, "")
        self.assertEqual([a["object_source"] for a in items], ["=k~2S"])

    def test_adding_an_accent_does_not_split_its_existing_multiline_base_object(self):
        accent, base, lower = glyph("~", 40, 23), glyph("k", 40), glyph("n", 40, -5)
        para = paragraph([accent, base, glyph(" ", 0), lower])
        offsets = {0: source_glyph_offsets(para)}
        para.pdf_paragraph_composition = [
            NS(pdf_formula=NS(pdf_character=[base, lower])),
            NS(pdf_line=NS(pdf_character=[accent])),
        ]
        page = NS(pdf_paragraph=[para], pdf_character=[], pdf_font=FONTS)
        groups = attach_math_marks(page, offsets, bb=BB)
        self.assertEqual(groups[0], [(base, accent)])
        source, items, _ = prepare_protected_annotations(
            para, [], fonts=FONTS, bb=BB, offsets=offsets[0], attachments=groups[0]
        )
        self.assertEqual(source.strip(), "")
        self.assertEqual([a["object_source"] for a in items], ["k~ n"])

    def test_vertical_directory_and_existing_complete_formula_are_unchanged(self):
        mark, base = glyph("~", 40, 23), glyph("k", 40)
        para = paragraph([mark, base])
        offsets = {0: source_glyph_offsets(para)}
        page = NS(pdf_paragraph=[para], pdf_character=[], pdf_font=FONTS)
        self.assertFalse(attach_math_marks(page, offsets, bb=BB, excluded={0}))
        para.vertical = True
        self.assertFalse(attach_math_marks(page, offsets, bb=BB))
        para.vertical = False
        formula = NS(pdf_character=[mark, base], box=base.box)
        para.pdf_paragraph_composition = [NS(pdf_formula=formula)]
        self.assertFalse(attach_math_marks(page, offsets, bb=BB))
        self.assertIs(para.pdf_paragraph_composition[0].pdf_formula, formula)

    def test_normalization_is_idempotent_and_keeps_all_draw_occurrences(self):
        base, mark = glyph("k", 40), glyph("~", 40, 23)
        para = paragraph([mark, glyph(" ", 0), base])
        page, offsets, groups = self.normalize(para)
        self.assertTrue(groups)
        first = para.unicode, offsets[0].copy()
        attach_math_marks(page, offsets, bb=BB)
        self.assertEqual((para.unicode, offsets[0]), first)
        self.assertEqual(
            [
                id(c)
                for comp in para.pdf_paragraph_composition
                for c in _characters(comp)
            ].count(id(mark)),
            1,
        )
