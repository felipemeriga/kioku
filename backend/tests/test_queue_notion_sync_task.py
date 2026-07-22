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


def _page(pid, title="p", parent="cosm"):
    return NotionPage(
        page_id=pid,
        title=title,
        parent_page_id=parent,
        last_edited_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


class TestNotionSyncTask(unittest.TestCase):
    def test_fast_poll_mode_enumerates_and_enqueues_page_tasks(self):
        from services.queue.tasks import notion_sync_task

        supabase = MagicMock()
        # Config lookup returns the config with encrypted token
        cfg_row = {
            "id": "cfg-1",
            "user_id": "u1",
            "root_folder_id": "root-1",
            "notion_page_id": "cosm",
            "integration_token_encrypted": "ENC",
            "last_fast_sync_at": None,
        }
        exec_mock = supabase.table.return_value.select.return_value.eq.return_value.execute
        exec_mock.return_value.data = [cfg_row]

        notion_mock = MagicMock()
        notion_mock.iter_pages_edited_since.return_value = iter(
            [_page("p1", parent="cosm"), _page("p2", parent="unrelated")]
        )

        def _get_page(pid):
            if pid == "cosm":
                return _page("cosm", parent=None)
            if pid == "unrelated":
                return _page("unrelated", parent=None)
            return _page(pid, parent="cosm")

        notion_mock.get_page.side_effect = _get_page

        pool = MagicMock()

        async def _enqueue(*a, **kw):
            return MagicMock(job_id="x")

        pool.enqueue_job = MagicMock(side_effect=_enqueue)

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
                "services.queue.tasks.decrypt_secret",
                return_value="notion-token",
                create=True,
            ),
            patch(
                "services.queue.tasks.create_job",
                side_effect=["page-job-1"],
                create=True,
            ),
            patch("services.queue.tasks.set_total_pages") as set_total_pages_mock,
        ):
            _run(
                notion_sync_task(
                    {"redis": pool},
                    {
                        "job_id": "sync-job-1",
                        "config_id": "cfg-1",
                        "full_reconcile": False,
                    },
                )
            )

        page_task_enqueues = [
            c
            for c in pool.enqueue_job.call_args_list
            if c.args and c.args[0] == "ingest_notion_page_task"
        ]
        self.assertEqual(len(page_task_enqueues), 1)
        payload = page_task_enqueues[0].args[1]
        self.assertEqual(payload["page_id"], "p1")
        self.assertEqual(payload["parent_job_id"], "sync-job-1")

        set_total_pages_mock.assert_called_once()
        self.assertEqual(set_total_pages_mock.call_args.kwargs["total"], 1)
