"""CLI login endpoints.

The CLI authenticates via a browser-handoff device-auth flow:

    POST /api/cli/auth/device/start    — CLI starts a pending request
    GET  /api/cli/auth/device/info     — browser fetches display fields
    POST /api/cli/auth/device/complete — authenticated browser binds tokens
    POST /api/cli/auth/device/deny     — authenticated browser denies
    POST /api/cli/auth/device/token    — CLI polls until authorized/denied

The CLI stores the returned access_token + refresh_token locally and
uses them via `Authorization: Bearer <access>` on subsequent calls.
Refresh happens client-side using Supabase's refresh_token endpoint
(exposed at the standard /auth/v1/token endpoint) — no new backend
surface needed for that.
"""

from __future__ import annotations

import hashlib
import os
import time as _time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase
from services import cli_auth

router = APIRouter(prefix="/api/cli")


# ---------------------------------------------------------------------------
# Device-auth rate limiter
# ---------------------------------------------------------------------------

_DEVICE_RATE_MAX = 10          # requests per window for /start (burst guard)
_DEVICE_TOKEN_RATE_MAX = 60    # requests per window for /token (poll headroom)
_DEVICE_RATE_WINDOW = 60       # seconds, per IP + bucket
_device_hits: dict[str, deque] = {}


def _device_rate_limit(ip: str, bucket: str) -> tuple[bool, int]:
    # Opportunistically drop keys whose deque emptied (one-shot IPs, GC).
    now = _time.time()
    for k in list(_device_hits):
        dqk = _device_hits[k]
        while dqk and now - dqk[0] > _DEVICE_RATE_WINDOW:
            dqk.popleft()
        if not dqk:
            del _device_hits[k]

    key = f"{bucket}:{ip}"
    dq = _device_hits.setdefault(key, deque())
    while dq and now - dq[0] > _DEVICE_RATE_WINDOW:
        dq.popleft()
    # /token polls every 2s → ~30/min; give it 2× headroom vs. /start.
    limit = _DEVICE_TOKEN_RATE_MAX if bucket == "token" else _DEVICE_RATE_MAX
    if len(dq) >= limit:
        return False, int(_DEVICE_RATE_WINDOW - (now - dq[0])) + 1
    dq.append(now)
    return True, 0


def _client_ip(request: Request) -> str:
    # Trusts X-Forwarded-For; assumes a trusted reverse proxy sets it.
    # The limiter is DoS-dampening, not a security boundary.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")


# ---------------------------------------------------------------------------
# Device-auth endpoints
# ---------------------------------------------------------------------------

class DeviceStartRequest(BaseModel):
    hostname: str = Field(default="unknown", max_length=120)
    os: str = Field(default="unknown", max_length=60)


@router.post("/auth/device/start")
async def device_start(body: DeviceStartRequest, request: Request):
    allowed, retry = _device_rate_limit(_client_ip(request), "start")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry)},
        )
    try:
        r = await cli_auth.create_request(body.hostname, body.os)
    except Exception as exc:  # noqa: BLE001 — Redis down etc.
        raise HTTPException(status_code=503, detail=f"Auth service unavailable: {exc}")
    return {
        "request_id": r["request_id"],
        "device_code": r["device_code"],
        "verification_url": f"{_frontend_url()}/cli-auth?req={r['request_id']}",
        "interval": 2,
        "expires_in": r["expires_in"],
    }


class DeviceTokenRequest(BaseModel):
    device_code: str = Field(min_length=8, max_length=200)


@router.post("/auth/device/token")
async def device_token(body: DeviceTokenRequest, request: Request, response: Response):
    allowed, retry = _device_rate_limit(_client_ip(request), "token")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry)},
        )
    try:
        result = await cli_auth.consume_by_device_code(body.device_code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Auth service unavailable: {exc}")
    status = result["status"]
    if status == "authorized":
        return result["tokens"]
    if status == "pending":
        raise HTTPException(status_code=428, detail="authorization_pending")
    if status == "denied":
        raise HTTPException(status_code=403, detail="access_denied")
    raise HTTPException(status_code=410, detail="expired_token")


class DeviceRequestIdRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=200)


class DeviceCompleteRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=200)
    refresh_token: str | None = None
    expires_at: int | None = None
    email: str | None = None


@router.post("/auth/device/complete")
async def device_complete(
    body: DeviceCompleteRequest,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    # access_token comes from the verified bearer header (can't be spoofed)
    authz = request.headers.get("authorization", "")
    access_token = authz[7:] if authz.lower().startswith("bearer ") else ""
    tokens = {
        "access_token": access_token,
        "refresh_token": body.refresh_token,
        "expires_at": body.expires_at,
        "user": {"id": user_id, "email": body.email},
    }
    try:
        ok = await cli_auth.authorize(body.request_id, tokens)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Auth service unavailable: {exc}")
    if not ok:
        raise HTTPException(status_code=410, detail="Request not found or already handled")
    return {"ok": True}


@router.post("/auth/device/deny")
async def device_deny(
    body: DeviceRequestIdRequest,
    user_id: str = Depends(get_current_user),
):
    try:
        await cli_auth.deny(body.request_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Auth service unavailable: {exc}")
    return {"ok": True}


@router.get("/auth/device/info")
async def device_info(req: str):
    try:
        rec = await cli_auth.get_by_request_id(req)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Auth service unavailable: {exc}")
    if not rec:
        return {"hostname": None, "os": None, "valid": False, "expired": True}
    return {
        "hostname": rec["hostname"],
        "os": rec["os"],
        "valid": rec["status"] == "pending",
        "expired": False,
    }


class MintApiKeyRequest(BaseModel):
    """CLI-flavored api key mint. Returns the plaintext token + config
    snippet the CLI needs to write."""
    scope_folder_id: str
    name: str = Field(min_length=1, max_length=80)


@router.post("/mint-api-key")
async def mint_api_key(
    body: MintApiKeyRequest,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """CLI wrapper around the api-keys endpoint that also returns the
    MCP config snippet ready to write into .mcp.json."""
    from routes.api_keys import (
        CreateKeyRequest, create_api_key,
    )
    sb = get_supabase()
    # Reuse the underlying create path — same validation, same delete-
    # existing-scoped-key behavior. Returns {key, id, ...}.
    result = await create_api_key(
        CreateKeyRequest(name=body.name, scope_folder_id=body.scope_folder_id),
        user_id=user_id,
    )
    mcp_url = os.environ.get("MCP_PUBLIC_URL", "http://localhost:8001/sse")
    return {
        "key": result.key,
        "id": result.id,
        "scope_folder_id": body.scope_folder_id,
        "scope_folder_name": result.scope_folder_name,
        "mcp_config": {
            "mcpServers": {
                "kioku": {
                    # "type": "sse" is REQUIRED — without it Claude Code parses
                    # the entry as a stdio server ("command: expected string,
                    # received undefined") and silently skips kioku, so none of
                    # its MCP tools register (breaking the briefing autogen and
                    # every in-session tool call).
                    "type": "sse",
                    "url": mcp_url,
                    "headers": {"Authorization": f"Bearer {result.key}"},
                },
            },
        },
    }


@router.get("/whoami")
async def whoami(user_id: str = Depends(get_current_user)):
    """Verify the CLI's token, return user + top-level folder shortlist so
    the interactive picker can render immediately after login."""
    sb = get_supabase()
    folders = (
        sb.table("folders").select("id, name, kind, parent_id")
        .eq("user_id", user_id).is_("parent_id", "null")
        .order("name").execute().data or []
    )
    return {"user_id": user_id, "root_folders": folders}


@router.get("/auth-config")
async def auth_config():
    """Return the Supabase URL + anon key so the CLI can call the
    Supabase refresh endpoint directly (bypassing the backend for token
    renewal — same pattern as any Supabase client SDK).

    Anon key is safe to expose publicly (by design). No auth required."""
    return {
        "supabase_url": os.environ["SUPABASE_URL"],
        "supabase_anon_key": (
            os.environ.get("SUPABASE_ANON_KEY")
            or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        ),
    }


class TranscriptTurn(BaseModel):
    role: str  # 'user' | 'assistant'
    content: str
    ts: str | None = None  # optional ISO timestamp


class SessionCaptureRequest(BaseModel):
    folder_id: str
    session_id: str
    transcript_delta: list[TranscriptTurn] = Field(..., min_length=1, max_length=200)
    cwd: str | None = None


# In-memory rate limiter keyed on (user_id, folder_id). The Stop hook
# is designed to fire at most every ~2 min under normal use; anything
# faster than that is a misconfigured client or a runaway loop. We cap
# at 6 requests per 10 minutes per folder — generous headroom over the
# CLI's own 5-turn/10-min debounce.
_CAPTURE_RATE_LIMIT_MAX = 6
_CAPTURE_RATE_LIMIT_WINDOW_S = 600
_capture_window: dict[tuple[str, str], list[float]] = {}


def _capture_rate_limit(user_id: str, folder_id: str) -> tuple[bool, int]:
    """Returns (allowed, retry_after_s). Prunes old entries as it goes."""
    import time as _time

    key = (user_id, folder_id)
    now = _time.time()
    window_start = now - _CAPTURE_RATE_LIMIT_WINDOW_S
    hits = [t for t in _capture_window.get(key, []) if t > window_start]
    if len(hits) >= _CAPTURE_RATE_LIMIT_MAX:
        retry = int(hits[0] + _CAPTURE_RATE_LIMIT_WINDOW_S - now) + 1
        _capture_window[key] = hits
        return (False, max(1, retry))
    hits.append(now)
    _capture_window[key] = hits
    return (True, 0)


@router.post("/session-capture")
async def session_capture(body: SessionCaptureRequest, request: Request):
    """Called by the CLI's `capture` subcommand (which runs as a
    Claude Code Stop hook every N turns / 10 minutes).

    Authenticated by api key (not user session) — the CLI uses the same
    scoped api key that .mcp.json holds. The folder_id must be inside
    the api key's scope subtree.

    Behavior:
        1. Verify api key + scope containment.
        2. Ensure the target folder has Mem0 wired (repo folders only).
           If not, return a 200 with skipped=true so the hook doesn't
           annoy the user.
        3. Ask Haiku to distill the transcript delta into 1-3 memory
           entries with the right category (preference / finding /
           decision / session).
        4. Save each via the existing Mem0 add path with hard dedup.
    """
    import hashlib
    from fastapi import HTTPException as HE

    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer rag_"):
        raise HE(status_code=401, detail="Bearer api key required")
    key = auth[len("Bearer "):]
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    sb = get_supabase()
    row = (
        sb.table("api_keys").select("user_id, scope_folder_id")
        .eq("key_hash", key_hash).limit(1).execute().data
    )
    if not row or not row[0].get("scope_folder_id"):
        raise HE(status_code=401, detail="Invalid or unscoped api key")
    user_id = row[0]["user_id"]
    scope_id = row[0]["scope_folder_id"]

    # Verify folder is inside scope
    from mcp_server import _descendant_folder_ids  # existing helper
    subtree = _descendant_folder_ids(sb, scope_id, user_id)
    if body.folder_id not in subtree:
        raise HE(status_code=403, detail="folder_id not in api key scope")

    # Rate limit AFTER auth so unauthenticated hammering shows as 401,
    # not 429 (giving less info to attackers). Legitimate hooks that
    # somehow fire too fast get a friendly 429 with Retry-After.
    allowed, retry = _capture_rate_limit(user_id, body.folder_id)
    if not allowed:
        raise HE(
            status_code=429,
            detail=(
                f"Capture rate limit exceeded — {_CAPTURE_RATE_LIMIT_MAX} "
                f"per {_CAPTURE_RATE_LIMIT_WINDOW_S // 60}min per folder. "
                f"Retry in {retry}s."
            ),
            headers={"Retry-After": str(retry)},
        )

    # Mem0 wired?
    from services.mem0_sync import get_client_for_folder
    from services.mem0_sync.client import MemoryScope
    mem0 = get_client_for_folder(sb, body.folder_id, user_id)
    if mem0 is None:
        return {"ok": True, "skipped": True, "reason": "Mem0 not wired for this folder"}

    # Distill via Haiku with a focused tool schema
    from services.llm import Task, complete

    transcript_text = "\n\n".join(
        f"[{t.role}]{' ' + t.ts if t.ts else ''}\n{t.content[:2000]}"
        for t in body.transcript_delta
    )
    if len(transcript_text) > 30_000:
        transcript_text = transcript_text[:30_000] + "\n\n… (truncated)"

    DISTILL_TOOL = {
        "name": "emit_memories",
        "description": "Emit 0-3 memory entries worth persisting from this transcript slice.",
        "input_schema": {
            "type": "object",
            "required": ["memories"],
            "properties": {
                "memories": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "required": ["category", "content"],
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["preference", "finding", "decision", "issue", "session"],
                                "description": (
                                    "preference: an eternal rule the user stated. "
                                    "finding: a concrete fact discovered during work. "
                                    "decision: an architectural or design choice made. "
                                    "issue: a bug or gotcha surfaced. "
                                    "session: a compact summary of what was done."
                                ),
                            },
                            "content": {
                                "type": "string",
                                "description": (
                                    "Concise standalone statement. Third-person is fine. "
                                    "Prefer specifics over generalities. Skip if nothing "
                                    "worth saving — an empty array is a valid answer."
                                ),
                            },
                        },
                    },
                },
            },
        },
    }
    DISTILL_SYSTEM = (
        "You are watching a coding session in Claude Code and deciding what "
        "is worth persisting to a long-term memory system.\n\n"
        "Rules:\n"
        "- Emit ONLY memories that will be useful in FUTURE sessions or on "
        "different PCs. A one-off debugging step is NOT worth saving.\n"
        "- If the user stated a preference (\"always X\", \"never Y\"), "
        "emit category='preference'.\n"
        "- If a concrete fact about the codebase was discovered or "
        "confirmed, emit category='finding'.\n"
        "- If an architectural decision was reached, emit category='decision'.\n"
        "- If a bug/gotcha was surfaced, emit category='issue'.\n"
        "- If the session did substantive shipped work, emit ONE "
        "category='session' summary (\"date: what was built + outcome\").\n"
        "- Emit 0 memories if there is nothing worth saving. Don't pad.\n"
        "- Max 3 memories per capture. Pick the most valuable ones.\n"
        "- Never emit code snippets — reference paths and describe the "
        "change instead."
    )
    msg = complete(
        task=Task.RAG_AGENT,
        system=DISTILL_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Session id: {body.session_id}\n"
                f"cwd: {body.cwd or '(unknown)'}\n"
                f"Turns since last capture: {len(body.transcript_delta)}\n\n"
                f"Transcript delta:\n\n{transcript_text}"
            ),
        }],
        tools=[DISTILL_TOOL],
        max_tokens=800,
    )
    memories: list[dict] = []
    for block in msg.content:
        if block.type == "tool_use" and block.name == "emit_memories":
            memories = list(block.input.get("memories") or [])
            break

    if not memories:
        return {"ok": True, "skipped": True, "reason": "Nothing worth saving in this delta."}

    # Save each via existing Mem0 add path
    saved: list[dict] = []
    for m in memories:
        cat = m.get("category")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        try:
            result = mem0.add(
                content=content,
                category=cat,
                scope=(MemoryScope.ETERNAL if cat == "preference" else MemoryScope.EPISODIC),
                tags=[f"session:{body.session_id[:8]}", "source:cli_capture"],
            )
            saved.append({"category": cat, "content": content, "raw": result})
        except Exception as exc:  # noqa: BLE001
            saved.append({
                "category": cat,
                "content": content,
                "error": str(exc)[:200],
            })

    return {"ok": True, "count": len(saved), "memories": saved}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    folder_id: str | None = None  # narrow to this subtree; default = key's scope
    limit: int = Field(default=5, ge=1, le=25)


