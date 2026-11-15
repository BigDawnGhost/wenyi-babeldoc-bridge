"""Unknown list markers keep their glyphs and explicit item boundaries."""

from __future__ import annotations

import unittest
from copy import deepcopy
from types import SimpleNamespace as NS

from wenyi_babeldoc_bridge.annotations import _characters, source_glyph_offsets


def paragraph(*, count=5, scale=1.0, cid=23, font="custom", continuations=True):
    compositions, texts, markers = [], [], []
    for index in range(count):
        for wrapped in range(2 if continuations else 1):
            y = 700 - (index * 24 + wrapped * 12) * scale
            chars = []
            if not wrapped:
                box = NS(x=20 * scale, y=y, x2=25 * scale, y2=y + 10 * scale)
                marker = NS(
                    char_unicode=f"(cid:{cid})",
                    pdf_character_id=cid,
                    pdf_style=NS(font_id=font, font_size=10 * scale),
                    box=box,
                    xobj_id=0,
                    vertical=False,
                )
                markers.append(marker)
                chars.append(marker)
            text = (
                "Some ordinary prose here"
                if not wrapped
                else "Continued ordinary prose"
            )
            for offset, char in enumerate(text):
                x = (32 + offset * 5) * scale
                chars.append(
                    NS(
                        char_unicode=char,
                        pdf_style=NS(font_id="body", font_size=10 * scale),
                        box=NS(x=x, y=y, x2=x + 5 * scale, y2=y + 10 * scale),
                        xobj_id=0,
                        vertical=False,
                    )
                )
            texts.append((f"(cid:{cid}) " if not wrapped else "") + text)
            compositions.append(
                NS(
                    pdf_line=NS(
                        pdf_character=chars,
                        box=NS(x=20 * scale, y=y, x2=180 * scale, y2=y + 10 * scale),
                    )
                )
            )
    return (
        NS(
            unicode=" ".join(texts),
            vertical=False,
            pdf_style=NS(font_id="body", font_size=10 * scale),
            pdf_paragraph_composition=compositions,
        ),
        markers,
    )


