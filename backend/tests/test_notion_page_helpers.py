import unittest
from unittest.mock import MagicMock

from services.notion_sync.page_helpers import fetch_block_tree


class TestFetchBlockTree(unittest.TestCase):
    def test_recurses_into_normal_containers(self):
        notion = MagicMock()
        notion.iter_child_blocks.side_effect = lambda bid: iter(
            {
                "page-1": [{"id": "toggle-1", "type": "toggle", "has_children": True}],
                "toggle-1": [{"id": "p", "type": "paragraph", "has_children": False}],
            }[bid]
        )

        blocks = list(fetch_block_tree(notion, "page-1"))

        self.assertEqual(blocks[0]["children"][0]["id"], "p")

    def test_does_not_descend_into_child_pages(self):
        # Each subpage is ingested as its own document — walking its blocks
        # here would cost a full API traversal per descendant page for nothing.
        notion = MagicMock()
        notion.iter_child_blocks.side_effect = lambda bid: iter(
            {
                "page-1": [
                    {
                        "id": "sub-1",
                        "type": "child_page",
                        "has_children": True,
                        "child_page": {"title": "Sub"},
                    }
                ],
            }[bid]
        )

        blocks = list(fetch_block_tree(notion, "page-1"))

        self.assertNotIn("children", blocks[0])
        notion.iter_child_blocks.assert_called_once_with("page-1")
