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
