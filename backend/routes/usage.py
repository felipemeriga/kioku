"""Chat token-usage + estimated-cost endpoints for the Settings usage view.

Aggregates the per-turn rows in chat_usage. All queries are scoped to the
authenticated caller (the service-role client bypasses RLS, so the user_id
filter is the real gate)."""

import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from db.client import get_supabase
from services.pricing import estimate_cost_usd

router = APIRouter(prefix="/api/usage")


def _require_usage_admin(sb, user_id: str) -> None:
    user = sb.auth.admin.get_user_by_id(user_id).user
    if not user or (user.email or "").lower() != "felipe.meriga@gmail.com":
        raise HTTPException(status_code=403, detail="Usage administration is restricted")


@router.get("/attribution")
def usage_attribution(
    month: str | None = Query(default=None), user_id: str = Depends(get_current_user)
):
    """Administrator-only, cross-user list-cost ledger for a UTC month."""
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    year, number = map(int, month.split("-"))
    next_month = f"{year + 1}-01" if number == 12 else f"{year}-{number + 1:02d}"
    sb = get_supabase()
    _require_usage_admin(sb, user_id)
    watched = (
        sb.table("watched_repos")
        .select("user_id,folder_id,remote_url,branch,last_sha,last_run_at,last_error")
        .execute()
        .data
        or []
    )
    owners = {}
    for owner_id in {repo["user_id"] for repo in watched}:
        owner = sb.auth.admin.get_user_by_id(owner_id).user
        owners[owner_id] = owner.email if owner else owner_id
    rows = []
    offset = 0
    while True:
        page = (
            sb.table("llm_usage_events")
            .select(
                "user_id,source,operation,folder_id,conversation_id,response_id,round_number,"
                "model,input_tokens,output_tokens,cache_write_5m_tokens,"
                "cache_write_1h_tokens,cache_read_tokens,list_cost_usd,created_at"
            )
            .gte("created_at", f"{month}-01T00:00:00+00:00")
            .lt("created_at", f"{next_month}-01T00:00:00+00:00")
            .order("created_at", desc=True)
            .range(offset, offset + 499)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < 500:
            break
        offset += 500

    for owner_id in {row.get("user_id") for row in rows} - owners.keys() - {None}:
        owner = sb.auth.admin.get_user_by_id(owner_id).user
        owners[owner_id] = owner.email if owner else owner_id
    folder_ids = list({r["folder_id"] for r in rows + watched if r.get("folder_id")})
    conversation_ids = list({r["conversation_id"] for r in rows if r.get("conversation_id")})
    folders = (
        (sb.table("folders").select("id,name").in_("id", folder_ids).execute().data or [])
        if folder_ids
        else []
    )
    conversations = (
        (
            sb.table("conversations").select("id,title").in_("id", conversation_ids).execute().data
            or []
        )
        if conversation_ids
        else []
    )
    folder_names = {r["id"]: r.get("name") or "Untitled repository" for r in folders}
    conversation_names = {r["id"]: r.get("title") or "Untitled" for r in conversations}
    total = Decimal("0")
    by_source: dict[str, Decimal] = defaultdict(Decimal)
    by_folder: dict[str, Decimal] = defaultdict(Decimal)
    by_response: dict[str, dict] = {}
    unpriced = 0
    for row in rows:
        cost = row.get("list_cost_usd")
        if cost is None:
            unpriced += 1
            continue
        amount = Decimal(str(cost))
        total += amount
        by_source[row["source"]] += amount
        if row["source"] == "mihari" and row.get("folder_id"):
            by_folder[row["folder_id"]] += amount
        if row.get("response_id"):
            key = row["response_id"]
            if key not in by_response:
                by_response[key] = {
                    "response_id": key,
                    "owner": owners.get(row.get("user_id"), "Unknown user"),
                    "conversation_id": row.get("conversation_id"),
                    "title": conversation_names.get(row.get("conversation_id"), "Untitled"),
                    "created_at": row["created_at"],
                    "cost_usd": Decimal("0"),
                    "rounds": [],
                    "additional_calls": [],
                }
            by_response[key]["cost_usd"] += amount
            call = {
                "round": row["round_number"],
                "model": row["model"],
                "operation": row["operation"],
                "cost_usd": str(amount),
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_write_tokens": (row["cache_write_5m_tokens"] + row["cache_write_1h_tokens"]),
                "cache_read_tokens": row["cache_read_tokens"],
            }
            bucket = "rounds" if row["round_number"] is not None else "additional_calls"
            by_response[key][bucket].append(call)
    responses = list(by_response.values())
    for response in responses:
        response["cost_usd"] = str(response["cost_usd"])
        response["rounds"].sort(key=lambda r: r["round"] or 0)
    responses.sort(key=lambda r: r["created_at"], reverse=True)
    mihari_calls = [
        {
            "created_at": r["created_at"],
            "operation": r["operation"],
            "owner": owners.get(r.get("user_id"), "Unknown user"),
            "repository": folder_names.get(r.get("folder_id"), "Unknown repository"),
            "model": r["model"],
            "cost_usd": r["list_cost_usd"],
        }
        for r in rows
        if r["source"] == "mihari"
    ]
    native_rows = []
    native_offset = 0
    while True:
        native_page = (
            sb.table("tsukai_native_usage")
            .select("*")
            .gte("created_at", f"{month}-01T00:00:00+00:00")
            .lt("created_at", f"{next_month}-01T00:00:00+00:00")
            .order("created_at", desc=True)
            .range(native_offset, native_offset + 499)
            .execute()
            .data
            or []
        )
        native_rows.extend(native_page)
        if len(native_page) < 500:
            break
        native_offset += 500
    known = [
        Decimal(str(row["list_equivalent_usd"]))
        for row in native_rows
        if row.get("list_equivalent_usd") is not None
    ]
    native = {
        "billing_mode": "subscription",
        "call_count": len(native_rows),
        "known_list_equivalent_usd": str(sum(known, Decimal("0"))) if known else None,
        "incomplete_calls": sum(not row["complete"] for row in native_rows),
        "unpriced_calls": sum(row.get("list_equivalent_usd") is None for row in native_rows),
        "calls": native_rows,
    }
    return {
        "native": native,
        "month": month,
        "total_cost_usd": str(total),
        "unpriced_calls": unpriced,
        "call_count": len(rows),
        "by_source": {key: str(value) for key, value in by_source.items()},
        "by_repository": [
            {
                **repo,
                "name": folder_names.get(repo["folder_id"], repo["remote_url"]),
                "owner": owners.get(repo["user_id"], repo["user_id"]),
                "cost_usd": str(by_folder.get(repo["folder_id"], Decimal("0"))),
            }
            for repo in watched
        ],
        "responses": responses,
        "mihari_calls": mihari_calls,
    }


@router.get("/conversations")
def usage_by_conversation(user_id: str = Depends(get_current_user)):
    """Per-conversation token + cost totals, highest cost first."""
    sb = get_supabase()
    _require_usage_admin(sb, user_id)
    rows = (
        sb.table("chat_usage")
        .select("conversation_id, model, input_tokens, output_tokens")
        .eq("user_id", user_id)
        .execute()
    ).data or []

    agg: dict[str, dict] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )
    for r in rows:
        cid = r["conversation_id"]
        a = agg[cid]
        a["input_tokens"] += r.get("input_tokens") or 0
        a["output_tokens"] += r.get("output_tokens") or 0
        a["cost_usd"] += estimate_cost_usd(
            r.get("model") or "", r.get("input_tokens") or 0, r.get("output_tokens") or 0
        )

    if not agg:
        return []

    titles = (
        sb.table("conversations")
        .select("id, title")
        .eq("user_id", user_id)
        .in_("id", list(agg.keys()))
        .execute()
    ).data or []
    title_by_id = {t["id"]: (t.get("title") or "Untitled") for t in titles}

    result = [
        {
            "conversation_id": cid,
            "title": title_by_id.get(cid, "Untitled"),
            "input_tokens": a["input_tokens"],
            "output_tokens": a["output_tokens"],
            "cost_usd": round(a["cost_usd"], 6),
        }
        for cid, a in agg.items()
    ]
    result.sort(key=lambda x: x["cost_usd"], reverse=True)
    return result


