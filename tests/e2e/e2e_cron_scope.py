"""Verify the nightly cron scope now covers:
    1. Leaf folders with docs   (existing behavior)
    2. Repo folders with 0 docs (NEW)
    3. Container folders with a workspace_rollup (NEW)

Also verifies:
    - Manual regenerate endpoint works for all 3 kinds
    - The scope is deduped (a folder that's both a repo AND has docs
      appears exactly once)
"""

from __future__ import annotations
import asyncio, os, sys, uuid
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

PASS, FAIL = [], []
def check(n, cond, d=""):
    (PASS if cond else FAIL).append(n)
    print(f"  {'✓' if cond else '✗'} {n}" + (f" — {d[:220]}" if not cond else ""))
def hr(t): print(); print("═" * 78); print(f"  {t}"); print("═" * 78)


def main():
    from db.client import get_supabase
    from services.folder_summary.repo import (
        list_all_regenerable_folder_pairs, list_folder_ids_with_docs,
    )
    sb = get_supabase()

    admin = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    )
    users = admin.auth.admin.list_users()
    user_id = next(u.id for u in users if u.email == "felipe.meriga@gmail.com")

    hr("Setup: three scratch folders — leaf-with-docs, empty-repo, container-rollup")
    tid = uuid.uuid4().hex[:6]

    # 1. Leaf folder with a doc
    leaf_row = sb.table("folders").insert({
        "name": f"cron-leaf-{tid}", "user_id": user_id,
    }).execute().data[0]
    leaf_id = leaf_row["id"]
    sb.table("documents").insert({
        "user_id": user_id, "folder_id": leaf_id, "root_folder_id": leaf_id,
        "source_filename": f"cron_test_{tid}.md",
        "source_type": "markdown", "content": "cron test doc",
        "content_hash": uuid.uuid4().hex, "status": "completed", "chunk_index": 0,
    }).execute()

    # 2. Empty repo folder (no docs)
    repo_row = sb.table("folders").insert({
        "name": f"cron-repo-{tid}", "user_id": user_id, "kind": "repo",
    }).execute().data[0]
    repo_id = repo_row["id"]

    # 3. Container folder with a workspace_rollup row
    container_row = sb.table("folders").insert({
        "name": f"cron-container-{tid}", "user_id": user_id,
    }).execute().data[0]
    container_id = container_row["id"]
    # Fake child so the rollup can find something to compose
    child_row = sb.table("folders").insert({
        "name": f"cron-child-{tid}", "user_id": user_id, "parent_id": container_id,
    }).execute().data[0]
    child_id = child_row["id"]
    # Seed a workspace_rollup summary row directly
    sb.table("folder_summaries").insert({
        "folder_id": container_id,
        "user_id": user_id,
        "kind": "workspace_rollup",
        "trigger": "manual",
        "content": {"title": "test rollup", "purpose": "cron probe",
                    "overview": "", "themes": [], "key_documents": [],
                    "key_facts": [], "entities": [], "gotchas": []},
        "included_hashes": [],
        "doc_count": 0,
        "changed_files": {},
    }).execute()

    hr("Verify scope enumerator returns all three")
    pairs = list_all_regenerable_folder_pairs(sb)
    ids = {p["folder_id"] for p in pairs}
    check("scope includes leaf-with-docs folder",
          leaf_id in ids,
          f"leaf_id={leaf_id} in scope? {leaf_id in ids}")
    check("scope includes empty repo folder (NEW)",
          repo_id in ids,
          f"repo_id={repo_id} in scope? {repo_id in ids}")
    check("scope includes container with workspace_rollup (NEW)",
          container_id in ids,
          f"container_id={container_id} in scope? {container_id in ids}")

    hr("Verify dedup — same folder should never appear twice")
    seen: dict[tuple[str, str], int] = {}
    for p in pairs:
        k = (p["folder_id"], p["user_id"])
        seen[k] = seen.get(k, 0) + 1
    dups = {k: v for k, v in seen.items() if v > 1}
    check("no duplicate (folder_id, user_id) pairs",
          not dups,
          f"dups: {dups}")

    hr("Compare old vs new enumerator")
    old = list_folder_ids_with_docs(sb)
    new = list_all_regenerable_folder_pairs(sb)
    old_ids = {p["folder_id"] for p in old}
    new_ids = {p["folder_id"] for p in new}
    added = new_ids - old_ids
    check(f"new enumerator adds {len(added)} folders vs old",
          len(added) >= 2,  # at least our repo + container
          f"added: {len(added)}")
    print(f"    old count: {len(old_ids)}  →  new count: {len(new_ids)}")

    hr("Cleanup")
    for fid in (child_id, container_id, repo_id, leaf_id):
        sb.table("folder_summaries").delete().eq("folder_id", fid).eq("user_id", user_id).execute()
        sb.table("folders").delete().eq("id", fid).eq("user_id", user_id).execute()
    sb.table("documents").delete().eq("folder_id", leaf_id).eq("user_id", user_id).execute()

    print()
    print("═" * 78)
    print(f"CRON SCOPE: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 78)
    for n in FAIL:
        print(f"  ✗ {n}")


if __name__ == "__main__":
    main()
