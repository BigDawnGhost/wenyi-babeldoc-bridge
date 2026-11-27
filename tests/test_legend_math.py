"""Regression for split chart math and editable fallback labels."""

from __future__ import annotations

import os
import tempfile
import unicodedata
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from wenyi_babeldoc_bridge.legend_math import fixed_legend_paragraphs


def _paragraph(text, x, y, size, render_order, layout_id):
    def box(left, right):
        return NS(x=left, y=y, x2=right, y2=y + size)

    style = NS(font_id="F1", font_size=size)
    chars = []
    for offset, letter in enumerate(text):
        chars.append(
            NS(
                char_unicode=letter,
                box=box(x + offset * size / 2, x + (offset + 1) * size / 2),
                pdf_style=style,
                render_order=render_order + offset,
                xobj_id=0,
                vertical=False,
            )
        )
    paragraph = NS(
        unicode=text,
        box=box(x, x + len(text) * size / 2),
        pdf_paragraph_composition=[NS(pdf_line=NS(pdf_character=chars))],
        layout_label="fallback_line",
        layout_id=layout_id,
        vertical=False,
    )
    return paragraph, chars[0]


class LegendMathTests(unittest.TestCase):
    def test_uses_draw_order_instead_of_il_order_and_excludes_neighboring_label(self):
        base, _ = _paragraph("β", 30, 60, 8, 20, 3)
        sub, _ = _paragraph("2", 34.3, 56, 6, 21, 4)
        tail, _ = _paragraph("=-1.4", 37.6, 60, 8, 22, 3)
        label, _ = _paragraph("S", 30, 75, 8, 27, 5)
        figure = NS(class_name="figure", box=NS(x=20, y=40, x2=100, y2=90))
        page = NS(page_layout=[figure], pdf_paragraph=[label, tail, base, sub])
        self.assertEqual(fixed_legend_paragraphs(page), {1, 2, 3})

    def test_requires_role_geometry_and_original_assignment_evidence(self):
        for item, attr, replacement in (
            ("figure", "class_name", "figure_caption"),
            ("figure", "box", NS(x=40, y=40, x2=100, y2=90)),
            ("base", "layout_label", "plain text"),
            ("tail", "layout_id", 9),
            ("sub_char", "xobj_id", 1),
            ("sub_char", "render_order", 30),
            ("sub_font", "font_size", 8),
            ("sub_box", "y", 60),
            ("sub_box", "x", 45),
            ("equals_char", "char_unicode", "<"),
        ):
            with self.subTest(item=item, attr=attr):
                base, _ = _paragraph("h", 30, 60, 8, 20, 3)
                sub, sub_char = _paragraph("Y", 34.3, 56, 6, 21, 4)
                tail, equals = _paragraph("=0.07", 37.6, 60, 8, 22, 3)
                figure = NS(class_name="figure", box=NS(x=20, y=40, x2=100, y2=90))
                targets = {
                    "figure": figure,
                    "base": base,
                    "tail": tail,
                    "sub_char": sub_char,
                    "sub_font": sub_char.pdf_style,
                    "sub_box": sub_char.box,
                    "equals_char": equals,
                }
                setattr(targets[item], attr, replacement)
                page = NS(page_layout=[figure], pdf_paragraph=[base, sub, tail])
                self.assertFalse(fixed_legend_paragraphs(page))


@unittest.skipUnless(
    os.environ.get("WENYI_BABELDOC_INTEGRATION") == "1",
    "Set WENYI_BABELDOC_INTEGRATION=1 to run real BabelDOC",
)
class LegendMathIntegrationTests(unittest.TestCase):
    def test_split_legend_geometry_survives_fillback_of_editable_chart_labels(self):
        import pymupdf

        from wenyi_babeldoc_bridge import pipeline
        from wenyi_babeldoc_bridge.probe_extract import create_session

        class FigureLayoutModel:
            @classmethod
            def load_onnx(cls):
                return cls()

            def handle_document(self, pages, *_):
                for page in pages:
                    box = NS(xyxy=(50, 50, 350, 200), conf=NS(item=lambda: 0.99), cls=0)
                    yield page, NS(names={0: "figure"}, boxes=[box])

        def legend_glyphs(page):
            return sorted(
                (
                    chr(code),
                    span["font"],
                    round(span["size"], 3),
                    round(x, 3),
                    round(y, 3),
                )
                for span in page.get_texttrace()
                for code, _, (x, y), _ in span["chars"]
                if 110 < y < 140
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=390, height=300)
                for panel in (80, 220):
                    for y, value in ((120, "0.07"), (132, "0.09")):
                        page.insert_text((panel, y), "h", fontsize=5.08)
                        page.insert_text((panel + 2.96, y + 2.54), "Y", fontsize=3.81)
                        page.insert_text((panel + 5.92, y), "=" + value, fontsize=5.08)
                    page.insert_text((panel, 155), "Error level", fontsize=9)
                    page.insert_text((panel, 171), "Q", fontsize=8)
                expected = legend_glyphs(page)
                self.assertEqual(len(expected), 28)
                pdf.save(root / "input.pdf")

            bb = pipeline.require_babeldoc()
            bb["DocLayoutModel"] = FigureLayoutModel
            with patch.object(pipeline, "require_babeldoc", return_value=bb):
                extracted = create_session(root / "input.pdf", "1", root / "session")
                session, docs = pipeline.restore_session_with_docs(
                    session_id=extracted.session_id, out_dir=extracted.out_dir
                )
                editable = session.paragraphs.paragraphs
                self.assertCountEqual(
                    [u.source for u in editable], ["Error level", "Q"] * 2
                )
                self.assertTrue(
                    all(u.layout_label == "fallback_line" for u in editable)
                )
                translated = {"Error level": "误差水平", "Q": "量"}
                result = pipeline.fillback_session(
                    session,
                    {u.id: translated[u.source] for u in editable},
                    _pristine_docs=docs,
                )
            with pymupdf.open(result) as pdf:
                self.assertEqual(legend_glyphs(pdf[0]), expected)
                raw = pdf[0].get_text()
                assert isinstance(raw, str)
                text = unicodedata.normalize("NFKC", raw)
                for label, translation in translated.items():
                    self.assertIn(translation, text)
                    self.assertNotIn(label, text)
