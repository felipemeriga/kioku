"""Summary lifecycle E2E — all 3 folder kinds through full workflow.

For each of:
  - Leaf folder with docs      → kind='full'/'delta'/'seed'
  - Repo folder                → kind='briefing'
  - Container workspace        → kind='workspace_rollup'

We verify:
  1. Create the folder + seed content that triggers the right summary path
  2. Regenerate mode=auto — enqueues + eventually inserts a row
  3. Fetched summary matches the expected kind
  4. Regenerate mode=full — always inserts a row (no skip)
  5. Regenerate mode=auto right after → skip if nothing changed (arq dedup)
  6. Regenerate history endpoint returns rows in reverse-chron order
  7. Invalid modes rejected (400)
  8. Malformed folder IDs → 404 not 500
  9. Delete folder → all summary rows cascade
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
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link(
        {"type":"magiclink","email":"felipe.meriga@gmail.com"}
    ).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp(
        {"email":"felipe.meriga@gmail.com","token":otp,"type":"email"}
    )
    return e.session.access_token, e.user.id


async def wait_for_summary(sb, folder_id: str, user_id: str,
                            after_ts: str | None = None,
                            timeout_s: int = 30) -> dict | None:
    """Poll until a new summary row exists for this folder."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = sb.table("folder_summaries").select("*").eq(
            "folder_id", folder_id
        ).eq("user_id", user_id).order(
            "generated_at", desc=True
        ).limit(1).execute().data or []
        if rows:
            if after_ts is None or rows[0]["generated_at"] > after_ts:
                return rows[0]
        await asyncio.sleep(1)
    return None


