"""Live usage access and attempt metadata from one connection, with no authority cache."""

from sqlalchemy import select

from .tables import attempts, jobs


async def usage_access_snapshot(store, job_id, owner_id):
    statement = (
        select(jobs, attempts)
        .select_from(jobs.outerjoin(attempts, attempts.c.job_id == jobs.c.id))
        .where(jobs.c.id == job_id, jobs.c.owner_id == owner_id)
        .order_by(attempts.c.number)
    )
    postgres = store.engine.dialect.name == "postgresql"
    if postgres:
        statement = statement.add_columns(
            store._deleted_expression(owner_id).label("scope_deleted")
        )
    async with store.read_connection() as conn:
        rows = (await conn.execute(statement)).all()
        if not rows:
            return None, False, []
        job = {column.name: rows[0]._mapping[column] for column in jobs.c}
        deleted = (
            bool(rows[0]._mapping["scope_deleted"])
            if postgres
            else await store._scope_deleted(conn, owner_id, job["conversation_id"])
        )
        if deleted:
            return job, True, []
        usage = []
        for joined in rows:
            if joined._mapping[attempts.c.id] is None:
                continue
            row = {column.name: joined._mapping[column] for column in attempts.c}
            usage.append(
                {
                    "attempt_id": row["id"],
                    "number": row["number"],
                    "status": row["status"],
                    "model": job["request"]["model"],
                    **store.attempt_timings(row, job["created_at"]),
                    "native_session_id": row["native_session_id"],
                    "counter_segment": row["counter_segment"],
                    "usage": row["usage"],
                    "error": row["error"],
                }
            )
        return job, False, usage
