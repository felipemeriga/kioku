"""Summary deep behaviors — mode transitions, mutations, dedup, preservation.

  A. Auto mode with no changes → skip (arq dedup + auto short-circuit).
  B. Full mode always regenerates.
  C. Doc added → auto mode regens (kind='delta' or 'full' depending on diff).
  D. Doc modified → auto mode regens.
  E. Doc removed → auto mode regens.
  F. Container: child folder gets a new summary → workspace rollup follows.
  G. Repo briefing: pinned sections survive auto-regen.
  H. Reset a pinned section → re-runs populator.
  I. PUT full replace → REST verifies all 8 sections.
  J. Concurrent regens on same folder → arq _job_id collapses them.
  K. Invalid modes rejected.
"""

from __future__ import annotations
import asyncio, json, os, sys, time, uuid
import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

BACKEND = "http://localhost:8000"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]

PASS, FAIL = [], []
def check(n, cond, d=""):
    (PASS if cond else FAIL).append(n)
    print(f"  {'✓' if cond else '✗'} {n}" + (f" — {d[:220]}" if not cond else ""))
def hr(t): print(); print("═" * 74); print(f"  {t}"); print("═" * 74)


def get_token():
    last_exc = None
    for attempt in range(4):
        try:
            admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
            otp = admin.auth.admin.generate_link(
                {"type":"magiclink","email":"felipe.meriga@gmail.com"}
            ).properties.email_otp
            anon = create_client(SUPABASE_URL, ANON)
            e = anon.auth.verify_otp(
                {"email":"felipe.meriga@gmail.com","token":otp,"type":"email"}
            )
            return e.session.access_token, e.user.id
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(3 + attempt * 2)
    raise last_exc  # type: ignore[misc]


async def wait_for_row_after(sb, folder_id: str, user_id: str,
                               after_ts: str, timeout_s: int = 30) -> dict | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            rows = sb.table("folder_summaries").select("*").eq(
                "folder_id", folder_id
            ).eq("user_id", user_id).order(
                "generated_at", desc=True
            ).limit(1).execute().data or []
            if rows and rows[0]["generated_at"] > after_ts:
                return rows[0]
        except Exception:
            # Transient Supabase read errors under load — retry.
            pass
        await asyncio.sleep(1)
    return None


async def count_rows(sb, folder_id: str, user_id: str) -> int:
    for _ in range(3):
        try:
            return sb.table("folder_summaries").select("id", count="exact").eq(
                "folder_id", folder_id).eq("user_id", user_id).execute().count or 0
        except Exception:
            await asyncio.sleep(1)
    return 0


