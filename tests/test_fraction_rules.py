"""Tests for when an original inline stencil can serve as a fraction rule."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from wenyi_babeldoc_bridge.fraction_rules import FractionRules


def _form(parameters, samples):
    return NS(
        box=NS(x=8, x2=12, y=13, y2=13.4),
        xobj_id=0,
        render_order=21,
        pdf_form_subtype=NS(
            pdf_inline_form=NS(
                image_parameters=json.dumps(parameters),
                form_data=(
                    base64.b64encode(samples).decode("ascii")
                    if isinstance(samples, bytes)
                    else samples
                ),
            )
        ),
    )


def _glyph(y, order):
    return NS(
        visual_bbox=NS(box=NS(x=8, x2=12, y=y, y2=y + 5)),
        pdf_style=NS(font_size=8),
        xobj_id=0,
        render_order=order,
        vertical=False,
    )


class FractionRuleTests(unittest.TestCase):
    def matches(self, rules):
        chars = [(0, 0, 1, _glyph(14, 20)), (0, 2, 3, _glyph(7, 22))]
        return rules.match("d 2", chars, body_size=12)

    def test_only_painting_one_pixel_masks_are_claimed(self):
        for params, paint, transparent in (
            ({"IM": True, "W": 1, "H": 1, "BPC": 1}, b"\x7f", b"\x80"),
            ({"IM": True, "W": 1, "H": 1, "D": [1, 0]}, b"\xff", b"\x00"),
            (
                {
                    "ImageMask": True,
                    "Width": 1,
                    "Height": 1,
                    "BitsPerComponent": 1,
                    "Decode": [1.0, 0.0],
                },
                b"\x80",
                b"\x7f",
            ),
        ):
            with self.subTest(params=params):
                mask = _form(params, paint + b"\n")
                # An opaque stencil in another form cannot lend its rule.
                invisible = _form(params, transparent + b"\n")
                other_scope = _form(params, paint + b"\n")
                other_scope.xobj_id = 1
                untouched = FractionRules([invisible, other_scope])
                self.assertEqual(self.matches(untouched), [])
                self.assertIs(untouched.remaining([invisible])[0], invisible)

                rules = FractionRules([mask, other_scope])
                [match] = self.matches(rules)
                self.assertIs(match.rule, mask)
                rules.claim([match])
                self.assertEqual(self.matches(rules), [])
                [remaining] = rules.remaining([mask, other_scope])
                self.assertIs(remaining, other_scope)

    def test_packed_mask_ignores_row_padding_but_requires_a_solid_rule(self):
        params = {"IM": True, "W": 9, "H": 2, "BPC": 1}
        [match] = self.matches(FractionRules([_form(params, b"\0\x7f\0\x7f\n")]))
        self.assertEqual(match.span, (0, 3))
        for samples in (b"\0\x7f\0\xff\n", b"\x80\x7f\0\x7f\n", b"\0\x7f\n"):
            with self.subTest(samples=samples):
                self.assertEqual(
                    self.matches(FractionRules([_form(params, samples)])), []
                )

    def test_declared_length_matches_exact_stencil_bytes(self):
        mask = _form({"IM": True, "W": 1, "H": 1, "D": [0, 1], "L": 1}, b"\0")
        [match] = self.matches(FractionRules([mask]))
        self.assertIs(match.rule, mask)

    def test_unknown_or_malformed_images_are_left_alone(self):
        for extra, samples in (
            ({"IM": False}, b"\0"),
            ({"BPC": 8}, b"\0"),
            ({"BPC": True}, b"\0"),
            ({"D": [0, 0]}, b"\0"),
            ({"D": [False, True]}, b"\0"),
            ({"Decode": None}, b"\0"),
            ({"W": 0}, b"\0"),
            ({"H": 0}, b"\0"),
            ({"Width": 2}, b"\0"),
            ({"L": 2}, b"\0"),
            ({"F": "/Fl"}, b"\0"),
            ({"Filter": ["/FlateDecode"]}, b"\0"),
            ({"DP": {}}, b"\0"),
            ({}, b""),
            ({}, None),
            ({}, "not base64"),
            ({}, b"\0\x80"),
        ):
            with self.subTest(extra=extra, samples=samples):
                form = _form({"IM": True, "W": 1, "H": 1, **extra}, samples)
                rules = FractionRules([form])
                self.assertEqual(self.matches(rules), [])
                self.assertIs(rules.remaining([form])[0], form)


@unittest.skipUnless(
    os.environ.get("WENYI_BABELDOC_INTEGRATION") == "1",
    "Set WENYI_BABELDOC_INTEGRATION=1 to run real BabelDOC",
)
class FractionRuleExtractionTests(unittest.TestCase):
    def test_native_extract_agrees_with_the_painted_rule(self):
        import pymupdf
        from babeldoc.format.pdf.document_il.il_version_1 import Box, PageLayout

        from wenyi_babeldoc_bridge import pipeline

        class FixedLayout:
            def __init__(self, config):
                pass

            def process(self, docs, pdf):
                docs.page[0].page_layout = [
                    PageLayout(
                        id=1, box=Box(50, 675, 450, 714), class_name="plain text"
                    )
                ]
                return docs

        bb = pipeline.require_babeldoc()
        bb["LayoutParser"] = FixedLayout
        for dictionary, sample, paints in (
            ("", None, False),
            ("/IM true /W 1 /H 1 /BPC 1", b"\0", True),
            ("/IM true /W 1 /H 1 /BPC 1", b"\x80", False),
            ("/IM true /W 1 /H 1 /D [1 0]", b"\x80", True),
            (
                "/ImageMask true /Width 1 /Height 1 /BitsPerComponent 1 /Decode [1 0]",
                b"\0",
                False,
            ),
        ):
            with self.subTest(dictionary=dictionary, sample=sample):
                with tempfile.TemporaryDirectory() as directory, pymupdf.open() as pdf:
                    root = Path(directory)
                    path = root / "fraction.pdf"
                    page = pdf.new_page(width=612, height=792)
                    prefix = "Assume m + "
                    x = 64 + pymupdf.get_text_length(
                        prefix, fontname="tiro", fontsize=12
                    )
                    page.insert_text((64, 100), prefix, fontname="tiro", fontsize=12)
                    page.insert_text((x, 96), "d", fontname="tiit", fontsize=8)
                    if sample is not None:
                        stream = pdf.get_new_xref()
                        pdf.update_object(stream, "<<>>")
                        pdf.update_stream(
                            stream,
                            (
                                f"q 4 0 0 -.4 {x} 694.6 cm BI {dictionary} ID ".encode()
                                + sample
                                + b"\nEI Q"
                            ),
                        )
                        contents = [*page.get_contents(), stream]
                        pdf.xref_set_key(
                            page.xref,
                            "Contents",
                            "[" + " ".join(f"{n} 0 R" for n in contents) + "]",
                        )
                    page.insert_text((x, 105), "2", fontname="tiro", fontsize=8)
                    page.insert_text(
                        (x + 7, 100), " remains bounded.", fontname="tiro", fontsize=12
                    )
                    pixels = page.get_pixmap(
                        matrix=pymupdf.Matrix(8, 8),
                        colorspace=pymupdf.csGRAY,
                        clip=pymupdf.Rect(x, 97.4, x + 4, 97.8),
                    )
                    self.assertEqual(min(pixels.samples) < 255, paints)
                    pdf.save(path)
                    with patch.object(pipeline, "require_babeldoc", return_value=bb):
                        session = pipeline.extract_to_session(
                            session_id="a" * 32,
                            pdf_path=path,
                            pages_spec=None,
                            out_dir=root,
                        )
                    [unit] = session.paragraphs.paragraphs
                    objects = [
                        item["object_source"]
                        for item in unit.annotations
                        if item.get("protected")
                    ]
                    self.assertEqual(any("d/2" in obj for obj in objects), paints)


if __name__ == "__main__":
    unittest.main()
