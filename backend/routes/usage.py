"""Chat token-usage + estimated-cost endpoints for the Settings usage view.

Aggregates the per-turn rows in chat_usage. All queries are scoped to the
authenticated caller (the service-role client bypasses RLS, so the user_id
filter is the real gate)."""

from collections import defaultdict

from fastapi import APIRouter, Depends

from auth import get_current_user
from db.client import get_supabase
from services.pricing import estimate_cost_usd

router = APIRouter(prefix="/api/usage")


@router.get("/conversations")
async def usage_by_conversation(user_id: str = Depends(get_current_user)):
    """Per-conversation token + cost totals, highest cost first."""
    sb = get_supabase()
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
async def usage_by_month(user_id: str = Depends(get_current_user)):
    """Per-month token + cost totals, newest month first."""
    sb = get_supabase()
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
