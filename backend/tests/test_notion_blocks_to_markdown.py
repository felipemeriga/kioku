import unittest

from services.notion_sync.blocks_to_markdown import blocks_to_markdown


def _block(type_: str, **kwargs) -> dict:
    body = {"type": type_, "has_children": False}
    body[type_] = {"rich_text": [{"plain_text": kwargs.get("text", "")}]}
    body.update({k: v for k, v in kwargs.items() if k != "text"})
    return body


class TestBlocksToMarkdown(unittest.TestCase):
    def test_heading_and_paragraph(self):
        blocks = [
            _block("heading_1", text="Title"),
            _block("paragraph", text="Some prose."),
        ]
        md = blocks_to_markdown(blocks)
        self.assertIn("# Title", md)
        self.assertIn("Some prose.", md)

    def test_bulleted_and_numbered_lists(self):
        blocks = [
            _block("bulleted_list_item", text="one"),
            _block("bulleted_list_item", text="two"),
            _block("numbered_list_item", text="first"),
        ]
        md = blocks_to_markdown(blocks)
        self.assertIn("- one", md)
        self.assertIn("- two", md)
        self.assertIn("1. first", md)

    def test_code_block_preserves_language(self):
        blocks = [
            {
                "type": "code",
                "has_children": False,
                "code": {
                    "rich_text": [{"plain_text": "print('hi')"}],
                    "language": "python",
                },
            }
        ]
        md = blocks_to_markdown(blocks)
        self.assertIn("```python", md)
        self.assertIn("print('hi')", md)
        self.assertIn("```", md)

    def test_image_block_emits_placeholder(self):
        blocks = [
            {
                "type": "image",
                "has_children": False,
                "image": {
                    "type": "external",
                    "external": {"url": "https://example.com/x.png"},
                },
            }
        ]
        md = blocks_to_markdown(blocks)
        self.assertIn("[[NOTION_IMAGE:", md)
        self.assertIn("https://example.com/x.png", md)

    def test_nested_children_rendered(self):
        parent = _block("bulleted_list_item", text="outer")
        parent["has_children"] = True
        parent["children"] = [_block("bulleted_list_item", text="inner")]
        md = blocks_to_markdown([parent])
        self.assertIn("- outer", md)
        self.assertIn("  - inner", md)

    def test_unknown_block_type_is_skipped_silently(self):
        blocks = [{"type": "unsupported_thing", "has_children": False}]
        md = blocks_to_markdown(blocks)
        self.assertEqual(md.strip(), "")
