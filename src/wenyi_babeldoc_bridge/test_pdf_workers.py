"""Worker operations preserve BabelDOC's options without importing its service graph."""

import sys
import unittest
from unittest.mock import MagicMock, patch

from wenyi_babeldoc_bridge.pdf_workers import save_clean, subset_fonts


class PdfWorkerTests(unittest.TestCase):
    def test_subset_uses_native_font_subsetting_and_closes_document(self):
        pdf = MagicMock()
        document = pdf.open.return_value.__enter__.return_value
        with patch.dict(sys.modules, {"pymupdf": pdf}):
            subset_fonts("synthetic.pdf", "subset.pdf")
        pdf.open.assert_called_once_with("synthetic.pdf")
        document.subset_fonts.assert_called_once_with(fallback=False)
        document.save.assert_called_once_with("subset.pdf")
        pdf.open.return_value.__exit__.assert_called_once()

    def test_save_preserves_all_requested_options(self):
        pdf = MagicMock()
        document = pdf.open.return_value.__enter__.return_value
        with patch.dict(sys.modules, {"pymupdf": pdf}):
            save_clean("synthetic.pdf", "clean.pdf", 3, False, False, False, True)
        document.save.assert_called_once_with(
            "clean.pdf",
            garbage=3,
            deflate=False,
            clean=False,
            deflate_fonts=False,
            linear=True,
        )

    def test_worker_errors_propagate_to_nonzero_process_exit(self):
        pdf = MagicMock()
        pdf.open.side_effect = ValueError("synthetic invalid PDF")
        with (
            patch.dict(sys.modules, {"pymupdf": pdf}),
            self.assertRaisesRegex(ValueError, "invalid PDF"),
        ):
            subset_fonts("synthetic.pdf", "subset.pdf")