class ListRowTests(unittest.TestCase):
    def capture(self, para):
        from wenyi_babeldoc_bridge.rows import capture_rows

        return capture_rows(para, source_glyph_offsets(para))

    def test_unknown_markers_capture_items_without_mutating_glyphs_or_paragraph(self):
        for scale, cid, font in (
            (0.6, 3, "Other"),
            (1.0, 23, "custom"),
            (2.4, 9, "F8"),
        ):
            with self.subTest(scale=scale, cid=cid):
                para, markers = paragraph(scale=scale, cid=cid, font=font)
                before = deepcopy(para)
                structure = self.capture(para)
                self.assertEqual(para, before)
                self.assertEqual(len(structure.rows), 5)
                self.assertEqual(structure.markers, tuple(markers))
                chunks = [
                    para.unicode[row["source_start"] : row["source_end"]]
                    for row in structure.rows
                ]
                self.assertTrue(
                    all(chunk.startswith(f"(cid:{cid}) ") for chunk in chunks)
                )
                self.assertTrue(
                    all("Continued ordinary prose" in chunk for chunk in chunks)
                )

    def test_tabs_are_not_unknown_marker_evidence(self):
        para, markers = paragraph()
        for char in markers:
            char.char_unicode = "\t"
        para.unicode = para.unicode.replace("(cid:23)", "\t")
        self.assertEqual(self.capture(para).rows, [])

    def test_sparse_and_nonwrapping_candidates_are_left_unchanged(self):
        for count, continuations in ((2, True), (5, False)):
            with self.subTest(count=count, continuations=continuations):
                para, _ = paragraph(count=count, continuations=continuations)
                self.assertEqual(self.capture(para).rows, [])

    def test_different_font_or_cid_cannot_establish_repetition(self):
        for field in ("font", "cid"):
            para, markers = paragraph()
            for index, char in enumerate(markers):
                if field == "font":
                    char.pdf_style.font_id = f"font-{index}"
                else:
                    char.char_unicode = f"(cid:{30 + index})"
                    char.pdf_character_id = 30 + index
            if field == "cid":
                para.unicode = " ".join(
                    "".join(char.char_unicode for char in _characters(comp))
                    for comp in para.pdf_paragraph_composition
                )
            self.assertEqual(self.capture(para).rows, [])

    def test_ambiguous_indent_invisible_and_vertical_candidates_are_rejected(self):
        for kind in ("indent", "invisible", "vertical", "no_ink", "wrong_cid"):
            with self.subTest(kind=kind):
                para, markers = paragraph()
                for index, char in enumerate(markers):
                    if kind == "indent":
                        char.box.x += index * 2
                        char.box.x2 += index * 2
                    elif kind == "invisible":
                        char.visual_roundtrip_text_render_mode = 3
                    elif kind == "vertical":
                        char.vertical = True
                    elif kind == "wrong_cid":
                        char.pdf_character_id = 99
                    else:
                        char.visual_bbox = NS(box=NS(x=0, y=0, x2=0, y2=0))
                self.assertEqual(self.capture(para).rows, [])

    def test_outdented_continuation_is_not_a_list(self):
        para, _ = paragraph()
        for char in para.pdf_paragraph_composition[1].pdf_line.pdf_character:
            char.box.x -= 12
            char.box.x2 -= 12
        self.assertEqual(self.capture(para).rows, [])

    def test_unknown_markers_are_frozen_even_without_mathematical_font_evidence(self):
        from wenyi_babeldoc_bridge.protected_objects import (
            prepare_protected_annotations,
        )
        from wenyi_babeldoc_bridge.rows import (
            partition_row_annotations,
            remap_source_rows,
        )

        para, markers = paragraph()
        offsets = source_glyph_offsets(para)
        structure = self.capture(para)
        original_boxes = [deepcopy(marker.box) for marker in markers]
        source, items, boundaries = prepare_protected_annotations(
            para,
            [],
            fonts=[NS(font_id="custom", name="UnknownFont")],
            bb={"Box": NS, "PdfFormula": NS, "PdfParagraphComposition": NS},
            offsets=offsets,
            fixed_glyphs=structure.markers,
        )
        self.assertNotIn("(cid:", source)
        self.assertEqual(len(items), 5)
        self.assertTrue(all(item["protected"] for item in items))
        rows = remap_source_rows(source, structure.rows, boundaries)
        self.assertEqual(partition_row_annotations(items, rows), items)
        frozen = [
            char
            for comp in para.pdf_paragraph_composition
            if getattr(comp, "pdf_formula", None)
            for char in _characters(comp)
        ]
        self.assertEqual(frozen, markers)
        self.assertEqual([marker.box for marker in markers], original_boxes)

    def test_markers_painted_after_body_still_anchor_at_item_starts(self):
        from wenyi_babeldoc_bridge.protected_objects import (
            prepare_protected_annotations,
        )
        from wenyi_babeldoc_bridge.rows import (
            anchor_row_markers,
            partition_row_annotations,
            remap_source_rows,
        )

        para, markers = paragraph()
        for comp in para.pdf_paragraph_composition[::2]:
            chars = comp.pdf_line.pdf_character
            chars.append(chars.pop(0))
        para.unicode = " ".join(
            "".join(char.char_unicode for char in _characters(comp))
            for comp in para.pdf_paragraph_composition
        )
        offsets = source_glyph_offsets(para)
        structure = self.capture(para)
        self.assertEqual(len(structure.rows), 5)
        self.assertEqual(structure.rows[0]["source_start"], 0)
        source, items, boundaries = prepare_protected_annotations(
            para,
            [],
            fonts=[],
            bb={"Box": NS, "PdfFormula": NS, "PdfParagraphComposition": NS},
            offsets=offsets,
            fixed_glyphs=structure.markers,
        )
        rows = remap_source_rows(source, structure.rows, boundaries)
        anchored = anchor_row_markers(para, items, rows, structure.markers)
        result = partition_row_annotations(anchored, rows)
        self.assertEqual(
            [item["source_start"] for item in result],
            [row["source_start"] for row in rows],
        )
        self.assertEqual([marker.char_unicode for marker in markers], ["(cid:23)"] * 5)

    def test_marker_native_object_can_retain_spaces_but_not_other_ink(self):
        from wenyi_babeldoc_bridge.rows import anchor_row_markers

        marker = NS(char_unicode="(cid:23)")
        space = NS(char_unicode=" ")
        formula = NS(pdf_character=[marker, space])
        para = NS(pdf_paragraph_composition=[NS(pdf_formula=formula)])
        items = [
            {
                "protected": True,
                "composition_index": 0,
                "source_start": 4,
                "source_end": 4,
            }
        ]
        rows = [{"source_start": 0, "source_end": 10}]
        anchored = anchor_row_markers(para, items, rows, (marker,))
        self.assertEqual(anchored[0]["source_start"], 0)
        self.assertEqual(items[0]["source_start"], 4)
        self.assertEqual(formula.pdf_character, [marker, space])
        formula.pdf_character.append(NS(char_unicode="x"))
        with self.assertRaisesRegex(ValueError, "indivisible native object"):
            anchor_row_markers(para, items, rows, (marker,))