@router.post("/search")
async def search(body: SearchRequest, request: Request):
    """Knowledge-base search from the CLI. Api-key auth. Uses the same
    fanout_search backend that MCP knowledge_base_search uses — docs +
    Mem0 in one call — so terminal results match what Claude Code
    would see for the same query.
    """
    import hashlib
    from fastapi import HTTPException as HE

    from mcp_server import _descendant_folder_ids
    from services.embeddings import embed_query
    from services.mem0_sync.fanout import fanout_search

    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer rag_"):
        raise HE(status_code=401, detail="Bearer api key required")
    key = auth[len("Bearer "):]
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    sb = get_supabase()
    row = (
        sb.table("api_keys").select("user_id, scope_folder_id")
        .eq("key_hash", key_hash).limit(1).execute().data
    )
    if not row or not row[0].get("scope_folder_id"):
        raise HE(status_code=401, detail="Invalid or unscoped api key")
    user_id = row[0]["user_id"]
    scope_id = row[0]["scope_folder_id"]

    # Narrow to sub-folder if requested; ensure it's inside scope
    target = body.folder_id or scope_id
    subtree = _descendant_folder_ids(sb, scope_id, user_id)
    if target not in subtree:
        raise HE(
            status_code=403,
            detail=f"folder_id {target!r} not in api-key scope",
        )

    # Embed + fanout
    embedding = embed_query(body.query)
    result = await fanout_search(
        sb,
        embedding=embedding,
        query_text=body.query,
        user_id=user_id,
        folder_id=target,
        limit=body.limit,
        channel="cli",
    )
    hits = []
    for h in result.hits[: body.limit]:
        md = h.metadata or {}
        hits.append({
            "source": h.source,
            "content": (h.content or "")[:1200],
            "similarity": h.score if h.score is not None else 0.0,
            "filename": md.get("source_filename"),
            "category": md.get("category"),
            "created_at": md.get("created_at"),
        })
    return {
        "query": body.query,
        "folder_id": target,
        "hits": hits,
    }


