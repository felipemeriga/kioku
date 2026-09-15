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


def _table_row(*cells: str) -> dict:
    return {
        "type": "table_row",
        "has_children": False,
        "table_row": {"cells": [[{"plain_text": c}] for c in cells]},
    }


class TestTables(unittest.TestCase):
    def test_table_renders_as_markdown_table(self):
        table = {
            "type": "table",
            "has_children": True,
            "table": {"table_width": 2, "has_column_header": True},
            "children": [
                _table_row("Service", "Production"),
                _table_row("business-api", "https://business.example.com"),
            ],
        }
        md = blocks_to_markdown([table])
        self.assertIn("| Service | Production |", md)
        self.assertIn("| --- | --- |", md)
        self.assertIn("| business-api | https://business.example.com |", md)

    def test_table_without_column_header_still_valid_markdown(self):
        table = {
            "type": "table",
            "has_children": True,
            "table": {"table_width": 2, "has_column_header": False},
            "children": [
                _table_row("Cert bucket", "c360-cxvh-ssl-certs"),
                _table_row("Route53 zone", "Z01514553F8W0BDSR7JW3"),
            ],
        }
        md = blocks_to_markdown([table])
        # No content row may be swallowed into a header position…
        self.assertIn("| Cert bucket | c360-cxvh-ssl-certs |", md)
        self.assertIn("| Route53 zone | Z01514553F8W0BDSR7JW3 |", md)
        # …and a separator must still exist so the table parses as markdown.
        self.assertIn("| --- | --- |", md)

    def test_table_rows_not_duplicated_by_generic_recursion(self):
        table = {
            "type": "table",
            "has_children": True,
            "table": {"table_width": 1, "has_column_header": False},
            "children": [_table_row("only-once")],
        }
        md = blocks_to_markdown([table])
        self.assertEqual(md.count("only-once"), 1)


class TestTransparentContainers(unittest.TestCase):
    def test_column_list_content_is_rendered(self):
        # Pages arranged side-by-side in columns live under
        # column_list -> column -> actual blocks. Layout containers must be
        # transparent, not swallow their children.
        blocks = [
            {
                "type": "column_list",
                "has_children": True,
                "children": [
                    {
                        "type": "column",
                        "has_children": True,
                        "children": [_block("paragraph", text="left side")],
                    },
                    {
                        "type": "column",
                        "has_children": True,
                        "children": [_block("paragraph", text="right side")],
                    },
                ],
            }
        ]
        md = blocks_to_markdown(blocks)
        self.assertIn("left side", md)
        self.assertIn("right side", md)

    def test_synced_block_content_is_rendered(self):
        blocks = [
            {
                "type": "synced_block",
                "has_children": True,
                "children": [_block("paragraph", text="synced text")],
            }
        ]
        md = blocks_to_markdown(blocks)
        self.assertIn("synced text", md)

    def test_child_page_content_does_not_leak_into_parent(self):
        # child_page blocks carry the entire subpage tree; the subpage is
        # ingested as its own document, so rendering it here would duplicate
        # every descendant page into the parent.
        blocks = [
            {
                "type": "child_page",
                "has_children": True,
                "child_page": {"title": "Subpage"},
                "children": [_block("paragraph", text="subpage body")],
            }
        ]
        md = blocks_to_markdown(blocks)
        self.assertNotIn("subpage body", md)
