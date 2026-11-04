"""Opt-in real BabelDOC round trips; uses generated PDFs and no translation API."""

from __future__ import annotations

import hashlib
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