@router.get("/monthly")
def usage_by_month(user_id: str = Depends(get_current_user)):
    """Per-month token + cost totals, newest month first."""
    sb = get_supabase()
    _require_usage_admin(sb, user_id)
    rows = (
        sb.table("chat_usage")
        .select("model, input_tokens, output_tokens, created_at")
        .eq("user_id", user_id)
        .execute()
    ).data or []

    agg: dict[str, dict] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )
    for r in rows:
        month = (r.get("created_at") or "")[:7]  # YYYY-MM
        if not month:
            continue
        a = agg[month]
        a["input_tokens"] += r.get("input_tokens") or 0
        a["output_tokens"] += r.get("output_tokens") or 0
        a["cost_usd"] += estimate_cost_usd(
            r.get("model") or "", r.get("input_tokens") or 0, r.get("output_tokens") or 0
        )

    result = [
        {
            "month": month,
            "input_tokens": a["input_tokens"],
            "output_tokens": a["output_tokens"],
            "cost_usd": round(a["cost_usd"], 6),
        }
        for month, a in agg.items()
    ]
    result.sort(key=lambda x: x["month"], reverse=True)
    return result


@router.get("/native/active-sessions")
def active_native_sessions(user_id: str = Depends(get_current_user)):
    """Private cross-owner runtime telemetry, guarded by current server admin identity."""
    import os

    import httpx

    from services.ai.facade import client_for
    from services.ai.scope import ExecutionScope

    sb = get_supabase()
    _require_usage_admin(sb, user_id)
    if not os.getenv("TSUKAI_URL"):
        return {
            "available": False,
            "sessions": [],
            "queued_counts": {},
            "reason": "Tsukai is not configured",
        }
    client = client_for(ExecutionScope(user_id, admin=True), "runtime.sessions.read", None)
    try:
        result = client.active_sessions()
    except (httpx.HTTPError, RuntimeError):
        raise HTTPException(503, "Tsukai runtime telemetry is unavailable") from None
    finally:
        client.close()
    sessions = result.get("sessions") or []
    owners = {}
    for owner_id in {session["owner_id"] for session in sessions}:
        account = sb.auth.admin.get_user_by_id(owner_id).user
        owners[owner_id] = account.email if account else owner_id
    for session in sessions:
        session["owner_label"] = owners.get(session["owner_id"], session["owner_id"])
    return {**result, "available": True}
