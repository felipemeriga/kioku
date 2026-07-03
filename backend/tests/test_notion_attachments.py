import unittest
from unittest.mock import patch


class TestResolveAttachments(unittest.TestCase):
    def test_image_placeholder_replaced_with_vision_output(self):
        from services.notion_sync.attachments import resolve_attachments

        markdown = "Intro\n\n[[NOTION_IMAGE:https://example.com/x.png]]\n\nOutro"

        with (
            patch("services.notion_sync.attachments._download_bytes", return_value=b"fake"),
            patch(
                "services.notion_sync.attachments.extract_from_image",
                return_value="A diagram showing X.",
            ),
        ):
            out = resolve_attachments(markdown)

        self.assertNotIn("[[NOTION_IMAGE", out)
        self.assertIn("A diagram showing X.", out)
        self.assertIn("[image]", out)

    def test_pdf_placeholder_replaced_via_docling(self):
        from services.notion_sync.attachments import resolve_attachments

        markdown = "[[NOTION_PDF:https://example.com/doc.pdf]]"

        with (
            patch("services.notion_sync.attachments._download_bytes", return_value=b"%PDF-1.7"),
            patch(
                "services.notion_sync.attachments.parse_document",
                return_value="# PDF Content\n\nBody.",
            ),
        ):
            out = resolve_attachments(markdown)

        self.assertNotIn("[[NOTION_PDF", out)
        self.assertIn("PDF Content", out)

    def test_file_placeholder_kept_as_plain_reference(self):
        from services.notion_sync.attachments import resolve_attachments

        markdown = "[[NOTION_FILE:report.xlsx|https://example.com/report.xlsx]]"
        out = resolve_attachments(markdown)
        self.assertIn("report.xlsx", out)
        self.assertNotIn("[[NOTION_FILE", out)

    def test_vision_failure_leaves_graceful_marker(self):
        from services.notion_sync.attachments import resolve_attachments

        markdown = "[[NOTION_IMAGE:https://example.com/broken.png]]"
        with patch("services.notion_sync.attachments._download_bytes", side_effect=OSError("boom")):
            out = resolve_attachments(markdown)
        self.assertNotIn("[[NOTION_IMAGE", out)
        self.assertIn("description unavailable", out.lower())
