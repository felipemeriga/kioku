"""Extract text from documents using Docling."""

import base64
import logging
import os
import tempfile
import threading
from pathlib import Path

from docling.document_converter import DocumentConverter
from langsmith import traceable

from services.llm import Task, complete

PLAIN_TEXT_EXTENSIONS = {".json", ".yaml", ".yml", ".txt", ".text"}

logger = logging.getLogger(__name__)

# PDFium (via pypdfium2) is not thread-safe; serialize text extraction so
# concurrent uploads on the worker pool can't race inside the C library.
_PDFIUM_LOCK = threading.Lock()


def _strip_image_markers(text: str) -> str:
    """Remove <!-- image --> markers and blank lines to check for real text content."""
    lines = text.splitlines()
    return "".join(
        line.strip() for line in lines if line.strip() and line.strip() != "<!-- image -->"
    )


def parse_document(file_bytes: bytes, filename: str) -> str:
    """Extract text content from a document file.

    Uses Docling for PDF, DOCX, HTML, Markdown.
    For PDFs, tries text extraction first (no OCR), then falls back to OCR
    if no meaningful text is found.
    Reads JSON, YAML, and plain text directly.
    Returns extracted text as a string.
    """
    suffix = Path(filename).suffix.lower()

    if suffix in PLAIN_TEXT_EXTENSIONS:
        return file_bytes.decode("utf-8", errors="replace")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        if suffix == ".pdf":
            return _parse_pdf(tmp_path)
        converter = DocumentConverter()
        result = converter.convert(tmp_path)
        return result.document.export_to_markdown()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _extract_pdf_text_fast(tmp_path: str) -> str:
    """Pull the embedded text layer with pypdfium2.

    ~1000x faster than running docling's layout model (measured: 0.26s vs
    272s for an 80-page PDF) and plenty for chunking + embedding, which don't
    need layout structure. Returns "" for scanned/image PDFs with no text
    layer, so the caller can fall back to OCR.
    """
    import pypdfium2 as pdfium

    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(tmp_path)
        try:
            parts = []
            for i in range(len(pdf)):
                page = pdf[i]
                textpage = page.get_textpage()
                parts.append(textpage.get_text_range())
                textpage.close()
                page.close()
            return "\n\n".join(parts)
        finally:
            pdf.close()


def _parse_pdf(tmp_path: str) -> str:
    """Parse PDF: fast embedded-text extraction first, fall back to docling's
    full OCR pipeline only for scanned/image PDFs that have no text layer."""
    try:
        text = _extract_pdf_text_fast(tmp_path)
    except Exception:
        logger.warning("fast PDF text extraction failed; falling back to docling", exc_info=True)
        text = ""

    if _strip_image_markers(text):
        logger.info("PDF parsed via fast text-layer extraction (pypdfium2)")
        return text

    # No embedded text — scanned/image-based PDF. Full docling pipeline + OCR.
    logger.info("No embedded text in PDF, falling back to docling OCR")
    converter = DocumentConverter()
    result = converter.convert(tmp_path)
    return result.document.export_to_markdown()


IMAGE_EXTRACTION_PROMPT = (
    "Analyze this image and extract all information from it.\n\n"
    "Respond in Markdown with these sections:\n\n"
    "## Text Content\n"
    "Extract ALL visible text from the image exactly as written. "
    'If no text is visible, write "No text content found."\n\n'
    "## Visual Description\n"
    "Describe what the image shows: diagrams, charts, photos, "
    "layouts, colors, relationships between elements. "
    "Be thorough and specific so someone who cannot see the image "
    "can understand its full content."
)


@traceable(name="extract_from_image", run_type="chain")
def extract_from_image(file_bytes: bytes, filename: str) -> str:
    """Extract text and visual description from an image using Claude Vision."""
    ext = filename.rsplit(".", 1)[-1].lower()
    media_type = "image/png" if ext == "png" else "image/jpeg"
    image_data = base64.standard_b64encode(file_bytes).decode("utf-8")

    response = complete(
        task=Task.IMAGE_OCR,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": IMAGE_EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    return response.content[0].text


AUDIO_MIME_TYPES = {
    "mp3": "audio/mpeg",
    "webm": "audio/webm",
    "m4a": "audio/mp4",
}


@traceable(name="transcribe_audio", run_type="chain")
def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """Transcribe audio to text using OpenAI Whisper API."""
    import openai

    ext = filename.rsplit(".", 1)[-1].lower()
    mime_type = AUDIO_MIME_TYPES.get(ext, "audio/mpeg")

    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    audio_file = (filename, file_bytes, mime_type)

    transcription = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        response_format="text",
    )

    return transcription
