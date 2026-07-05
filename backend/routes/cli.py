"""CLI login endpoints.

The CLI needs to authenticate as the user without shipping the Supabase
anon key. We wrap Supabase's magic-link OTP flow behind two endpoints:

    POST /api/cli/otp/send    — trigger the OTP email
    POST /api/cli/otp/verify  — exchange OTP for tokens

The CLI stores the returned access_token + refresh_token locally and
uses them via `Authorization: Bearer <access>` on subsequent calls.
Refresh happens client-side using Supabase's refresh_token endpoint
(exposed at the standard /auth/v1/token endpoint) — no new backend
surface needed for that.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from supabase import create_client

from auth import get_current_user
from db.client import get_supabase

router = APIRouter(prefix="/api/cli")


def _anon_client():
    """Anon-key Supabase client — the flow is user-initiated so the
    permissions of an anon key are appropriate (magic-link, verify OTP)."""
    url = os.environ["SUPABASE_URL"]
    # Anon key: read from env; prefer SUPABASE_ANON_KEY if set, fall back to
    # the publishable key format some setups use.
    key = os.environ.get("SUPABASE_ANON_KEY") \
        or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    if not key:
        raise HTTPException(
            status_code=500,
            detail=(
                "SUPABASE_ANON_KEY is not configured server-side. "
                "The CLI login flow needs it. Add it to backend/.env."
            ),
        )
    return create_client(url, key)


class SendOtpRequest(BaseModel):
    email: EmailStr


@router.post("/otp/send")
async def send_otp(body: SendOtpRequest):
    """Trigger Supabase magic-link email. Returns 200 whether or not the
    email exists (Supabase behavior — prevents enumeration)."""
    anon = _anon_client()
    try:
        anon.auth.sign_in_with_otp({"email": body.email})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Send OTP failed: {exc}")
    return {"ok": True, "email": body.email}


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    token: str = Field(min_length=6, max_length=10)


@router.post("/otp/verify")
async def verify_otp(body: VerifyOtpRequest):
    """Exchange OTP for a session. Returns access + refresh tokens
    plus the user id/email so the CLI can store + display them."""
    anon = _anon_client()
    try:
        res = anon.auth.verify_otp({
            "email": body.email,
            "token": body.token,
            "type": "email",
        })
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired code: {exc}",
        )
    if not res.session or not res.user:
        raise HTTPException(status_code=401, detail="OTP verification failed")
    return {
        "access_token": res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "expires_at": res.session.expires_at,
        "user": {
            "id": res.user.id,
            "email": res.user.email,
        },
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
                "agentic-rag": {
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
    import json as _json
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

    # Mem0 wired?
    from services.mem0_sync import MemoryCategory, get_client_for_folder
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