@router.get("/scope-info")
async def scope_info(request: Request):
    """Compact scope summary for the SessionStart hook — auth via the
    scoped api key (not the user session). Returns the api key's scope
    folder + a flat list of descendants so the hook can print a
    Claude-Code-ready context block."""
    import hashlib

    from fastapi import HTTPException as HE

    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer rag_"):
        raise HE(status_code=401, detail="Bearer api key required")
    key = auth[len("Bearer "):]
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    sb = get_supabase()
    row = (
        sb.table("api_keys")
        .select("user_id, scope_folder_id")
        .eq("key_hash", key_hash).limit(1).execute().data
    )
    if not row or not row[0].get("scope_folder_id"):
        raise HE(status_code=401, detail="Invalid or unscoped api key")
    scope_id = row[0]["scope_folder_id"]
    user_id = row[0]["user_id"]

    scope_row = (
        sb.table("folders").select("id, name")
        .eq("id", scope_id).eq("user_id", user_id).limit(1).execute().data
    )
    scope_name = scope_row[0]["name"] if scope_row else "(scope)"

    # BFS the subtree
    subtree = [scope_id]
    frontier = [scope_id]
    while frontier:
        r = (
            sb.table("folders").select("id")
            .in_("parent_id", frontier).eq("user_id", user_id).execute()
            .data or []
        )
        next_ids = [x["id"] for x in r]
        if not next_ids:
            break
        subtree.extend(next_ids)
        frontier = next_ids
    rows = (
        sb.table("folders").select("id, name, kind, parent_id")
        .in_("id", subtree).eq("user_id", user_id).execute()
        .data or []
    )
    by_id = {r["id"]: r for r in rows}
    def path(fid: str) -> str:
        parts: list[str] = []
        cur: str | None = fid
        for _ in range(30):
            if not cur or cur not in by_id:
                break
            parts.append(by_id[cur]["name"])
            cur = by_id[cur].get("parent_id")
        return "/".join(reversed(parts))

    summaries = (
        sb.table("folder_summaries").select("folder_id")
        .in_("folder_id", subtree).eq("user_id", user_id).execute()
        .data or []
    )
    summarized = {r["folder_id"] for r in summaries}
    return {
        "scope_name": scope_name,
        "folders": sorted(
            [
                {
                    "id": r["id"], "name": r["name"],
                    "kind": r.get("kind") or "folder",
                    "path": path(r["id"]),
                    "has_summary": r["id"] in summarized,
                }
                for r in rows
            ],
            key=lambda x: x["path"],
        ),
    }