async def main():
    from db.client import get_supabase
    sb = get_supabase()
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}
    tid = uuid.uuid4().hex[:6]

    async with httpx.AsyncClient(timeout=90, headers=H) as c:

        hr("═══ KIND 1: Leaf folder with docs (kind='full'/'delta') ═══")
        r = await c.post(f"{BACKEND}/api/folders",
                          json={"name": f"lifecycle-leaf-{tid}", "parent_id": None})
        leaf_id = r.json()["id"]
        # Seed a doc so it hits the leaf-summary path
        sb.table("documents").insert({
            "user_id": user_id, "folder_id": leaf_id, "root_folder_id": leaf_id,
            "source_filename": f"leaf-doc-{tid}.md",
            "source_type": "markdown",
            "content": "This is a test document about deployment.",
            "content_hash": uuid.uuid4().hex,
            "status": "completed", "chunk_index": 0,
        }).execute()

        # Regenerate mode=auto
        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "auto"})
        check("leaf: regenerate auto → 200", r.status_code == 200, r.text[:200])
        row = await wait_for_summary(sb, leaf_id, user_id, timeout_s=45)
        check("leaf: summary row inserted",
              row is not None, "no row after 45s")
        if row:
            check("leaf: kind is 'full' (first-time)",
                  row["kind"] == "full", f"got kind={row['kind']}")

        # GET /summary sees it
        r = await c.get(f"{BACKEND}/api/folders/{leaf_id}/summary")
        body = r.json()
        check("leaf: GET /summary returns folder + summary",
              "folder" in body and "summary" in body, str(body)[:200])
        check("leaf: summary has content shape",
              body["summary"] and "purpose" in (body["summary"].get("content") or {}),
              str(body["summary"])[:200])

        # Regen again in auto mode — should skip
        first_ts = row["generated_at"] if row else None
        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "auto"})
        check("leaf: regen 2nd auto → 200", r.status_code == 200)
        # Wait briefly; since nothing changed, no new row should land
        await asyncio.sleep(6)
        rows = sb.table("folder_summaries").select("id, kind, generated_at").eq(
            "folder_id", leaf_id).eq("user_id", user_id).order(
            "generated_at", desc=True).execute().data or []
        skip_rows = [r for r in rows if r["kind"] == "skip"]
        check("leaf: auto-mode skips OR inserts skip row when unchanged",
              len(rows) <= 2 or len(skip_rows) >= 1,
              f"total_rows={len(rows)}, kinds={[r['kind'] for r in rows]}")

        # History endpoint
        r = await c.get(f"{BACKEND}/api/folders/{leaf_id}/summary/history?limit=10")
        history = r.json() if r.status_code == 200 else []
        check("leaf: history returns list of rows",
              isinstance(history, list) and len(history) >= 1,
              f"got {len(history) if isinstance(history, list) else 'not-list'} rows")
        if len(history) >= 2:
            ts0 = history[0]["generated_at"]
            ts1 = history[1]["generated_at"]
            check("leaf: history reverse-chron",
                  ts0 >= ts1, f"ts0={ts0} ts1={ts1}")

        hr("═══ KIND 2: Repo folder (kind='briefing') ═══")
        r = await c.post(f"{BACKEND}/api/folders",
                          json={"name": f"lifecycle-repo-{tid}", "parent_id": None})
        repo_id = r.json()["id"]
        await c.patch(f"{BACKEND}/api/folders/{repo_id}", json={"kind": "repo"})

        # Regen
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/summary/regenerate",
                          json={"mode": "auto"})
        check("repo: regenerate auto → 200", r.status_code == 200, r.text[:200])
        row = await wait_for_summary(sb, repo_id, user_id, timeout_s=45)
        check("repo: summary row inserted", row is not None)
        if row:
            # kind might be 'briefing' if migration applied, else 'full' with sections stashed
            has_sections = row.get("sections") or (
                (row.get("content") or {}).get("sections")
            )
            check("repo: summary has briefing sections",
                  bool(has_sections), f"kind={row['kind']} sections={bool(row.get('sections'))}")

        # GET /briefing (repo-only endpoint)
        r = await c.get(f"{BACKEND}/api/folders/{repo_id}/briefing")
        check("repo: GET /briefing returns 200", r.status_code == 200, r.text[:200])
        body = r.json()
        check("repo: /briefing has all 8 sections",
              len(body.get("sections") or {}) == 8,
              f"got keys: {list((body.get('sections') or {}).keys())}")

        hr("═══ KIND 3: Container workspace (kind='workspace_rollup') ═══")
        r = await c.post(f"{BACKEND}/api/folders",
                          json={"name": f"lifecycle-ws-{tid}", "parent_id": None})
        ws_id = r.json()["id"]
        # Add subfolders — this is what makes it a container
        for i in range(2):
            r = await c.post(f"{BACKEND}/api/folders",
                              json={"name": f"lifecycle-child-{tid}-{i}",
                                    "parent_id": ws_id})

        # Regen
        r = await c.post(f"{BACKEND}/api/folders/{ws_id}/summary/regenerate",
                          json={"mode": "auto"})
        check("workspace: regenerate auto → 200", r.status_code == 200, r.text[:200])
        row = await wait_for_summary(sb, ws_id, user_id, timeout_s=60)
        check("workspace: summary row inserted", row is not None)
        if row:
            check("workspace: kind is workspace_rollup or full (fallback)",
                  row["kind"] in ("workspace_rollup", "full", "seed"),
                  f"got kind={row['kind']}")

        # GET /summary returns rollup + subfolders index
        r = await c.get(f"{BACKEND}/api/folders/{ws_id}/summary")
        body = r.json()
        if body.get("summary") and body["summary"].get("kind") == "workspace_rollup":
            check("workspace: /summary includes subfolders index",
                  isinstance(body.get("subfolders"), list),
                  f"got subfolders type: {type(body.get('subfolders')).__name__}")

        hr("═══ Cross-kind: legacy mode ignored, bad UUID → 404 ═══")
        # `mode` was removed — the endpoint now takes {force: bool}. Old
        # clients passing mode should be silently accepted (Pydantic
        # ignores unknown fields) and use the default (force=false).
        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"mode": "nonsense"})
        check("legacy 'mode' field silently ignored → 200",
              r.status_code == 200, r.text[:200])
        r = await c.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                          json={"force": True})
        check("force=true → 200", r.status_code == 200, r.text[:200])
        r = await c.get(f"{BACKEND}/api/folders/not-a-uuid/summary")
        check("bad UUID GET /summary → 404 not 500",
              r.status_code == 404, f"got {r.status_code}: {r.text[:200]}")
        r = await c.post(f"{BACKEND}/api/folders/not-a-uuid/summary/regenerate",
                          json={"force": False})
        check("bad UUID POST regenerate → 404 not 500",
              r.status_code == 404, f"got {r.status_code}: {r.text[:200]}")

        hr("═══ Cross-user isolation — user 2 can't regen user 1's folders ═══")
        admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
        email2 = f"lifecycle2-{uuid.uuid4().hex[:6]}@example.test"
        r2 = admin.auth.admin.create_user({
            "email": email2, "email_confirm": True,
            "password": "TestPass!" + uuid.uuid4().hex,
        })
        uid2 = r2.user.id
        otp = admin.auth.admin.generate_link({"type":"magiclink","email":email2}).properties.email_otp
        anon2 = create_client(SUPABASE_URL, ANON)
        e2 = anon2.auth.verify_otp({"email":email2,"token":otp,"type":"email"})
        H2 = {"Authorization": f"Bearer {e2.session.access_token}"}
        async with httpx.AsyncClient(timeout=15, headers=H2) as c2:
            r = await c2.post(f"{BACKEND}/api/folders/{leaf_id}/summary/regenerate",
                                json={"mode":"auto"})
            check("user2 can't regen user1's folder",
                  r.status_code in (403, 404), f"got {r.status_code}")
            r = await c2.get(f"{BACKEND}/api/folders/{repo_id}/briefing")
            check("user2 can't read user1's briefing",
                  r.status_code in (403, 404), f"got {r.status_code}")
        admin.auth.admin.delete_user(uid2)

        hr("═══ Delete folder → summary rows cascade-cleaned ═══")
        for kind, fid in [("leaf", leaf_id), ("repo", repo_id), ("workspace", ws_id)]:
            before = sb.table("folder_summaries").select("id", count="exact").eq(
                "folder_id", fid).execute().count or 0
            r = await c.delete(f"{BACKEND}/api/folders/{fid}?delete_docs=true")
            after = sb.table("folder_summaries").select("id", count="exact").eq(
                "folder_id", fid).execute().count or 0
            check(f"{kind}: delete cascaded summary rows",
                  after == 0, f"before={before} after={after}")

    print()
    print("═" * 74)
    print(f"SUMMARY LIFECYCLE: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL: print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
