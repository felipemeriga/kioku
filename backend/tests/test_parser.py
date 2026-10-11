"""Tests for PDF parsing: fast text-layer extraction with OCR fallback."""

from unittest.mock import MagicMock, patch


class TestParsePdf:
    def test_uses_fast_text_extraction_and_skips_docling(self):
        from services import parser

        with (
            patch.object(parser, "_extract_pdf_text_fast", return_value="Real document text."),
            patch.object(parser, "DocumentConverter") as converter,
        ):
            out = parser._parse_pdf("/tmp/whatever.pdf")

        assert out == "Real document text."
        converter.assert_not_called()  # text layer present → no docling/OCR

    def test_falls_back_to_docling_ocr_when_no_text_layer(self):
        from services import parser

        doc = MagicMock()
        doc.document.export_to_markdown.return_value = "OCR'd text"
        converter_instance = MagicMock()
        converter_instance.convert.return_value = doc

        # pypdfium2 returns only image markers / whitespace → no real text
        with (
            patch.object(parser, "_extract_pdf_text_fast", return_value="<!-- image -->\n\n"),
            patch.object(parser, "DocumentConverter", return_value=converter_instance) as converter,
        ):
            out = parser._parse_pdf("/tmp/scanned.pdf")

        assert out == "OCR'd text"
        converter.assert_called_once()  # scanned PDF → docling OCR fallback

    def test_falls_back_to_docling_when_fast_extraction_raises(self):
        from services import parser

        doc = MagicMock()
        doc.document.export_to_markdown.return_value = "recovered via docling"
        converter_instance = MagicMock()
        converter_instance.convert.return_value = doc

        with (
            patch.object(parser, "_extract_pdf_text_fast", side_effect=RuntimeError("boom")),
            patch.object(parser, "DocumentConverter", return_value=converter_instance),
        ):
            out = parser._parse_pdf("/tmp/broken.pdf")

        assert out == "recovered via docling"
