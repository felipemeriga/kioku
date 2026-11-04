"""SQL is authoritative. Every attempt write checks its unexpired fencing lease."""

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from .protocol import TERMINAL, JobRequest
from .tables import acks, attempts, events, jobs, locks, metadata, sessions


class Conflict(Exception):
    pass


class Fenced(Conflict):
    pass


class Store:
    def __init__(self, url: str, workspace_dir="/data/workspaces"):
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.workspace_dir = workspace_dir
        self._local_lock = asyncio.Lock()

    async def create_test_schema(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    @asynccontextmanager
    async def transaction(self):
        # Advisory transaction lock coordinates replicas and all admission/lease updates.
        # No native IO occurs under this lock. SQLite is fixture-only.
        async with self._local_lock:
            async with self.engine.begin() as conn:
                if conn.dialect.name == "postgresql":
                    await conn.execute(text("SELECT pg_advisory_xact_lock(831740221)"))
                yield conn

    async def ping(self):
        async with self.engine.connect() as conn:
            await conn.execute(select(jobs.c.id).limit(1))

    async def _event(self, conn, job_id, kind, data, attempt_id=None):
        seq = (await conn.execute(select(jobs.c.next_seq).where(jobs.c.id == job_id))).scalar_one()
        now = time.time()
        await conn.execute(
            insert(events).values(
                job_id=job_id, seq=seq, attempt_id=attempt_id, type=kind, data=data, created_at=now
            )
        )
        await conn.execute(
            update(jobs).where(jobs.c.id == job_id).values(next_seq=seq + 1, updated_at=now)
        )
        return seq

    @staticmethod
    def _chat_key(owner, conversation):
        return "chat:" + hashlib.sha256(f"{owner}:{conversation}".encode()).hexdigest()

    @staticmethod
    def policy_fingerprint(request):
        policy = {
            "system_prompt": request.system_prompt,
            "model": request.model,
            "folders": sorted(request.folder_ids),
            "tools": sorted(request.tool_allowlist),
            "thinking_tokens": request.thinking_tokens,
            "max_tokens": request.max_tokens,
            "native_cli": "2.1.285",
            "host_prompt_version": "kioku-grounded-v1",
        }
        return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()

    async def admit(self, request: JobRequest, queue_capacity=100, request_sha256=None):
        payload = request.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        now = time.time()
        async with self.transaction() as conn:
            existing = (
                (
                    await conn.execute(
                        select(jobs).where(
                            jobs.c.owner_id == request.owner_id,
                            jobs.c.caller == request.caller,
                            jobs.c.idempotency_key == request.idempotency_key,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                if existing["payload_hash"] != digest:
                    raise Conflict("idempotency_payload_conflict")
                return dict(existing)
            count = (
                await conn.execute(
                    select(func.count())
                    .select_from(jobs)
                    .where(jobs.c.status.in_(["queued", "running"]))
                )
            ).scalar_one()
            if count >= queue_capacity:
                raise Conflict("queue_full")
            if request.profile == "metadata_child":
                parent = (
                    (
                        await conn.execute(
                            select(jobs).where(
                                jobs.c.id == request.parent_job_id,
                                jobs.c.owner_id == request.owner_id,
                                jobs.c.status == "running",
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                if (
                    not parent
                    or parent["profile"] != "chat"
                    or request.root_job_id != request.parent_job_id
                    or not set(request.folder_ids).issubset(parent["request"]["folder_ids"])
                ):
                    raise Conflict("invalid_metadata_parent")
            job_id = str(uuid.uuid4())
            if request.conversation_id:
                key = self._chat_key(request.owner_id, request.conversation_id)
                held = (await conn.execute(select(locks).where(locks.c.key == key))).first()
                if held:
                    raise Conflict("conversation_busy")
                state = (
                    (
                        await conn.execute(
                            select(sessions).where(
                                sessions.c.owner_id == request.owner_id,
                                sessions.c.conversation_id == request.conversation_id,
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                if state and not request.rebuild_from_committed_history:
                    if state["state"] != "ready":
                        raise Conflict("conversation_needs_rebuild")
                    if state["policy_fingerprint"] != self.policy_fingerprint(request):
                        raise Conflict("conversation_policy_changed")
                if state and request.rebuild_from_committed_history:
                    old = {
                        k: state[k]
                        for k in (
                            "generation",
                            "native_session_id",
                            "workspace",
                            "state",
                            "policy_fingerprint",
                        )
                    }
                    native_id = str(uuid.uuid4())
                    await conn.execute(
                        update(sessions)
                        .where(
                            sessions.c.owner_id == request.owner_id,
                            sessions.c.conversation_id == request.conversation_id,
                        )
                        .values(
                            native_session_id=native_id,
                            generation=state["generation"] + 1,
                            policy_fingerprint=self.policy_fingerprint(request),
                            history=[*state["history"], old],
                            state="new",
                            workspace=f"{self.workspace_dir}/chat/{native_id}",
                            last_cost=None,
                            last_counters=None,
                            updated_at=now,
                        )
                    )
            await conn.execute(
                insert(jobs).values(
                    id=job_id,
                    owner_id=request.owner_id,
                    caller=request.caller,
                    idempotency_key=request.idempotency_key,
                    payload_hash=digest,
                    request_sha256=request_sha256 or digest,
                    request=payload,
                    status="queued",
                    profile=request.profile,
                    conversation_id=request.conversation_id,
                    attempt_count=0,
                    next_seq=1,
                    created_at=now,
                    updated_at=now,
                    queue_deadline=now + (30 if request.profile == "chat" else 1800),
                    cancel_requested=False,
                )
            )
            if request.conversation_id:
                await conn.execute(
                    insert(locks).values(key=key, job_id=job_id, lease_until=now + 30)
                )
            await self._event(conn, job_id, "job.queued", {"profile": request.profile})
        return await self.get(job_id)

    async def get(self, job_id):
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(jobs).where(jobs.c.id == job_id))).mappings().first()
            return dict(row) if row else None

    async def unacknowledged(self, owner_id, caller):
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                select(jobs)
                .where(
                    jobs.c.owner_id == owner_id,
                    jobs.c.caller == caller,
                    jobs.c.status == "completed",
                    ~select(acks.c.job_id).where(acks.c.job_id == jobs.c.id).exists(),
                )
                .limit(100)
            )
            return [dict(r) for r in rows.mappings()]

    async def claim(self, worker_id, only_job_id=None):
        now = time.time()
        async with self.transaction() as conn:
            active = (
                (await conn.execute(select(jobs.c.profile).where(jobs.c.status == "running")))
                .scalars()
                .all()
            )
            candidates = (
                (
                    await conn.execute(
                        select(jobs)
                        .where(jobs.c.status == "queued")
                        .order_by(jobs.c.created_at)
                        .with_for_update(skip_locked=True)
                        .limit(100)
                    )
                )
                .mappings()
                .all()
            )
            chosen = None
            for job in candidates:
                if only_job_id and job["id"] != only_job_id:
                    continue
                child = job["profile"] == "metadata_child"
                if (child and active.count("metadata_child") >= 1) or (
                    not child and sum(p != "metadata_child" for p in active) >= 2
                ):
                    continue
                if job["caller"] == "mihari" and any(p == "completion" for p in active):
                    continue
                if now > job["queue_deadline"]:
                    await self._terminal(conn, job, "failed", error={"code": "queue_timeout"})
                    continue
                if child:
                    parent_id = job["request"]["parent_job_id"]
                    parent = (
                        (await conn.execute(select(jobs).where(jobs.c.id == parent_id)))
                        .mappings()
                        .first()
                    )
                    parent_attempt = (
                        (
                            await conn.execute(
                                select(attempts).where(
                                    attempts.c.job_id == parent_id,
                                    attempts.c.status == "running",
                                    attempts.c.lease_until > now,
                                )
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if (
                        not parent
                        or parent["status"] != "running"
                        or parent["cancel_requested"]
                        or not parent_attempt
                    ):
                        await self._terminal(
                            conn, job, "failed", error={"code": "metadata_parent_inactive"}
                        )
                        continue
                chosen = dict(job)
                break
            if chosen is None:
                return None
            job = chosen
            req = JobRequest.model_validate(job["request"])
            attempt_id, fence, native_id = (str(uuid.uuid4()) for _ in range(3))
            resume = False
            session = None
            owner_path = hashlib.sha256(req.owner_id.encode()).hexdigest()[:24]
            workspace = f"{self.workspace_dir}/{owner_path}/{job['id']}"
            if req.conversation_id:
                session = (
                    (
                        await conn.execute(
                            select(sessions).where(
                                sessions.c.owner_id == req.owner_id,
                                sessions.c.conversation_id == req.conversation_id,
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                if session:
                    native_id, workspace, resume = (
                        session["native_session_id"],
                        session["workspace"],
                        session["state"] != "new",
                    )
                else:
                    workspace = f"{self.workspace_dir}/chat/{native_id}"
                    await conn.execute(
                        insert(sessions).values(
                            owner_id=req.owner_id,
                            conversation_id=req.conversation_id,
                            native_session_id=native_id,
                            generation=1,
                            policy_fingerprint=self.policy_fingerprint(req),
                            history=[],
                            state="new",
                            workspace=workspace,
                            updated_at=now,
                        )
                    )
            attempt = dict(
                id=attempt_id,
                job_id=job["id"],
                number=job["attempt_count"] + 1,
                fence=fence,
                worker_id=worker_id,
                status="running",
                lease_until=now + 30,
                deadline=min(now + 300, parent_attempt["deadline"]) if req.ai_depth else now + 300,
                started_at=now,
                native_session_id=native_id,
                resume=resume,
                counter_segment=str(uuid.uuid4()),
            )
            await conn.execute(insert(attempts).values(**attempt))
            await conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(status="running", attempt_count=attempt["number"])
            )
            await conn.execute(
                update(locks)
                .where(locks.c.job_id == job["id"])
                .values(attempt_id=attempt_id, fence=fence, lease_until=now + 30)
            )
            await self._event(
                conn,
                job["id"],
                "attempt.started",
                {"number": attempt["number"], "native_session_id": native_id, "resume": resume},
                attempt_id,
            )
            return {
                "job": job,
                "attempt": attempt,
                "workspace": workspace,
                "previous_usage": dict(session) if session else None,
            }

    async def _owned(self, conn, attempt):
        current = (
            (await conn.execute(select(attempts).where(attempts.c.id == attempt["id"])))
            .mappings()
            .first()
        )
        if (
            not current
            or current["fence"] != attempt["fence"]
            or current["status"] != "running"
            or current["lease_until"] <= time.time()
        ):
            raise Fenced("attempt_lease_lost")
        job = (
            (await conn.execute(select(jobs).where(jobs.c.id == attempt["job_id"])))
            .mappings()
            .one()
        )
        if job["profile"] == "metadata_child":
            parent = (
                (
                    await conn.execute(
                        select(jobs).where(jobs.c.id == job["request"]["parent_job_id"])
                    )
                )
                .mappings()
                .first()
            )
            if not parent or parent["status"] != "running" or parent["cancel_requested"]:
                raise Fenced("metadata_parent_inactive")
        return current

    async def heartbeat(self, attempt):
        async with self.transaction() as conn:
            await self._owned(conn, attempt)
            await conn.execute(
                update(attempts)
                .where(attempts.c.id == attempt["id"])
                .values(lease_until=time.time() + 30)
            )
            await conn.execute(
                update(locks)
                .where(locks.c.attempt_id == attempt["id"])
                .values(lease_until=time.time() + 30)
            )
            return (
                await conn.execute(
                    select(jobs.c.cancel_requested).where(jobs.c.id == attempt["job_id"])
                )
            ).scalar_one()

    async def append(self, attempt, kind, data):
        async with self.transaction() as conn:
            await self._owned(conn, attempt)
            return await self._event(conn, attempt["job_id"], kind, data, attempt["id"])

    async def _terminal(self, conn, job, status, result=None, error=None, attempt_id=None):
        await conn.execute(
            update(jobs)
            .where(jobs.c.id == job["id"])
            .values(status=status, result=result, error=error, updated_at=time.time())
        )
        await conn.execute(delete(locks).where(locks.c.job_id == job["id"]))
        await self._event(
            conn, job["id"], "job." + status, {"result": result, "error": error}, attempt_id
        )
        if job["conversation_id"] and status != "completed":
            await conn.execute(
                update(sessions)
                .where(
                    sessions.c.owner_id == job["owner_id"],
                    sessions.c.conversation_id == job["conversation_id"],
                )
                .values(state="needs_rebuild", updated_at=time.time())
            )

    async def finish(self, attempt, status, result=None, error=None, retry=False):
        if result is not None:
            result = {**result, "attempt_id": attempt["id"]}
        async with self.transaction() as conn:
            await self._owned(conn, attempt)
            job = (
                (await conn.execute(select(jobs).where(jobs.c.id == attempt["job_id"])))
                .mappings()
                .one()
            )
            if job["cancel_requested"]:
                status, result, error, retry = (
                    "cancelled",
                    None,
                    {"code": "cancelled", "usage_complete": False},
                    False,
                )
            await conn.execute(
                update(attempts)
                .where(attempts.c.id == attempt["id"])
                .values(
                    status=status,
                    finished_at=time.time(),
                    error=error,
                    usage=result.get("usage") if result else None,
                )
            )
            if retry and not job["conversation_id"] and job["attempt_count"] < 2:
                # Fresh session and explicit evidence/errors on each bounded repair.
                request = dict(job["request"])
                request["metadata"] = {**request["metadata"], "repair_error": error}
                await conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(status="queued", error=error, request=request)
                )
                await self._event(
                    conn,
                    job["id"],
                    "attempt.failed",
                    {"error": error, "retry": True},
                    attempt["id"],
                )
                return
            if result and job["conversation_id"]:
                usage = result["usage"]
                await conn.execute(
                    update(sessions)
                    .where(
                        sessions.c.owner_id == job["owner_id"],
                        sessions.c.conversation_id == job["conversation_id"],
                    )
                    .values(
                        state="ready",
                        last_cost=usage.get("native_total_cost_usd"),
                        last_counters=usage.get("native_counters"),
                        updated_at=time.time(),
                    )
                )
            await self._terminal(conn, job, status, result, error, attempt["id"])

    async def recover(self):
        async with self.transaction() as conn:
            expired = (
                (
                    await conn.execute(
                        select(attempts).where(
                            attempts.c.status == "running", attempts.c.lease_until < time.time()
                        )
                    )
                )
                .mappings()
                .all()
            )
            for attempt in expired:
                job = (
                    (await conn.execute(select(jobs).where(jobs.c.id == attempt["job_id"])))
                    .mappings()
                    .one()
                )
                await conn.execute(
                    update(attempts)
                    .where(attempts.c.id == attempt["id"])
                    .values(
                        status="uncertain", finished_at=time.time(), error={"code": "worker_lost"}
                    )
                )
                await self._terminal(
                    conn,
                    job,
                    "uncertain",
                    error={
                        "code": "worker_lost",
                        "usage_complete": False,
                        "requires_explicit_recovery": True,
                    },
                    attempt_id=attempt["id"],
                )
            return len(expired)

    async def cancel(self, job_id):
        async with self.transaction() as conn:
            job = (await conn.execute(select(jobs).where(jobs.c.id == job_id))).mappings().one()
            if job["status"] in TERMINAL:
                return
            await conn.execute(
                update(jobs).where(jobs.c.id == job_id).values(cancel_requested=True)
            )
            if job["status"] == "queued":
                await self._terminal(conn, job, "cancelled", error={"code": "cancelled"})

    async def replay(self, job_id, after=0, limit=100):
        async with self.engine.connect() as conn:
            first = (
                await conn.execute(select(func.min(events.c.seq)).where(events.c.job_id == job_id))
            ).scalar_one()
            if first is not None and after < first - 1:
                raise Conflict("replay_expired")
            rows = (
                (
                    await conn.execute(
                        select(events)
                        .where(events.c.job_id == job_id, events.c.seq > after)
                        .order_by(events.c.seq)
                        .limit(limit)
                    )
                )
                .mappings()
                .all()
            )
            return [
                {
                    "schema_version": 1,
                    **dict(r),
                    "created_at": datetime.fromtimestamp(r["created_at"], timezone.utc).isoformat(),
                }
                for r in rows
            ]

    async def acknowledge(self, job_id, consumer, reference):
        async with self.transaction() as conn:
            job = (await conn.execute(select(jobs).where(jobs.c.id == job_id))).mappings().one()
            if job["status"] != "completed":
                raise Conflict("result_not_completed")
            ack = (
                (
                    await conn.execute(
                        select(acks).where(acks.c.job_id == job_id, acks.c.consumer == consumer)
                    )
                )
                .mappings()
                .first()
            )
            if ack:
                if ack["reference"] != reference:
                    raise Conflict("ack_reference_conflict")
                return
            await conn.execute(
                insert(acks).values(
                    job_id=job_id, consumer=consumer, reference=reference, created_at=time.time()
                )
            )

    async def tool_event(self, job_id, attempt_id, kind, data):
        async with self.transaction() as conn:
            attempt = (
                (
                    await conn.execute(
                        select(attempts).where(
                            attempts.c.id == attempt_id, attempts.c.job_id == job_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if not attempt:
                raise Fenced("unknown_attempt")
            await self._owned(conn, attempt)
            await self._event(conn, job_id, kind, data, attempt_id)

    async def prune(self):
        async with self.transaction() as conn:
            await conn.execute(
                delete(events).where(
                    events.c.created_at < time.time() - 7 * 86400,
                    events.c.job_id.in_(select(jobs.c.id).where(jobs.c.status.in_(TERMINAL))),
                )
            )
