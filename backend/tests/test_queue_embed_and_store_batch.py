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

    def test_embeds_contextualized_shape_but_stores_raw_content(self):
        # The embed INPUT is header + situating blurb + chunk; the stored
        # `content` stays the raw chunk and metadata.context carries the blurb.
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
            "metadata_base": {"source_filename": "Overview", "total_chunks": 2},
            "chunks": ["hello world", "second chunk"],
            "contexts": ["about greetings", ""],
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
                "services.queue.tasks.increment_processed_batches",
                return_value={"completed": False},
            ),
        ):
            self._run(embed_and_store_batch_task({"redis": None}, payload))

        embedded = embed_mock.call_args.args[0]
        # chunk 0 carries header + the situating blurb; chunk 1 has no blurb.
        self.assertIn("Source: Overview", embedded[0])
        self.assertIn("about greetings", embedded[0])
        self.assertIn("hello world", embedded[0])
        self.assertIn("second chunk", embedded[1])
        self.assertNotIn("about greetings", embedded[1])

        insert_call = supabase.table.return_value.insert.call_args.args[0]
        self.assertEqual(len(insert_call), 2)
        self.assertEqual(insert_call[0]["user_id"], "u1")
        self.assertEqual(insert_call[0]["notion_page_id"], "p1")
        self.assertEqual(insert_call[0]["source_type"], "notion")
        self.assertEqual(insert_call[0]["embedding"], [0.1] * 1024)
        # Stored content is the RAW chunk, and the blurb lands in metadata.context.
        self.assertEqual(insert_call[0]["content"], "hello world")
        self.assertEqual(insert_call[0]["metadata"]["context"], "about greetings")
        self.assertNotIn("context", insert_call[1]["metadata"])

    def test_large_batch_insert_is_sub_batched(self):
        # A full 128-chunk batch is a multi-MB payload; it must be inserted in
        # sub-batches of <=25 rows so a single request never overruns the
        # PostgREST read timeout under concurrent ingestion.
        from services.queue.tasks import embed_and_store_batch_task

        n = 128
        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.return_value.data = []

        payload = {
            "job_id": "job-1",
            "row_template": {
                "user_id": "u1",
                "root_folder_id": "root",
                "source_filename": "big.pdf",
                "source_type": "pdf",
                "status": "completed",
            },
            "chunks": [f"chunk {i}" for i in range(n)],
            "chunk_index_offset": 0,
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
                return_value=[[0.0] * 1024] * n,
            ),
            patch(
                "services.queue.tasks.increment_processed_batches",
                return_value={"completed": True},
            ),
        ):
            self._run(embed_and_store_batch_task({"redis": None}, payload))

        insert_calls = supabase.table.return_value.insert.call_args_list
        # ceil(128 / 25) == 6 inserts
        self.assertEqual(len(insert_calls), 6)
        inserted_rows = [call.args[0] for call in insert_calls]
        self.assertTrue(all(len(rows) <= 25 for rows in inserted_rows))
        self.assertEqual(sum(len(rows) for rows in inserted_rows), n)
        # chunk_index must stay contiguous across sub-batches.
        flat = [row for rows in inserted_rows for row in rows]
        self.assertEqual([r["chunk_index"] for r in flat], list(range(n)))

    def test_replace_existing_page_deletes_only_after_embed_succeeds(self):
        # The whole point of replace_existing_page is that the delete happens
        # here, after Voyage/Anthropic succeeded — never before.
        from services.queue.tasks import embed_and_store_batch_task

        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.return_value.data = []

        payload = {
            "job_id": "job-1",
            "row_template": {
                "user_id": "u1",
                "root_folder_id": "root-1",
                "source_type": "notion",
                "notion_page_id": "p1",
                "status": "completed",
            },
            "chunks": ["a"],
            "replace_existing_page": True,
        }

        with (
            patch(
                "services.queue.tasks.get_supabase_thread_safe",
                return_value=supabase,
                create=True,
            ),
            patch("services.queue.tasks.embed_batch", return_value=[[0.0] * 1024]),
            patch(
                "services.queue.tasks.increment_processed_batches",
                return_value={"completed": True},
            ),
        ):
            self._run(embed_and_store_batch_task({"redis": None}, payload))

        delete_eq = supabase.table.return_value.delete.return_value.eq
        delete_eq.assert_called_with("user_id", "u1")
        chained = delete_eq.return_value.eq
        chained.assert_called_with("root_folder_id", "root-1")
        chained.return_value.eq.assert_called_with("notion_page_id", "p1")
        supabase.table.return_value.insert.assert_called_once()

    def test_replace_existing_page_keeps_old_rows_when_embed_fails(self):
        from services.queue.tasks import embed_and_store_batch_task

        supabase = MagicMock()

        payload = {
            "job_id": "job-1",
            "row_template": {
                "user_id": "u1",
                "root_folder_id": "root-1",
                "source_type": "notion",
                "notion_page_id": "p1",
                "status": "completed",
            },
            "chunks": ["a"],
            "replace_existing_page": True,
        }

        with (
            patch(
                "services.queue.tasks.get_supabase_thread_safe",
                return_value=supabase,
                create=True,
            ),
            patch(
                "services.queue.tasks.embed_batch",
                side_effect=RuntimeError("401 api key invalid"),
            ),
            patch("services.queue.tasks.mark_failed"),
        ):
            with self.assertRaises(RuntimeError):
                self._run(embed_and_store_batch_task({"redis": None}, payload))

        supabase.table.return_value.delete.assert_not_called()
        supabase.table.return_value.insert.assert_not_called()

    def test_no_delete_without_replace_flag(self):
        from services.queue.tasks import embed_and_store_batch_task

        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.return_value.data = []

        payload = {
            "job_id": "job-1",
            "row_template": {
                "user_id": "u1",
                "root_folder_id": "root-1",
                "source_type": "notion",
                "notion_page_id": "p1",
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
            patch("services.queue.tasks.embed_batch", return_value=[[0.0] * 1024]),
            patch(
                "services.queue.tasks.increment_processed_batches",
                return_value={"completed": True},
            ),
        ):
            self._run(embed_and_store_batch_task({"redis": None}, payload))

        supabase.table.return_value.delete.assert_not_called()

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
