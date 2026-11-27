"""Regression tests for model boxes that split continuous text."""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from wenyi_babeldoc_bridge.preservation.boxes import repair_layout_boxes


def detection(label, bounds, confidence=0.9):
    return (tuple((64, value) for value in bounds), confidence, label)


def glyphs(text, *, x: float = 10, y: float = 60, first=0, context=0):
    result = []
    for i, c in enumerate(text):
        box = NS(x=x + i * 5, y=y, x2=x + (i + 1) * 5, y2=y + 8)
        result.append(
            NS(
                char_unicode=c,
                box=box,
                vertical=False,
                pdf_style=NS(font_id="body", font_size=10),
                xobj_id=context,
                render_order=first + i,
            )
        )
    return result


class LayoutRepairTests(unittest.TestCase):
    def test_clipped_single_line_includes_both_ends_of_original_text(self):
        body = detection("plain text", (23, 30, 97, 43))
        chars = glyphs("Regularly", x=10) + glyphs("used.", x=75, first=20)
        self.assertEqual(
            repair_layout_boxes([body], chars, 100),
            [detection("plain text", (10, 30, 100, 43))],
        )

    def test_clipped_edge_does_not_claim_a_word_from_another_text_box(self):
        chars = glyphs("Peak", x=20)
        # The label contains the whole word after native padding, not before.
        label = detection("plain text", (18, 32.5, 42, 39))
        for neighbor in (
            detection("plain text", (38.9, 30, 90, 43)),
            detection("plain text", (5, 30, 21.1, 43)),
        ):
            for order in ((neighbor, label), (label, neighbor)):
                with self.subTest(order=order):
                    boxes = list(order)
                    self.assertEqual(
                        repair_layout_boxes(boxes, chars, 100), list(order)
                    )
                    self.assertEqual(boxes, list(order))

    def test_line_gap_context_and_full_blocks_prevent_expansion(self):
        body = detection("plain text", (23, 30, 97, 43))
        full = detection("plain text", (23, 30, 97, 80))
        for boxes, chars in (
            ([full], glyphs("Regularly")),
            ([body], glyphs("Regularly", y=45)),
            ([body], glyphs("Re", x=7) + glyphs("gularly", x=23, first=2)),
            ([body], glyphs("Re") + glyphs("gularly", x=23, first=2, context=1)),
        ):
            with self.subTest(boxes=boxes, glyphs=chars):
                self.assertEqual(repair_layout_boxes(boxes, chars, 100), boxes)

    def test_contained_duplicate_caption_does_not_split_edges_of_outer_caption(self):
        outer = detection("figure_caption", (10, 55, 210, 80), 0.6)
        inner = detection("figure_caption", (20, 56, 206, 80.2), 0.9)
        separate = detection("figure_caption", (20, 85, 206, 110), 0.8)
        smaller = detection("figure_caption", (50, 60, 170, 72), 0.9)
        other_role = detection("plain text", (20, 56, 206, 80))
        boxes = [inner, separate, other_role, outer, smaller]
        union = detection("figure_caption", (10, 55, 210, 80.2), 0.6)
        self.assertEqual(
            repair_layout_boxes(boxes, [], 120), [separate, other_role, union, smaller]
        )

    def test_neighboring_text_box_can_only_lose_the_raised_mark(self):
        upper = detection("plain text", (8, 13, 60, 29.2))
        duplicate = detection("plain text", (9, 13, 59, 29.1))
        body = detection("plain text", (8, 30.5, 60, 65))
        above = glyphs("Above.", y=78)
        left = glyphs("of", first=10)
        mark = glyphs("e", x=24, y=62.5, first=12)[0]
        mark.visual_bbox = NS(box=NS(x=24, y=69.2, x2=28, y2=70.4))
        base = glyphs("M", x=23, first=13)

        def is_accent(char):
            return char is mark  # The PDF glyph name, not the "e" Unicode fallback.

        boxes = [upper, body, duplicate]
        chars = above + left + [mark] + base
        self.assertEqual(
            repair_layout_boxes(boxes, chars, 100, is_accent=is_accent),
            [
                detection("plain text", (8, 13, 60, 28)),
                body,
                detection("plain text", (9, 13, 59, 28)),
            ],
        )
        # Neither a second glyph in the strip nor a non-prose detection may be
        # clipped. Similar geometry alone does not establish draw continuity.
        other_glyph = glyphs("y", x=50, y=63, first=20)
        caption = detection("figure_caption", (8, 13, 60, 29.2))
        for case_boxes, case_chars in (
            (boxes, chars + other_glyph),
            ([caption, body, duplicate], chars),
            (boxes, above + left + [mark] + glyphs("M", x=23, first=14)),
            (boxes, above + left + [mark] + glyphs("M", x=23, y=58, first=13)),
            (boxes, above + left + [mark] + glyphs("M", x=23, first=13, context=1)),
            (boxes, above + left + [mark] + glyphs("M", x=31, first=13)),
            (boxes, above + glyphs("f.", first=10) + [mark] + base),
        ):
            with self.subTest(boxes=case_boxes, glyphs=case_chars):
                self.assertEqual(
                    repair_layout_boxes(
                        case_boxes, case_chars, 100, is_accent=is_accent
                    ),
                    case_boxes,
                )
        self.assertEqual(repair_layout_boxes(boxes, chars, 100), boxes)


