"""Live execution access checks reuse transport without caching authority."""

import uuid

import pytest

from tsukai.protocol import JobRequest


@pytest.mark.parametrize("delete_account", [False, True])
async def test_access_lookup_retains_live_ownership_and_deletion_checks(store, delete_account):
    from sqlalchemy import event

    job = await store.admit(
        JobRequest(
            idempotency_key=str(uuid.uuid4()),
            owner_id="owner",
            caller="backend",
            operation="test",
            prompt="fixture",
            profile="chat",
            conversation_id="conversation",
        )
    )
    transactions = []

    def begin(conn):
        transactions.append(True)

    event.listen(store.engine.sync_engine, "begin", begin)
    try:
        found, deleted = await store.get_for_access(job["id"], "owner")
    finally:
        event.remove(store.engine.sync_engine, "begin", begin)
    assert found["id"] == job["id"] and deleted is False
    assert len(transactions) == 1
    assert await store.get_for_access(job["id"], "foreign-owner") == (None, False)
    assert await store.get_for_access("missing", "owner") == (None, False)
    await store.begin_deletion("owner", None if delete_account else "conversation")
    found, deleted = await store.get_for_access(job["id"], "owner")
    assert found["id"] == job["id"] and deleted is True


async def test_active_attempt_access_keeps_all_reads_on_one_connection(store):
    from sqlalchemy import event

    job = await store.admit(
        JobRequest(
            idempotency_key=str(uuid.uuid4()),
            owner_id="owner",
            caller="backend",
            operation="test",
            prompt="fixture",
            profile="chat",
            conversation_id="conversation",
        )
    )
    attempt = (await store.claim("worker"))["attempt"]
    transactions = []

    def begin(conn):
        transactions.append(True)

    event.listen(store.engine.sync_engine, "begin", begin)
    try:
        found, deleted, current = await store.get_attempt_for_access(
            job["id"], "owner", attempt["id"]
        )
    finally:
        event.remove(store.engine.sync_engine, "begin", begin)
    assert len(transactions) == 1
    assert found["id"] == job["id"] and deleted is False
    assert current["id"] == attempt["id"]
    assert await store.get_attempt_for_access(job["id"], "foreign", attempt["id"]) == (
        None,
        False,
        None,
    )
    assert (await store.get_attempt_for_access(job["id"], "owner", "other-attempt"))[2] is None
    await store.begin_deletion("owner", "conversation")
    found, deleted, current = await store.get_attempt_for_access(job["id"], "owner", attempt["id"])
    assert found["id"] == job["id"] and deleted is True and current is None
