"""Durable, tenant-scoped citations and exact model-visible tool artifacts."""

import hashlib
import json
from uuid import uuid4

from db.client import get_supabase_thread_safe
from services.citations import CitationRegistry


class DurableCitations:
    def __init__(self, job_id: str, attempt_id: str, owner_id: str):
        self.job_id, self.attempt_id, self.owner_id = job_id, attempt_id, owner_id

    def register(self, result: dict) -> int:
        metadata = result.get("metadata") or {}
        registry = CitationRegistry()
        registry.register(result)
        source = registry.entries()[0]
        # Opaque identity includes tenant, folder/repo and immutable revision when available.
        identity = [
            self.owner_id,
            metadata.get("folder_id"),
            metadata.get("repository_id"),
            metadata.get("document_id") or metadata.get("source_id"),
            source.get("file") or metadata.get("source_filename"),
            metadata.get("revision_id"),
            metadata.get("indexed_head") or metadata.get("head_sha"),
        ]
        key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        source["source_id"] = key
        source["revision_id"] = metadata.get("revision_id")
        source["indexed_head"] = metadata.get("indexed_head") or metadata.get("head_sha")
        number = (
            get_supabase_thread_safe()
            .rpc(
                "tsukai_register_citation",
                {
                    "p_job_id": self.job_id,
                    "p_attempt_id": self.attempt_id,
                    "p_source_key": key,
                    "p_source": source,
                },
            )
            .execute()
            .data
        )
        return int(number)


def sources_for(job_id: str, attempt_id: str | None = None) -> list[dict]:
    query = get_supabase_thread_safe().table("tsukai_citation_sources").select("number,source")
    query = query.eq("job_id", job_id)
    if attempt_id:
        query = query.eq("attempt_id", attempt_id)
    rows = query.order("number").execute().data or []
    return [{**row["source"], "number": row["number"]} for row in rows]


def save_trace(
    owner_id: str, job_id: str, attempt_id: str, folder_ids: list[str], trace: dict, result: str
) -> str:
    trace_id = str(uuid4())
    get_supabase_thread_safe().table("tsukai_tool_traces").insert(
        {
            "id": trace_id,
            "owner_id": owner_id,
            "job_id": job_id,
            "attempt_id": attempt_id,
            "folder_ids": folder_ids,
            "trace": trace,
            "result": result,
        }
    ).execute()
    return trace_id


def scope_locations(owner_id: str, folder_ids: list[str]) -> dict:
    rows = (
        get_supabase_thread_safe()
        .table("folders")
        .select("id,name,parent_id")
        .eq("user_id", owner_id)
        .execute()
        .data
        or []
    )
    by_id = {row["id"]: row for row in rows}
    paths = {}
    for folder in folder_ids:
        parts, seen, cursor = [], set(), folder
        while cursor in by_id and cursor not in seen:
            seen.add(cursor)
            row = by_id[cursor]
            parts.insert(0, row["name"])
            cursor = row.get("parent_id")
        paths[folder] = parts
    return {"user_id": owner_id, "folder_ids": folder_ids, "breadcrumbs": paths}
