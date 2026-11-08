"""Real PDF annotation geometry without layout assets or translation services."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from wenyi_babeldoc_bridge.annotations import capture_links, restore_links


@unittest.skipUnless(importlib.util.find_spec("pymupdf"), "PyMuPDF not installed")
class PDFLinkTests(unittest.TestCase):
    def test_resolved_named_destination_becomes_selected_page_jump(self):
        import pymupdf

        with tempfile.TemporaryDirectory() as directory:
            with pymupdf.open() as source:
                for _ in range(3):
                    source.new_page(width=300, height=400)
                source[0].insert_link(
                    {
                        "kind": pymupdf.LINK_GOTO,
                        "from": pymupdf.Rect(50, 60, 100, 80),
                        "page": 2,
                        "to": pymupdf.Point(60, 100),
                    }
                )
                data = source.tobytes()
            with pymupdf.open(stream=data, filetype="pdf") as source:
                xref = source[0].get_links()[0]["xref"]
                source.xref_set_key(xref, "A/D", "(reference)")
                source.xref_set_key(
                    source.pdf_catalog(),
                    "Names",
                    f"<< /Dests << /Names [(reference) "
                    f"[{source[2].xref} 0 R /XYZ 60 300 0]] >> >>",
                )
                data = source.tobytes()
            path = Path(directory) / "named.pdf"
            with pymupdf.open(stream=data, filetype="pdf") as source:
                self.assertEqual(source[0].get_links()[0]["kind"], pymupdf.LINK_NAMED)
                records = capture_links(source)
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["action"]["kind"], pymupdf.LINK_GOTO)
                source.xref_set_key(source[0].xref, "Annots", "null")
                source.delete_pages([1])
                source.save(path)
            restore_links(path, records, [0, 2], {})
            with pymupdf.open(path) as result:
                link = result[0].get_links()[0]
                self.assertEqual(link["kind"], pymupdf.LINK_GOTO)
                self.assertEqual(link["page"], 1)
                self.assertEqual(tuple(link["to"]), (60, 100))

    def test_failed_text_link_is_not_restored_at_stale_source_rectangle(self):
        import pymupdf

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.pdf"
            with pymupdf.open() as source:
                page = source.new_page(width=300, height=400)
                for index in range(3):
                    page.insert_link(
                        {
                            "kind": pymupdf.LINK_URI,
                            "from": pymupdf.Rect(
                                50, 60 + index * 30, 100, 80 + index * 30
                            ),
                            "uri": f"https://example.org/{index}",
                        }
                    )
                data = source.tobytes()
            with pymupdf.open(stream=data, filetype="pdf") as source:
                records = capture_links(source)
                records[0]["text_bound"] = records[1]["text_bound"] = True
                source.xref_set_key(source[0].xref, "Annots", "null")
                source.save(path)
            restore_links(path, records, [0], {records[1]["id"]: [[10, 200, 40, 220]]})
            with pymupdf.open(path) as result:
                links = result[0].get_links()
                self.assertEqual(
                    [link["uri"] for link in links],
                    ["https://example.org/1", "https://example.org/2"],
                )

    def test_static_links_keep_crop_rotation_geometry_and_selected_destinations(self):
        import pymupdf

        for rotation in (0, 90, 180, 270):
            with (
                self.subTest(rotation=rotation),
                tempfile.TemporaryDirectory() as directory,
            ):
                with pymupdf.open() as source:
                    for _ in range(3):
                        source.new_page(width=300, height=400)
                    source[0].set_cropbox(pymupdf.Rect(20, 30, 280, 370))
                    source[0].set_rotation(rotation)
                    source[2].set_cropbox(pymupdf.Rect(10, 20, 290, 380))
                    source[2].set_rotation(rotation)
                    source[0].insert_link(
                        {
                            "kind": pymupdf.LINK_URI,
                            "from": pymupdf.Rect(50, 60, 100, 80),
                            "uri": "https://example.org",
                        }
                    )
                    source[0].insert_link(
                        {
                            "kind": pymupdf.LINK_GOTO,
                            "from": pymupdf.Rect(110, 60, 140, 80),
                            "page": 2,
                            "to": pymupdf.Point(60, 100),
                        }
                    )
                    data = source.tobytes()
                path = Path(directory) / "translated.pdf"
                with pymupdf.open(stream=data, filetype="pdf") as source:
                    original = source[0].get_links()
                    records = capture_links(source)
                    for page in source:
                        source.xref_set_key(page.xref, "Annots", "null")
                    source.delete_pages([1])
                    source.save(path)
                restore_links(path, records, [0, 2], {})
                with pymupdf.open(path) as result:
                    links = result[0].get_links()
                    self.assertEqual(len(links), 2)
                    for before, after in zip(original, links):
                        for expected, actual in zip(before["from"], after["from"]):
                            self.assertAlmostEqual(expected, actual, places=3)
                    self.assertEqual(links[1]["page"], 1)
                    self.assertEqual(tuple(links[1]["to"]), tuple(original[1]["to"]))


if __name__ == "__main__":
    unittest.main()
