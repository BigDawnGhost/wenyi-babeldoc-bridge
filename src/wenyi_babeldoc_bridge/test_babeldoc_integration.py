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
    def test_vertical_glyphs_and_links_survive_fillback_and_legacy_recovery(self):
        import pymupdf
        from babeldoc.format.pdf.document_il.il_version_1 import Box, PageLayout
        from fastapi.testclient import TestClient

        from wenyi_babeldoc_bridge import server
        from wenyi_babeldoc_bridge.pipeline import (
            load_session_docs,
            persist_session_snapshot,
            require_babeldoc,
        )
        from wenyi_babeldoc_bridge.schema import ParagraphUnit

        class FixedLayout:
            def __init__(self, config):
                pass

            def process(self, docs, pdf):
                for page in docs.page:
                    page.page_layout = [
                        PageLayout(
                            id=1,
                            box=Box(60, 680, 300, 710),
                            conf=1,
                            class_name="plain text",
                        ),
                        PageLayout(
                            id=2,
                            box=Box(470, 580, 490, 600),
                            conf=1,
                            class_name="plain text",
                        ),
                        PageLayout(
                            id=3,
                            box=Box(470, 540, 490, 560),
                            conf=1,
                            class_name="plain text",
                        ),
                        PageLayout(
                            id=4,
                            box=Box(5, 100, 45, 740),
                            conf=1,
                            class_name="abandon",
                        ),
                        PageLayout(
                            id=5,
                            box=Box(550, 180, 600, 700),
                            conf=1,
                            class_name="plain text",
                        ),
                    ]
                return docs

        def glyphs(page):
            return sorted(
                (
                    char["c"],
                    span["font"],
                    round(span["size"], 3),
                    tuple(round(value, 3) for value in char["origin"]),
                    tuple(round(value, 3) for value in line["dir"]),
                )
                for block in page.get_text("rawdict")["blocks"]
                if "lines" in block
                for line in block["lines"]
                if line["dir"] != (1.0, 0.0)
                for span in line["spans"]
                for char in span["chars"]
                if char["c"].strip()
            )

        native = require_babeldoc()
        native["LayoutParser"] = FixedLayout
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with pymupdf.open() as source:
                page = source.new_page(width=612, height=792)
                page.insert_text(
                    (64, 100), "See reference", fontname="tiro", fontsize=12
                )
                marker_x = 64 + pymupdf.get_text_length(
                    "See reference", fontname="tiro", fontsize=12
                )
                page.insert_text((marker_x, 95), "1", fontname="tiro", fontsize=8)
                page.insert_link(
                    {
                        "kind": pymupdf.LINK_URI,
                        "from": pymupdf.Rect(marker_x, 85, marker_x + 8, 100),
                        "uri": "https://example.org/reference",
                    }
                )
                for digit, y in (("2", 200), ("4", 240)):
                    page.insert_text((472, y), digit, fontname="tibo", fontsize=10)
                page.insert_text(
                    (30, 550),
                    "arXiv:2108.05348v1 [cs.CE] 4 Aug 2021",
                    fontname="tiro",
                    fontsize=20,
                    rotate=90,
                )
                page.insert_text(
                    (582, 550),
                    "ROTATED SIDEBAR MUST STAY",
                    fontname="tiro",
                    fontsize=20,
                    rotate=90,
                )
                for text, name in (
                    ("arXiv:2108.05348v1", "arxiv"),
                    ("ROTATED SIDEBAR MUST STAY", "rotated"),
                ):
                    page.insert_link(
                        {
                            "kind": pymupdf.LINK_URI,
                            "from": page.search_for(text)[0],
                            "uri": f"https://example.org/sidebar/{name}",
                        }
                    )
                expected = glyphs(page)
                self.assertTrue(expected)
                pdf_bytes = source.tobytes()
            with (
                patch.object(server, "_BASE", root),
                patch.object(server, "_SESSIONS", {}),
                patch(
                    "wenyi_babeldoc_bridge.pipeline.require_babeldoc",
                    return_value=native,
                ),
                TestClient(server.app) as client,
            ):
                response = client.post(
                    "/extract", files={"file": ("identity.pdf", pdf_bytes)}
                )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                units = payload["paragraphs"]["paragraphs"]
                self.assertTrue(any(unit["source"] == "2" for unit in units))
                self.assertTrue(any(unit["source"] == "4" for unit in units))
                self.assertTrue(any(unit["annotations"] for unit in units))
                body = {
                    "session_id": payload["session_id"],
                    "translations": {unit["id"]: unit["source"] for unit in units},
                }
                session = server._SESSIONS[payload["session_id"]]
                frozen = load_session_docs(session)
                vertical = {
                    f"{page.page_number}:{index}": para
                    for page in frozen.page
                    for index, para in enumerate(page.pdf_paragraph)
                    if para.vertical
                }
                self.assertEqual(len(vertical), 2)
                self.assertFalse(set(vertical) & set(body["translations"]))
                snapshot = session.snapshot_path
                digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
                for attempt in range(3):
                    if attempt == 1:
                        # Recreate a pre-protection session that exported rotated
                        # text and marked its original links as text-bound.
                        for pid, para in vertical.items():
                            items = []
                            for link in session.paragraphs.links:
                                uri = link["action"].get("uri", "")
                                if not uri.startswith("https://example.org/sidebar/"):
                                    continue
                                left, bottom, right, top = link["from"]
                                if (
                                    para.box.x < right
                                    and para.box.x2 > left
                                    and para.box.y < top
                                    and para.box.y2 > bottom
                                ):
                                    link["text_bound"] = True
                                    items.append(
                                        {
                                            "id": f"link:{link['id']}",
                                            "kind": "link",
                                            "mode": "range",
                                            "source_start": 0,
                                            "source_end": len(para.unicode),
                                            "link_id": link["id"],
                                        }
                                    )
                            self.assertTrue(items)
                            page_number, index = map(int, pid.split(":"))
                            session.paragraphs.paragraphs.append(
                                ParagraphUnit(
                                    id=pid,
                                    page=page_number,
                                    index=index,
                                    source=para.unicode,
                                    annotations=items,
                                )
                            )
                            body["translations"][pid] = "Changed sidebar text"
                            body.setdefault("annotations", {})[pid] = {
                                "target_digest": "stale",
                                "placements": [],
                            }
                            body.setdefault("rows", {})[pid] = [
                                {"target_start": -1, "target_end": -1}
                            ]
                        session.paragraphs.paragraphs.sort(
                            key=lambda unit: (unit.page, unit.index)
                        )
                        session.paragraphs.write_json(
                            session.out_dir / "paragraphs.json"
                        )
                        session.docs = frozen
                        persist_session_snapshot(session)
                        session.docs = None
                    if attempt:
                        server._SESSIONS.clear()
                    result = client.post("/fillback", json=body)
                    self.assertEqual(result.status_code, 200, result.text[:500])
                    statistics = json.loads(
                        result.headers["X-Wenyi-PDF-Annotation-Stats"]
                    )
                    self.assertEqual(statistics["skipped"], 0)
                    with pymupdf.open(stream=result.content, filetype="pdf") as output:
                        self.assertEqual(len(output), 1)
                        self.assertEqual(glyphs(output[0]), expected)
                        links = {link["uri"]: link for link in output[0].get_links()}
                        self.assertEqual(
                            set(links),
                            {
                                "https://example.org/reference",
                                "https://example.org/sidebar/arxiv",
                                "https://example.org/sidebar/rotated",
                            },
                        )
                        link = links["https://example.org/reference"]
                        self.assertTrue(
                            link["from"].intersects(output[0].search_for("1")[0])
                        )
                        self.assertNotIn("Changed sidebar text", output[0].get_text())
                    self.assertEqual(
                        hashlib.sha256(snapshot.read_bytes()).hexdigest(), digest
                    )
                # Unchanged text does not authorize restoring an explicitly failed link.
                annotations = {}
                for unit in units:
                    if unit["annotations"]:
                        annotations[unit["id"]] = {
                            "target_digest": hashlib.sha256(
                                unit["source"].encode()
                            ).hexdigest(),
                            "placements": [
                                {
                                    "id": item["id"],
                                    "mode": item["mode"],
                                    "target_start": item["source_start"],
                                    "target_end": item["source_end"],
                                    "status": (
                                        "fallback"
                                        if item["kind"] == "link"
                                        or item.get("link_ids")
                                        else "aligned"
                                    ),
                                }
                                for item in unit["annotations"]
                            ],
                        }
                result = client.post(
                    "/fillback", json={**body, "annotations": annotations}
                )
                self.assertEqual(result.status_code, 200, result.text[:500])
                statistics = json.loads(result.headers["X-Wenyi-PDF-Annotation-Stats"])
                self.assertGreater(statistics["reasons"]["alignment_failed"], 0)
                with pymupdf.open(stream=result.content, filetype="pdf") as output:
                    self.assertEqual(
                        {link["uri"] for link in output[0].get_links()},
                        {
                            "https://example.org/sidebar/arxiv",
                            "https://example.org/sidebar/rotated",
                        },
                    )
                    self.assertEqual(glyphs(output[0]), expected)
                    self.assertIn("reference", output[0].get_text())
                self.assertEqual(
                    client.delete(f"/session/{payload['session_id']}").status_code, 200
                )

    def test_directory_rows_remain_separate_across_fillback_and_restore(self):
        import pymupdf
        from babeldoc.format.pdf.document_il.il_version_1 import Box, PageLayout
        from fastapi.testclient import TestClient

        from wenyi_babeldoc_bridge import server
        from wenyi_babeldoc_bridge.pipeline import require_babeldoc

        class FixedLayout:
            """Keep this structural regression independent of ONNX region classification."""

            def __init__(self, config):
                pass

            def process(self, docs, pdf):
                for page in docs.page:
                    page.page_layout = [
                        PageLayout(
                            id=1, box=Box(50, 680, 560, 720), conf=1, class_name="title"
                        ),
                        PageLayout(
                            id=2,
                            box=Box(50, 585, 560, 665),
                            conf=1,
                            class_name="plain text",
                        ),
                        PageLayout(
                            id=3,
                            box=Box(50, 410, 560, 460),
                            conf=1,
                            class_name="plain text",
                        ),
                    ]
                return docs

        native = require_babeldoc()
        native["LayoutParser"] = FixedLayout

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with pymupdf.open() as source:
                page = source.new_page(width=612, height=792)
                page.insert_text((60, 100), "Contents", fontname="tibo", fontsize=16)
                for index in range(5):
                    y = 140 + index * 14
                    title = f"3.{index + 1} Coordinate transformation "
                    page.insert_text((60, y), title, fontname="tiro", fontsize=10)
                    x = 60 + pymupdf.get_text_length(
                        title, fontname="tiro", fontsize=10
                    )
                    page.insert_text((x, y), "x", fontname="tiit", fontsize=10)
                    page.insert_text((320, y), ". " * 28, fontname="tiro", fontsize=10)
                    page.insert_text(
                        (520, y), str(index + 6), fontname="tiro", fontsize=10
                    )
                page.insert_text(
                    (60, 350),
                    "This is ordinary prose that continues\non another visual line.",
                    fontname="tiro",
                    fontsize=10,
                )
                pdf_bytes = source.tobytes()
            with (
                patch.object(server, "_BASE", root),
                patch.object(server, "_SESSIONS", {}),
                patch(
                    "wenyi_babeldoc_bridge.pipeline.require_babeldoc",
                    return_value=native,
                ),
                TestClient(server.app) as client,
            ):
                extracted = client.post(
                    "/extract", files={"file": ("contents.pdf", pdf_bytes)}
                )
                self.assertEqual(extracted.status_code, 200, extracted.text)
                payload = extracted.json()
                units = payload["paragraphs"]["paragraphs"]
                self.assertEqual(sum(len(unit["rows"]) for unit in units), 5)
                translations, annotations, rows = {}, {}, {}
                for unit in units:
                    source_rows = unit["rows"] or [
                        {"source_start": 0, "source_end": len(unit["source"])}
                    ]
                    parts, targets, placements = [], [], []
                    cursor = 0
                    for row in source_rows:
                        start, end = row["source_start"], row["source_end"]
                        text = "译文 " + unit["source"][start:end]
                        parts.append(text)
                        targets.append(
                            {"target_start": cursor, "target_end": cursor + len(text)}
                        )
                        for item in unit["annotations"]:
                            if (
                                start
                                <= item["source_start"]
                                <= item["source_end"]
                                <= end
                            ):
                                placements.append(
                                    {
                                        "id": item["id"],
                                        "mode": item["mode"],
                                        "target_start": cursor
                                        + 3
                                        + item["source_start"]
                                        - start,
                                        "target_end": cursor
                                        + 3
                                        + item["source_end"]
                                        - start,
                                        "status": "aligned",
                                    }
                                )
                        cursor += len(text) + 1
                    target = "\n".join(parts)
                    translations[unit["id"]] = target
                    if unit["rows"]:
                        rows[unit["id"]] = targets
                    if placements:
                        annotations[unit["id"]] = {
                            "target_digest": hashlib.sha256(
                                target.encode()
                            ).hexdigest(),
                            "placements": placements,
                        }
                body = {
                    "session_id": payload["session_id"],
                    "translations": translations,
                    "annotations": annotations,
                    "rows": rows,
                }
                self.assertEqual(
                    client.post("/fillback", json={**body, "rows": {}}).status_code, 400
                )
                for attempt in range(2):
                    if attempt:
                        server._SESSIONS.clear()
                        restored = client.get(f"/session/{payload['session_id']}")
                        self.assertEqual(
                            restored.json()["paragraphs"], payload["paragraphs"]
                        )
                    response = client.post("/fillback", json=body)
                    self.assertEqual(response.status_code, 200, response.text[:500])
                    with pymupdf.open(
                        stream=response.content, filetype="pdf"
                    ) as result:
                        self.assertEqual(len(result), 1)
                        boxes = [result[0].search_for(f"3.{i + 1}") for i in range(5)]
                        self.assertTrue(all(len(found) == 1 for found in boxes))
                        baselines = [found[0].y0 for found in boxes]
                        self.assertTrue(
                            all(b - a > 8 for a, b in zip(baselines, baselines[1:]))
                        )
                        self.assertIn("译文", result[0].get_text())
                        self.assertIn("x", result[0].get_text())
                self.assertEqual(
                    client.delete(f"/session/{payload['session_id']}").status_code, 200
                )

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
                        snapshot = folder / "styles_and_formulas.native.json.gz"
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