# ---------------------------------------------------------------------------
# Folder summary endpoint
# ---------------------------------------------------------------------------

SUMMARY_TTL_DAYS = 7
DOC_TTL_DAYS = 30
STABLE_SECTION_ORDER = [
    "overview", "architecture", "preferences", "important_files",
    "how_it_runs", "deployment", "dependencies",
]


def _parse_iso(ts: str) -> datetime | None:
    """Parse a Postgres/ISO timestamp robustly. Postgres emits fractional
    seconds with any digit count (e.g. '.4716'), but Python 3.10's
    fromisoformat only accepts exactly 3 or 6 digits — normalize to 6."""
    s = ts.strip().replace("Z", "+00:00")
    if "." in s:
        head, _, tail = s.partition(".")
        i = 0
        while i < len(tail) and tail[i].isdigit():
            i += 1
        frac, rest = tail[:i], tail[i:]
        s = f"{head}.{(frac + '000000')[:6]}{rest}"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _needs_generation(generated_at: str | None, ttl_days: int = SUMMARY_TTL_DAYS) -> bool:
    """True if there's no summary yet or the latest one is older than the TTL."""
    if not generated_at:
        return True
    ts = _parse_iso(generated_at)
    if ts is None:
        return True
    return datetime.now(timezone.utc) - ts > timedelta(days=ttl_days)


