"""Tests for PDF parsing: fast text-layer extraction, graceful scanned-PDF error."""

from unittest.mock import patch

import pytest


class TestParsePdf:
    def test_uses_fast_text_extraction(self):
        from services import parser

        with patch.object(parser, "_extract_pdf_text_fast", return_value="Real document text."):
            out = parser._parse_pdf("/tmp/whatever.pdf")

        assert out == "Real document text."

    def test_scanned_pdf_raises_clear_error(self):
        from services import parser

        # pypdfium2 returns only image markers / whitespace → no real text layer.
        with patch.object(parser, "_extract_pdf_text_fast", return_value="<!-- image -->\n\n"):
            with pytest.raises(parser.ScannedPdfError):
                parser._parse_pdf("/tmp/scanned.pdf")

    def test_extraction_failure_raises_clear_error(self):
        from services import parser

        with patch.object(parser, "_extract_pdf_text_fast", side_effect=RuntimeError("boom")):
            with pytest.raises(parser.ScannedPdfError):
                parser._parse_pdf("/tmp/broken.pdf")