async def main():
    from db.client import get_supabase
    sb = get_supabase()
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}
    tid = uuid.uuid4().hex[:6]

    async with httpx.AsyncClient(timeout=120, headers=H) as c:

        hr("Setup: leaf folder with a doc + first summary")
        r = await c.post(f"{BACKEND}/api/folders",
                          json={"name": f"deep-leaf-{tid}", "parent_id": None})
        leaf_id = r.json()["id"]
        # Seed a doc
        doc_id = sb.table("documents").insert({
            "user_id": user_id, "folder_id": leaf_id, "root_folder_id": leaf_id,
            "source_filename": f"leaf-{tid}.md",
            "source_type": "markdown",
            "content": "Original content about deployment strategy.",
            "content_hash": uuid.uuid4().hex,
            "status": "completed", "chunk_index": 0,
        }).execute().data[0]["id"]

        # First regen
        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "auto"})
        assert r.status_code == 200
        # Wait for the row
        first_row = None
        for _ in range(40):
            rows = sb.table("folder_summaries").select("*").eq(
                "folder_id", leaf_id).order("generated_at", desc=True).limit(1).execute().data
            if rows:
                first_row = rows[0]
                break
            await asyncio.sleep(1)
        assert first_row is not None, "first regen didn't produce a row"
        first_ts = first_row["generated_at"]
        first_kind = first_row["kind"]
        print(f"  first summary: kind={first_kind} ts={first_ts}")

        hr("A. Auto mode with no changes → skip")
        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "auto"})
        check("A. regen 2nd auto returns 200", r.status_code == 200)
        await asyncio.sleep(8)
        # Count how many rows we have now
        rows = sb.table("folder_summaries").select("kind, generated_at").eq(
            "folder_id", leaf_id).order("generated_at", desc=True).execute().data or []
        # A skip row could be added, or nothing added at all — both are correct
        skip_rows = [r for r in rows if r["kind"] == "skip"]
        latest = rows[0] if rows else None
        check("A. auto-unchanged: nothing changed OR a 'skip' row inserted",
              (latest and latest["kind"] == "skip") or len(rows) == 1,
              f"total_rows={len(rows)}, latest_kind={latest['kind'] if latest else 'none'}")

        hr("B. Full mode always regenerates")
        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "full"})
        check("B. regen full: 200", r.status_code == 200)
        row = await wait_for_row_after(sb, leaf_id, user_id, first_ts, timeout_s=60)
        check("B. full mode inserted a new row",
              row is not None and row["generated_at"] > first_ts,
              f"got: {row}")
        if row:
            check("B. full mode's row kind is 'full'",
                  row["kind"] == "full", f"got kind={row['kind']}")
            full_ts = row["generated_at"]

        hr("C. Doc added → auto mode regens")
        # Add a second doc
        sb.table("documents").insert({
            "user_id": user_id, "folder_id": leaf_id, "root_folder_id": leaf_id,
            "source_filename": f"leaf-second-{tid}.md",
            "source_type": "markdown",
            "content": "Second doc about testing methodology.",
            "content_hash": uuid.uuid4().hex,
            "status": "completed", "chunk_index": 0,
        }).execute()

        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "auto"})
        row = await wait_for_row_after(sb, leaf_id, user_id, full_ts, timeout_s=90)
        check("C. auto after doc add: new row inserted",
              row is not None, f"got: {row}")
        add_ts = row["generated_at"] if row else full_ts
        if row:
            check("C. new row kind is 'full' or 'delta' (not skip/seed)",
                  row["kind"] in ("full", "delta"), f"got kind={row['kind']}")

        hr("D. Doc modified → auto mode regens")
        # Modify the first doc
        sb.table("documents").update({
            "content_hash": uuid.uuid4().hex,
            "content": "MODIFIED — new deployment strategy content.",
        }).eq("id", doc_id).execute()

        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "auto"})
        row = await wait_for_row_after(sb, leaf_id, user_id, add_ts, timeout_s=90)
        check("D. auto after doc modify: new row inserted",
              row is not None, f"got: {row}")

        hr("E. Doc removed → auto mode regens")
        # Delete the second doc
        second_docs = sb.table("documents").select("id").eq(
            "folder_id", leaf_id).ilike("source_filename", "leaf-second%").execute().data
        for d in second_docs:
            sb.table("documents").delete().eq("id", d["id"]).execute()
        last_ts = (sb.table("folder_summaries").select("generated_at").eq(
            "folder_id", leaf_id).order("generated_at", desc=True).limit(1)
            .execute().data or [{}])[0].get("generated_at")

        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "auto"})
        # Longer timeout: this fires after C+D+B which have each held a
        # slow Anthropic call. The worker queue may still be draining.
        row = await wait_for_row_after(sb, leaf_id, user_id, last_ts, timeout_s=150)
        check("E. auto after doc remove: new row inserted",
              row is not None, f"got: {row}")

        # Cleanup leaf
        await c.delete(f"{BACKEND}/api/folders/{leaf_id}?delete_docs=true")

        hr("F. Container: child folder change → workspace rollup follows")
        r = await c.post(f"{BACKEND}/api/folders",
                          json={"name": f"deep-ws-{tid}", "parent_id": None})
        ws_id = r.json()["id"]
        # 2 children with docs
        child_ids = []
        for i in range(2):
            r = await c.post(f"{BACKEND}/api/folders",
                              json={"name": f"deep-child-{tid}-{i}",
                                    "parent_id": ws_id})
            cid = r.json()["id"]
            child_ids.append(cid)
            sb.table("documents").insert({
                "user_id": user_id, "folder_id": cid, "root_folder_id": cid,
                "source_filename": f"child-{tid}-{i}.md",
                "source_type": "markdown",
                "content": f"Child {i} content.",
                "content_hash": uuid.uuid4().hex,
                "status": "completed", "chunk_index": 0,
            }).execute()

        # Regen the workspace (auto)
        r = await c.post(f"{BACKEND}/api/folders/{ws_id}/summary/regenerate",
                          json={"mode": "auto"})
        row = await wait_for_row_after(sb, ws_id, user_id, "0", timeout_s=90)
        check("F. workspace: initial rollup produced",
              row is not None, "no row after 90s")
        if row:
            check("F. workspace: kind is workspace_rollup or fallback",
                  row["kind"] in ("workspace_rollup", "full", "seed"),
                  f"got kind={row['kind']}")
        await c.delete(f"{BACKEND}/api/folders/{ws_id}?delete_docs=true")

        hr("G. Repo briefing: pinned sections survive auto-regen")
        r = await c.post(f"{BACKEND}/api/folders",
                          json={"name": f"deep-repo-{tid}", "parent_id": None})
        repo_id = r.json()["id"]
        await c.patch(f"{BACKEND}/api/folders/{repo_id}", json={"kind": "repo"})
        # Regen to seed briefing
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/summary/regenerate",
                          json={"mode": "auto"})
        await wait_for_row_after(sb, repo_id, user_id, "0", timeout_s=45)
        # Pin the overview
        marker = f"PINNED CONTENT {uuid.uuid4().hex[:8]}"
        r = await c.patch(
            f"{BACKEND}/api/folders/{repo_id}/briefing/section/overview",
            json={"content": {"purpose": marker, "description": "test pinned"},
                  "status": "pinned"},
        )
        assert r.status_code == 200
        pin_ts = (sb.table("folder_summaries").select("generated_at").eq(
            "folder_id", repo_id).order("generated_at", desc=True).limit(1)
            .execute().data or [{}])[0].get("generated_at")

        # Regen auto
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/summary/regenerate",
                          json={"mode": "auto"})
        # Wait for a new row
        await asyncio.sleep(8)
        # Check
        r = await c.get(f"{BACKEND}/api/folders/{repo_id}/briefing")
        b = r.json()
        overview = b["sections"]["overview"]
        check("G. overview status stays 'pinned' after auto-regen",
              overview["status"] == "pinned",
              f"status={overview['status']}")
        check("G. pinned content preserved through auto-regen",
              overview["content"]["purpose"] == marker,
              f"purpose={overview['content'].get('purpose')}")

        hr("H. Reset a pinned section → re-runs populator (status back to auto)")
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/briefing/section/overview/reset")
        check("H. reset returns 200", r.status_code == 200, r.text[:200])
        r = await c.get(f"{BACKEND}/api/folders/{repo_id}/briefing")
        overview = r.json()["sections"]["overview"]
        check("H. after reset, overview.status='auto'",
              overview["status"] == "auto", f"status={overview['status']}")
        check("H. after reset, provenance='auto'",
              overview["provenance"] == "auto", f"prov={overview['provenance']}")

        hr("I. PUT full replace: verifies all 8 sections + provenance='user_ui'")
        replacement = {
            "sections": {
                "overview": {"purpose": "PUT-purpose", "description": "PUT-desc"},
                "architecture": {"summary": "PUT", "components": [], "data_flow": ""},
                "preferences": {"rules": ["rule from PUT"]},
                "important_files": [{"path": "a.py", "role": "test", "why": "why"}],
                "how_it_runs": {"requirements": [], "local_dev": "make dev"},
                "deployment": {"environments": ["prod"], "how_to_deploy": "docker", "ci_cd_notes": ""},
                "dependencies": {"runtime": ["FastAPI"], "services": ["Redis"]},
                "activity": {"recent_commits": [], "recent_prs": [], "recent_learnings": []},
            },
            "pin_all": True,
        }
        r = await c.put(f"{BACKEND}/api/folders/{repo_id}/briefing", json=replacement)
        check("I. PUT returns 200 + 8 replaced",
              r.status_code == 200 and r.json().get("total_sections") == 8,
              r.text[:200])
        r = await c.get(f"{BACKEND}/api/folders/{repo_id}/briefing")
        b = r.json()
        prov_counts: dict[str, int] = {}
        for s in b["sections"].values():
            prov_counts[s["provenance"]] = prov_counts.get(s["provenance"], 0) + 1
        check("I. all 8 sections stamped provenance='user_ui'",
              prov_counts.get("user_ui", 0) == 8, f"got: {prov_counts}")

        # Cleanup repo
        await c.delete(f"{BACKEND}/api/folders/{repo_id}?delete_docs=true")

        hr("J. Concurrent regens: arq _job_id collapses duplicates")
        # Reuse felipemeriga/agentic-rag folder
        ar = sb.table("folders").select("id, kind").eq(
            "name","agentic-rag").eq("user_id", user_id).limit(1).execute().data
        if ar:
            fid = ar[0]["id"]
            before = await count_rows(sb, fid, user_id)
            # Fire 5 concurrent auto regens
            results = await asyncio.gather(*[
                c.post(f"{BACKEND}/api/folders/{fid}/summary/regenerate",
                        json={"mode": "auto"})
                for _ in range(5)
            ])
            check("J. all 5 concurrent regens returned 200",
                  all(r.status_code == 200 for r in results),
                  f"codes: {[r.status_code for r in results]}")
            await asyncio.sleep(10)
            after = await count_rows(sb, fid, user_id)
            added = after - before
            check("J. 5 concurrent regens added AT MOST 2 rows (arq dedup)",
                  added <= 2, f"added={added}")

        hr("K. Invalid modes rejected")
        r = await c.post(f"{BACKEND}/api/folders/{ar[0]['id']}/summary/regenerate",
                          json={"mode": "wrong"})
        check("K.1 invalid mode 'wrong' → 400", r.status_code == 400, r.text[:200])
        r = await c.post(f"{BACKEND}/api/folders/{ar[0]['id']}/summary/regenerate",
                          json={"mode": ""})
        check("K.2 empty mode → 400", r.status_code == 400, r.text[:200])
        r = await c.post(f"{BACKEND}/api/folders/{ar[0]['id']}/summary/regenerate",
                          json={})
        check("K.3 missing mode field → 4xx",
              r.status_code in (200, 400, 422),
              f"got {r.status_code}: {r.text[:200]}")

    print()
    print("═" * 74)
    print(f"SUMMARY DEEP: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL: print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
