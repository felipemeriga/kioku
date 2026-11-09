"""One live snapshot must retain all failed/successful usage and access checks."""

import uuid

import httpx
import pytest
from sqlalchemy import event
from test_app import body, headers

from tsukai.app import create_app
from tsukai.config import Settings
from tsukai.protocol import JobRequest
from tsukai.usage_snapshot import usage_access_snapshot


async def test_usage_snapshot_retains_failed_attempts_with_one_checkout(store):
    request = JobRequest(
        idempotency_key=str(uuid.uuid4()),
        owner_id="owner",
        caller="backend",
        operation="test",
        prompt="fixture",
    )
    job = await store.admit(request)
    assert (await usage_access_snapshot(store, job["id"], "owner"))[2] == []
    first = await store.claim("worker")
    await store.finish(
        first["attempt"],
        "failed",
        retry=True,
        error={"code": "fixture"},
        result={"text": "", "usage": {"complete": True, "list_equivalent_usd": 0.001}},
    )
    second = await store.claim("worker")
    await store.finish(
        second["attempt"],
        "completed",
        result={"text": "answer", "usage": {"complete": True, "list_equivalent_usd": 0.002}},
    )
    expected = await store.attempt_usage(job["id"])
    checkouts = []
    statements = []

    def checkout(*_):
        checkouts.append(True)

    def executed(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    pool = store.engine.sync_engine.pool
    event.listen(pool, "checkout", checkout)
    event.listen(store.engine.sync_engine, "before_cursor_execute", executed)
    try:
        found, deleted, usage = await usage_access_snapshot(store, job["id"], "owner")
    finally:
        event.remove(pool, "checkout", checkout)
        event.remove(store.engine.sync_engine, "before_cursor_execute", executed)
    assert found["id"] == job["id"] and deleted is False
    assert usage == expected and [row["status"] for row in usage] == ["failed", "completed"]
    assert len(checkouts) == 1
    assert len(statements) == 2
    assert await usage_access_snapshot(store, job["id"], "foreign") == (None, False, [])
    assert await usage_access_snapshot(store, "missing", "owner") == (None, False, [])
    await store.begin_deletion("owner")
    found, deleted, usage = await usage_access_snapshot(store, job["id"], "owner")
    assert found["id"] == job["id"] and deleted is True and usage == []


@pytest.mark.parametrize("revocation", ["owner", "conversation", "wrong_owner", "folder", "caller"])
async def test_usage_endpoint_keeps_owner_caller_scope_and_tombstone_authorization(
    store, revocation
):
    settings = Settings(
        service_token="service-" + "x" * 32,
        capability_key="scope-" + "y" * 32,
        entitled_owners=frozenset({"owner", "other"}),
        auth_probe=False,
    )
    payload = body(profile="chat", conversation_id="conversation", folder_ids=["folder"])
    job = await store.admit(JobRequest.model_validate(payload))
    app = create_app(settings, store)
    auth = headers(settings, payload)
    expected = 410
    if revocation == "owner":
        await store.begin_deletion("owner")
    elif revocation == "conversation":
        await store.begin_deletion("owner", "conversation")
    elif revocation == "wrong_owner":
        auth = headers(settings, payload, owner_id="other")
        expected = 404
    elif revocation == "folder":
        auth = headers(settings, payload, folder_ids=["other-folder"])
        expected = 403
    else:
        auth = headers(settings, payload, sub="mihari")
        expected = 403
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://fixture"
    ) as client:
        response = await client.get(f"/v1/jobs/{job['id']}/usage", headers=auth)
    assert response.status_code == expected
    assert "attempts" not in response.json()
