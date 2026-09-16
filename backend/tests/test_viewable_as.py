import unittest

from routes.documents import _infer_viewable_as


class TestInferViewableAs(unittest.TestCase):
    def test_notion_pages_are_markdown_despite_missing_extension(self):
        # Notion page titles have no extension; their content is generated
        # markdown and must not fall through to plain text.
        self.assertEqual(_infer_viewable_as("GStreamer Commands", "notion", {}), "markdown")

    def test_extension_still_wins_for_files(self):
        self.assertEqual(_infer_viewable_as("notes.md", "markdown", {}), "markdown")
        self.assertEqual(_infer_viewable_as("api.json", "json", {}), "code")
        self.assertEqual(_infer_viewable_as("doc.pdf", "pdf", {}), "pdf")

    def test_unknown_defaults_to_text(self):
        self.assertEqual(_infer_viewable_as("mystery", "text", {}), "text")
