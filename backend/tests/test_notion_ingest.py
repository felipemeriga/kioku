import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.notion_sync.client import NotionPage


def _page(pid="p1", title="Overview", parent=None):
    return NotionPage(
        page_id=pid,
        title=title,
        last_edited_time=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        parent_page_id=parent,
    )


class TestIngestNotionPage(unittest.TestCase):
    def test_deletes_existing_chunks_then_inserts_fresh(self):
        from services.notion_sync.ingest import ingest_notion_page

        supabase = MagicMock()
        eq_chain = supabase.table.return_value.delete.return_value.eq.return_value
        eq_chain = eq_chain.eq.return_value.eq.return_value
        eq_chain.execute.return_value.data = [{}, {}]

        client = MagicMock()
        client.get_page.return_value = _page("p1", "Overview", parent="root")
        client.iter_child_blocks.return_value = iter(
            [
                {
                    "type": "heading_1",
                    "has_children": False,
                    "heading_1": {"rich_text": [{"plain_text": "Hello"}]},
                },
                {
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": [{"plain_text": "World."}]},
                },
            ]
        )

        with (
            patch(
                "services.notion_sync.ingest.ensure_notion_folder_path",
                return_value=("leaf-fid", ""),
            ),
            patch(
                "services.notion_sync.ingest.chunk_text",
                return_value=["chunk-a", "chunk-b"],
            ),
            patch(
                "services.notion_sync.ingest.embed_document",
                side_effect=[[0.0] * 1024, [0.1] * 1024],
            ),
            patch(
                "services.notion_sync.ingest.extract_metadata",
                return_value={"topic": "t", "keywords": []},
            ),
        ):
            result = ingest_notion_page(
                supabase,
                notion=client,
                user_id="u1",
                root_folder_id="root-fid",
                mapped_root_page_id="root",
                page_id="p1",
            )

        # A delete on documents was attempted
        supabase.table.assert_any_call("documents")
        # Two inserts (one per chunk)
        insert_calls = supabase.table.return_value.insert.call_args_list
        self.assertEqual(len(insert_calls), 2)
        for call in insert_calls:
            row = call.args[0]
            self.assertEqual(row["notion_page_id"], "p1")
            self.assertEqual(row["source_type"], "notion")
            self.assertEqual(row["root_folder_id"], "root-fid")
            self.assertEqual(row["folder_id"], "leaf-fid")
            self.assertEqual(row["user_id"], "u1")

        self.assertEqual(result["chunks"], 2)

    def test_walks_ancestors_up_to_mapped_root(self):
        from services.notion_sync.ingest import ingest_notion_page

        client = MagicMock()
        pages = {
            "p1": _page("p1", "Sprint 43", parent="sp"),
            "sp": _page("sp", "Sprint planning", parent="cosm"),
            "cosm": _page("cosm", "Cosm", parent=None),
        }
        client.get_page.side_effect = lambda pid: pages[pid]
        client.iter_child_blocks.return_value = iter([])

        supabase = MagicMock()
        eq_chain = supabase.table.return_value.delete.return_value.eq.return_value
        eq_chain = eq_chain.eq.return_value.eq.return_value
        eq_chain.execute.return_value.data = []

        with (
            patch("services.notion_sync.ingest.ensure_notion_folder_path") as ensure,
            patch("services.notion_sync.ingest.chunk_text", return_value=[]),
        ):
            ensure.return_value = ("leaf", "Sprint planning")
            ingest_notion_page(
                supabase,
                notion=client,
                user_id="u1",
                root_folder_id="root-fid",
                mapped_root_page_id="cosm",
                page_id="p1",
            )

        args = ensure.call_args
        # ancestor_titles excludes both the mapped root AND the page itself
        self.assertEqual(args.kwargs["ancestor_titles"], ["Sprint planning"])
