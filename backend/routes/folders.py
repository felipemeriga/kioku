"""Folder CRUD + summary endpoints for organizing documents."""

import os
import re

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import get_current_user
from db.client import get_supabase
from services.folder_summary.repo import (
    get_folder,
    get_latest_summary,
    get_summary_history,
)

router = APIRouter(prefix="/api/folders")


# Shared UUID guard — Postgres raises 22P02 on non-UUID input, which
# bubbles as a 500. All path-param IDs go through this first so
# nonsense hits a 404 instead of leaking a DB error.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _require_uuid(folder_id: str) -> None:
    if not _UUID_RE.match(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


class CreateFolderRequest(BaseModel):
    name: str
    parent_id: str | None = None


class RenameFolderRequest(BaseModel):
    name: str | None = None
    kind: str | None = None  # 'folder' | 'repo' — omit to leave unchanged


@router.get("")
async def list_folders(
    parent_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """List folders for a given parent (or root if parent_id is None)."""
    sb = get_supabase()
    query = sb.table("folders").select("*").eq("user_id", user_id)

    if parent_id:
        query = query.eq("parent_id", parent_id)
    else:
        query = query.is_("parent_id", "null")

    result = query.order("name").execute()
    return result.data


def _validate_folder_name(name: str) -> str:
    """Return a sanitized name or raise HTTPException(400).

    Rejects:
      - empty / whitespace-only
      - purely '.' or '..' (would confuse breadcrumbs)
      - control characters (would break the UI + the search index)
      - > 120 chars (protect against absurd inputs, DB has room but the
        sidebar tree ellipsis breaks earlier)
    """
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Folder name cannot be empty")
    trimmed = name.strip()
    if trimmed in (".", ".."):
        raise HTTPException(status_code=400, detail="Folder name cannot be '.' or '..'")
    if any(ord(ch) < 32 for ch in trimmed):
        raise HTTPException(status_code=400, detail="Folder name contains control characters")
    if len(trimmed) > 120:
        raise HTTPException(status_code=400, detail="Folder name is too long (max 120 chars)")
    return trimmed


def _check_unique_sibling(
    sb, *, name: str, parent_id: str | None, user_id: str, excluding_id: str | None = None
) -> None:
    """Raise 409 if a folder with the same name already exists under the same
    parent (case-sensitive match, matching whatever the user typed)."""
    q = (
        sb.table("folders").select("id")
        .eq("user_id", user_id).eq("name", name)
    )
    if parent_id is None:
        q = q.is_("parent_id", "null")
    else:
        q = q.eq("parent_id", parent_id)
    hits = q.execute().data or []
    if excluding_id:
        hits = [h for h in hits if h["id"] != excluding_id]
    if hits:
        scope = "root" if parent_id is None else "this parent"
        raise HTTPException(
            status_code=409,
            detail=f"A folder named '{name}' already exists at {scope}.",
        )


@router.post("")
async def create_folder(
    body: CreateFolderRequest,
    user_id: str = Depends(get_current_user),
):
    """Create a new folder."""
    name = _validate_folder_name(body.name)
    sb = get_supabase()

    # Wrap everything that talks to Postgrest — the upstream WAF may
    # reject weird payloads (SQL-looking names, malformed data) with a
    # 403 HTML page. We convert those into a clean 400 so the client
    # can retry with a different name instead of seeing a raw stack.
    try:
        # Verify parent folder belongs to user if specified
        if body.parent_id:
            parent = (
                sb.table("folders")
                .select("id")
                .eq("id", body.parent_id)
                .eq("user_id", user_id)
                .execute()
            )
            if not parent.data:
                raise HTTPException(status_code=404, detail="Parent folder not found")

        _check_unique_sibling(
            sb, name=name, parent_id=body.parent_id, user_id=user_id
        )

        result = (
            sb.table("folders")
            .insert(
                {
                    "name": name,
                    "parent_id": body.parent_id,
                    "user_id": user_id,
                }
            )
            .execute()
        )
    except HTTPException:
        # Preserve intentional HTTPExceptions raised inside the block.
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=(
                "Couldn't create folder — the storage backend rejected the "
                "request. Try a simpler name without shell/SQL characters."
            ),
        )
    return result.data[0]


@router.patch("/{folder_id}")
async def update_folder(
    folder_id: str,
    body: RenameFolderRequest,
    user_id: str = Depends(get_current_user),
):
    """Update a folder — name and/or kind. Both are optional; if body has
    neither, this is a no-op that returns the current row.

    kind='repo' is the CLI's "turn this folder into a repo" affordance —
    it's the same state that GitHub-connect would set, without requiring
    a GitHub binding first."""
    _require_uuid(folder_id)
    sb = get_supabase()
    updates: dict = {}

    if body.name is not None:
        name = _validate_folder_name(body.name)
        existing = (
            sb.table("folders").select("parent_id")
            .eq("id", folder_id).eq("user_id", user_id)
            .limit(1).execute().data
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Folder not found")
        _check_unique_sibling(
            sb, name=name, parent_id=existing[0].get("parent_id"),
            user_id=user_id, excluding_id=folder_id,
        )
        updates["name"] = name

    if body.kind is not None:
        if body.kind not in ("folder", "repo"):
            raise HTTPException(
                status_code=400,
                detail="kind must be 'folder' or 'repo'",
            )
        updates["kind"] = body.kind

    if not updates:
        row = (
            sb.table("folders").select("*")
            .eq("id", folder_id).eq("user_id", user_id).limit(1).execute().data
        )
        if not row:
            raise HTTPException(status_code=404, detail="Folder not found")
        return row[0]

    result = (
        sb.table("folders")
        .update(updates)
        .eq("id", folder_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Folder not found")
    return result.data[0]


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: str,
    delete_docs: bool = False,
    user_id: str = Depends(get_current_user),
):
    """Delete a folder + all subfolders.

    By default documents are DETACHED (folder_id set to null) so uploaded
    files aren't lost — they resurface at "All Documents". Pass
    `delete_docs=true` to also physically delete the docs and their
    original files from Supabase Storage.
    """
    _require_uuid(folder_id)
    sb = get_supabase()
    # Fetch first so we know what to clean up + can return proper 404.
    row = (
        sb.table("folders").select("id, name")
        .eq("id", folder_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")

    docs_deleted = 0
    files_removed = 0
    if delete_docs:
        # Gather ALL docs under this folder subtree BEFORE the cascade sets
        # their folder_id to null (once null we can't identify them by folder).
        descendant_ids = _descendant_folder_ids(sb, folder_id, user_id)
        docs = (
            sb.table("documents").select("id, source_filename, source_type, metadata")
            .eq("user_id", user_id).in_("folder_id", descendant_ids)
            .execute().data
            or []
        )
        docs_deleted = len(docs)
        # Remove originals from storage where applicable.
        by_bucket: dict[str, list[str]] = {}
        for d in docs:
            meta = d.get("metadata") or {}
            path = meta.get("file_url") or meta.get("image_url") or meta.get("audio_url")
            if not path:
                continue
            if meta.get("image_url"):
                bucket = "images"
            elif meta.get("audio_url"):
                bucket = "audio"
            else:
                bucket = "documents"
            by_bucket.setdefault(bucket, []).append(path)
        for bucket, paths in by_bucket.items():
            try:
                sb.storage.from_(bucket).remove(paths)
                files_removed += len(paths)
            except Exception:  # noqa: BLE001 — non-fatal, DB rows still get deleted
                pass
        # Delete doc rows explicitly so the folder cascade doesn't just null
        # them out and leave a bunch of homeless docs at the root.
        if docs:
            ids = [d["id"] for d in docs]
            for i in range(0, len(ids), 100):
                sb.table("documents").delete().in_("id", ids[i:i+100]).execute()

    sb.table("folders").delete().eq("id", folder_id).eq("user_id", user_id).execute()
    return {"ok": True, "docs_deleted": docs_deleted, "files_removed": files_removed}


def _descendant_folder_ids(sb, folder_id: str, user_id: str) -> list[str]:
    """BFS the folder tree — folder + every subfolder id, inclusive."""
    result = [folder_id]
    frontier = [folder_id]
    while frontier:
        r = (
            sb.table("folders").select("id")
            .in_("parent_id", frontier).eq("user_id", user_id).execute().data
        )
        next_ids = [row["id"] for row in (r or [])]
        if not next_ids:
            break
        result.extend(next_ids)
        frontier = next_ids
    return result


class RegenerateSummaryRequest(BaseModel):
    # Body is intentionally empty — the endpoint is idempotent and the
    # task decides internally whether to regen or skip based on content
    # hashes. `force` bypasses the skip check (used by 'Rebuild anyway'
    # buttons or when the user knows better than the diff).
    force: bool = False


@router.get("/{folder_id}/summary")
async def get_folder_summary(
    folder_id: str,
    user_id: str = Depends(get_current_user),
):
    """Latest folder summary + minimal metadata for the panel."""
    _require_uuid(folder_id)
    sb = get_supabase()
    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    latest = get_latest_summary(sb, folder_id, user_id)

    # For container / workspace-rollup summaries, hand the frontend the
    # structured subfolder index so the Folder Detail page can render the
    # workspace grid without a second round-trip.
    subfolders_index = None
    if latest and latest.get("kind") == "workspace_rollup":
        try:
            from services.folder_summary.rollup import (
                build_workspace_orientation_payload,
            )
            subfolders_index = build_workspace_orientation_payload(
                sb, folder_id=folder_id, user_id=user_id, latest_row=latest,
            )["subfolders"]
        except Exception:  # noqa: BLE001
            pass

    return {
        "folder": folder,
        "summary": latest,
        "subfolders": subfolders_index,
    }


@router.get("/{folder_id}/summary/history")
async def get_folder_summary_history(
    folder_id: str,
    # Bound the limit — an unbounded negative value reaches Postgres as
    # `LIMIT -1` and raises, surfacing as an uncaught 500.
    limit: int = Query(default=10, ge=1, le=100),
    user_id: str = Depends(get_current_user),
):
    _require_uuid(folder_id)
    sb = get_supabase()
    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return get_summary_history(sb, folder_id, user_id, limit=limit)


@router.post("/{folder_id}/summary/regenerate")
async def regenerate_folder_summary(
    folder_id: str,
    body: RegenerateSummaryRequest,
    user_id: str = Depends(get_current_user),
):
    """Enqueue a summarize_folder_task and return the arq job id.

    Body is optional. `force: true` bypasses the skip-if-unchanged check
    (used by the 'Rebuild anyway' UI). Otherwise the task decides
    internally whether to regen based on content-hash diff.
    """
    _require_uuid(folder_id)

    sb = get_supabase()
    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Repo briefings are authored in-session by the agent via MCP; backend
    # generation no longer applies to repo folders.
    if (folder.get("kind") or "folder") == "repo":
        raise HTTPException(
            status_code=400,
            detail="repo briefings are authored in-session by the agent; nothing to regenerate",
        )

    # `mode` is always "full" from the task's perspective now — either it
    # rebuilds or it skips. `force=True` translates to mode="full" which
    # bypasses the skip check. force=False maps to mode="auto" which lets
    # the task's own diff detection short-circuit if nothing changed.
    task_mode = "full" if body.force else "auto"

    pool = await create_pool(_redis_settings())
    try:
        # Bucketed job_id: dedups clicks within the same 10-second window
        # so hammering Regenerate collapses to one job, but a legitimate
        # re-click after content changes still enqueues.
        import time as _time
        bucket = int(_time.time()) // 10
        job = await pool.enqueue_job(
            "summarize_folder_task",
            {
                "folder_id": folder_id,
                "user_id": user_id,
                "mode": task_mode,
                "trigger": "manual",
            },
            _job_id=f"summarize:{folder_id}:{task_mode}:{bucket}",
        )
    finally:
        await pool.close()

    return {"ok": True, "job_id": job.job_id if job else None, "force": body.force}


@router.get("/{folder_id}/breadcrumbs")
async def get_breadcrumbs(
    folder_id: str,
    user_id: str = Depends(get_current_user),
):
    """Return the breadcrumb path from root to the given folder.

    Malformed UUIDs return [] (200) — this endpoint historically
    behaves like 'best-effort lookup' since it's often called
    speculatively from the frontend to decide whether to render.
    """
    if not _UUID_RE.match(folder_id):
        return []
    sb = get_supabase()
    breadcrumbs = []
    current_id: str | None = folder_id

    while current_id:
        result = (
            sb.table("folders")
            .select("id, name, parent_id")
            .eq("id", current_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            break
        folder = result.data[0]
        breadcrumbs.append({"id": folder["id"], "name": folder["name"]})
        current_id = folder.get("parent_id")

    breadcrumbs.reverse()
    return breadcrumbs
