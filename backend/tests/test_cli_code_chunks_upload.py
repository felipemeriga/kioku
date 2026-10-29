"""A slow indexing delete must not block unrelated API work."""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

from routes.cli import CodeChunkIn, CodeChunksDelta, CodeFileIn, code_chunks_upload


def test_three_slow_code_chunk_uploads_keep_event_loop_responsive():
    started = threading.Event()
    completed = threading.Event()
    db = MagicMock()

    def slow_delete():
        started.set()
        time.sleep(0.2)
        completed.set()

    query = db.table.return_value.delete.return_value
    query.eq.return_value.eq.return_value.in_.return_value.execute.side_effect = slow_delete
    payloads = [
        CodeChunksDelta(
            folder_id=f"repo-{i}",
            files=[CodeFileIn(file="a.py", file_hash="hash", chunks=[CodeChunkIn(content="x")])],
        )
        for i in range(3)
    ]
    queued = []

    class Pool:
        async def enqueue_job(self, name, data):
            queued.append((name, data))

        async def close(self):
            pass

    async def create_pool(_settings):
        return Pool()

    async def run():
        tasks = [
            asyncio.create_task(code_chunks_upload(payload, MagicMock())) for payload in payloads
        ]
        await asyncio.sleep(0.05)
        assert started.is_set()
        assert not completed.is_set()  # the slow DB call is still running
        results = await asyncio.gather(*tasks)
        assert [result["chunks_queued"] for result in results] == [1, 1, 1]

    with (
        patch("routes.cli._code_chunks_scope", return_value="user-a"),
        patch("routes.cli.get_supabase", return_value=db),
        patch("arq.create_pool", side_effect=create_pool),
    ):
        asyncio.run(run())

    assert len(queued) == 3
    assert all(name == "embed_code_chunks_task" for name, _ in queued)
