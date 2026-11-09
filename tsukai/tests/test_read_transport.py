"""Production read transport removes round trips without weakening fenced writes."""

import uuid

import pytest
from sqlalchemy import delete, event, func, literal, select, text, update

from tsukai.protocol import JobRequest
from tsukai.store import Store
from tsukai.tables import jobs


def postgres(store):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("real PostgreSQL read transport acceptance")


async def admit(store, conversation=None):
    return await store.admit(
        JobRequest(
            idempotency_key=str(uuid.uuid4()),
            owner_id="owner",
            caller="backend",
            operation="test",
            prompt="fixture",
            profile="chat" if conversation else "completion",
            conversation_id=conversation,
        )
    )


async def test_reads_are_autocommit_but_engine_begin_keeps_a_real_shared_pool_transaction(store):
    postgres(store)
    assert store.engine.pool is store._read_engine.pool
    async with store.read_connection() as conn:
        await conn.execute(select(literal(1)))
        raw = await conn.get_raw_connection()
        driver = raw.driver_connection
        assert driver.is_in_transaction() is False
        assert raw.dbapi_connection.autocommit is True
    async with store.engine.begin() as conn:
        assert (
            await conn.scalar(select(func.current_setting("transaction_isolation")))
            == "read committed"
        )
        raw = await conn.get_raw_connection()
        assert raw.driver_connection is driver
        assert raw.driver_connection.is_in_transaction() is True
        assert raw.dbapi_connection.autocommit is False
    async with store.read_connection() as conn:
        await conn.execute(select(literal(1)))
        raw = await conn.get_raw_connection()
        assert raw.driver_connection is driver
        assert raw.driver_connection.is_in_transaction() is False
        assert raw.dbapi_connection.autocommit is True


@pytest.mark.parametrize(
    "kind", ["update", "delete", "text", "driver_sql", "for_update", "dml_cte"]
)
async def test_read_connection_rejects_mutation_and_locking_before_execution(store, kind):
    postgres(store)
    job = await admit(store)
    statements = {
        "update": update(jobs).where(jobs.c.id == job["id"]).values(cancel_requested=True),
        "delete": delete(jobs).where(jobs.c.id == job["id"]),
        "text": text("UPDATE tsukai_jobs SET cancel_requested=true"),
        "for_update": select(jobs).with_for_update(),
        "dml_cte": select(literal(1)).add_cte(
            update(jobs).values(cancel_requested=True).returning(jobs.c.id).cte()
        ),
    }
    async with store.read_connection() as conn:
        with pytest.raises(ValueError, match="SELECT statements only"):
            if kind == "driver_sql":
                await conn.exec_driver_sql("DELETE FROM tsukai_jobs")
            else:
                await conn.execute(statements[kind])
    assert (await store.get(job["id"]))["cancel_requested"] is False


async def test_explicit_engine_transaction_rolls_back_all_writes(store):
    postgres(store)
    job = await admit(store)
    with pytest.raises(RuntimeError, match="abort"):
        async with store.engine.begin() as conn:
            await conn.execute(
                update(jobs).where(jobs.c.id == job["id"]).values(cancel_requested=True)
            )
            raise RuntimeError("abort")
    assert (await store.get(job["id"]))["cancel_requested"] is False


@pytest.mark.parametrize("conversation", [None, "", "会議/🙂/ação"])
async def test_single_statement_tombstone_hash_matches_python_for_null_empty_unicode(
    store, conversation
):
    postgres(store)
    job = await admit(store, conversation)
    sql_hash = func.pg_catalog.encode(
        func.pg_catalog.sha256(
            func.pg_catalog.convert_to(func.coalesce(literal(conversation), ""), "UTF8")
        ),
        "hex",
    )
    async with store.read_connection() as conn:
        assert await conn.scalar(select(sql_hash)) == store.hash_id(conversation or "")
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store._read_engine.sync_engine, "before_cursor_execute", record)
    try:
        found, deleted = await store.get_for_access(job["id"], "owner")
    finally:
        event.remove(store._read_engine.sync_engine, "before_cursor_execute", record)
    assert found["id"] == job["id"] and deleted is False
    assert len(statements) == 1
    await store.begin_deletion("owner", conversation)
    assert (await store.get_for_access(job["id"], "owner"))[1] is True


async def test_one_statement_attempt_lookup_is_owner_bound_and_never_matches_another_job(store):
    postgres(store)
    job = await admit(store, "first")
    attempt = (await store.claim("worker"))["attempt"]
    other = await admit(store, "second")
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store._read_engine.sync_engine, "before_cursor_execute", record)
    try:
        found, deleted, active = await store.get_attempt_for_access(
            job["id"], "owner", attempt["id"]
        )
    finally:
        event.remove(store._read_engine.sync_engine, "before_cursor_execute", record)
    assert len(statements) == 1
    assert found["id"] == job["id"] and deleted is False and active["id"] == attempt["id"]
    assert await store.get_attempt_for_access(job["id"], "other", attempt["id"]) == (
        None,
        False,
        None,
    )
    assert (await store.get_attempt_for_access(other["id"], "owner", attempt["id"]))[2] is None


async def test_open_read_connection_still_observes_newly_committed_revocation(store):
    postgres(store)
    job = await admit(store, "live")
    other = Store(store.engine.url.render_as_string(hide_password=False))
    query = (
        select(store._deleted_expression("owner")).select_from(jobs).where(jobs.c.id == job["id"])
    )
    try:
        async with store.read_connection() as conn:
            assert await conn.scalar(query) is False
            await other.begin_deletion("owner", "live")
            assert await conn.scalar(query) is True
    finally:
        await other.engine.dispose()


async def test_pre_ping_replaces_a_closed_read_connection_before_reusing_it(store):
    postgres(store)
    job = await admit(store)
    async with store.read_connection() as conn:
        await conn.execute(select(literal(1)))
        driver = (await conn.get_raw_connection()).driver_connection
        await driver.close()
    assert (await store.get(job["id"]))["id"] == job["id"]
    async with store.read_connection() as conn:
        replacement = (await conn.get_raw_connection()).driver_connection
        assert replacement is not driver and not replacement.is_closed()
