"""Exercise the combined box policies against actual parsed glyphs, without ONNX."""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from wenyi_babeldoc_bridge import _native
from wenyi_babeldoc_bridge.native import Document
from wenyi_babeldoc_bridge.preservation.layout import prepare_layout_repair


def detection(role, coords):
    return (tuple((64, v) for v in coords), 0.9, role)


class MixedLayoutTests(unittest.TestCase):
    def test_toc_page_keeps_caption_repair_and_skips_a_competing_formula(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.pdf"
            with pymupdf.open() as source:
                page = source.new_page(width=400, height=300)
                page.insert_text((30, 30), "Contents")
                for i, title in enumerate(("Overview", "Energy levels", "References")):
                    y = 70 + i * 25
                    page.insert_text((30, y), title + " ............")
                    page.insert_text((300, y), "42")
                page.insert_text((30, 210), "Figure 2: The measured levels.")
                source.save(path)

            [parsed] = Document(_native.Document.parse(str(path), [0])).page
            caption = detection("figure_caption", (26, 192, 240, 216))
            formula = detection("formula", (29, 86, 63, 96))
            boxes = [
                detection("plain text", (25, 52, 320, 126)),
                formula,
                caption,
                detection("figure_caption", (28, 193, 238, 215)),
            ]
            with pymupdf.open(path) as pdf:
                labels = pdf[0].search_for("42")
                repaired = prepare_layout_repair(path, pdf, [parsed])(
                    parsed, boxes, 300
                )
            self.assertEqual(
                [b for b in repaired if b[2] == "figure_caption"], [caption]
            )
            self.assertIn(formula, repaired)
            # First and third rows get fixed digit boxes. The second keeps the
            # original layout because it intersects a formula detection.
            self.assertEqual(len(labels), 3)
            numbers = [
                pymupdf.Rect([axis[1] for axis in rect])
                for rect, _, role in repaired
                if role == "number"
            ]
            self.assertEqual(len(numbers), 2)
            self.assertEqual(
                [
                    any((label.tl + label.br) / 2 in rect for rect in numbers)
                    for label in labels
                ],
                [True, False, True],
            )
