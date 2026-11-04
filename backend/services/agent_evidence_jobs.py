"""Durable database-backed evidence maintenance on the existing arq worker."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from db.client import get_supabase_thread_safe
from services.agent_evidence import EvidenceStore, enabled, rpc
from services.agent_evidence_models import BUCKET, PARSER_VERSION, canonical
from services.agent_evidence_parser import iter_segment
from services.agent_evidence_purge import purge_evidence_outbox

log = logging.getLogger(__name__)


def process_session(sb, session):
    store = EvidenceStore(sb, session["user_id"], session["folder_id"])
    s = store.session(session["id"])
    pending = (
        store._query("agent_evidence_objects")
        .eq("session_id", s["id"])
        .not_.is_("committed_revision", "null")
        .eq("kind", "segment")
        .lt("indexed_parser_version", PARSER_VERSION)
        .limit(256)
        .execute()
        .data
    )
    for obj in sorted(
        pending, key=lambda o: (o["stream_id"], o["generation"], o["descriptor"]["first_record"])
    ):
        descriptor = obj["descriptor"]
        state = {}
        if descriptor["first_record"] > 1:
            previous = (
                store._query("agent_evidence_objects")
                .eq("session_id", s["id"])
                .eq("stream_id", obj["stream_id"])
                .eq("generation", obj["generation"])
                .eq("descriptor->>last_record", str(descriptor["first_record"] - 1))
                .gte("indexed_parser_version", PARSER_VERSION)
                .limit(1)
                .execute()
                .data
            )
            if not previous:
                continue
            state = dict(previous[0].get("parser_state") or {})
        raw = store.download(obj)
        events = []
        for event in iter_segment(raw, descriptor, s, state):
            events.append(event)
            if len(events) >= 1000:
                rpc(
                    sb,
                    "publish_agent_evidence_index",
                    {
                        "p_session_id": s["id"],
                        "p_object_id": obj["object_id"],
                        "p_events": events,
                        "p_state": {},
                        "p_parser_version": PARSER_VERSION,
                        "p_complete": False,
                    },
                )
                events = []
        rpc(
            sb,
            "publish_agent_evidence_index",
            {
                "p_session_id": s["id"],
                "p_object_id": obj["object_id"],
                "p_events": events,
                "p_state": state,
                "p_parser_version": PARSER_VERSION,
                "p_complete": True,
            },
        )
    # SQL is canonical. Recheck after Storage writes to repair a newer revision
    # that won the race while this worker materialized the previous snapshot.
    for _ in range(3):
        latest = store.session(s["id"])
        if latest["materialized_revision"] == latest["manifest_revision"]:
            # Verify the small current head before skipping, repairing stale writers.
            try:
                if sb.storage.from_(BUCKET).download(
                    store.prefix(latest) + "/manifest.json"
                ) == canonical(latest["manifest_json"]):
                    break
            except Exception:
                pass
        payload = canonical(latest["manifest_json"])
        path = store.prefix(latest) + "/manifest.json"
        bucket = sb.storage.from_(BUCKET)
        bucket.upload(path, payload, {"content-type": "application/json", "upsert": "true"})
        current = store.session(s["id"])
        if current["manifest_revision"] == latest["manifest_revision"]:
            sb.table("agent_evidence_sessions").update(
                {"materialized_revision": latest["manifest_revision"]}
            ).eq("id", s["id"]).eq("user_id", s["user_id"]).eq(
                "manifest_revision", latest["manifest_revision"]
            ).execute()
            break


def purge_session(sb, s):
    store = EvidenceStore(sb, s["user_id"], s["folder_id"])
    rows = (
        store._query("agent_evidence_objects").eq("session_id", s["id"]).limit(1000).execute().data
    )
    paths = [row["storage_path"] for row in rows if row.get("storage_path")]
    # Parent tombstones retain native identities, including empty metadata-only archives.
    paths.append(store.prefix(s, deleted=True) + "/manifest.json")
    for start in range(0, len(paths), 1000):
        sb.storage.from_(BUCKET).remove(paths[start : start + 1000])
    if len(rows) >= 1000:
        # Delete metadata only for purged objects so the next pass advances.
        sb.table("agent_evidence_objects").delete().eq("session_id", s["id"]).eq(
            "user_id", s["user_id"]
        ).in_("object_id", [row["object_id"] for row in rows]).execute()
        return
    sb.table("agent_evidence_objects").delete().eq("session_id", s["id"]).eq(
        "user_id", s["user_id"]
    ).execute()
    sb.table("agent_evidence_sessions").update(
        {
            "purged_at": datetime.now(timezone.utc).isoformat(),
            "manifest_json": {},
            "gaps": [],
            "producer_gaps": {},
        }
    ).eq("id", s["id"]).eq("user_id", s["user_id"]).execute()


def purge_tombstoned_sessions(sb):
    sessions = (
        sb.table("agent_evidence_sessions")
        .select("*")
        .not_.is_("deleted_at", "null")
        .is_("purged_at", "null")
        .order("deleted_at")
        .limit(25)
        .execute()
        .data
    )
    for session in sessions:
        try:
            purge_session(sb, session)
        except Exception as exc:
            log.warning("evidence session purge retry code=%s", type(exc).__name__)


def reap_evidence(sb, after_id=None):
    """A bounded sweep repairs enqueue loss AND stale materialized Storage heads."""
    q = sb.table("agent_evidence_sessions").select("*").order("id")
    if after_id:
        q = q.gt("id", after_id)
    sessions = q.limit(25).execute().data
    for s in sessions:
        try:
            if s.get("deleted_at"):
                if not s.get("purged_at"):
                    purge_session(sb, s)
            elif s["manifest_revision"] > 0:
                process_session(sb, s)
        except Exception as exc:
            # No provider message/SQL inputs or original body in operational logs.
            log.warning(
                "evidence maintenance failed session=%s code=%s", s["id"], type(exc).__name__
            )
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    expired = (
        sb.table("agent_evidence_batches")
        .select("*")
        .in_("state", ["staged", "expired"])
        .lt("created_at", cutoff)
        .limit(25)
        .execute()
        .data
    )
    for batch in expired:
        try:
            paths = rpc(sb, "expire_agent_evidence_batch", {"p_batch_row_id": batch["id"]})
            if paths:
                sb.storage.from_(BUCKET).remove(paths)
            sb.table("agent_evidence_batches").update(
                {"cleanup_paths": [], "state": "expired_clean"}
            ).eq("id", batch["id"]).execute()
        except Exception as exc:
            log.warning("evidence staging cleanup failed code=%s", type(exc).__name__)
    return sessions[-1]["id"] if len(sessions) == 25 else None


async def agent_evidence_maintenance(ctx):
    # A disabled capture feature must not disable account/folder erasure.
    await asyncio.to_thread(purge_evidence_outbox, get_supabase_thread_safe())
    await asyncio.to_thread(purge_tombstoned_sessions, get_supabase_thread_safe())
    if not enabled():
        return
    ctx["evidence_cursor"] = await asyncio.to_thread(
        reap_evidence, get_supabase_thread_safe(), ctx.get("evidence_cursor")
    )
