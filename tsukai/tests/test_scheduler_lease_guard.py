"""A blocked SQL path cannot silently extend native or publisher lease authority."""

import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tsukai.config import Settings
from tsukai.protocol import JobRequest
from tsukai.scheduler import Scheduler
from tsukai.store import Fenced


def scheduler(tmp_path, **overrides):
    store = SimpleNamespace(
        append=AsyncMock(),
        heartbeat=AsyncMock(),
        finish=AsyncMock(),
        get=AsyncMock(return_value={"status": "running"}),
    )
    settings = Settings(
        workspace_dir=str(tmp_path), heartbeat_seconds=0.01, kill_grace_seconds=0.01
    )
    native = SimpleNamespace(run=AsyncMock(), stop=AsyncMock())
    value = Scheduler(store, settings, native)
    for key, item in overrides.items():
        setattr(store, key, item)
    return value


def claim(tmp_path, lease=0.1):
    req = JobRequest(
        idempotency_key=str(uuid.uuid4()),
        owner_id="owner",
        caller="backend",
        operation="test",
        profile="chat",
        conversation_id="conversation",
        prompt="private",
    )
    return {
        "job": {"id": str(uuid.uuid4()), "request": req.model_dump(mode="json")},
        "attempt": {
            "id": str(uuid.uuid4()),
            "job_id": "job",
            "lease_until": time.time() + lease,
            "deadline": time.time() + 10,
        },
        "workspace": str(tmp_path),
    }


async def test_stalled_append_is_cancelled_at_actual_lease_expiry(tmp_path):
    cancelled = asyncio.Event()

    async def append(*_args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    value = scheduler(tmp_path, append=AsyncMock(side_effect=append))
    attempt = {"lease_until": time.time() + 0.05}
    with pytest.raises(Fenced, match="event_persistence_lease_lost"):
        await asyncio.wait_for(value.append_with_lease(attempt, "text.delta", {"text": "x"}), 1)
    assert cancelled.is_set()


async def test_committed_heartbeat_extension_keeps_pending_append_alive(tmp_path):
    released = asyncio.Event()
    started = asyncio.Event()

    async def append(*_args):
        started.set()
        await released.wait()
        return 7

    value = scheduler(tmp_path, append=AsyncMock(side_effect=append))
    attempt = {"lease_until": time.time() + 0.05}
    task = asyncio.create_task(value.append_with_lease(attempt, "text.delta", {"text": "x"}))
    await started.wait()
    attempt["lease_until"] = time.time() + 0.5
    await asyncio.sleep(0.08)  # Beyond the original lease, still owned by its committed extension.
    assert not task.done()
    released.set()
    assert await task == 7


async def test_external_cancellation_settles_inflight_append(tmp_path):
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def append(*_args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    value = scheduler(tmp_path, append=AsyncMock(side_effect=append))
    task = asyncio.create_task(
        value.append_with_lease({"lease_until": time.time() + 60}, "text.delta", {})
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


async def test_independent_watchdog_stops_native_when_heartbeat_sql_hangs(tmp_path, monkeypatch):
    monkeypatch.setattr("tsukai.scheduler.FINALIZE_SECONDS", 0.05)
    value = scheduler(tmp_path)
    started, stopped = asyncio.Event(), asyncio.Event()

    async def run(*_args):
        started.set()
        await asyncio.Event().wait()

    async def heartbeat(*_args):
        await asyncio.Event().wait()

    value.native.run.side_effect = run
    value.native.stop.side_effect = lambda *_: stopped.set()
    value.store.heartbeat.side_effect = heartbeat
    task = asyncio.create_task(value.execute(claim(tmp_path, lease=0.08)))
    await started.wait()
    await asyncio.wait_for(stopped.wait(), 1)
    await asyncio.wait_for(task, 1)
    value.native.run.assert_awaited_once()
    value.store.finish.assert_not_awaited()
    assert not value.cancelling and not value.finishing


async def test_64_chunk_spool_drain_is_bounded_when_write_and_heartbeat_hang(tmp_path, monkeypatch):
    monkeypatch.setattr("tsukai.scheduler.FINALIZE_SECONDS", 0.05)
    value = scheduler(tmp_path)
    persisted = []
    blocked = asyncio.Event()
    append_cancelled = asyncio.Event()

    async def append(_attempt, _kind, data):
        if not persisted:
            persisted.append(data["text"])
            return
        blocked.set()
        try:
            await asyncio.Event().wait()
        finally:
            append_cancelled.set()

    async def heartbeat(*_args):
        await asyncio.Event().wait()

    async def run(_claim, _req, emit, _config):
        await emit("text.delta", {"text": "first"})
        await asyncio.sleep(0.3)
        for _ in range(63):
            await emit("text.delta", {"text": "later"})
        return {"text": "first" + "later" * 63, "usage": {}}

    value.store.append.side_effect = append
    value.store.heartbeat.side_effect = heartbeat
    value.native.run.side_effect = run
    task = asyncio.create_task(value.execute(claim(tmp_path, lease=0.6)))
    await asyncio.wait_for(blocked.wait(), 1)
    await asyncio.wait_for(task, 1)
    assert persisted == ["first"] and append_cancelled.is_set()
    value.native.stop.assert_awaited()
    value.store.finish.assert_not_awaited()
    spools = list(tmp_path.glob("events-*.spool"))
    assert len(spools) == 1
    records = [json.loads(line) for line in spools[0].read_text().splitlines()]
    assert len(records) == 64
    assert "".join(r["data"]["text"] for r in records) == "first" + "later" * 63


async def test_healthy_long_provider_and_64_chunks_survive_live_renewals(tmp_path):
    value = scheduler(tmp_path)
    current = claim(tmp_path, lease=0.06)
    persisted = []

    async def heartbeat(attempt):
        attempt["lease_until"] = time.time() + 0.1  # Represents committed store authority.
        return False

    async def append(_attempt, _kind, data):
        persisted.append(data["text"])

    async def run(_claim, _req, emit, _config):
        await asyncio.sleep(0.2)  # Longer than the initial lease, no false cancellation.
        for _ in range(64):
            await emit("text.delta", {"text": "chunk"})
        return {"text": "chunk" * 64, "usage": {}}

    value.store.heartbeat.side_effect = heartbeat
    value.store.append.side_effect = append
    value.native.run.side_effect = run
    await asyncio.wait_for(value.execute(current), 1)
    assert "".join(persisted) == "chunk" * 64
    value.store.finish.assert_awaited_once()
    assert value.store.finish.call_args.args[1] == "completed"
    value.native.stop.assert_not_awaited()
    assert not list(tmp_path.glob("*.tmp"))


async def test_publisher_fence_stops_active_native_before_local_lease_expiry(tmp_path):
    value = scheduler(tmp_path)
    current = claim(tmp_path, lease=10)

    async def run(_claim, _req, emit, _config):
        await emit("text.delta", {"text": "not authoritative"})
        await asyncio.Event().wait()

    value.native.run.side_effect = run
    value.store.append.side_effect = Fenced("attempt_lease_lost")
    await asyncio.wait_for(value.execute(current), 1)
    value.native.stop.assert_awaited()
    assert value.store.finish.call_args.args[1] == "cancelled"
