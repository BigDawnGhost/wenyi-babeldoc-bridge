"""Real parsing/typesetting regressions for conservatively repaired math ownership."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("WENYI_BABELDOC_INTEGRATION") == "1",
    "Set WENYI_BABELDOC_INTEGRATION=1 to run real BabelDOC",
)
class MathAttachmentIntegrationTests(unittest.TestCase):
    def test_detached_accents_and_page_script_survive_reflow_and_restore(self):
        for side in ("left", "right"):
            for vertical in ("upper", "lower"):
                with self.subTest(side=side, vertical=vertical):
                    self._assert_reflow_and_restore(side, vertical)

    def _assert_reflow_and_restore(self, side, vertical):
        import pymupdf
        from babeldoc.format.pdf.document_il.il_version_1 import Box, PageLayout
        from fastapi.testclient import TestClient

        from wenyi_babeldoc_bridge import server
        from wenyi_babeldoc_bridge.pipeline import require_babeldoc

        class FixedLayout:
            def __init__(self, config):
                pass

            def process(self, docs, pdf):
                for page in docs.page:
                    page.page_layout = [
                        PageLayout(
                            id=1,
                            box=Box(50, 630, 430, 715),
                            conf=1,
                            class_name="plain text",
                        )
                    ]
                return docs

        def chars(page: Any) -> list[tuple[str, tuple[float, float], float]]:
            return [
                (c["c"], c["origin"], span["size"])
                for block in page.get_text("rawdict")["blocks"]
                if "lines" in block
                for line in block["lines"]
                for span in line["spans"]
                for c in span["chars"]
            ]

        with pymupdf.open() as source:
            page = source.new_page(width=612, height=792)
            x = 64
            runs = []
            variables = {}
            for text, font, key in (
                ("Before ", "tiro", None),
                ("M", "tiit", "left-M"),
                ("=", "tiro", None),
                ("M", "tiit", "right-M"),
                (". Next C=", "tiro", None),
                ("k", "tiit", "k"),
                ("S", "tiit", None),
                (", after.", "tiro", None),
            ):
                if key == "k" and side == "left":
                    square_x = x
                    x += 4
                if key:
                    variables[key] = x
                runs.append(((x, 100), text, font, 12))
                x += pymupdf.get_text_length(text, fontname=font, fontsize=12)
                if key == "k":
                    if side == "right":
                        square_x = x + 0.4
                    # Keep the ordinary-font variables distinct from a prose word.
                    x += 4
            # Paint attachments before the baseline text, as many PDFs do.
            page.insert_text(
                (variables["right-M"] + 2, 97), "^", fontname="tiro", fontsize=12
            )
            page.insert_text((variables["k"], 97), "~", fontname="tiro", fontsize=12)
            page.insert_text(
                (square_x, 94 if vertical == "upper" else 104),
                "2",
                fontname="tiro",
                fontsize=7.2,
            )
            for origin, text, font, size in runs:
                page.insert_text(origin, text, fontname=font, fontsize=size)
            original_chars = chars(page)
            pdf_bytes = source.tobytes()
        original_k = next(c for c in original_chars if c[0] == "k")
        original_square = next(c for c in original_chars if c[0] == "2")
        original_tilde = next(c for c in original_chars if c[0] == "~")
        native = require_babeldoc()
        native["LayoutParser"] = FixedLayout
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "_BASE", Path(directory)),
            patch.object(server, "_SESSIONS", {}),
            patch(
                "wenyi_babeldoc_bridge.pipeline.require_babeldoc", return_value=native
            ),
            TestClient(server.app) as client,
        ):
            response = client.post(
                "/extract", files={"file": ("attachments.pdf", pdf_bytes)}
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            [unit] = payload["paragraphs"]["paragraphs"]
            objects = [a for a in unit["annotations"] if a.get("protected")]
            self.assertEqual(len(objects), 2, objects)
            self.assertIn("^", objects[0]["object_source"])
            self.assertTrue(
                all(c in objects[1]["object_source"] for c in ("k", "~", "2", "S"))
            )
            self.assertNotIn("^", unit["source"])
            self.assertNotIn("~", unit["source"])
            self.assertNotIn("2", unit["source"])
            for prefix in (
                "条件",
                "为了检验重新排版时数学符号是否跟随基字移动，我们先加入一段较长的中文说明，然后使用条件",
            ):
                target = prefix + "；接着，继续。"
                placements = [
                    {
                        "id": item["id"],
                        "mode": "point",
                        "target_start": position,
                        "target_end": position,
                        "target_order": order,
                        "status": "aligned",
                    }
                    for order, (item, position) in enumerate(
                        zip(objects, (len(prefix), len(prefix) + 4))
                    )
                ]
                body = {
                    "session_id": payload["session_id"],
                    "translations": {unit["id"]: target},
                    "annotations": {
                        unit["id"]: {
                            "target_digest": hashlib.sha256(
                                target.encode()
                            ).hexdigest(),
                            "placements": placements,
                        }
                    },
                }
                attempts = []
                for attempt in range(2):
                    if attempt:
                        server._SESSIONS.clear()
                    filled = client.post("/fillback", json=body)
                    self.assertEqual(filled.status_code, 200, filled.text[:200])
                    with pymupdf.open(stream=filled.content, filetype="pdf") as output:
                        self.assertEqual(len(output), 1)
                        rendered = chars(output[0])
                    for letter in ("^", "~", "k", "2", "S"):
                        self.assertEqual(
                            sum(c[0] == letter for c in rendered), 1, rendered
                        )
                    k = next(c for c in rendered if c[0] == "k")
                    square = next(c for c in rendered if c[0] == "2")
                    tilde = next(c for c in rendered if c[0] == "~")
                    for actual, original in (
                        (square, original_square),
                        (tilde, original_tilde),
                    ):
                        for axis in (0, 1):
                            self.assertAlmostEqual(
                                (actual[1][axis] - k[1][axis]) / k[2],
                                (original[1][axis] - original_k[1][axis])
                                / original_k[2],
                                places=3,
                            )
                        self.assertAlmostEqual(
                            actual[2] / k[2], original[2] / original_k[2], places=3
                        )
                    hat = next(c for c in rendered if c[0] == "^")
                    matrices = [c for c in rendered if c[0] == "M"]
                    self.assertEqual(len(matrices), 2)
                    right = max(matrices, key=lambda c: c[1][0])
                    self.assertLess(abs(hat[1][0] - right[1][0]), right[2] * 0.3)
                    self.assertLess(hat[1][1], right[1][1])
                    self.assertTrue(any(c[0] == "继" for c in rendered))
                    attempts.append(rendered)
                self.assertEqual(attempts[0], attempts[1])
            deleted = client.delete(f"/session/{payload['session_id']}")
            self.assertEqual(deleted.status_code, 200)
            self.assertFalse((Path(directory) / payload["session_id"]).exists())
