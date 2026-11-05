"""Original evidence transport and owner-scoped frontend reads."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from datetime import date
from uuid import UUID

from anyio import fail_after
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from auth import get_current_user
from db.client import get_supabase_thread_safe
from services import agent_history
from services.agent_evidence import EvidenceStore, enabled, fail
from services.agent_evidence_models import (
    MAX_BATCH_OBJECTS,
    MAX_OBJECT_BYTES,
    BatchRequest,
    attachment_content_type,
)
from services.agent_evidence_presentation import fragment_presentation

router = APIRouter(tags=["agent-evidence"])
UPLOAD = "/api/agent-evidence"
READ = "/api/folders/{folder_id}/agent-sessions"
_uploads = asyncio.Semaphore(4)


def _feature():
    if not enabled():
        fail("feature_disabled", 503)


def _key(request: Request):
    """Same scoped rag_ key hashing as routes.cli; no inference/auth-provider changes."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer rag_"):
        fail("api_key_required", 401)
    sb = get_supabase_thread_safe()
    rows = (
        sb.table("api_keys")
        .select("user_id,scope_folder_id")
        .eq("key_hash", hashlib.sha256(auth[7:].encode()).hexdigest())
        .limit(1)
        .execute()
        .data
    )
    if not rows or not rows[0].get("scope_folder_id"):
        fail("invalid_api_key", 401)
    return sb, rows[0]["user_id"], rows[0]["scope_folder_id"]


