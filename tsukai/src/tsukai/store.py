"""SQL is authoritative. Every attempt write checks its unexpired fencing lease."""

import asyncio
import hashlib
import json
import os
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from .protocol import TERMINAL, JobRequest
from .tables import acks, attempts, events, jobs, locks, metadata, sessions, tombstones


class Conflict(Exception):
    pass


class Fenced(Conflict):
    pass


class Store:
    def __init__(self, url: str, workspace_dir="/data/workspaces", database_ca_file=None):
        url = make_url(url)
        options = {"pool_pre_ping": True}
        if url.drivername == "postgresql+asyncpg":
            # Leave headroom under the dedicated role's six-connection limit.
            # SQL work is short-lived; model execution never holds a connection.
            options.update(pool_size=4, max_overflow=0, pool_timeout=5)
            modes = [url.query[key] for key in ("ssl", "sslmode") if key in url.query]
            if any(not isinstance(mode, str) for mode in modes) or len(set(modes)) > 1:
                raise ValueError("conflicting PostgreSQL TLS modes")
            ca_files = [
                value
                for value in (
                    database_ca_file,
                    os.getenv("TSUKAI_DATABASE_CA_FILE"),
                    url.query.get("sslrootcert"),
                )
                if value
            ]
            if any(not isinstance(value, str) for value in ca_files) or len(set(ca_files)) > 1:
                raise ValueError("conflicting PostgreSQL CA files")
            if ca_files and modes and modes[0] != "verify-full":
                raise ValueError("a PostgreSQL CA file requires verify-full TLS mode")
            if (modes and modes[0] == "verify-full") or ca_files:
                # asyncpg's string mode defaults to ~/.postgresql/root.crt, which is not
                # provisioned in the readonly nonroot image. Use platform CA trust while
                # preserving mandatory certificate AND server hostname verification.
                context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
                if ca_files:
                    # Supabase uses a private CA. Add its operator-provisioned public trust
                    # anchor without replacing system roots or weakening verification.
                    context.load_verify_locations(cafile=ca_files[0])
                context.verify_mode = ssl.CERT_REQUIRED
                context.check_hostname = True
                options["connect_args"] = {"ssl": context}
                url = url.difference_update_query(["ssl", "sslmode", "sslrootcert"])
        self.engine = create_async_engine(url, **options)
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
        if request.response_schema is not None:
            policy["structured_transport"] = "result-wrapper-v1"
        return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()

    async def admit(self, request: JobRequest, queue_capacity=100, request_sha256=None):
        payload = request.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        now = time.time()
        async with self.transaction() as conn:
            blocked = (
                await conn.execute(
                    select(tombstones.c.id).where(
                        tombstones.c.owner_sha256 == self.hash_id(request.owner_id),
                        tombstones.c.conversation_sha256.in_(
                            ["*", self.hash_id(request.conversation_id or "")]
                        ),
                    )
                )
            ).first()
            if blocked:
                raise Conflict("execution_scope_deleted")
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
                    # A burst's third root must be able to wait for either occupied
                    # 300s root slot, with 30s scheduling grace. Keep the queue bounded
                    # without increasing native concurrency or the execution limit.
                    queue_deadline=now + (330 if request.profile == "chat" else 1800),
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

    async def expire_queued(self):
        async with self.transaction() as conn:
            expired = (
                (
                    await conn.execute(
                        select(jobs).where(
                            jobs.c.status == "queued", jobs.c.queue_deadline < time.time()
                        )
                    )
                )
                .mappings()
                .all()
            )
            for job in expired:
                await self._terminal(conn, job, "failed", error={"code": "queue_timeout"})
            return len(expired)

    async def claim(self, worker_id, only_job_id=None):
        now = time.time()
        async with self.transaction() as conn:
            active_rows = (
                (
                    await conn.execute(
                        select(jobs.c.profile, jobs.c.caller, jobs.c.owner_id).where(
                            jobs.c.status == "running"
                        )
                    )
                )
                .mappings()
                .all()
            )
            active = [row["profile"] for row in active_rows]
            owner_active = {}
            for row in active_rows:
                if row["profile"] != "metadata_child":
                    owner_active[row["owner_id"]] = owner_active.get(row["owner_id"], 0) + 1
            served = dict(
                (
                    await conn.execute(
                        select(jobs.c.owner_id, func.max(attempts.c.started_at))
                        .join(attempts, attempts.c.job_id == jobs.c.id)
                        .group_by(jobs.c.owner_id)
                    )
                ).all()
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

            # First avoid an owner's second root while another owner is waiting. Then
            # prefer chat, with one priority level per minute of queue aging; ties go to
            # least recently served owner and original admission order. SQL is shared state.
            def fair_order(job):
                base = (
                    3
                    if job["profile"] == "metadata_child"
                    else 2
                    if job["profile"] == "chat"
                    else 1
                )
                aged = base + int(max(0, now - job["created_at"]) / 60)
                return (
                    owner_active.get(job["owner_id"], 0),
                    -aged,
                    served.get(job["owner_id"], 0),
                    job["created_at"],
                )

            candidates = sorted(candidates, key=fair_order)
            chosen = None
            for job in candidates:
                if only_job_id and job["id"] != only_job_id:
                    continue
                child = job["profile"] == "metadata_child"
                if (child and active.count("metadata_child") >= 1) or (
                    not child and sum(p != "metadata_child" for p in active) >= 2
                ):
                    continue
                if job["caller"] == "mihari" and any(
                    row["caller"] == "mihari" for row in active_rows
                ):
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
                "repair_diagnostic": (
                    await conn.execute(
                        select(attempts.c.diagnostic).where(
                            attempts.c.job_id == job["id"],
                            attempts.c.number == attempt["number"] - 1,
                        )
                    )
                ).scalar_one_or_none(),
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
            await conn.execute(
                update(attempts)
                .where(attempts.c.id == attempt["id"])
                .values(
                    first_event_at=attempt.get("first_event_at"),
                    first_text_at=attempt.get("first_text_at"),
                )
            )
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

    async def finish(self, attempt, status, result=None, error=None, retry=False, diagnostic=None):
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
                    first_event_at=attempt.get("first_event_at"),
                    first_text_at=attempt.get("first_text_at"),
                    error=error,
                    usage=result.get("usage") if result else None,
                    diagnostic=diagnostic,
                )
            )
            if retry and not job["conversation_id"] and job["attempt_count"] < 2:
                # Fresh session and explicit evidence/errors on each bounded repair.
                await conn.execute(
                    update(jobs).where(jobs.c.id == job["id"]).values(status="queued", error=error)
                )
                await self._event(
                    conn,
                    job["id"],
                    "attempt.failed",
                    {"error": error, "retry": True},
                    attempt["id"],
                )
                return
            if result and status == "completed" and job["conversation_id"]:
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

    @staticmethod
    def hash_id(value):
        return hashlib.sha256(value.encode()).hexdigest()

    async def scope_deleted(self, owner_id, conversation_id=None):
        async with self.engine.connect() as conn:
            return (
                await conn.execute(
                    select(tombstones.c.id).where(
                        tombstones.c.owner_sha256 == self.hash_id(owner_id),
                        tombstones.c.conversation_sha256.in_(
                            ["*", self.hash_id(conversation_id or "")]
                        ),
                    )
                )
            ).first() is not None

    async def begin_deletion(self, owner_id, conversation_id=None):
        owner_hash = self.hash_id(owner_id)
        scope_hash = self.hash_id(conversation_id) if conversation_id is not None else "*"
        key = self.hash_id(owner_hash + ":" + scope_hash)
        async with self.transaction() as conn:
            existing = (
                (await conn.execute(select(tombstones).where(tombstones.c.id == key)))
                .mappings()
                .first()
            )
            if existing:
                return dict(existing)
            scope = jobs.c.owner_id == owner_id
            session_scope = sessions.c.owner_id == owner_id
            if conversation_id is not None:
                scope = and_(scope, jobs.c.conversation_id == conversation_id)
                session_scope = and_(session_scope, sessions.c.conversation_id == conversation_id)
            selected = (await conn.execute(select(jobs).where(scope))).mappings().all()
            selected_sessions = (
                (await conn.execute(select(sessions).where(session_scope))).mappings().all()
            )
            artifacts = []
            for session in selected_sessions:
                artifacts.extend(
                    [
                        {
                            "workspace": session["workspace"],
                            "native_session_id": session["native_session_id"],
                        },
                        *[
                            {
                                "workspace": old["workspace"],
                                "native_session_id": old["native_session_id"],
                            }
                            for old in session["history"]
                        ],
                    ]
                )
            for job in selected:
                await conn.execute(
                    update(jobs).where(jobs.c.id == job["id"]).values(cancel_requested=True)
                )
                if job["status"] == "queued":
                    await self._terminal(conn, job, "cancelled", error={"code": "scope_deleted"})
                if job["profile"] != "chat":
                    rows = (
                        (
                            await conn.execute(
                                select(attempts.c.native_session_id).where(
                                    attempts.c.job_id == job["id"]
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    workspace = f"{self.workspace_dir}/{self.hash_id(owner_id)[:24]}/{job['id']}"
                    artifacts.extend(
                        {"workspace": workspace, "native_session_id": native} for native in rows
                    )
            record = {
                "id": key,
                "owner_sha256": owner_hash,
                "conversation_sha256": scope_hash,
                "status": "pending",
                "job_ids": [job["id"] for job in selected],
                "session_keys": [
                    {"owner_id": row["owner_id"], "conversation_id": row["conversation_id"]}
                    for row in selected_sessions
                ],
                "artifacts": artifacts,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            await conn.execute(insert(tombstones).values(**record))
            return record

    async def deletion(self, deletion_id):
        async with self.engine.connect() as conn:
            row = (
                (await conn.execute(select(tombstones).where(tombstones.c.id == deletion_id)))
                .mappings()
                .first()
            )
            return dict(row) if row else None

    async def pending_deletions(self):
        async with self.engine.connect() as conn:
            rows = (
                (await conn.execute(select(tombstones).where(tombstones.c.status == "pending")))
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def deletion_reap_ready(self, record, remote_grace):
        async with self.engine.connect() as conn:
            active = (
                await conn.execute(
                    select(jobs.c.id).where(
                        jobs.c.id.in_(record["job_ids"]), jobs.c.status.in_(["queued", "running"])
                    )
                )
            ).first()
            if active:
                return False
            uncertain = (
                await conn.execute(
                    select(func.max(attempts.c.finished_at)).where(
                        attempts.c.job_id.in_(record["job_ids"]), attempts.c.status == "uncertain"
                    )
                )
            ).scalar_one()
            # A lost worker's last heartbeat may race expiry. Wait beyond kill+heartbeat bounds.
            return uncertain is None or time.time() > uncertain + remote_grace + 5

    async def complete_deletion(self, record):
        async with self.transaction() as conn:
            active = (
                await conn.execute(
                    select(jobs.c.id).where(
                        jobs.c.id.in_(record["job_ids"]), jobs.c.status.in_(["queued", "running"])
                    )
                )
            ).first()
            if active:
                raise Conflict("deletion_execution_still_active")
            for table in (acks, events, locks, attempts):
                await conn.execute(delete(table).where(table.c.job_id.in_(record["job_ids"])))
            await conn.execute(delete(jobs).where(jobs.c.id.in_(record["job_ids"])))
            for key in record["session_keys"]:
                await conn.execute(
                    delete(sessions).where(
                        sessions.c.owner_id == key["owner_id"],
                        sessions.c.conversation_id == key["conversation_id"],
                    )
                )
            await conn.execute(
                update(tombstones)
                .where(tombstones.c.id == record["id"])
                .values(
                    status="cleaned",
                    job_ids=[],
                    session_keys=[],
                    artifacts=[],
                    updated_at=time.time(),
                )
            )

    async def active_sessions(self):
        now = time.time()
        async with self.engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        select(
                            jobs,
                            attempts.c.id.label("active_attempt_id"),
                            attempts.c.native_session_id,
                            attempts.c.started_at,
                            attempts.c.worker_id,
                        )
                        .join(attempts, attempts.c.job_id == jobs.c.id)
                        .where(
                            jobs.c.status == "running",
                            attempts.c.status == "running",
                            attempts.c.lease_until > now,
                        )
                    )
                )
                .mappings()
                .all()
            )
            queued = (
                await conn.execute(
                    select(jobs.c.profile, func.count())
                    .where(jobs.c.status == "queued")
                    .group_by(jobs.c.profile)
                )
            ).all()
            return [dict(row) for row in rows], dict(queued)

    @staticmethod
    def attempt_timings(row, created_at):
        def iso(value):
            return (
                datetime.fromtimestamp(value, timezone.utc).isoformat()
                if value is not None
                else None
            )

        start = row["started_at"]
        return {
            **{
                key: iso(row[key])
                for key in ("started_at", "first_event_at", "first_text_at", "finished_at")
            },
            "queue_wait_seconds": max(0, start - created_at),
            "elapsed_seconds": max(0, (row["finished_at"] or time.time()) - start),
            "first_event_seconds": row["first_event_at"] - start
            if row["first_event_at"] is not None
            else None,
            "first_text_seconds": row["first_text_at"] - start
            if row["first_text_at"] is not None
            else None,
        }

    async def attempt_usage(self, job_id):
        async with self.engine.connect() as conn:
            job = (
                (
                    await conn.execute(
                        select(jobs.c.request, jobs.c.created_at).where(jobs.c.id == job_id)
                    )
                )
                .mappings()
                .one()
            )
            rows = (
                (
                    await conn.execute(
                        select(attempts)
                        .where(attempts.c.job_id == job_id)
                        .order_by(attempts.c.number)
                    )
                )
                .mappings()
                .all()
            )
            return [
                {
                    "attempt_id": row["id"],
                    "number": row["number"],
                    "status": row["status"],
                    "model": job["request"]["model"],
                    **self.attempt_timings(row, job["created_at"]),
                    "native_session_id": row["native_session_id"],
                    "counter_segment": row["counter_segment"],
                    "usage": row["usage"],
                    "error": row["error"],
                }
                for row in rows
            ]

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
            cutoff = time.time() - 30 * 86400
            await conn.execute(
                update(attempts).where(attempts.c.finished_at < cutoff).values(diagnostic=None)
            )
            old = (
                (
                    await conn.execute(
                        select(jobs).where(
                            jobs.c.updated_at < cutoff,
                            jobs.c.status.in_(["failed", "uncertain", "cancelled"]),
                        )
                    )
                )
                .mappings()
                .all()
            )
            for job in old:
                request = {
                    **job["request"],
                    "prompt": "[expired diagnostic evidence]",
                    "system_prompt": "",
                    "metadata": {},
                    "response_schema": None,
                }
                result = job["result"]
                if result:
                    result = {**result, "text": "", "structured": None}
                await conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(
                        request=request,
                        result=result,
                        error={"code": "diagnostic_expired", "usage_complete": False},
                    )
                )
            await conn.execute(
                delete(events).where(
                    events.c.created_at < time.time() - 7 * 86400,
                    events.c.job_id.in_(select(jobs.c.id).where(jobs.c.status.in_(TERMINAL))),
                )
            )
