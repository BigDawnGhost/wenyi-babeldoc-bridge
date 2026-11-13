"""Native graph regressions use synthetic PDFs, with no models or network."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from wenyi_babeldoc_bridge import _native
from wenyi_babeldoc_bridge.native import Document


class NativeGraphTests(unittest.TestCase):
    def test_projection_and_new_process_restore_preserve_the_complete_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            with pymupdf.open() as pdf:
                page = pdf.new_page()
                for index in range(80):
                    page.draw_line((40, 100 + index), (200, 100 + index))
                page.insert_text((50, 60), "Native snapshot roundtrip.")
                pdf.save(source)
            doc = Document(_native.Document.parse(str(source)))
            before = json.loads(doc.native.snapshot())
            doc.sync()
            self.assertEqual(before, json.loads(doc.native.snapshot()))
            frozen = root / "snapshot.json"
            frozen.write_text(doc.snapshot(), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; from pathlib import Path; "
                    "from wenyi_babeldoc_bridge.native import Document; "
                    "d=Document.restore(Path(sys.argv[1]).read_text()); "
                    "assert len(d.page)==1; assert d.page[0].page_number==0",
                    str(frozen),
                ],
                check=True,
            )
            restored = Document.restore(frozen.read_text())
            self.assertEqual(before, json.loads(restored.native.snapshot()))
            for invalid in ("aliases", "history", "pages"):
                with self.subTest(invalid=invalid):
                    damaged = json.loads(frozen.read_text())
                    if invalid == "aliases":
                        groups = damaged["artifact"]["shared_alias_paths"][
                            "PdfCharacter"
                        ]
                        groups.append(groups[0])
                        message = "duplicate alias"
                    elif invalid == "history":
                        damaged["artifact"]["graphic_state_nodes"] = [
                            {"ordinal": 0, "parent_ordinal": 0}
                        ]
                        message = "invalid graphics-state parent"
                    else:
                        damaged["page_objects"] = []
                        message = "missing the parser page map"
                    with self.assertRaisesRegex(RuntimeError, message):
                        Document.restore(json.dumps(damaged))

    def test_recovery_configuration_does_not_load_a_model(self):
        from wenyi_babeldoc_bridge.pipeline import (
            _build_translation_config,
            require_babeldoc,
        )

        bb = require_babeldoc()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(bb["DocLayoutModel"], "load_onnx") as onnx,
            patch.object(bb["DocLayoutModel"], "load_available") as available,
        ):
            root = Path(directory)
            _build_translation_config(
                bb,
                pdf_path=root / "source.pdf",
                pages_spec=None,
                out_dir=root,
                work_dir=root / "working",
                load_layout_model=False,
            )
            onnx.assert_not_called()
            available.assert_not_called()

    def test_revision_mismatch_fails_before_decoding_the_graph(self):
        with self.assertRaisesRegex(RuntimeError, "version mismatch"):
            _native.Document.restore(
                json.dumps(
                    {
                        "schema": "wenyi-babeldoc-native/v1",
                        "revision": "wrong",
                        "artifact": {},
                        "page_objects": [],
                    }
                )
            )
