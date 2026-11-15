"""Smoke assertions accept PDF whitespace without hiding missing translations."""

import importlib.util
import unittest
from pathlib import Path

import pymupdf

spec = importlib.util.spec_from_file_location(
    "smoke_desktop", Path(__file__).resolve().parents[2] / "scripts/smoke_desktop.py"
)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class FillbackTextTests(unittest.TestCase):
    def test_extracted_cells_require_text_but_exclude_numeric_inputs(self):
        smoke.verify_extracted_cells({"N", "Gender"}, {"N", "Gender"}, {"15", "22.0"})
        for sources in ({"N"}, {"N", "Gender", "15"}, {"N", "Gender", "22.0"}):
            with self.subTest(sources=sources), self.assertRaises(AssertionError):
                smoke.verify_extracted_cells(sources, {"N", "Gender"}, {"15", "22.0"})

    def test_numeric_glyph_checks_reject_changed_font_size_or_position(self):
        regions = [pymupdf.Rect(60, 50, 160, 90)]
        with pymupdf.open() as source:
            page = source.new_page()
            page.insert_text((72, 72), "22.0", fontsize=14)
            expected = smoke.numeric_cell_glyphs(page, regions)
            smoke.verify_numeric_glyphs(page, expected, regions)
        for font, size, x in (
            ("tiro", 14, 72),
            ("helv", 12, 72),
            ("helv", 14, 73),
        ):
            with (
                self.subTest(font=font, size=size, x=x),
                pymupdf.open() as changed,
                self.assertRaises(AssertionError),
            ):
                page = changed.new_page()
                page.insert_text((x, 72), "22.0", fontname=font, fontsize=size)
                smoke.verify_numeric_glyphs(page, expected, regions)

    def test_pdf_nonbreaking_spaces_preserve_all_expected_text(self):
        smoke.verify_fillback_text(
            "Synthetic\xa0translated\xa0paragraph.\nCis\xa0male\nN\n15\n22.0\n",
            ("Cis male", "N", "15", "22.0"),
        )

    def test_cjk_translation_is_required_not_just_the_english_paragraph(self):
        text = "Synthetic translated paragraph.\n中文译文\n"
        smoke.verify_fillback_text(text, ("中文译文",))
        with self.assertRaises(AssertionError):
            smoke.verify_fillback_text(
                "Synthetic translated paragraph.\n", ("中文译文",)
            )

    def test_missing_translations_still_fail(self):
        for text in (
            "Synthetic translated paragraph.\nN\n15\n22.0\n",
            "Cis male\nN\n15\n22.0\n",
        ):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                smoke.verify_fillback_text(text, ("Cis male", "N", "15", "22.0"))