@unittest.skipUnless(
    os.environ.get("WENYI_BABELDOC_INTEGRATION") == "1",
    "Set WENYI_BABELDOC_INTEGRATION=1 to run real BabelDOC",
)
class LayoutRepairIntegrationTests(unittest.TestCase):
    def test_same_line_columns_stay_separate_in_both_detection_orders(self):
        import pymupdf
        from fastapi.testclient import TestClient

        from wenyi_babeldoc_bridge import server
        from wenyi_babeldoc_bridge.pipeline import require_babeldoc

        label = "Peak"
        prose = "This text belongs in the right column."
        end = 64 + pymupdf.get_text_length(label, fontname="tiro", fontsize=12)
        right_box = (end - 1.1, 87, 400, 102)
        label_box = (58, 85, 90, 104)

        class FixedModel:
            def __init__(self, bounds):
                self.boxes = [
                    NS(xyxy=rect, conf=NS(item=lambda: 0.8), cls=0) for rect in bounds
                ]

            def handle_document(self, pages, *_):
                for page in pages:
                    yield page, NS(names={0: "plain text"}, boxes=self.boxes)

        with pymupdf.open() as original:
            page = original.new_page(width=612, height=792)
            page.insert_text((64, 100), label, fontname="tiro", fontsize=12)
            page.insert_text((154, 100), prose, fontname="tiro", fontsize=12)
            pdf_bytes = original.tobytes()

        bb = require_babeldoc()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "_BASE", Path(directory)),
            patch.object(server, "_SESSIONS", {}),
            patch("wenyi_babeldoc_bridge.pipeline.require_babeldoc", return_value=bb),
            TestClient(server.app) as client,
        ):
            for bounds in ((right_box, label_box), (label_box, right_box)):
                with self.subTest(bounds=bounds):
                    model = FixedModel(bounds)
                    bb["DocLayoutModel"] = NS(load_onnx=lambda model=model: model)
                    extracted = client.post(
                        "/extract", files={"file": ("columns.pdf", pdf_bytes)}
                    )
                    self.assertEqual(extracted.status_code, 200, extracted.text)
                    payload = extracted.json()
                    self.assertEqual(
                        client.delete(f"/session/{payload['session_id']}").status_code,
                        200,
                    )
                    units = payload["paragraphs"]["paragraphs"]
                    self.assertEqual(
                        [(u["id"], u["source"]) for u in units],
                        [("0:0", label), ("0:1", prose)],
                    )

    def test_inline_accent_does_not_split_a_wrapped_prose_unit(self):
        import pymupdf
        from fastapi.testclient import TestClient

        from wenyi_babeldoc_bridge import server
        from wenyi_babeldoc_bridge.pipeline import require_babeldoc

        class FixedModel:
            @classmethod
            def load_onnx(cls):
                return cls()

            def handle_document(self, pages, *_):
                # The tilde straddles the two padded text boxes, while both
                # neighboring letters belong to the lower box.
                for page in pages:
                    yield (
                        page,
                        NS(
                            names={0: "plain text"},
                            boxes=[
                                NS(xyxy=bounds, conf=NS(item=lambda: 0.8), cls=0)
                                for bounds in [
                                    (62, 163, 400, 189),
                                    (62, 190.4, 400, 223),
                                    (62, 231, 400, 248),
                                ]
                            ],
                        ),
                    )

        above = "The previous paragraph remains separate."
        below = "A separate paragraph starts here."
        prefix = "We calculate the value of"
        wrap = "This sentence wraps onto the following line."
        size = 12
        with pymupdf.open() as original:
            page = original.new_page(width=612, height=792)
            page.insert_text((64, 178), above, fontname="tiro", fontsize=size)
            page.insert_text((80, 200), prefix, fontname="tiro", fontsize=size)
            x = 83 + pymupdf.get_text_length(prefix, fontname="tiro", fontsize=size)
            base_width = pymupdf.get_text_length("M", fontname="tiit", fontsize=size)
            accent_width = pymupdf.get_text_length("~", fontname="tiit", fontsize=size)
            page.insert_text(
                (x + (base_width - accent_width) / 2, 193),
                "~",
                fontname="tiit",
                fontsize=size,
            )
            page.insert_text((x, 200), "M", fontname="tiit", fontsize=size)
            page.insert_text(
                (x + base_width, 200),
                ", which controls the error.",
                fontname="tiro",
                fontsize=size,
            )
            page.insert_text((64, 218), wrap, fontname="tiro", fontsize=size)
            page.insert_text((64, 244), below, fontname="tiro", fontsize=size)
            pdf_bytes = original.tobytes()

        bb = require_babeldoc()
        bb["DocLayoutModel"] = FixedModel
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "_BASE", Path(directory)),
            patch.object(server, "_SESSIONS", {}),
            patch("wenyi_babeldoc_bridge.pipeline.require_babeldoc", return_value=bb),
            TestClient(server.app) as client,
        ):
            extracted = client.post(
                "/extract", files={"file": ("accent.pdf", pdf_bytes)}
            )
            self.assertEqual(extracted.status_code, 200, extracted.text)
            payload = extracted.json()
            first, body, last = payload["paragraphs"]["paragraphs"]
            self.assertEqual([first["source"], last["source"]], [above, below])
            self.assertEqual(
                [first["id"], body["id"], last["id"]], ["0:0", "0:1", "0:2"]
            )
            self.assertTrue(body["source"].startswith(prefix), body["source"])
            self.assertIn("which controls the error.", body["source"])
            self.assertTrue(body["source"].endswith(wrap), body["source"])
            [formula] = [item for item in body["annotations"] if item.get("protected")]
            self.assertEqual(formula["object_source"], "M~")

            target = "计算该值以控制误差。"
            server._SESSIONS.clear()
            filled = client.post(
                "/fillback",
                json={
                    "session_id": payload["session_id"],
                    "translations": {
                        first["id"]: above,
                        body["id"]: target,
                        last["id"]: below,
                    },
                    "annotations": {
                        body["id"]: {
                            "target_digest": hashlib.sha256(
                                target.encode()
                            ).hexdigest(),
                            "placements": [
                                {
                                    "id": formula["id"],
                                    "mode": "point",
                                    "target_start": 4,
                                    "target_end": 4,
                                    "status": "aligned",
                                }
                            ],
                        }
                    },
                },
            )
            self.assertEqual(filled.status_code, 200, filled.text[:200])
            with pymupdf.open(stream=filled.content, filetype="pdf") as rendered:
                page = rendered[0]
                plot = page.get_text("text", clip=pymupdf.Rect(62, 186, 400, 223))
                self.assertIn(target, "".join(c for c in plot if c in target))
                self.assertNotIn("which", plot)
                origins = {
                    chr(c[0]): c[2]
                    for span in page.get_texttrace()
                    for c in span["chars"]
                    if chr(c[0]) in "M~"
                }
                self.assertLess(origins["~"][1], origins["M"][1])
            self.assertEqual(
                client.delete(f"/session/{payload['session_id']}").status_code, 200
            )

    def test_clipped_prose_and_overlapping_caption_export_whole_translation_units(self):
        import pymupdf
        from fastapi.testclient import TestClient

        from wenyi_babeldoc_bridge import server
        from wenyi_babeldoc_bridge.pipeline import require_babeldoc

        prose = "Regularly distributed points are used."
        caption = "Figure 3: The measured error decreases."
        continuation = "The same conditions apply to both curves."
        end = 64 + pymupdf.get_text_length(prose, fontname="tiro", fontsize=12)

        class FixedModel:
            @classmethod
            def load_onnx(cls):
                return cls()

            def handle_document(self, pages, *_):
                for page in pages:
                    yield (
                        page,
                        NS(
                            names={0: "plain text", 1: "figure_caption"},
                            boxes=[
                                NS(
                                    xyxy=(80, 89, end - 2, 104),
                                    conf=NS(item=lambda: 0.8),
                                    cls=0,
                                ),
                                NS(
                                    xyxy=(98, 187, 405, 219),
                                    conf=NS(item=lambda: 0.9),
                                    cls=1,
                                ),
                                NS(
                                    xyxy=(62, 186, 408, 219),
                                    conf=NS(item=lambda: 0.5),
                                    cls=1,
                                ),
                            ],
                        ),
                    )

        with pymupdf.open() as original:
            page = original.new_page(width=612, height=792)
            for y, text in ((100, prose), (200, caption), (213, continuation)):
                page.insert_text((64, y), text, fontname="tiro", fontsize=12)
            pdf_bytes = original.tobytes()

        bb = require_babeldoc()
        bb["DocLayoutModel"] = FixedModel
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "_BASE", Path(directory)),
            patch.object(server, "_SESSIONS", {}),
            patch("wenyi_babeldoc_bridge.pipeline.require_babeldoc", return_value=bb),
            TestClient(server.app) as client,
        ):
            extracted = client.post(
                "/extract", files={"file": ("layout.pdf", pdf_bytes)}
            )
            self.assertEqual(extracted.status_code, 200, extracted.text)
            payload = extracted.json()
            units = payload["paragraphs"]["paragraphs"]
            self.assertEqual(
                [u["source"] for u in units], [prose, f"{caption} {continuation}"]
            )
            translations = {
                u["id"]: text
                for u, text in zip(units, ("采用规则分布的点。", "图三：误差下降。"))
            }
            server._SESSIONS.clear()
            filled = client.post(
                "/fillback",
                json={
                    "session_id": payload["session_id"],
                    "translations": translations,
                },
            )
            self.assertEqual(filled.status_code, 200, filled.text[:200])
            with pymupdf.open(stream=filled.content, filetype="pdf") as pdf:
                text = pdf[0].get_text()
                assert isinstance(text, str)
                self.assertIn("采用规则分布的点。", text)
                self.assertIn("图三：误差下降。", text)
                self.assertNotRegex(text, "[A-Za-z]")
            self.assertEqual(
                client.delete(f"/session/{payload['session_id']}").status_code, 200
            )
