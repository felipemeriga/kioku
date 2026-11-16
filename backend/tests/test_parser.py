"""Tests for PDF parsing: fast text-layer extraction, graceful scanned-PDF error."""

from io import BytesIO
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


@pytest.mark.parametrize("filename", ["disguised.docx", "disguised.html", "disguised.md"])
def test_mislabeled_pdf_rejected_before_model_pipeline_initialization(filename):
    from docling.exceptions import ConversionError
    from reportlab.pdfgen import canvas

    from services import parser

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(20, 20, "Text in a disguised PDF")
    pdf.save()
    # Use the real Docling format detector and conversion allowlist. No model
    # pipeline may be constructed, even though the bytes identify a valid PDF.
    with patch.object(parser.DocumentConverter, "_get_pipeline") as initialize:
        with pytest.raises(ConversionError):
            parser.parse_document(buffer.getvalue(), filename)
        initialize.assert_not_called()


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("note.md", b"# Heading\n\nSafe document text."),
        ("note.html", b"<html><body><p>Safe document text.</p></body></html>"),
    ],
)
def test_simple_document_formats_remain_supported(filename, content):
    from services.parser import parse_document

    assert "Safe document text." in parse_document(content, filename)


def test_docx_remains_supported():
    from docx import Document

    from services.parser import parse_document

    document = Document()
    document.add_paragraph("Safe document text.")
    buffer = BytesIO()
    document.save(buffer)
    assert "Safe document text." in parse_document(buffer.getvalue(), "note.docx")
