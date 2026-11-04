"""Retry durable domain deletion intents until the runner confirms sensitive cleanup."""

from datetime import datetime, timedelta, timezone

from db.client import get_supabase_thread_safe
from services.ai.facade import client_for
from services.ai.scope import ExecutionScope


def reconcile_deletions():
    sb = get_supabase_thread_safe()
    rows = (
        sb.table("tsukai_domain_deletions")
        .select("*")
        .in_("state", ["pending", "submitted"])
        .order("created_at")
        .limit(50)
        .execute()
        .data
        or []
    )
    for row in rows:
        operation = "session.delete" if row["kind"] == "conversation" else "account.delete"
        profile = "chat" if row["kind"] == "conversation" else None
        client = client_for(ExecutionScope(row["owner_id"]), operation, profile)
        try:
            tombstone = row.get("tombstone_id")
            if tombstone:
                status = client.deletion_status(tombstone)
            else:
                body = {"owner_id": row["owner_id"], "action": "delete_account"}
                path = "/v1/account/delete"
                if row["kind"] == "conversation":
                    body.update(
                        {"conversation_id": row["conversation_id"], "action": "delete_conversation"}
                    )
                    path = f"/v1/conversations/{row['conversation_id']}/delete"
                status = client.delete_domain(path, body)
                tombstone = status["tombstone_id"]
            sb.table("tsukai_domain_deletions").update(
                {
                    "tombstone_id": tombstone,
                    "state": "cleaned" if status["status"] == "cleaned" else "submitted",
                }
            ).eq("id", row["id"]).execute()
        finally:
            client.close()
    # Full tool artifacts have explicit seven-day availability; source citations
    # and bounded message previews follow their domain conversation retention.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    sb.table("tsukai_tool_traces").delete().lt("created_at", cutoff).execute()
    deleted_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    sb.table("tsukai_domain_deletions").delete().eq("state", "cleaned").lt(
        "created_at", deleted_cutoff
    ).execute()
