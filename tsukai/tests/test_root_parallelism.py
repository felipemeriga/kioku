"""Optional capacity never changes default admission, fairness or reserved lanes."""

import asyncio

import pytest
from sqlalchemy import select
from test_store import request

from tsukai.config import Settings
from tsukai.store import Store
from tsukai.tables import jobs


@pytest.mark.parametrize("value", ["", "0", "5", "-1", "2.0", "three", " 3", "03"])
def test_invalid_environment_capacity_fails_configuration(monkeypatch, value):
    monkeypatch.setenv("TSUKAI_ROOT_PARALLELISM", value)
    with pytest.raises(ValueError, match="TSUKAI_ROOT_PARALLELISM"):
        Settings()


@pytest.mark.parametrize("value", [0, 5, -1, True, 2.0, "3", None])
def test_invalid_explicit_capacity_fails_before_engine_creation(value):
    with pytest.raises(ValueError, match="TSUKAI_ROOT_PARALLELISM"):
        Settings(root_parallelism=value)
    with pytest.raises(ValueError, match="TSUKAI_ROOT_PARALLELISM"):
        Store("sqlite+aiosqlite://", root_parallelism=value)


def test_default_and_explicit_environment_capacity(monkeypatch):
    monkeypatch.delenv("TSUKAI_ROOT_PARALLELISM", raising=False)
    assert Settings().root_parallelism == 2
    for value in range(1, 5):
        monkeypatch.setenv("TSUKAI_ROOT_PARALLELISM", str(value))
        assert Settings().root_parallelism == value


async def test_default_two_root_capacity_is_unchanged(store):
    for i in range(3):
        await store.admit(request(profile="chat", conversation_id=f"default-{i}"))
    assert len(await store.dispatch("worker")) == 2
    assert await store.claim("worker") is None


async def test_configured_three_global_roots_keep_mihari_and_metadata_limits_across_instances(
    store,
):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("cross-instance PostgreSQL advisory-lock capacity")
    url = store.engine.url.render_as_string(hide_password=False)
    first, second = Store(url, root_parallelism=3), Store(url, root_parallelism=3)
    try:
        chats = []
        for i in range(2):
            chats.append(await store.admit(request(profile="chat", conversation_id=f"chat-{i}")))
        for i in range(2):
            await store.admit(
                request().model_copy(update={"caller": "mihari", "owner_id": f"maint-{i}"})
            )
        claims = await asyncio.gather(
            first.claim("first"),
            second.claim("second"),
            first.claim("first"),
            second.claim("second"),
            first.claim("first"),
        )
        claimed = [c for c in claims if c]
        assert len(claimed) == 3
        assert sum(c["job"]["caller"] == "mihari" for c in claimed) == 1
        assert sum(c["job"]["profile"] == "chat" for c in claimed) == 2
        child = await store.admit(
            request(
                profile="metadata_child",
                ai_depth=1,
                operation="text_to_sql",
                parent_job_id=chats[0]["id"],
                root_job_id=chats[0]["id"],
            )
        )
        child_claim = await second.claim("child-worker")
        assert child_claim["job"]["id"] == child["id"]
        # A second metadata child cannot consume a root lane or exceed the reserved lane.
        await store.admit(
            request(
                profile="metadata_child",
                ai_depth=1,
                operation="text_to_sql",
                parent_job_id=chats[1]["id"],
                root_job_id=chats[1]["id"],
            )
        )
        assert await first.dispatch("full-worker", capacity=99) == []
        chat_attempt = next(c["attempt"] for c in claimed if c["job"]["profile"] == "chat")
        await first.finish(chat_attempt, "completed", result={"text": "done", "usage": {}})
        # Even with a free root slot, a second Mihari remains excluded.
        assert await second.claim("worker") is None
        async with first.read_connection() as conn:
            active = (
                await conn.execute(
                    select(jobs.c.profile, jobs.c.caller).where(jobs.c.status == "running")
                )
            ).all()
        assert len(active) == 3 and sum(r.caller == "mihari" for r in active) == 1
    finally:
        await first.engine.dispose()
        await second.engine.dispose()


@pytest.mark.parametrize("roots", [1, 2, 3, 4])
@pytest.mark.parametrize("occupied", [0, 1, 5])
async def test_scheduler_uses_root_capacity_plus_reserved_child_slot(tmp_path, roots, occupied):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from tsukai.scheduler import Scheduler

    fake = SimpleNamespace(pending_deletions=AsyncMock(return_value=[]), prune=AsyncMock())
    scheduler = Scheduler(
        fake, Settings(root_parallelism=roots, workspace_dir=str(tmp_path)), native=object()
    )
    scheduler.auth_state = "ready"
    scheduler.tasks = {str(i): object() for i in range(occupied)}

    async def dispatch(worker, capacity):
        scheduler.draining = True
        assert capacity == max(0, roots + 1 - occupied)
        return []

    fake.dispatch = AsyncMock(side_effect=dispatch)
    await scheduler.loop()
    fake.dispatch.assert_awaited_once()
    assert scheduler.db_available
