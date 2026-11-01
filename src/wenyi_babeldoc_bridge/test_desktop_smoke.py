"""Smoke assertions accept PDF whitespace without hiding missing translations."""

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "smoke_desktop", Path(__file__).resolve().parents[2] / "scripts/smoke_desktop.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class FillbackTextTests(unittest.TestCase):
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
