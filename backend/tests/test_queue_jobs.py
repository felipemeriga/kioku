import unittest
from unittest.mock import MagicMock


class TestJobsHelpers(unittest.TestCase):
    def test_create_job_inserts_row_and_returns_id(self):
        from services.queue.jobs import create_job

        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "job-1"}]

        job_id = create_job(
            sb,
            user_id="u1",
            kind="notion_sync",
            source_ref="cfg-1",
            root_folder_id="root-1",
        )

        self.assertEqual(job_id, "job-1")
        inserted = sb.table.return_value.insert.call_args.args[0]
        self.assertEqual(inserted["kind"], "notion_sync")
        self.assertEqual(inserted["source_ref"], "cfg-1")
        self.assertEqual(inserted["status"], "queued")

    def test_get_active_job_returns_existing(self):
        from services.queue.jobs import get_active_job

        sb = MagicMock()
        table = sb.table.return_value
        chain = table.select.return_value.eq.return_value.eq.return_value.in_.return_value
        chain.execute.return_value.data = [{"id": "existing-job", "status": "running"}]

        got = get_active_job(sb, kind="notion_sync", source_ref="cfg-1")
        self.assertEqual(got, {"id": "existing-job", "status": "running"})

    def test_get_active_job_returns_none_when_absent(self):
        from services.queue.jobs import get_active_job

        sb = MagicMock()
        table = sb.table.return_value
        chain = table.select.return_value.eq.return_value.eq.return_value.in_.return_value
        chain.execute.return_value.data = []

        self.assertIsNone(get_active_job(sb, kind="notion_sync", source_ref="cfg-1"))

    def test_mark_running_sets_status_and_started_at(self):
        from services.queue.jobs import mark_running

        sb = MagicMock()
        mark_running(sb, job_id="job-1")

        update = sb.table.return_value.update.call_args.args[0]
        self.assertEqual(update["status"], "running")
        self.assertIn("started_at", update)

    def test_increment_batches_uses_read_modify_write(self):
        from services.queue.jobs import increment_processed_batches

        sb = MagicMock()
        table = sb.table.return_value
        select_chain = table.select.return_value.eq.return_value.single.return_value
        select_chain.execute.return_value.data = {
            "processed_batches": 4,
            "total_batches": 10,
        }
        table.update.return_value.eq.return_value.execute.return_value.data = [{}]

        result = increment_processed_batches(sb, job_id="job-1")
        self.assertEqual(result["processed_batches"], 5)
        self.assertFalse(result["completed"])

    def test_increment_batches_marks_completed_at_total(self):
        from services.queue.jobs import increment_processed_batches

        sb = MagicMock()
        table = sb.table.return_value
        select_chain = table.select.return_value.eq.return_value.single.return_value
        select_chain.execute.return_value.data = {
            "processed_batches": 9,
            "total_batches": 10,
        }
        table.update.return_value.eq.return_value.execute.return_value.data = [{}]

        result = increment_processed_batches(sb, job_id="job-1")
        self.assertEqual(result["processed_batches"], 10)
        self.assertTrue(result["completed"])
        update_calls = [c.args[0] for c in sb.table.return_value.update.call_args_list]
        self.assertTrue(any("status" in u and u["status"] == "completed" for u in update_calls))

    def test_mark_failed_sets_status_error_and_completed_at(self):
        from services.queue.jobs import mark_failed

        sb = MagicMock()
        mark_failed(sb, job_id="job-1", error="boom")

        update = sb.table.return_value.update.call_args.args[0]
        self.assertEqual(update["status"], "failed")
        self.assertEqual(update["error"], "boom")
        self.assertIn("completed_at", update)