def _repo(sb, user_id, folder_id, scope_id=None):
    try:
        UUID(folder_id)
    except (ValueError, TypeError):
        fail("not_found", 404)
    rows = (
        sb.table("folders")
        .select("id,user_id,parent_id,kind")
        .eq("id", folder_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows or rows[0].get("kind") != "repo":
        fail("not_found", 404)
    if scope_id is not None:
        current, seen = rows[0], set()
        while current["id"] != scope_id:
            if current["id"] in seen or len(seen) > 128 or not current.get("parent_id"):
                fail("not_found", 404)
            seen.add(current["id"])
            ancestors = (
                sb.table("folders")
                .select("id,parent_id")
                .eq("id", current["parent_id"])
                .eq("user_id", user_id)
                .limit(1)
                .execute()
                .data
            )
            if not ancestors:
                fail("not_found", 404)
            current = ancestors[0]


def _read_store(folder_id: str, user_id: str):
    _feature()
    sb = get_supabase_thread_safe()
    _repo(sb, user_id, folder_id)
    return EvidenceStore(sb, user_id, folder_id)


def _key_store(request, batch_id=None, session_id=None):
    _feature()
    sb, user, scope = _key(request)
    store = EvidenceStore(sb, user)
    record = store.batch(batch_id) if batch_id else store.session(session_id)
    _repo(sb, user, record["folder_id"], scope)
    store.folder_id = record["folder_id"]
    return store


@router.get(UPLOAD + "/capabilities")
def capabilities(request: Request):
    _key(request)
    return {
        "enabled": enabled(),
        "schema": 1,
        "max_object_bytes": MAX_OBJECT_BYTES,
        "max_batch_objects": MAX_BATCH_OBJECTS,
    }


@router.post(UPLOAD + "/batches")
async def prepare(request: Request):
    _feature()
    sb, user, scope = await run_in_threadpool(_key, request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            fail("control_payload_too_large", 413)
    try:
        data = BatchRequest.model_validate_json(body)
    except ValidationError:
        fail("invalid_batch", 422)
    await run_in_threadpool(_repo, sb, user, data.folder_id, scope)
    return await run_in_threadpool(EvidenceStore(sb, user, data.folder_id).prepare, data)


@router.get(UPLOAD + "/batches/{batch_id}")
def batch_status(batch_id: str, request: Request):
    store = _key_store(request, batch_id=batch_id)
    b = store.batch(batch_id)
    return {
        k: b.get(k) for k in ("batch_id", "session_id", "state", "committed_revision", "error_code")
    }


@router.put(UPLOAD + "/batches/{batch_id}/objects/{object_id}")
async def upload(batch_id: str, object_id: str, request: Request):
    store = await run_in_threadpool(_key_store, request, batch_id)
    async with _uploads:
        length = 0
        digest = hashlib.sha256()
        with tempfile.TemporaryFile(buffering=0) as body:
            try:
                with fail_after(300):
                    async for chunk in request.stream():
                        length += len(chunk)
                        if length > MAX_OBJECT_BYTES:
                            fail("object_too_large", 413)
                        digest.update(chunk)
                        await run_in_threadpool(body.write, chunk)
            except TimeoutError:
                fail("upload_timeout", 408)
            return await run_in_threadpool(
                store.upload, batch_id, object_id, body, digest.hexdigest(), length
            )


@router.post(UPLOAD + "/batches/{batch_id}/commit")
def commit(batch_id: str, request: Request):
    result = _key_store(request, batch_id=batch_id).commit(batch_id)
    # The SQL receipt remains pending even if Redis is unavailable. The worker's
    # database reaper is the durable fallback, so no transient in-process task is needed.
    return result


@router.get(UPLOAD + "/sessions/{session_id}/inventory")
def inventory(
    session_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=256),
):
    return _key_store(request, session_id=session_id).inventory(session_id, cursor, limit)


@router.get(READ)
def sessions(
    folder_id: str,
    user_id: str = Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    agent: str | None = None,
):
    if agent not in (None, "claude_code", "codex"):
        fail("invalid_agent", 422)
    return _read_store(folder_id, user_id).list_sessions(cursor, limit, agent)


@router.get(READ + "/evidence-for-entry/{entry_id}")
def entry(folder_id: str, entry_id: str, user_id: str = Depends(get_current_user)):
    return _read_store(folder_id, user_id).resolve_entry(entry_id)


@router.get(READ + "/{session_id}/days")
def days(
    folder_id: str,
    session_id: str,
    timezone: str = "UTC",
    start: date | None = None,
    end: date | None = None,
    user_id: str = Depends(get_current_user),
):
    return _read_store(folder_id, user_id).days(session_id, timezone, start, end)


@router.get(READ + "/{session_id}/events")
def events(
    folder_id: str,
    session_id: str,
    before: str | None = None,
    after: str | None = None,
    around: str | None = None,
    date: str | None = None,
    timezone: str = "UTC",
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user),
):
    return _read_store(folder_id, user_id).window(
        session_id, before=before, after=after, around=around, day=date, tz=timezone, limit=limit
    )


@router.get(READ + "/{session_id}/raw-records")
def raw_records(
    folder_id: str,
    session_id: str,
    before: str | None = None,
    after: str | None = None,
    around: str | None = None,
    date: str | None = None,
    timezone: str = "UTC",
    limit: int = Query(50, ge=1, le=100),
    user_id: str = Depends(get_current_user),
):
    return _read_store(folder_id, user_id).window(
        session_id,
        before=before,
        after=after,
        around=around,
        day=date,
        tz=timezone,
        limit=limit,
        raw=True,
    )


@router.get(READ + "/{session_id}/events/{event_id}/content")
def content(
    folder_id: str,
    session_id: str,
    event_id: str,
    offset: int = Query(0, ge=0),
    limit_bytes: int = Query(65536, ge=1, le=65536),
    user_id: str = Depends(get_current_user),
):
    store = _read_store(folder_id, user_id)
    text, presentation = store.event_content_view(session_id, store.event(session_id, event_id))
    full = text.encode()
    # UTF-8 boundaries are preserved in expanded text; raw byte reads remain exact.
    start = offset
    while start < len(full) and full[start] & 0xC0 == 0x80:
        start += 1
    value = full[start : start + limit_bytes].decode("utf-8", errors="ignore")
    if not value and start < len(full):
        # A tiny byte limit must still advance over one complete Unicode character.
        value = full[start : start + 4].decode("utf-8", errors="ignore")[:1]
    end = start + len(value.encode())
    return {
        "event_id": event_id,
        "content": value,
        "byte_length": len(full),
        "viewer_truncated": start > 0 or end < len(full),
        "has_more": end < len(full),
        "next_offset": end if end < len(full) else None,
        "presentation": presentation
        if start == 0 and end == len(full)
        else fragment_presentation(value, presentation["source_truncated"]),
    }


def _bytes_response(data, request, download=False, name="original.bin", limit=65536):
    total = len(data)
    start, end = 0, min(total, limit) - 1
    range_header = request.headers.get("range")
    if download and not range_header:
        end = total - 1
    if range_header:
        import re

        match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
        if not match:
            raise HTTPException(416, headers={"Content-Range": f"bytes */{total}"})
        start = int(match[1])
        end = min(int(match[2]) if match[2] else total - 1, total - 1)
        if start > end or start >= total or end - start + 1 > MAX_OBJECT_BYTES:
            raise HTTPException(416, headers={"Content-Range": f"bytes */{total}"})
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
        "X-Original-Sha256": hashlib.sha256(data).hexdigest(),
        "Cache-Control": "private, no-store",
    }
    if download:
        # Never put an arbitrary original filename into an HTTP header.
        headers["Content-Disposition"] = 'attachment; filename="' + name + '"'
    status = 206 if range_header or start > 0 or end < total - 1 else 200
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return Response(
        data[start : end + 1],
        status_code=status,
        media_type="application/octet-stream",
        headers=headers,
    )


