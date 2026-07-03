"""CRUD helpers for the `ingestion_jobs` table.

All helpers take a Supabase client as the first arg so they can be used from
either the FastAPI process (for enqueue-time creation and lookups) or the arq
worker process (for progress updates).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def create_job(
    supabase,
    *,
    user_id: str,
    kind: str,
    source_ref: str,
    root_folder_id: str | None = None,
    parent_job_id: str | None = None,
    total_pages: int | None = None,
) -> str:
    """Insert a new job row (status='queued') and return its id."""
    row: dict[str, Any] = {
        "user_id": user_id,
        "kind": kind,
        "source_ref": source_ref,
        "status": "queued",
    }
    if root_folder_id is not None:
        row["root_folder_id"] = root_folder_id
    if parent_job_id is not None:
        row["parent_job_id"] = parent_job_id
    if total_pages is not None:
        row["total_pages"] = total_pages

    inserted = supabase.table("ingestion_jobs").insert(row).execute().data
    return inserted[0]["id"]


def get_active_job(supabase, *, kind: str, source_ref: str) -> dict | None:
    """Return the currently queued/running job for (kind, source_ref) or None."""
    rows = (
        supabase.table("ingestion_jobs")
        .select("*")
        .eq("kind", kind)
        .eq("source_ref", source_ref)
        .in_("status", ["queued", "running"])
        .execute()
        .data
    ) or []
    return rows[0] if rows else None


def mark_running(supabase, *, job_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    (
        supabase.table("ingestion_jobs")
        .update({"status": "running", "started_at": now})
        .eq("id", job_id)
        .execute()
    )


def set_total_batches(supabase, *, job_id: str, total: int) -> None:
    (
        supabase.table("ingestion_jobs")
        .update({"total_batches": total, "current_step": "embedding"})
        .eq("id", job_id)
        .execute()
    )


def set_total_pages(supabase, *, job_id: str, total: int) -> None:
    (
        supabase.table("ingestion_jobs")
        .update({"total_pages": total, "current_step": "ingesting_pages"})
        .eq("id", job_id)
        .execute()
    )


def increment_processed_pages(supabase, *, job_id: str) -> dict:
    row = (
        supabase.table("ingestion_jobs")
        .select("processed_pages,total_pages")
        .eq("id", job_id)
        .single()
        .execute()
        .data
    ) or {"processed_pages": 0, "total_pages": 0}
    new_processed = (row.get("processed_pages") or 0) + 1
    (
        supabase.table("ingestion_jobs")
        .update({"processed_pages": new_processed})
        .eq("id", job_id)
        .execute()
    )
    return {
        "processed_pages": new_processed,
        "total_pages": row.get("total_pages") or 0,
    }


def increment_processed_batches(supabase, *, job_id: str) -> dict:
    """Increment processed_batches; mark completed if we hit total_batches."""
    row = (
        supabase.table("ingestion_jobs")
        .select("processed_batches,total_batches")
        .eq("id", job_id)
        .single()
        .execute()
        .data
    ) or {"processed_batches": 0, "total_batches": 0}
    new_processed = (row.get("processed_batches") or 0) + 1
    total = row.get("total_batches") or 0
    (
        supabase.table("ingestion_jobs")
        .update({"processed_batches": new_processed})
        .eq("id", job_id)
        .execute()
    )
    completed = total > 0 and new_processed >= total
    if completed:
        now = datetime.now(timezone.utc).isoformat()
        (
            supabase.table("ingestion_jobs")
            .update({"status": "completed", "completed_at": now})
            .eq("id", job_id)
            .execute()
        )
    return {"processed_batches": new_processed, "completed": completed}


def mark_failed(supabase, *, job_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    (
        supabase.table("ingestion_jobs")
        .update({"status": "failed", "error": error, "completed_at": now})
        .eq("id", job_id)
        .execute()
    )
