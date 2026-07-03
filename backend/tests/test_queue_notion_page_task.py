import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.notion_sync.client import NotionPage


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _page(pid="p1", title="Overview", parent="cosm"):
    return NotionPage(
        page_id=pid,
        title=title,
        parent_page_id=parent,
        last_edited_time=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )


class TestIngestNotionPageTask(unittest.TestCase):
    def _mock_enqueue_pool(self):
        pool = MagicMock()

        # arq's enqueue_job is an async method returning a job
        async def _enqueue(*args, **kwargs):
            return MagicMock(job_id="task-x")

        pool.enqueue_job = MagicMock(side_effect=_enqueue)
        return pool

    def test_deletes_existing_chunks_and_enqueues_one_batch(self):
        from services.queue.tasks import ingest_notion_page_task

        supabase = MagicMock()
        table = supabase.table.return_value
        delete_chain = table.delete.return_value.eq.return_value.eq.return_value.eq.return_value
        delete_chain.execute.return_value.data = [{}]

        notion_mock = MagicMock()
        notion_mock.get_page.return_value = _page()
        notion_mock.iter_child_blocks.return_value = iter(
            [
                {
                    "type": "heading_1",
                    "has_children": False,
                    "heading_1": {"rich_text": [{"plain_text": "Hi"}]},
                },
            ]
        )

        pool = self._mock_enqueue_pool()

        payload = {
            "job_id": "page-job-1",
            "parent_job_id": "sync-job-1",
            "config_id": "cfg-1",
            "user_id": "u1",
            "root_folder_id": "root-1",
            "mapped_root_page_id": "cosm",
            "page_id": "p1",
            "integration_token": "notion-token",
        }

        with (
            patch(
                "services.queue.tasks.get_supabase_thread_safe",
                return_value=supabase,
                create=True,
            ),
            patch(
                "services.queue.tasks.NotionClient",
                return_value=notion_mock,
                create=True,
            ),
            patch(
                "services.queue.tasks.ensure_notion_folder_path",
                return_value=("leaf-fid", "Cosm"),
                create=True,
            ),
            patch(
                "services.queue.tasks.chunk_text",
                return_value=["c1", "c2", "c3"],
                create=True,
            ),
            patch("services.queue.tasks.set_total_batches") as set_total_mock,
        ):
            _run(ingest_notion_page_task({"redis": pool}, payload))

        supabase.table.assert_any_call("documents")
        set_total_mock.assert_called_once()
        self.assertEqual(set_total_mock.call_args.kwargs["total"], 1)
        # Exactly one enqueue call
        self.assertEqual(pool.enqueue_job.call_count, 1)
        args = pool.enqueue_job.call_args
        self.assertEqual(args.args[0], "embed_and_store_batch_task")
        batch_payload = args.args[1]
        self.assertEqual(batch_payload["chunks"], ["c1", "c2", "c3"])
        self.assertEqual(batch_payload["row_template"]["notion_page_id"], "p1")
        self.assertEqual(batch_payload["row_template"]["source_type"], "notion")

    def test_multiple_batches_when_over_128_chunks(self):
        from services.queue.tasks import ingest_notion_page_task

        supabase = MagicMock()
        table = supabase.table.return_value
        delete_chain = table.delete.return_value.eq.return_value.eq.return_value.eq.return_value
        delete_chain.execute.return_value.data = []

        notion_mock = MagicMock()
        notion_mock.get_page.return_value = _page()
        notion_mock.iter_child_blocks.return_value = iter([])

        pool = self._mock_enqueue_pool()

        payload = {
            "job_id": "job",
            "parent_job_id": None,
            "config_id": "cfg-1",
            "user_id": "u1",
            "root_folder_id": "root-1",
            "mapped_root_page_id": "cosm",
            "page_id": "p1",
            "integration_token": "t",
        }

        with (
            patch(
                "services.queue.tasks.get_supabase_thread_safe",
                return_value=supabase,
                create=True,
            ),
            patch(
                "services.queue.tasks.NotionClient",
                return_value=notion_mock,
                create=True,
            ),
            patch(
                "services.queue.tasks.ensure_notion_folder_path",
                return_value=("leaf", ""),
                create=True,
            ),
            patch(
                "services.queue.tasks.chunk_text",
                return_value=[f"c{i}" for i in range(200)],
                create=True,
            ),
            patch("services.queue.tasks.set_total_batches"),
        ):
            _run(ingest_notion_page_task({"redis": pool}, payload))

        self.assertEqual(pool.enqueue_job.call_count, 2)