@router.get(READ + "/{session_id}/events/{event_id}/raw")
def raw_event(
    folder_id: str,
    session_id: str,
    event_id: str,
    request: Request,
    download: bool = False,
    user_id: str = Depends(get_current_user),
):
    store = _read_store(folder_id, user_id)
    return _bytes_response(
        store.event_raw(session_id, store.event(session_id, event_id)),
        request,
        download,
        name="original.jsonl",
    )


@router.get(READ + "/{session_id}/attachments/{attachment_id}")
def attachment(
    folder_id: str,
    session_id: str,
    attachment_id: str,
    request: Request,
    content: bool = False,
    download: bool = False,
    user_id: str = Depends(get_current_user),
):
    store = _read_store(folder_id, user_id)
    obj = store.object(session_id, attachment_id)
    if obj["kind"] != "attachment":
        fail("not_found", 404)
    if content or download:
        return _bytes_response(store.download(obj), request, download)
    return {
        "id": obj["object_id"],
        "original_name": obj["descriptor"].get("original_name", "attachment"),
        "byte_length": obj["byte_length"],
        "content_type": attachment_content_type(obj["descriptor"].get("original_name")),
        "source_event_id": obj["descriptor"].get("source_event_id"),
        "available": bool(obj.get("uploaded_at")),
        "sha256": obj["sha256"],
    }


@router.get(READ + "/{session_id}")
def session(folder_id: str, session_id: str, user_id: str = Depends(get_current_user)):
    store = _read_store(folder_id, user_id)
    return store.metadata(store.session(session_id))


@router.delete(READ + "/{session_id}")
def delete(folder_id: str, session_id: str, user_id: str = Depends(get_current_user)):
    return _read_store(folder_id, user_id).delete(session_id)


@router.get("/api/folders/{folder_id}/agent-history/days")
def history_days(
    folder_id: str,
    start: date,
    end: date,
    timezone: str = "UTC",
    agent: str | None = None,
    user_id: str = Depends(get_current_user),
):
    return agent_history.days(_read_store(folder_id, user_id), start, end, timezone, agent)


@router.get("/api/folders/{folder_id}/agent-history/sessions")
def history_sessions(
    folder_id: str,
    date: date,
    timezone: str = "UTC",
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    agent: str | None = None,
    user_id: str = Depends(get_current_user),
):
    return agent_history.sessions(
        _read_store(folder_id, user_id), date, timezone, cursor, limit, agent
    )
