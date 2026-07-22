"""Replace Notion attachment placeholders with resolved content.

Placeholders emitted by blocks_to_markdown:
    [[NOTION_IMAGE:<url>]]
    [[NOTION_PDF:<url>]]
    [[NOTION_FILE:<name>|<url>]]

Images route through Claude Vision (services.parser.extract_from_image).
PDFs route through Docling (services.parser.parse_document).
Other files leave a human-readable label — MVP does not extract their content.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from services.parser import extract_from_image, parse_document

logger = logging.getLogger(__name__)

_IMG_RE = re.compile(r"\[\[NOTION_IMAGE:(?P<url>[^\]]+)\]\]")
_PDF_RE = re.compile(r"\[\[NOTION_PDF:(?P<url>[^\]]+)\]\]")
_FILE_RE = re.compile(r"\[\[NOTION_FILE:(?P<name>[^|]+)\|(?P<url>[^\]]+)\]\]")


def resolve_attachments(markdown: str) -> str:
    markdown = _IMG_RE.sub(_replace_image, markdown)
    markdown = _PDF_RE.sub(_replace_pdf, markdown)
    markdown = _FILE_RE.sub(_replace_file, markdown)
    return markdown


def _replace_image(match: re.Match[str]) -> str:
    url = match.group("url")
    filename = _filename_from_url(url) or "image.png"
    try:
        data = _download_bytes(url)
        description = extract_from_image(data, filename)
    except Exception:
        logger.exception("Notion image vision failed for %s", url)
        return f"> [image] description unavailable ({url})"
    return f"> [image] {description}"


def _replace_pdf(match: re.Match[str]) -> str:
    url = match.group("url")
    filename = _filename_from_url(url) or "attachment.pdf"
    try:
        data = _download_bytes(url)
        text = parse_document(data, filename)
    except Exception:
        logger.exception("Notion pdf parse failed for %s", url)
        return f"> [pdf] content unavailable ({url})"
    return f"> [pdf: {filename}]\n\n{text}\n"


def _replace_file(match: re.Match[str]) -> str:
    name = match.group("name")
    url = match.group("url")
    return f"> [file: {name}]({url})"


def _download_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "agentic-rag-notion-sync/1.0"})
    with urlopen(req, timeout=30) as resp:  # noqa: S310 — URL comes from Notion API
        return resp.read()


def _filename_from_url(url: str) -> str | None:
    path = urlparse(url).path
    if not path:
        return None
    return path.rsplit("/", 1)[-1] or None
