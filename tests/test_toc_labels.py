"""TOC eligibility uses physical pages; page labels are never destinations."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf

from wenyi_babeldoc_bridge.preservation.toc import (
    ContentsRow,
    front_toc,
    separate_cells,
)


def _dotted_rows(page, *, left=50):
    for i in range(3):
        y = 120 + i * 15
        page.insert_text((left, y), f"Entry {i} ..............")
        page.insert_text((left + 310, y), "42")


class FrontContentsTests(unittest.TestCase):
    def test_native_glyph_disagreement_or_intersecting_formula_keeps_model_boxes(self):
        row = ContentsRow(
            pymupdf.Rect(30, 40, 80, 50), pymupdf.Rect(250, 40, 260, 50), "7"
        )
        char = SimpleNamespace(
            char_unicode="x", box=SimpleNamespace(x=250, y=50, x2=260, y2=60)
        )
        coords = tuple((64, float(v)) for v in (40, 40, 60, 50))
        boxes = [(coords, 1.0, "plain text")]
        self.assertIs(separate_cells(boxes, [row], [char], 100), boxes)
        char.char_unicode = "7"
        self.assertNotEqual(separate_cells(boxes, [row], [char], 100), boxes)
        boxes = [(coords, 1.0, "formula")]
        self.assertIs(separate_cells(boxes, [row], [char], 100), boxes)

    def test_requires_contents_run_before_first_bookmarked_section(self):
        with pymupdf.open() as doc:
            for _ in range(5):
                doc.new_page()
            for n in range(5):
                page = doc[n]
                if n in (1, 3):
                    page.insert_text((50, 60), "Contents")
                _dotted_rows(page)
            # Identical dotted rows before the heading and at the destination
            # are not TOC rows. 42 is a printed label, not the physical bound.
            doc.set_toc([[1, "First section", 4]])
            found = front_toc(doc, {0, 1, 2, 3, 4})
            self.assertEqual({n: len(v) for n, v in found.items()}, {1: 3, 2: 3})
            self.assertEqual(list(front_toc(doc, {2})), [2])

    def test_no_outline_continuation_stops_at_gap(self):
        with pymupdf.open() as doc:
            for _ in range(3):
                doc.new_page()
            doc[0].insert_text((50, 60), "Table of Contents")
            for n in (0, 2):
                _dotted_rows(doc[n])
            self.assertEqual(list(front_toc(doc, {0, 2})), [0])

    def test_unbounded_continuation_must_keep_the_confirmed_page_number_column(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), "Contents")
            _dotted_rows(page)
            _dotted_rows(doc.new_page(), left=140)  # Not the contents column.
            self.assertEqual(list(front_toc(doc, {0, 1})), [0])

    def test_unconfirmed_heading_does_not_hide_a_later_contents_run(self):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((50, 60), "Contents")
            page = doc.new_page()
            page.insert_text((50, 60), "Table of Contents")
            _dotted_rows(page)
            self.assertEqual(list(front_toc(doc, {1})), [1])

    def test_run_that_ends_in_body_text_does_not_restart_on_the_next_page(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), "Contents")
            _dotted_rows(page)
            for i in range(4):
                page.insert_text((50, 185 + i * 16), "The body has already started.")
            _dotted_rows(doc.new_page())  # A later table has identical geometry.
            self.assertEqual(list(front_toc(doc, {0, 1})), [0])
            self.assertEqual(front_toc(doc, {1}), {})

    def test_page_folio_does_not_close_an_otherwise_continuous_run(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), "Contents")
            _dotted_rows(page)
            page.insert_text((300, 820), "Page 1")
            page = doc.new_page()
            page.insert_text((300, 25), "Page 2")
            _dotted_rows(page)
            self.assertEqual(list(front_toc(doc, {1})), [1])

    def test_superscript_within_a_title_is_not_intervening_prose(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), "Contents")
            _dotted_rows(page)
            page.insert_text((75, 130), "(0)", fontsize=6)
            _dotted_rows(doc.new_page())
            self.assertEqual(list(front_toc(doc, {0, 1})), [0, 1])

    def test_two_dotted_columns_on_the_same_baseline_are_not_one_title(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), "Contents")
            for i in range(3):
                y = 120 + i * 15
                page.insert_text((50, y), f"Left topic ......{i + 2}")
                page.insert_text((300, y), f"Right topic ......{i + 6}")
            self.assertEqual(front_toc(doc, {0}), {})

    def test_link_covering_the_whole_block_is_not_three_independent_links(self):
        with pymupdf.open() as doc:
            doc.new_page()
            doc.new_page()
            page = doc[0]
            page.insert_text((50, 60), "Contents")
            for i in range(3):
                y = 120 + i * 15
                page.insert_text((50, y), f"Table row {i}")
                page.insert_text((360, y), "42")
            page.insert_link(
                {
                    "kind": pymupdf.LINK_GOTO,
                    "from": pymupdf.Rect(40, 100, 400, 160),
                    "page": 1,
                }
            )
            with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as reopened:
                self.assertEqual(front_toc(reopened, {0}), {})

    def test_unreadable_outline_disables_only_the_optional_repair(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), "Contents")
            _dotted_rows(page)
            with (
                patch.object(
                    doc, "get_toc", side_effect=pymupdf.FileDataError("invalid outline")
                ),
                self.assertLogs(
                    "wenyi_babeldoc_bridge.preservation.toc", level="WARNING"
                ),
            ):
                self.assertEqual(front_toc(doc, {0}), {})

    def test_title_and_number_links_must_agree_on_the_destination_point(self):
        for same_target in (True, False):
            with self.subTest(same_target=same_target), pymupdf.open() as doc:
                doc.new_page()
                doc.new_page()
                page = doc[0]
                page.insert_text((50, 60), "Contents")
                for i in range(3):
                    y = 120 + i * 15
                    title = f"Linked title {i}"
                    page.insert_text((50, y), title)
                    page.insert_text((360, y), "42")
                    for part in (title, "42"):
                        page.insert_link(
                            {
                                "kind": pymupdf.LINK_GOTO,
                                "from": page.search_for(part)[-1],
                                "page": 1,
                                "to": pymupdf.Point(
                                    50, 100 if same_target or part == title else 200
                                ),
                            }
                        )
                with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as reopened:
                    self.assertEqual(
                        len(front_toc(reopened, {0}).get(0, [])),
                        3 if same_target else 0,
                    )

    def test_first_internal_destination_bounds_unbookmarked_linked_tables(self):
        with pymupdf.open() as doc:
            for _ in range(4):
                doc.new_page()
            for n in range(4):
                page = doc[n]
                if n == 1:
                    page.insert_text((50, 60), "Contents")
                for i in range(3):
                    y = 120 + i * 15
                    text = f"Linked subject {i}"
                    page.insert_text((50, y), text)
                    page.insert_text((360, y), "99")
                    page.insert_link(
                        {
                            "kind": pymupdf.LINK_GOTO,
                            "from": page.search_for(text)[0],
                            "page": 2,
                        }
                    )
            # None of the three otherwise indistinguishable linked tables
            # counts: one precedes Contents, two are at/after its first target.
            with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as reopened:
                self.assertEqual(list(front_toc(reopened, set(range(4)))), [1])

    @unittest.skipUnless(
        os.environ.get("WENYI_BABELDOC_INTEGRATION") == "1", "real bridge"
    )
    def test_translated_titles_do_not_own_printed_numbers_or_their_links(self):
        from wenyi_babeldoc_bridge.pipeline import (
            fillback_session,
            restore_session_with_docs,
        )
        from wenyi_babeldoc_bridge.probe_extract import create_session

        labels = ("42", "42", "37")
        titles = ("First section", "Another section", "Final section")
        targets = (
            "较长的章节标题用于检查页码是否仍留在原来的位置" * 2,
            "第二项",
            "第三项",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.pdf"
            with pymupdf.open() as pdf:
                for _ in range(3):
                    pdf.new_page()
                page = pdf[1]
                page.insert_text((60, 75), "Contents")
                for i, (title, label) in enumerate(zip(titles, labels)):
                    y = 130 + 22 * i
                    page.insert_text((60, y), title)
                    page.insert_text((310, y), label)
                    box = page.search_for(title if i == 1 else label)[-1]
                    page.insert_link(
                        {
                            "kind": pymupdf.LINK_GOTO,
                            "from": box,
                            "page": 2,
                            "to": pymupdf.Point(30, 100 + 40 * i),
                        }
                    )
                pdf[2].insert_text((60, 80), "Body")
                pdf.set_toc([[1, "First section", 3]])
                pdf.save(path)
            session = create_session(path, "2-3", Path(tmp) / "session")
            session, docs = restore_session_with_docs(
                session_id=session.session_id, out_dir=session.out_dir
            )
            units = session.paragraphs.paragraphs
            self.assertCountEqual(
                [u.source for u in units if u.page == 1], ["Contents", *titles]
            )
            changes = dict(zip(titles, targets))
            translations = {
                u.id: changes[u.source] if u.source in changes else u.source
                for u in units
            }
            linked_title = next(u for u in units if u.source == titles[1])
            [link] = [a for a in linked_title.annotations if a["kind"] == "link"]
            alignment = {
                linked_title.id: {
                    "target_digest": hashlib.sha256(targets[1].encode()).hexdigest(),
                    "placements": [
                        {
                            "id": link["id"],
                            "mode": "range",
                            "status": "aligned",
                            "target_start": 0,
                            "target_end": len(targets[1]),
                        }
                    ],
                }
            }
            out = fillback_session(
                session, translations, alignment, _pristine_docs=docs
            )
            with pymupdf.open(out) as rendered, pymupdf.open(path) as source:

                def cells(page):
                    return [
                        (w[4], tuple(round(v, 2) for v in w[:4]))
                        for w in page.get_text("words")
                        if w[4].isdecimal()
                    ]

                self.assertCountEqual(cells(rendered[0]), cells(source[1]))
                for _, box in cells(source[1]):
                    self.assertTrue(
                        all(
                            word[4].isdecimal()
                            for word in rendered[0].get_text("words")
                            if not (pymupdf.Rect(word[:4]) & pymupdf.Rect(box)).is_empty
                        )
                    )
                rendered_text = rendered[0].get_text()
                assert isinstance(rendered_text, str)
                for target in targets:
                    self.assertIn(target, "".join(rendered_text.split()))
                src_links = sorted(
                    source[1].get_links(), key=lambda link: link["from"].y0
                )
                out_links = sorted(
                    rendered[0].get_links(), key=lambda link: link["from"].y0
                )
                self.assertEqual(len(out_links), 3)
                for i, (old, new) in enumerate(zip(src_links, out_links)):
                    self.assertEqual((new["page"], new["to"]), (1, old["to"]))
                    if i == 1:
                        [text_box] = rendered[0].search_for(targets[i])
                        self.assertTrue(
                            new["from"].contains((text_box.tl + text_box.br) / 2)
                        )
                    else:
                        self.assertEqual(new["from"], old["from"])
