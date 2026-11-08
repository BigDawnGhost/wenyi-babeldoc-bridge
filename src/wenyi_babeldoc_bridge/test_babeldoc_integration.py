"""Opt-in real BabelDOC round trips; uses generated PDFs and no translation API."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("WENYI_BABELDOC_INTEGRATION") == "1",
    "Set WENYI_BABELDOC_INTEGRATION=1 to run real BabelDOC (may download assets)",
)
class BabelDOCIntegrationTests(unittest.TestCase):
    def test_inline_formulas_and_links_survive_aligned_fillback_and_restore(self):
        import pymupdf
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"WENYI_BABELDOC_STATE_DIR": str(root)}):
                from wenyi_babeldoc_bridge import server

            with pymupdf.open() as source:
                for _ in range(3):
                    source.new_page(width=595, height=842)
                text = "Research supports this result"
                source[0].insert_text((64, 100), text, fontsize=12)
                marker_x = 64 + pymupdf.get_text_length(text, fontsize=12)
                source[0].insert_text((marker_x, 95), "1", fontsize=8)
                source[0].insert_link(
                    {
                        "kind": pymupdf.LINK_GOTO,
                        "from": pymupdf.Rect(marker_x, 85, marker_x + 8, 100),
                        "page": 2,
                        "to": pymupdf.Point(64, 100),
                    }
                )
                source[1].insert_text((64, 100), "Omitted page", fontsize=12)
                source[2].insert_text((64, 100), "Reference site", fontsize=12)
                source[2].insert_link(
                    {
                        "kind": pymupdf.LINK_URI,
                        "from": pymupdf.Rect(64, 85, 145, 105),
                        "uri": "https://example.org/reference",
                    }
                )
                pdf_bytes = source.tobytes()

            with (
                patch.object(server, "_BASE", root),
                patch.object(server, "_SESSIONS", {}),
                TestClient(server.app) as client,
            ):
                extracted = client.post(
                    "/extract",
                    files={"file": ("inline.pdf", pdf_bytes)},
                    data={"pages": "1,3"},
                )
                self.assertEqual(extracted.status_code, 200, extracted.text)
                payload = extracted.json()
                units = payload["paragraphs"]["paragraphs"]
                all_items = [item for unit in units for item in unit["annotations"]]
                self.assertTrue(any(item["kind"] == "formula" for item in all_items))
                linked_ids = {
                    link_id
                    for item in all_items
                    for link_id in (
                        [item["link_id"]]
                        if item["kind"] == "link"
                        else item.get("link_ids", [])
                    )
                }
                self.assertEqual(len(linked_ids), 2)
                translations, annotations = {}, {}
                for unit in units:
                    prefix = "Translated " if len(unit["source"]) > 5 else ""
                    text = prefix + unit["source"]
                    translations[unit["id"]] = text
                    if unit["annotations"]:
                        annotations[unit["id"]] = {
                            "target_digest": hashlib.sha256(text.encode()).hexdigest(),
                            "placements": [
                                {
                                    "id": item["id"],
                                    "mode": item["mode"],
                                    "target_start": len(prefix) + item["source_start"],
                                    "target_end": len(prefix) + item["source_end"],
                                    "status": "aligned",
                                }
                                for item in unit["annotations"]
                            ],
                        }
                body = {
                    "session_id": payload["session_id"],
                    "translations": translations,
                    "annotations": annotations,
                }
                missing = client.post("/fillback", json={**body, "annotations": {}})
                self.assertEqual(missing.status_code, 200, missing.text[:500])
                statistics = json.loads(missing.headers["X-Wenyi-PDF-Annotation-Stats"])
                self.assertEqual(statistics["applied"], 0)
                self.assertEqual(statistics["skipped"], len(all_items))
                with pymupdf.open(stream=missing.content, filetype="pdf") as result:
                    self.assertIn("Translated", result[0].get_text())
                    self.assertEqual(result[0].get_links(), [])
                    self.assertEqual(result[1].get_links(), [])
                for attempt in range(2):
                    if attempt:
                        server._SESSIONS.clear()
                        restored = client.get(f"/session/{payload['session_id']}")
                        self.assertEqual(restored.status_code, 200, restored.text)
                        self.assertEqual(
                            restored.json()["paragraphs"], payload["paragraphs"]
                        )
                    response = client.post("/fillback", json=body)
                    self.assertEqual(response.status_code, 200, response.text[:500])
                    with pymupdf.open(
                        stream=response.content, filetype="pdf"
                    ) as result:
                        self.assertEqual(len(result), 2)
                        goto = result[0].get_links()
                        uri = result[1].get_links()
                        self.assertEqual(len(goto), 1)
                        self.assertEqual(goto[0]["page"], 1)
                        self.assertEqual(len(uri), 1)
                        self.assertEqual(uri[0]["uri"], "https://example.org/reference")
                        glyphs = [
                            (char, span)
                            for block in result[0].get_text("rawdict")["blocks"]
                            if "lines" in block
                            for line in block["lines"]
                            for span in line["spans"]
                            for char in span["chars"]
                        ]
                        markers = [
                            (char, span) for char, span in glyphs if char["c"] == "1"
                        ]
                        self.assertTrue(markers)
                        self.assertTrue(all(span["size"] < 10 for _, span in markers))
                        self.assertTrue(
                            any(
                                pymupdf.Rect(char["bbox"]).intersects(goto[0]["from"])
                                for char, _ in markers
                            )
                        )
                deleted = client.delete(f"/session/{payload['session_id']}")
                self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_failed_link_keeps_translation_and_valid_link_in_same_paragraph(self):
        import pymupdf
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            from wenyi_babeldoc_bridge import server

            with pymupdf.open() as source:
                page = source.new_page(width=595, height=842)
                page.insert_text((64, 100), "Alpha Beta", fontsize=12)
                for word, uri in (
                    ("Alpha", "https://example.org/valid"),
                    ("Beta", "https://example.org/failed"),
                ):
                    page.insert_link(
                        {
                            "kind": pymupdf.LINK_URI,
                            "from": page.search_for(word)[0],
                            "uri": uri,
                        }
                    )
                pdf_bytes = source.tobytes()
            with (
                patch.object(server, "_BASE", root),
                patch.object(server, "_SESSIONS", {}),
                TestClient(server.app) as client,
            ):
                health = client.get("/health").json()
                self.assertIn("annotation-best-effort-v1", health["capabilities"])
                extracted = client.post(
                    "/extract", files={"file": ("siblings.pdf", pdf_bytes)}
                )
                self.assertEqual(extracted.status_code, 200, extracted.text)
                payload = extracted.json()
                [unit] = payload["paragraphs"]["paragraphs"]
                items = [item for item in unit["annotations"] if item["kind"] == "link"]
                self.assertEqual(len(items), 2)
                target = "中文 " + unit["source"]
                placements = [
                    {
                        "id": item["id"],
                        "mode": item["mode"],
                        "target_start": 3 + item["source_start"],
                        "target_end": 3 + item["source_end"],
                        "status": (
                            "fallback"
                            if unit["source"][item["source_start"] : item["source_end"]]
                            == "Beta"
                            else "aligned"
                        ),
                    }
                    for item in items
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
                for attempt in range(2):
                    if attempt:
                        server._SESSIONS.clear()
                    response = client.post("/fillback", json=body)
                    self.assertEqual(response.status_code, 200, response.text[:500])
                    statistics = json.loads(
                        response.headers["X-Wenyi-PDF-Annotation-Stats"]
                    )
                    self.assertEqual(statistics["translated"]["applied"], 1)
                    self.assertEqual(statistics["translated"]["skipped"], 1)
                    self.assertEqual(statistics["reasons"], {"alignment_failed": 1})
                    diagnostics = json.loads(
                        (
                            root / payload["session_id"] / "annotation_stats.json"
                        ).read_text()
                    )
                    self.assertEqual(diagnostics["summary"], statistics)
                    with pymupdf.open(
                        stream=response.content, filetype="pdf"
                    ) as result:
                        self.assertIn("中文", result[0].get_text())
                        self.assertIn("Beta", result[0].get_text())
                        [link] = result[0].get_links()
                        self.assertEqual(link["uri"], "https://example.org/valid")
                deleted = client.delete(f"/session/{payload['session_id']}")
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertFalse((root / payload["session_id"]).exists())

    def test_extract_fillback_restore_page_selection_and_delete(self):
        import pymupdf
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"WENYI_BABELDOC_STATE_DIR": str(root)}):
                from wenyi_babeldoc_bridge import server

            with pymupdf.open() as source:
                for number in (1, 2):
                    page = source.new_page(width=595, height=842)
                    page.insert_text((64, 80), f"Synthetic page {number}", fontsize=20)
                    page.insert_textbox(
                        pymupdf.Rect(64, 110, 530, 230),
                        f"Original paragraph on page {number}. "
                        "This generated document tests paragraph extraction, "
                        "stable identities and translated PDF typesetting. "
                        "No private documents or model translation services are used.",
                        fontsize=12,
                    )
                pdf_bytes = source.tobytes()

            with (
                patch.object(server, "_BASE", root),
                patch.object(server, "_SESSIONS", {}),
                TestClient(server.app) as client,
            ):
                full_ids = set()
                for pages, expected_pages in ((None, 2), ("2", 1)):
                    with self.subTest(pages=pages):
                        response = client.post(
                            "/extract",
                            files={"file": ("synthetic.pdf", pdf_bytes)},
                            data={"pages": pages} if pages else {},
                        )
                        self.assertEqual(response.status_code, 200, response.text)
                        payload = response.json()
                        session_id = payload["session_id"]
                        units = payload["paragraphs"]["paragraphs"]
                        self.assertTrue(units)
                        ids = {unit["id"] for unit in units}
                        self.assertEqual(len(ids), len(units))
                        for unit in units:
                            self.assertEqual(
                                unit["id"], f"{unit['page']}:{unit['index']}"
                            )
                        if pages:
                            self.assertTrue(all(unit["page"] == 1 for unit in units))
                            self.assertEqual(ids, full_ids)
                        else:
                            full_ids = {
                                unit["id"] for unit in units if unit["page"] == 1
                            }

                        folder = root / session_id
                        snapshot = folder / "styles_and_formulas.pickle"
                        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
                        mapping = {
                            unit["id"]: f"首次回填验证 {index}"
                            for index, unit in enumerate(units)
                        }
                        first_id = units[0]["id"]
                        for invalid in (
                            {
                                key: value
                                for key, value in mapping.items()
                                if key != first_id
                            },
                            {**mapping, "999:999": "unknown"},
                            {**mapping, first_id: " "},
                        ):
                            rejected = client.post(
                                "/fillback",
                                json={
                                    "session_id": session_id,
                                    "translations": invalid,
                                },
                            )
                            self.assertEqual(rejected.status_code, 400, rejected.text)

                        for attempt in range(2):
                            if attempt:
                                server._SESSIONS.clear()
                                restored = client.get(f"/session/{session_id}")
                                self.assertEqual(
                                    restored.status_code, 200, restored.text
                                )
                                self.assertTrue(restored.json()["restored"])
                                mapping = {
                                    key: text.replace("首次", "再次")
                                    for key, text in mapping.items()
                                }
                            result = client.post(
                                "/fillback",
                                json={
                                    "session_id": session_id,
                                    "translations": mapping,
                                },
                            )
                            self.assertEqual(result.status_code, 200, result.text[:500])
                            with pymupdf.open(
                                stream=result.content, filetype="pdf"
                            ) as pdf:
                                self.assertEqual(len(pdf), expected_pages)
                                text = "".join(page.get_text() for page in pdf)
                                compact = "".join(text.split())
                                for translation in mapping.values():
                                    self.assertIn("".join(translation.split()), compact)
                                self.assertNotIn("Originalparagraph", compact)
                                self.assertTrue(
                                    all(
                                        abs(page.rect.width - 595) < 1
                                        and abs(page.rect.height - 842) < 1
                                        for page in pdf
                                    )
                                )
                            self.assertEqual(
                                hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                                digest,
                            )

                        deleted = client.delete(f"/session/{session_id}")
                        self.assertEqual(deleted.status_code, 200, deleted.text)
                        self.assertFalse(folder.exists())
                        self.assertTrue(root.exists())
                        self.assertEqual(
                            client.get(f"/session/{session_id}").status_code, 404
                        )


if __name__ == "__main__":
    unittest.main()