def _api_key_scope(request: Request) -> tuple[str, str]:
    """(user_id, scope_folder_id) from the Bearer api key. Mirrors scope-info."""
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer rag_"):
        raise HTTPException(status_code=401, detail="Bearer api key required")
    key_hash = hashlib.sha256(auth[len("Bearer "):].encode()).hexdigest()
    sb = get_supabase()
    row = (
        sb.table("api_keys").select("user_id, scope_folder_id")
        .eq("key_hash", key_hash).limit(1).execute().data
    )
    if not row or not row[0].get("scope_folder_id"):
        raise HTTPException(status_code=401, detail="Invalid or unscoped api key")
    return row[0]["user_id"], row[0]["scope_folder_id"]


def _is_uuid(s: str) -> bool:
    """A folder_id that isn't a well-formed UUID can never match a real folder.
    Guard before it reaches a uuid DB column, where Postgres raises 22P02
    ('invalid input syntax for type uuid') and surfaces as an uncaught 500."""
    import uuid as _uuid
    try:
        _uuid.UUID(str(s))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


@router.get("/folder-summary")
async def folder_summary(request: Request, folder_id: str):
    user_id, _scope = _api_key_scope(request)
    # scope_folder_id unused — ownership is checked against folders.user_id below
    if not _is_uuid(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")
    sb = get_supabase()
    # Ownership check (the api key's user must own the folder).
    owns = (
        sb.table("folders").select("id")
        .eq("id", folder_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not owns:
        raise HTTPException(status_code=404, detail="Folder not found")
    latest = (
        sb.table("folder_summaries")
        .select("content, generated_at")
        .eq("folder_id", folder_id).eq("user_id", user_id)
        .order("generated_at", desc=True).limit(1).execute().data
    )
    generated_at = latest[0]["generated_at"] if latest else None
    sections = (latest[0]["content"] or {}).get("sections") if latest else None

    # Detailed-doc staleness (30-day clock, independent of the concise 7-day).
    # Defensive: if the repo_documentation table isn't migrated yet, treat the
    # doc as needing generation rather than 500-ing the hook.
    doc_generated_at = None
    try:
        doc_row = (
            sb.table("repo_documentation")
            .select("generated_at")
            .eq("folder_id", folder_id).eq("user_id", user_id)
            .order("generated_at", desc=True).limit(1).execute().data
        )
        doc_generated_at = doc_row[0]["generated_at"] if doc_row else None
    except Exception:  # noqa: BLE001 — table may not exist pre-migration
        doc_generated_at = None

    return {
        "folder_id": folder_id,
        "needs_generation": _needs_generation(generated_at),
        "generated_at": generated_at,
        "sections": sections,
        "section_order": STABLE_SECTION_ORDER,
        "doc_needs_generation": _needs_generation(doc_generated_at, ttl_days=DOC_TTL_DAYS),
        "doc_generated_at": doc_generated_at,
    }
