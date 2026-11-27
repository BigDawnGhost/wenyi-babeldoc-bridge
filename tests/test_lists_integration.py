"""Real HTTP/native round trip of generated unknown list glyphs, without an LLM."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def make_unknown_list_pdf():
    import pymupdf

    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        for index in range(3):
            y = 100 + index * 28
            page.insert_text(
                (78, y), f"Item {index + 1} contains ordinary prose.", fontsize=12
            )
            page.insert_text(
                (78, y + 14), "The continuation has the same body indent.", fontsize=12
            )
        # A generated Type3 glyph deliberately has no Unicode mapping. Its
        # arbitrary code/name/font must not need a document-specific correction.
        glyph = doc.get_new_xref()
        doc.update_object(glyph, "<<>>")
        doc.update_stream(
            glyph,
            b"500 0 0 -200 500 800 d1 "
            b"370 300 m 370 366 316 420 250 420 c "
            b"184 420 130 366 130 300 c 130 234 184 180 250 180 c "
            b"316 180 370 234 370 300 c f",
        )
        font = doc.get_new_xref()
        doc.update_object(
            font,
            f"<< /Type /Font /Subtype /Type3 /Name /UnknownMarkers "
            f"/FontBBox [0 -200 500 800] /FontMatrix [.001 0 0 .001 0 0] "
            f"/Encoding << /Type /Encoding /Differences [23 /C15] >> "
            f"/FirstChar 23 /LastChar 23 /Widths [500] "
            f"/CharProcs << /C15 {glyph} 0 R >> /Resources <<>> >>",
        )
        resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
        doc.xref_set_key(resources, "Font/Mark", f"{font} 0 R")
        stream = doc.get_new_xref()
        doc.update_object(stream, "<<>>")
        doc.update_stream(
            stream,
            b" ".join(
                f"q BT /Mark 12 Tf 1 0 0 1 64 {792 - 100 - index * 28} Tm "
                f"<17> Tj ET Q".encode()
                for index in range(3)
            ),
        )
        doc.xref_set_key(
            page.xref,
            "Contents",
            f"[{' '.join(f'{xref} 0 R' for xref in page.get_contents())} {stream} 0 R]",
        )
        return doc.tobytes()


@unittest.skipUnless(
    os.environ.get("WENYI_BABELDOC_INTEGRATION") == "1",
    "Set WENYI_BABELDOC_INTEGRATION=1 to run real BabelDOC",
)
class ListIntegrationTests(unittest.TestCase):
    def test_unknown_markers_survive_explicit_rows_fillback_recovery_and_delete(self):
        import pymupdf
        from babeldoc.format.pdf.document_il.il_version_1 import Box, PageLayout
        from fastapi.testclient import TestClient

        from wenyi_babeldoc_bridge import server
        from wenyi_babeldoc_bridge.native import Document
        from wenyi_babeldoc_bridge.pipeline import require_babeldoc

        class FixedLayout:
            def __init__(self, config):
                pass

            def process(self, docs, pdf):
                for page in docs.page:
                    page.page_layout = [
                        PageLayout(
                            id=1,
                            box=Box(60, 610, 440, 710),
                            conf=1,
                            class_name="plain text",
                        )
                    ]
                return docs

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
            pdf_bytes = make_unknown_list_pdf()
            with pymupdf.open(stream=pdf_bytes, filetype="pdf") as source:
                original_gids = [
                    char[1]
                    for span in source[0].get_texttrace()
                    if span["font"] == "UnknownMarkers"
                    for char in span["chars"]
                ]
            self.assertEqual(len(original_gids), 3)
            extracted = client.post(
                "/extract", files={"file": ("unknown.pdf", pdf_bytes)}
            )
            self.assertEqual(extracted.status_code, 200, extracted.text)
            payload = extracted.json()
            [unit] = payload["paragraphs"]["paragraphs"]
            self.assertEqual(len(unit["rows"]), 3, unit)
            self.assertNotIn("(cid:", unit["source"])
            objects = [item for item in unit["annotations"] if item.get("protected")]
            self.assertEqual(len(objects), 3)
            self.assertEqual({item["object_source"] for item in objects}, {"(cid:23)"})
            translated, rows, placements = [], [], []
            cursor = 0
            for index, row in enumerate(unit["rows"]):
                text = f"第{index + 1}项正文，明确保留本条的边界。\n换行仍属于本条。"
                translated.append(text)
                rows.append({"target_start": cursor, "target_end": cursor + len(text)})
                [marker] = [
                    item
                    for item in objects
                    if row["source_start"] <= item["source_start"] <= row["source_end"]
                ]
                placements.append(
                    {
                        "id": marker["id"],
                        "mode": "point",
                        "target_start": cursor,
                        "target_end": cursor,
                        "target_order": index,
                        "status": "aligned",
                    }
                )
                cursor += len(text) + 1
            text = "\n".join(translated)
            body = {
                "session_id": payload["session_id"],
                "translations": {unit["id"]: text},
                "rows": {unit["id"]: rows},
                "annotations": {
                    unit["id"]: {
                        "target_digest": hashlib.sha256(text.encode()).hexdigest(),
                        "placements": placements,
                    }
                },
            }
            invalid = client.post(
                "/fillback", json={**body, "rows": {unit["id"]: rows[:2]}}
            )
            self.assertEqual(invalid.status_code, 400)
            attempts = []
            for attempt in range(2):
                if attempt:
                    server._SESSIONS.clear()
                with (
                    patch(
                        "wenyi_babeldoc_bridge.native.LayoutParser.__init__",
                        side_effect=AssertionError(
                            "Recovery must not load the layout model"
                        ),
                    ),
                    patch.object(
                        Document, "refresh", autospec=True, side_effect=Document.refresh
                    ) as refresh,
                    patch.object(
                        Document, "sync", autospec=True, side_effect=Document.sync
                    ) as sync,
                ):
                    filled = client.post("/fillback", json=body)
                self.assertEqual(
                    filled.status_code,
                    200,
                    filled.text[:200] if filled.status_code != 200 else "",
                )
                # Keep the projection and writer sync for the row draw-order edit.
                self.assertEqual((refresh.call_count, sync.call_count), (2, 2))
                with pymupdf.open(stream=filled.content, filetype="pdf") as result:
                    self.assertEqual(len(result), 1)
                    glyphs = [
                        (span["font"], char)
                        for span in result[0].get_texttrace()
                        for char in span["chars"]
                    ]
                    markers = [item for item in glyphs if item[0] == "UnknownMarkers"]
                    self.assertEqual(len(markers), 3, glyphs)
                    self.assertEqual([item[1][1] for item in markers], original_gids)
                    self.assertEqual(
                        len({round(item[1][2][1], 1) for item in markers}), 3
                    )
                    rendered_text = result[0].get_text("text")
                    assert isinstance(rendered_text, str)
                    self.assertIn("明确", rendered_text.replace("\n", ""))
                    attempts.append(glyphs)
            self.assertEqual(attempts[0], attempts[1])
            deleted = client.delete(f"/session/{payload['session_id']}")
            self.assertEqual(deleted.status_code, 200)
            self.assertFalse((Path(directory) / payload["session_id"]).exists())
