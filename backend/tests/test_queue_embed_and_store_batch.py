import asyncio
import unittest
from unittest.mock import MagicMock, patch


class TestEmbedAndStoreBatchTask(unittest.TestCase):
    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_one_voyage_call_and_bulk_insert(self):
        from services.queue.tasks import embed_and_store_batch_task

        supabase = MagicMock()
        insert_chain = supabase.table.return_value.insert.return_value
        insert_chain.execute.return_value.data = [{"id": "d1"}, {"id": "d2"}]

        payload = {
            "job_id": "job-1",
            "row_template": {
                "user_id": "u1",
                "root_folder_id": "root-1",
                "folder_id": "leaf-1",
                "source_filename": "Overview",
                "source_type": "notion",
                "notion_page_id": "p1",
                "notion_last_edited_time": "2026-07-01T12:00:00+00:00",
                "notion_parent_path": "Cosm",
                "status": "completed",
            },
            "chunks": ["hello world", "second chunk"],
        }

        with (
            patch(
                "services.queue.tasks.get_supabase_thread_safe",
                return_value=supabase,
                create=True,
            ),
            patch(
                "services.queue.tasks.get_supabase",
                return_value=supabase,
                create=True,
            ),
            patch(
                "services.queue.tasks.embed_batch",
                return_value=[[0.1] * 1024, [0.2] * 1024],
            ) as embed_mock,
            patch(
                "services.queue.tasks.extract_metadata",
                return_value={"topic": "t", "keywords": []},
            ),
            patch(
                "services.queue.tasks.increment_processed_batches",
                return_value={"completed": False},
            ),
        ):
            self._run(embed_and_store_batch_task({"redis": None}, payload))

        embed_mock.assert_called_once_with(["hello world", "second chunk"])
        insert_call = supabase.table.return_value.insert.call_args.args[0]
        self.assertEqual(len(insert_call), 2)
        self.assertEqual(insert_call[0]["user_id"], "u1")
        self.assertEqual(insert_call[0]["notion_page_id"], "p1")
        self.assertEqual(insert_call[0]["source_type"], "notion")
        self.assertEqual(insert_call[0]["embedding"], [0.1] * 1024)

    def test_metadata_extraction_parallel_across_chunks(self):
        from services.queue.tasks import embed_and_store_batch_task

        calls: list[str] = []

        def _record_metadata(text: str) -> dict:
            calls.append(text)
            return {"topic": "t"}

        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.return_value.data = []

        payload = {
            "job_id": "job-1",
            "row_template": {
                "user_id": "u1",
                "root_folder_id": "root",
                "source_filename": "x",
                "source_type": "notion",
                "status": "completed",
            },
            "chunks": ["a", "b", "c", "d", "e"],
        }
        with (
            patch(
                "services.queue.tasks.get_supabase_thread_safe",
                return_value=supabase,
                create=True,
            ),
            patch(
                "services.queue.tasks.get_supabase",
                return_value=supabase,
                create=True,
            ),
            patch("services.queue.tasks.embed_batch", return_value=[[0.0] * 1024] * 5),
            patch("services.queue.tasks.extract_metadata", side_effect=_record_metadata),
            patch(
                "services.queue.tasks.increment_processed_batches",
                return_value={"completed": False},
            ),
        ):
            self._run(embed_and_store_batch_task({"redis": None}, payload))
        self.assertEqual(sorted(calls), ["a", "b", "c", "d", "e"])

    def test_marks_failed_on_exception(self):
        from services.queue.tasks import embed_and_store_batch_task

        supabase = MagicMock()

        payload = {
            "job_id": "job-1",
            "row_template": {
                "user_id": "u1",
                "root_folder_id": "root",
                "source_filename": "x",
                "source_type": "notion",
                "status": "completed",
            },
            "chunks": ["a"],
        }

        with (
            patch(
                "services.queue.tasks.get_supabase_thread_safe",
                return_value=supabase,
                create=True,
            ),
            patch(
                "services.queue.tasks.get_supabase",
                return_value=supabase,
                create=True,
            ),
            patch(
                "services.queue.tasks.embed_batch",
                side_effect=RuntimeError("voyage down"),
            ),
            patch("services.queue.tasks.mark_failed") as mark_failed_mock,
        ):
            with self.assertRaises(RuntimeError):
                self._run(embed_and_store_batch_task({"redis": None}, payload))
        mark_failed_mock.assert_called_once()
        kw = mark_failed_mock.call_args.kwargs
        self.assertEqual(kw["job_id"], "job-1")
        self.assertIn("voyage down", kw["error"])
