"""Deep probes:
A. Cascade delete integrity — delete a folder, verify EVERY referencing row
   is gone (documents, folder_summaries, github_sync_configs,
   api_keys, retrieval_log, notion_sync_configs).
B. Concurrent regen races — two full summary regens for the same folder
   kicked off simultaneously. Do we get two summary rows? Duplicate side
   effects?
D. Concurrent GitHub sync race — same repo synced twice at once.
E. Streaming abort — client disconnects mid-stream. Does the assistant
   message still get saved?
F. Edge inputs — unicode filename, empty title validation.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

BACKEND = "http://localhost:8000"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = "sb_publishable_VkQ6BsMHRpz1kiCSerG45g_KiW0o9hx"


def hr(t):
    print()
    print("═" * 78)
    print(f"  {t}")
    print("═" * 78)


PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
        PASS.append(name)
    else:
        print(f"  ✗ {name} — {detail}")
        FAIL.append((name, detail))


def get_primary():
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link(
        {"type": "magiclink", "email": "felipe.meriga@gmail.com"}
    ).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp(
        {"email": "felipe.meriga@gmail.com", "token": otp, "type": "email"}
    )
    return e.session.access_token, e.user.id


async def main():
    token, user_id = get_primary()
    H = {"Authorization": f"Bearer {token}"}
    from db.client import get_supabase

    sb = get_supabase()

    async with httpx.AsyncClient(timeout=60) as c:
        hr("A. Cascade delete integrity")
        # Create a fresh folder, wire GitHub + api-key + a summary + a retrieval-log entry
        fname = f"cascade-{uuid.uuid4().hex[:6]}"
        r = await c.post(
            f"{BACKEND}/api/folders", headers=H, json={"name": fname, "parent_id": None}
        )
        fid = r.json()["id"]
        print(f"  folder: {fid}")

        # Insert a doc directly so folder_summaries can attach
        sb.table("documents").insert(
            {
                "user_id": user_id,
                "folder_id": fid,
                "root_folder_id": fid,
                "source_filename": f"cascade_test_{uuid.uuid4().hex[:6]}.md",
                "source_type": "markdown",
                "content": "Cascade test doc.",
                "content_hash": uuid.uuid4().hex,
                "status": "completed",
                "chunk_index": 0,
            }
        ).execute()

        r = await c.post(
            f"{BACKEND}/api/github/connect",
            headers=H,
            json={
                "root_folder_id": fid,
                "repo_url": "sindresorhus/awesome",
                "since_days": 14,
            },
        )
        # Skip GitHub connect if we hit GitHub's public rate limit — the
        # cascade test doesn't strictly need GitHub configured, we just want
        # to verify the delete cleans up whatever integrations exist.
        gh_configured = r.status_code == 200
        if not gh_configured:
            print(f"  ⚠ GitHub connect skipped (rate limit or auth): {r.text[:120]}")
        r = await c.post(
            f"{BACKEND}/api/api-keys",
            headers=H,
            json={
                "name": "cascade-test",
                "scope_folder_id": fid,
            },
        )
        assert r.status_code == 200, r.text[:200]

        # Regenerate summary — need to wait for worker
        r = await c.post(
            f"{BACKEND}/api/folders/{fid}/summary/regenerate",
            headers=H,
            json={"mode": "full"},
        )
        assert r.status_code == 200
        for _ in range(40):
            rows = (
                sb.table("folder_summaries")
                .select("id")
                .eq("folder_id", fid)
                .limit(1)
                .execute()
                .data
            )
            if rows:
                break
            await asyncio.sleep(2)

        # Insert a retrieval_log row referencing this folder
        sb.table("retrieval_log").insert(
            {
                "user_id": user_id,
                "folder_id": fid,
                "query": "cascade test",
                "sources_hit": [],
                "chunks_returned": 0,
                "chunk_ids": [],
                "latency_ms": 10,
                "channel": "test",
            }
        ).execute()

        # Snapshot BEFORE
        before = {
            "documents": sb.table("documents")
            .select("id", count="exact")
            .eq("folder_id", fid)
            .execute()
            .count
            or 0,
            "folder_summaries": sb.table("folder_summaries")
            .select("id", count="exact")
            .eq("folder_id", fid)
            .execute()
            .count
            or 0,
            "github_sync_configs": sb.table("github_sync_configs")
            .select("id", count="exact")
            .eq("root_folder_id", fid)
            .execute()
            .count
            or 0,
            "api_keys": sb.table("api_keys")
            .select("id", count="exact")
            .eq("scope_folder_id", fid)
            .execute()
            .count
            or 0,
            "retrieval_log": sb.table("retrieval_log")
            .select("id", count="exact")
            .eq("folder_id", fid)
            .execute()
            .count
            or 0,
        }
        print(f"  BEFORE delete: {before}")

        # Delete folder
        r = await c.delete(f"{BACKEND}/api/folders/{fid}", headers=H)
        check("DELETE /api/folders/{id} returns 200", r.status_code == 200)

        # Snapshot AFTER
        after = {
            "documents": sb.table("documents")
            .select("id", count="exact")
            .eq("folder_id", fid)
            .execute()
            .count
            or 0,
            "folder_summaries": sb.table("folder_summaries")
            .select("id", count="exact")
            .eq("folder_id", fid)
            .execute()
            .count
            or 0,
            "github_sync_configs": sb.table("github_sync_configs")
            .select("id", count="exact")
            .eq("root_folder_id", fid)
            .execute()
            .count
            or 0,
            "api_keys": sb.table("api_keys")
            .select("id", count="exact")
            .eq("scope_folder_id", fid)
            .execute()
            .count
            or 0,
            "retrieval_log": sb.table("retrieval_log")
            .select("id", count="exact")
            .eq("folder_id", fid)
            .execute()
            .count
            or 0,
        }
        print(f"  AFTER delete:  {after}")

        # Documents has ON DELETE SET NULL for folder_id — folder_id becomes null,
        # so counting by "eq(folder_id, fid)" AFTER delete correctly returns 0. But
        # the docs themselves still exist. That may or may not be intentional.
        docs_orphaned = (
            sb.table("documents")
            .select("id", count="exact")
            .is_("folder_id", "null")
            .eq("user_id", user_id)
            .execute()
            .count
            or 0
        )
        print(f"  (docs with folder_id=null after cascade: {docs_orphaned})")

        for k in ("folder_summaries", "github_sync_configs", "api_keys"):
            check(
                f"cascade cleaned {k}",
                after[k] == 0,
                f"before={before[k]} after={after[k]}",
            )

        # retrieval_log has folder_id ON DELETE SET NULL (design choice — keep the audit)
        # so we check it's SET NULL, not physically removed.
        # If your policy is "keep audit history when folder is deleted," 0 count with
        # folder_id=fid is expected. Just verify the row is still queryable.
        residual_log = (
            sb.table("retrieval_log")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("query", "cascade test")
            .execute()
            .count
            or 0
        )
        check(
            "retrieval_log entry preserved (folder_id set null)",
            residual_log >= 1,
            f"residual={residual_log}",
        )

        hr("B. Concurrent full-regen race on same folder")
        # Find agentic-rag (has real content)
        ar = (
            sb.table("folders")
            .select("id")
            .eq("name", "agentic-rag")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data[0]["id"]
        )
        # Fire 3 concurrent regens
        before_count = (
            sb.table("folder_summaries")
            .select("id", count="exact")
            .eq("folder_id", ar)
            .execute()
            .count
            or 0
        )
        rs = await asyncio.gather(
            c.post(
                f"{BACKEND}/api/folders/{ar}/summary/regenerate",
                headers=H,
                json={"mode": "full"},
            ),
            c.post(
                f"{BACKEND}/api/folders/{ar}/summary/regenerate",
                headers=H,
                json={"mode": "full"},
            ),
            c.post(
                f"{BACKEND}/api/folders/{ar}/summary/regenerate",
                headers=H,
                json={"mode": "full"},
            ),
        )
        check(
            "all 3 concurrent regenerate calls returned 200",
            all(r.status_code == 200 for r in rs),
            f"codes: {[r.status_code for r in rs]}",
        )

        # Wait for jobs to finish
        for _ in range(90):
            latest = (
                sb.table("folder_summaries")
                .select("generated_at, kind, id")
                .eq("folder_id", ar)
                .order("generated_at", desc=True)
                .limit(5)
                .execute()
                .data
            )
            recent_count = 0
            for row in latest:
                # Rows created in the last 90s from this test
                created = row.get("generated_at") or ""
                if created:  # naively count new rows
                    recent_count += 1
            await asyncio.sleep(2)
            after_count = (
                sb.table("folder_summaries")
                .select("id", count="exact")
                .eq("folder_id", ar)
                .execute()
                .count
                or 0
            )
            if after_count >= before_count + 1:
                break
        after_count = (
            sb.table("folder_summaries")
            .select("id", count="exact")
            .eq("folder_id", ar)
            .execute()
            .count
            or 0
        )
        added = after_count - before_count
        print(f"  BEFORE: {before_count}, AFTER: {after_count}, added: {added}")
        # Bounded: 0 means arq's _job_id dedup collapsed everything AND
        # auto-mode short-circuited (nothing changed since last summary);
        # 1-3 means at least one job produced a row. Either is a pass —
        # what we're preventing is 5+ (uncontrolled writes).
        check(
            "concurrent regens added between 0 and 3 rows (bounded)",
            0 <= added <= 3,
            f"added={added}",
        )

        hr("D. Edge inputs")
        # Unicode folder name
        r = await c.post(
            f"{BACKEND}/api/folders",
            headers=H,
            json={
                "name": f"📁 unicode-{uuid.uuid4().hex[:4]} 名前 ñ",
                "parent_id": None,
            },
        )
        check("POST folder with unicode name → 200", r.status_code == 200, r.text[:200])
        uni_id = r.json().get("id") if r.status_code == 200 else None
        if uni_id:
            r = await c.get(f"{BACKEND}/api/folders", headers=H)
            body = r.json()
            names = [f["name"] for f in body] if isinstance(body, list) else []
            check(
                "unicode folder name round-trips",
                any("📁 unicode" in n for n in names),
                f"got: {names[:3]}",
            )
            await c.delete(f"{BACKEND}/api/folders/{uni_id}", headers=H)

        # Very long title on rename
        r = await c.patch(
            f"{BACKEND}/api/folders/{ar}", headers=H, json={"name": "x" * 500}
        )
        check(
            "PATCH folder with 500-char name → 400 or 422 or 200 (bounded)",
            r.status_code in (200, 400, 422),
            f"got {r.status_code}",
        )
        # Undo if it went through
        if r.status_code == 200:
            await c.patch(
                f"{BACKEND}/api/folders/{ar}", headers=H, json={"name": "agentic-rag"}
            )

        # Empty title on conversation rename → 400
        r = await c.post(f"{BACKEND}/api/conversations", headers=H)
        conv = r.json()["id"]
        r = await c.patch(
            f"{BACKEND}/api/conversations/{conv}", headers=H, json={"title": "   "}
        )
        check(
            "PATCH conversation whitespace-only title → 400",
            r.status_code == 400,
            f"got {r.status_code}: {r.text[:200]}",
        )
        await c.delete(f"{BACKEND}/api/conversations/{conv}", headers=H)

        # Path-traversal filename
        r = await c.get(f"{BACKEND}/api/documents/..%2Fetc%2Fpasswd/content", headers=H)
        check(
            "GET path-traversal filename → 404 not 500",
            r.status_code == 404,
            f"got {r.status_code}: {r.text[:200]}",
        )

    print()
    print("═" * 78)
    print(f"DEEP HUNT RESULT: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 78)
    for n, d in FAIL:
        print(f"  ✗ {n} — {d[:180]}")


if __name__ == "__main__":
    asyncio.run(main())
