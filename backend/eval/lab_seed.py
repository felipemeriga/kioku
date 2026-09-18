"""Seed (and tear down) the kioku eval-lab corpus through the REAL pipeline.

Creates a dedicated root folder 'kioku-eval-lab', uploads every file under
eval/lab_corpus/ to Storage, and enqueues the same ingest_document_task the
web upload uses — so the lab docs are chunked, embedded, and searchable
exactly like production content. This is a persistent fixture: seed once,
run eval/edge_lab.py against it repeatedly.

The corpus is adversarial by design (see eval/edge_lab.py for what each file
probes): polysemy distractors, a doc that contradicts real code, superseded
vs current versions of the same fact, a cross-lingual duplicate, pseudo-code
that must lose to real code, and a buried single-sentence answer.

Run inside the backend environment / container:
    python -m eval.lab_seed <user_id>            # seed + wait for ingestion
    python -m eval.lab_seed <user_id> --teardown # delete folder + docs

Idempotent: re-seeding removes prior lab docs first (content-hash dedup would
otherwise skip re-upload).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from arq import create_pool

from db.client import get_supabase
from services.ingestion import (
    compute_content_hash,
    upload_document_to_storage,
)
from services.queue.jobs import create_job
from services.queue.settings import _redis_settings

LAB_ROOT_NAME = "kioku-eval-lab"
CORPUS_DIR = Path(__file__).parent / "lab_corpus"


def _get_or_create_root(sb, user_id: str) -> str:
    existing = (
        sb.table("folders")
        .select("id")
        .eq("user_id", user_id)
        .eq("name", LAB_ROOT_NAME)
        .is_("parent_id", "null")
        .execute()
    ).data
    if existing:
        return existing[0]["id"]
    created = (
        sb.table("folders")
        .insert({"user_id": user_id, "name": LAB_ROOT_NAME, "kind": "folder", "parent_id": None})
        .execute()
    ).data
    return created[0]["id"]


def _lab_doc_ids(sb, user_id: str, root_id: str) -> list[str]:
    rows = (
        sb.table("documents")
        .select("id")
        .eq("user_id", user_id)
        .eq("root_folder_id", root_id)
        .execute()
    ).data or []
    return [r["id"] for r in rows]


def _delete_lab_docs(sb, user_id: str, root_id: str) -> int:
    ids = _lab_doc_ids(sb, user_id, root_id)
    if ids:
        sb.table("documents").delete().in_("id", ids).execute()
    return len(ids)


async def _enqueue_all(sb, user_id: str, root_id: str) -> list[str]:
    # Skip macOS AppleDouble sidecars (._foo.md) a tar copy can leave behind.
    files = sorted(f for f in CORPUS_DIR.glob("*.md") if not f.name.startswith("._"))
    if not files:
        raise SystemExit(f"no corpus files under {CORPUS_DIR}")
    pool = await create_pool(_redis_settings())
    job_ids: list[str] = []
    try:
        for f in files:
            file_bytes = f.read_bytes()
            content_hash = compute_content_hash(file_bytes)
            storage_path = upload_document_to_storage(file_bytes, user_id, content_hash, f.name)
            job_id = create_job(
                sb,
                user_id=user_id,
                kind="upload",
                source_ref=f.name,
                root_folder_id=root_id,
            )
            await pool.enqueue_job(
                "ingest_document_task",
                {
                    "job_id": job_id,
                    "user_id": user_id,
                    "folder_id": root_id,
                    "root_folder_id": root_id,
                    "storage_bucket": "documents",
                    "storage_path": storage_path,
                    "filename": f.name,
                    "source_type": "text",
                    "media_kind": "document",
                    "media_url": storage_path,
                    "content_hash": content_hash,
                },
            )
            job_ids.append(job_id)
            print(f"  enqueued {f.name} (job {job_id[:8]})")
    finally:
        await pool.close()
    return job_ids


def _wait_for_ingestion(sb, job_ids: list[str], timeout_s: int = 300) -> bool:
    """Poll ingestion_jobs until all terminal (completed/failed) or timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = (
            sb.table("ingestion_jobs").select("id,status").in_("id", job_ids).execute()
        ).data or []
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        done = by_status.get("completed", 0) + by_status.get("failed", 0)
        print(f"  ingestion: {by_status}")
        if done >= len(job_ids):
            return by_status.get("failed", 0) == 0
        time.sleep(5)
    return False


def seed(user_id: str) -> int:
    sb = get_supabase()
    root_id = _get_or_create_root(sb, user_id)
    print(f"lab root {LAB_ROOT_NAME} = {root_id}")
    removed = _delete_lab_docs(sb, user_id, root_id)
    if removed:
        print(f"  removed {removed} prior lab docs (idempotent re-seed)")
    job_ids = asyncio.run(_enqueue_all(sb, user_id, root_id))
    print(f"enqueued {len(job_ids)} docs; waiting for ingestion...")
    ok = _wait_for_ingestion(sb, job_ids)
    chunks = (
        sb.table("documents").select("id", count="exact").eq("root_folder_id", root_id).execute()
    ).count
    print(f"{'OK' if ok else 'INCOMPLETE'}: {chunks} chunks under lab root")
    return 0 if ok else 1


def teardown(user_id: str) -> int:
    sb = get_supabase()
    existing = (
        sb.table("folders")
        .select("id")
        .eq("user_id", user_id)
        .eq("name", LAB_ROOT_NAME)
        .is_("parent_id", "null")
        .execute()
    ).data
    if not existing:
        print("no lab root to remove")
        return 0
    root_id = existing[0]["id"]
    removed = _delete_lab_docs(sb, user_id, root_id)
    sb.table("folders").delete().eq("id", root_id).execute()
    print(f"removed {removed} lab docs and root {LAB_ROOT_NAME}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m eval.lab_seed <user_id> [--teardown]")
        sys.exit(2)
    uid = sys.argv[1]
    if "--teardown" in sys.argv:
        sys.exit(teardown(uid))
    sys.exit(seed(uid))
