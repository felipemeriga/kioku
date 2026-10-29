"""Exercise concurrent code indexing without an external embedding service."""

import asyncio
import threading
import time
from unittest.mock import patch


def test_three_repositories_complete_with_bounded_database_writes():
    from services.queue.tasks import embed_code_chunks_task

    lock = threading.Lock()
    inserted: set[tuple[str, int]] = set()
    active = 0
    peak = 0

    class InsertQuery:
        def __init__(self, rows):
            self.rows = rows

        def execute(self):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.01)
                with lock:
                    inserted.update((row["folder_id"], row["start_line"]) for row in self.rows)
            finally:
                with lock:
                    active -= 1

    class Table:
        def insert(self, rows):
            return InsertQuery(rows)

    class Supabase:
        def table(self, name):
            assert name == "code_chunks"
            return Table()

    async def run():
        payloads = [
            {
                "rows": [
                    {"folder_id": f"repo-{repo}", "start_line": i, "content": "code"}
                    for i in range(128)
                ]
            }
            for repo in range(3)
        ]
        await asyncio.gather(*(embed_code_chunks_task({}, payload) for payload in payloads))

    with (
        patch("services.queue.tasks.get_supabase_thread_safe", return_value=Supabase()),
        patch(
            "services.embeddings.embed_code_batch",
            side_effect=lambda texts: [[0.1] for _ in texts],
        ),
    ):
        asyncio.run(run())

    assert len(inserted) == 3 * 128
    assert 1 < peak <= 6
