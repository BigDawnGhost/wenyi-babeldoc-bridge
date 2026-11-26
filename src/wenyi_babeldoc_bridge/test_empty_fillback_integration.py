"""HTTP regression for a valid extraction with no editable paragraphs."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("WENYI_BABELDOC_INTEGRATION") == "1",
    "Set WENYI_BABELDOC_INTEGRATION=1 to run real BabelDOC",
)
class EmptyFillbackIntegrationTests(unittest.TestCase):
    def test_formula_only_pdf_survives_cold_fillback(self):
        self._assert_formula_only_round_trip(pages=None)

    def test_formula_only_selection_survives_cold_fillback(self):
        self._assert_formula_only_round_trip(pages="2")

    def _assert_formula_only_round_trip(self, *, pages):
        import pymupdf
        from babeldoc.format.pdf.document_il.il_version_1 import Box, PageLayout
        from fastapi.testclient import TestClient

        from wenyi_babeldoc_bridge import pipeline, server

        class FixedLayout:
            def __init__(self, config):
                pass

            def process(self, docs, pdf):
                for page in docs.page:
                    page.page_layout = [
                        PageLayout(
                            id=1,
                            box=Box(50, 675, 400, 710),
                            conf=1,
                            class_name="plain text",
                        )
                    ]
                return docs

        def glyphs(page):
            return [
                (code, gid, span["font"], span["size"], tuple(round(v, 3) for v in xy))
                for span in page.get_texttrace()
                for code, gid, xy, _ in span["chars"]
            ]

        with pymupdf.open() as original:
            if pages:
                excluded = original.new_page(width=612, height=792)
                excluded.insert_text((64, 100), "This page is not selected.")
            page = original.new_page(width=612, height=792)
            page.insert_text((64, 100), "S={a,b}", fontname="tiro", fontsize=12)
            page.draw_line((63, 104), (107, 104), width=0.75)
            original_glyphs = glyphs(page)
            original_pixels = page.get_pixmap(dpi=144).samples
            pdf_bytes = original.tobytes()

        bb = pipeline.require_babeldoc()
        bb["LayoutParser"] = FixedLayout
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "_BASE", Path(directory)),
            patch.object(server, "_SESSIONS", {}),
            patch.object(pipeline, "require_babeldoc", return_value=bb),
            patch.object(
                bb["DocLayoutModel"], "load_onnx", return_value=object()
            ) as load_model,
            TestClient(server.app) as client,
        ):
            extracted = client.post(
                "/extract",
                files={"file": ("formula.pdf", pdf_bytes)},
                data={"pages": pages} if pages else {},
            )
            self.assertEqual(extracted.status_code, 200, extracted.text)
            payload = extracted.json()
            self.assertEqual(payload["paragraph_count"], 0)
            self.assertEqual(payload["paragraphs"]["paragraphs"], [])
            session_id = payload["session_id"]
            # POST, not GET, must restore the on-disk snapshot.
            server._SESSIONS.clear()
            filled = client.post(
                "/fillback", json={"session_id": session_id, "translations": {}}
            )
            self.assertEqual(filled.status_code, 200, filled.text[:500])
            self.assertTrue(server._SESSIONS[session_id].restored)
            load_model.assert_called_once()
            with pymupdf.open(stream=filled.content, filetype="pdf") as output:
                self.assertEqual(len(output), 1)
                text = output[0].get_text()
                assert isinstance(text, str)
                self.assertEqual(text.strip(), "S={a,b}")
                self.assertEqual(glyphs(output[0]), original_glyphs)
                self.assertTrue(
                    output[0].get_pixmap(dpi=144).samples == original_pixels,
                    "formula page render changed",
                )
            formula_id = f"{int(pages or '1') - 1}:0"
            for field, value in (
                ("translations", "invalid formula edit"),
                ("annotations", {}),
                ("rows", []),
            ):
                with self.subTest(field=field):
                    rejected = client.post(
                        "/fillback",
                        json={"session_id": session_id, field: {formula_id: value}},
                    )
                    self.assertEqual(rejected.status_code, 400, rejected.text)
                    self.assertIn("unknown", rejected.json()["detail"])
            self.assertEqual(client.delete(f"/session/{session_id}").status_code, 200)
            self.assertFalse((Path(directory) / session_id).exists())
