"""Private durable execution API. Disconnects never own or cancel accepted work."""

import hashlib
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select

from .auth import authorize, capability, service_auth
from .config import Settings
from .models import CatalogUnavailable, ModelCatalog
from .protocol import TERMINAL, Ack, JobRequest, StrictModel
from .scheduler import Scheduler
from .store import Conflict, Store
from .tables import attempts


class ToolEvent(StrictModel):
    attempt_id: str
    type: str
    data: dict


def create_app(settings=None, store=None, native=None):
    settings = settings or Settings()
    supplied_store = store is not None
    if store is None:
        # Defer production configuration validation to startup, so tooling can import.
        store = (
            Store(settings.database_url, workspace_dir=settings.workspace_dir)
            if settings.database_url
            else None
        )
    scheduler = Scheduler(store, settings, native) if store else None
    model_catalog = ModelCatalog(settings)

    @asynccontextmanager
    async def lifespan(app):
        if not supplied_store:
            settings.validate()
        if scheduler is None:
            raise RuntimeError("TSUKAI_DATABASE_URL is required")
        await scheduler.start()
        yield
        await scheduler.drain()
        await store.engine.dispose()

    app = FastAPI(title="Tsukai", version="1", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.scheduler = scheduler
    app.state.model_catalog = model_catalog

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        code = str(exc)
        status = 410 if code == "replay_expired" else 503 if code == "queue_full" else 409
        return JSONResponse({"error": {"code": code}}, status_code=status)

    async def scoped_job(request, job_id):
        cap = capability(request, settings)
        job = await store.get(job_id)
        if job is None or job["owner_id"] != cap.owner_id:
            raise HTTPException(404, "job_not_found")
        if await store.scope_deleted(job["owner_id"], job["conversation_id"]):
            raise HTTPException(410, "execution_scope_deleted")
        authorize(cap, JobRequest.model_validate(job["request"]))
        return cap, job

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        good = (
            scheduler
            and not scheduler.draining
            and scheduler.db_available
            and scheduler.auth_state == "ready"
            and time.monotonic() >= scheduler.quota_until
        )
        return JSONResponse(
            {
                "ready": bool(good),
                "auth": scheduler.auth_state if scheduler else "unconfigured",
                "draining": scheduler.draining if scheduler else False,
            },
            status_code=200 if good else 503,
        )

    @app.get("/v1/admin/active-sessions")
    async def admin_active_sessions(request: Request):
        from datetime import datetime, timezone

        cap = capability(request, settings, allow_admin=True)
        if (
            not cap.admin
            or cap.sub != "backend"
            or cap.operations != ["runtime.sessions.read"]
            or cap.profiles
            or cap.folder_ids
            or cap.tool_allowlist
            or cap.ai_depth
            or cap.parent_job_id
            or cap.root_job_id
        ):
            raise HTTPException(403, "runtime_admin_capability_required")
        rows, queued = await store.active_sessions()
        active = []
        for row in rows:
            process = scheduler.native.processes.get(row["active_attempt_id"])
            state = "starting" if row["worker_id"] == scheduler.worker_id else "remote"
            if row["active_attempt_id"] in scheduler.finishing:
                state = "finishing"
            if process:
                state = "running" if process.returncode is None else "finishing"
            if row["cancel_requested"]:
                state = "cancelling"
            req = row["request"]
            active.append(
                {
                    "job_id": row["id"],
                    "attempt_id": row["active_attempt_id"],
                    "native_session_id": row["native_session_id"],
                    "owner_id": row["owner_id"],
                    "caller": row["caller"],
                    "conversation_id": row["conversation_id"],
                    "folder_ids": req["folder_ids"],
                    "operation": req["operation"],
                    "profile": req["profile"],
                    "model_requested": req["model"],
                    "native_cli_version": settings.native_version,
                    "state": state,
                    "started_at": datetime.fromtimestamp(
                        row["started_at"], timezone.utc
                    ).isoformat(),
                    "elapsed_seconds": round(max(0, time.time() - row["started_at"]), 3),
                    "pid": process.pid if process and process.returncode is None else None,
                }
            )
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sessions": active,
            "queued_counts": {
                "total": sum(queued.values()),
                **{
                    profile: queued.get(profile, 0)
                    for profile in ("chat", "completion", "metadata_child")
                },
            },
        }

    @app.get("/v1/models")
    async def supported_models(request: Request):
        cap = capability(request, settings)
        if (
            cap.sub != "backend"
            or cap.operations != ["runtime.models.read"]
            or cap.profiles
            or cap.folder_ids
            or cap.tool_allowlist
            or cap.ai_depth
            or cap.parent_job_id
            or cap.root_job_id
            or cap.admin
        ):
            raise HTTPException(403, "model_catalog_capability_required")
        try:
            return {
                **await model_catalog.get(),
                "request_controls": {"reasoning_effort": ["low", "medium", "high"]},
            }
        except CatalogUnavailable:
            raise HTTPException(503, "model_catalog_unavailable") from None

    @app.post("/v1/jobs", status_code=202)
    async def submit(request: Request):
        cap = capability(request, settings)
        if scheduler.draining:
            raise HTTPException(503, "runner_draining")
        if scheduler.auth_state == "quota_limited" or time.monotonic() < scheduler.quota_until:
            raise HTTPException(429, "quota_limited")
        if scheduler.auth_state != "ready":
            raise HTTPException(503, scheduler.auth_state)
        raw = await request.body()
        if len(raw) > 2 * 1024 * 1024:
            raise HTTPException(413, "request_too_large")
        try:
            payload = json.loads(raw)
            req = JobRequest.model_validate(payload)
        except (ValueError, ValidationError):
            raise HTTPException(422, "invalid_job_request") from None
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        authorize(cap, req, digest)
        if req.model not in settings.allowed_models:
            if not req.model.startswith("claude-"):
                raise HTTPException(422, "unsupported_model")
            try:
                catalog = await model_catalog.get()
            except CatalogUnavailable:
                raise HTTPException(503, "model_catalog_unavailable") from None
            if catalog["stale"]:
                raise HTTPException(503, "model_catalog_unavailable")
            if req.model not in {
                row["resolvedModel"] for row in catalog["models"] if row["selectable"]
            }:
                raise HTTPException(422, "unsupported_model")
            if req.reasoning_effort is not None:
                levels = next(
                    row.get("supportedEffortLevels")
                    for row in catalog["models"]
                    if row["resolvedModel"] == req.model and row["selectable"]
                )
                if isinstance(levels, list) and req.reasoning_effort not in levels:
                    raise HTTPException(422, "unsupported_reasoning_effort")
        if "repair_error" in req.metadata:
            raise HTTPException(422, "reserved_metadata_key")
        job = await store.admit(req, request_sha256=digest)
        await scheduler.notify(job["id"])
        return {
            "job_id": job["id"],
            "status": job["status"],
            "events_url": f"/v1/jobs/{job['id']}/events",
            "result_url": f"/v1/jobs/{job['id']}/result",
        }

    @app.post("/v1/conversations/{conversation_id}/rebuild", status_code=202)
    async def rebuild(conversation_id: str, request: Request):
        raw = await request.body()
        try:
            payload = json.loads(raw)
        except ValueError:
            raise HTTPException(422, "invalid_job_request") from None
        if (
            payload.get("conversation_id") != conversation_id
            or payload.get("rebuild_from_committed_history") is not True
        ):
            raise HTTPException(422, "explicit_committed_history_rebuild_required")
        return await submit(request)

    @app.get("/v1/jobs")
    async def list_results(request: Request, unacknowledged: bool = True):
        cap = capability(request, settings)
        found = await store.unacknowledged(cap.owner_id, cap.sub)
        result = []
        for job in found:
            try:
                authorize(cap, JobRequest.model_validate(job["request"]))
                if not await store.scope_deleted(job["owner_id"], job["conversation_id"]):
                    result.append(job)
            except HTTPException:
                continue
        return {"jobs": result}

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        _, job = await scoped_job(request, job_id)
        return job

    @app.get("/v1/jobs/{job_id}/result")
    async def get_result(job_id: str, request: Request):
        _, job = await scoped_job(request, job_id)
        return {
            "job_id": job_id,
            "status": job["status"],
            "result": job["result"],
            "error": job["error"],
            "request_sha256": job["request_sha256"],
        }

    @app.get("/v1/jobs/{job_id}/usage")
    async def get_usage(job_id: str, request: Request):
        await scoped_job(request, job_id)
        return {"job_id": job_id, "attempts": await store.attempt_usage(job_id)}

    @app.post("/v1/jobs/{job_id}/ack")
    async def ack_result(job_id: str, body: Ack, request: Request):
        cap, _ = await scoped_job(request, job_id)
        if body.consumer != cap.sub:
            raise HTTPException(403, "ack_consumer_mismatch")
        await store.acknowledge(job_id, body.consumer, body.reference)
        return {"acknowledged": True}

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, request: Request):
        await scoped_job(request, job_id)
        await scheduler.cancel(job_id)
        return {"job_id": job_id, "cancel_requested": True}

    @app.get("/v1/jobs/{job_id}/events")
    async def stream(job_id: str, request: Request, after: int = 0):
        cap, job = await scoped_job(request, job_id)
        cursor = request.headers.get("last-event-id")
        try:
            after = int(cursor) if cursor else after
        except ValueError:
            raise HTTPException(422, "invalid_replay_cursor") from None
        if after < 0 or after >= job["next_seq"]:
            raise HTTPException(409, "invalid_replay_cursor")
        initial = await store.replay(job_id, after)
        if not initial and job["next_seq"] > after + 1:
            raise Conflict("replay_expired")

        async def generate():
            import asyncio

            nonlocal after
            heartbeat = time.monotonic()
            batch = initial
            while True:
                if await request.is_disconnected():
                    return
                if time.time() >= cap.exp:
                    return  # Client reconnects with renewed short-lived current-scope grant.
                delivered = 0
                for event in batch:
                    data = json.dumps(event, separators=(",", ":"))
                    frame = f"id: {event['seq']}\nevent: {event['type']}\ndata: {data}\n\n"
                    delivered += len(frame.encode())
                    if delivered > settings.subscriber_bytes:
                        return
                    yield frame
                    after = event["seq"]
                current = await store.get(job_id)
                if current["status"] in TERMINAL and after >= current["next_seq"] - 1:
                    return
                if time.monotonic() - heartbeat > 15:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.1)
                batch = await store.replay(job_id, after)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/jobs/{job_id}/attempts/{attempt_id}")
    async def active_attempt(job_id: str, attempt_id: str, request: Request):
        cap, job = await scoped_job(request, job_id)
        if cap.sub != "backend":
            raise HTTPException(403, "backend_only")
        async with store.engine.connect() as conn:
            attempt = (
                (
                    await conn.execute(
                        select(attempts).where(
                            attempts.c.id == attempt_id, attempts.c.job_id == job_id
                        )
                    )
                )
                .mappings()
                .first()
            )
        active = bool(
            attempt
            and attempt["status"] == "running"
            and attempt["lease_until"] > time.time()
            and job["status"] == "running"
            and not job["cancel_requested"]
        )
        return {
            "active": active,
            "job_id": job_id,
            "attempt_id": attempt_id,
            "owner_id": job["owner_id"],
            "folder_ids": job["request"]["folder_ids"],
            "tool_allowlist": job["request"]["tool_allowlist"],
            "deadline": attempt["deadline"] if attempt else None,
            "ai_depth": job["request"]["ai_depth"],
        }

    @app.post("/v1/jobs/{job_id}/tool-events")
    async def tool_events(job_id: str, body: ToolEvent, request: Request):
        cap, _ = await scoped_job(request, job_id)
        if cap.sub != "backend" or body.type not in {
            "tool.started",
            "retrieval.completed",
            "tool.completed",
        }:
            raise HTTPException(403, "unsupported_tool_event")
        if len(json.dumps(body.data)) > 65536:
            raise HTTPException(413, "tool_event_too_large")
        # Domain middleware sanitizes evidence and persists private full artifacts.
        await store.tool_event(job_id, body.attempt_id, body.type, body.data)
        return {"accepted": True}

    async def admit_deletion(request, conversation_id=None):
        cap = capability(request, settings, allow_cleanup=True)
        raw = await request.body()
        if len(raw) > 4096:
            raise HTTPException(413, "request_too_large")
        try:
            body = json.loads(raw)
        except ValueError:
            raise HTTPException(422, "invalid_deletion_request") from None
        expected = {"owner_id": cap.owner_id, "action": "delete_account"}
        operation, profiles = "account.delete", []
        if conversation_id is not None:
            expected = {
                "owner_id": cap.owner_id,
                "conversation_id": conversation_id,
                "action": "delete_conversation",
            }
            operation, profiles = "session.delete", ["chat"]
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if (
            body != expected
            or cap.sub != "backend"
            or cap.operations != [operation]
            or cap.profiles != profiles
            or cap.request_sha256 != digest
            or cap.ai_depth
            or cap.parent_job_id
            or cap.root_job_id
            or cap.tool_allowlist
        ):
            raise HTTPException(403, "cleanup_capability_mismatch")
        record = await store.begin_deletion(cap.owner_id, conversation_id)
        scheduler.wake.set()
        return {"deletion_id": record["id"], "status": record["status"]}

    @app.post("/v1/conversations/{conversation_id}/delete", status_code=202)
    async def delete_conversation(conversation_id: str, request: Request):
        return await admit_deletion(request, conversation_id)

    @app.post("/v1/account/delete", status_code=202)
    async def delete_account(request: Request):
        return await admit_deletion(request)

    @app.get("/v1/deletions/{deletion_id}")
    async def deletion_status(deletion_id: str, request: Request):
        cap = capability(request, settings, allow_cleanup=True)
        record = await store.deletion(deletion_id)
        if record is None or record["owner_sha256"] != store.hash_id(cap.owner_id):
            raise HTTPException(404, "deletion_not_found")
        operation = "account.delete" if record["conversation_sha256"] == "*" else "session.delete"
        if cap.sub != "backend" or cap.operations != [operation]:
            raise HTTPException(403, "cleanup_capability_mismatch")
        return {"deletion_id": deletion_id, "status": record["status"]}

    @app.post("/internal/recheck-auth")
    async def recheck_auth(request: Request):
        service_auth(request, settings)
        if scheduler.draining:
            raise HTTPException(503, "runner_draining")
        await scheduler.recheck_auth()
        return {"auth": scheduler.auth_state, "database_available": scheduler.db_available}

    @app.post("/internal/drain")
    async def drain(request: Request):
        service_auth(request, settings)
        await scheduler.drain()
        return {"drained": True}

    return app


app = create_app()
