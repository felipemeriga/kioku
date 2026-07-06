"""REST sanity walk — probes every backend endpoint we've built, logging
pass/fail. Also collects HTTP status + response snippets for anything
unexpected.

Categories:
  A. Docs + folders CRUD
  B. Chat + conversations
  C. Folder summaries
  D. Mem0 integration + memory ops
  E. GitHub integration
  F. API keys
  G. Retrieval log
  H. Documents content endpoint (per viewable_as)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/agentic-rag/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/agentic-rag/backend")

BACKEND = "http://localhost:8000"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = "sb_publishable_VkQ6BsMHRpz1kiCSerG45g_KiW0o9hx"

MEM0_KEY = "m0-DOov2IyXkEkeDTYOJPM1RP06YPOeNDn5WLvxT8Oa"


def hr(t):
    print(); print("═" * 78); print(f"  {t}"); print("═" * 78)


PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
        PASS.append(name)
    else:
        print(f"  ✗ {name} — {detail}")
        FAIL.append((name, detail))


def get_token():
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link({"type":"magiclink","email":"felipe.meriga@gmail.com"}).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp({"email":"felipe.meriga@gmail.com","token":otp,"type":"email"})
    return e.session.access_token, e.user


async def main():
    token, user = get_token()
    H = {"Authorization": f"Bearer {token}"}
    user_id = user.id
    from db.client import get_supabase
    sb = get_supabase()

    async with httpx.AsyncClient(timeout=45, headers=H) as c:

        hr("A. Health + folders CRUD")
        r = await c.get(f"{BACKEND}/api/health")
        check("GET /api/health", r.status_code == 200, str(r.status_code))

        r = await c.get(f"{BACKEND}/api/folders")
        check("GET /api/folders", r.status_code == 200)
        roots = r.json()

        # Create + rename + delete a scratch folder
        fname = f"bughunt-{uuid.uuid4().hex[:6]}"
        r = await c.post(f"{BACKEND}/api/folders", json={"name": fname, "parent_id": None})
        check("POST /api/folders (create)", r.status_code == 200, r.text[:200])
        scratch = r.json() if r.status_code == 200 else {}
        scratch_id = scratch.get("id")

        if scratch_id:
            r = await c.patch(f"{BACKEND}/api/folders/{scratch_id}", json={"name": f"{fname}-renamed"})
            check("PATCH /api/folders/{id} (rename)", r.status_code == 200, r.text[:200])

            r = await c.get(f"{BACKEND}/api/folders/{scratch_id}/breadcrumbs")
            check("GET /api/folders/{id}/breadcrumbs", r.status_code == 200)

        # Bad IDs
        bogus = "00000000-0000-0000-0000-000000000000"
        r = await c.get(f"{BACKEND}/api/folders/{bogus}/breadcrumbs")
        check("GET breadcrumbs bogus id (200 empty)", r.status_code == 200 and r.json() == [])

        hr("B. Chat + conversations")
        r = await c.get(f"{BACKEND}/api/conversations")
        check("GET /api/conversations", r.status_code == 200)

        r = await c.post(f"{BACKEND}/api/conversations")
        check("POST /api/conversations (create)", r.status_code == 200)
        conv = r.json() if r.status_code == 200 else {}
        conv_id = conv.get("id")

        if conv_id:
            r = await c.patch(f"{BACKEND}/api/conversations/{conv_id}", json={"title": "Bug hunt renamed"})
            check("PATCH /api/conversations/{id} (rename)", r.status_code == 200)

            r = await c.patch(f"{BACKEND}/api/conversations/{conv_id}", json={"title": "   "})
            check("PATCH conversations empty title → 400", r.status_code in (400, 422),
                  f"got {r.status_code}: {r.text[:150]}")

            r = await c.get(f"{BACKEND}/api/conversations/{conv_id}")
            check("GET /api/conversations/{id} (with messages)", r.status_code == 200)

            r = await c.delete(f"{BACKEND}/api/conversations/{conv_id}")
            check("DELETE /api/conversations/{id}", r.status_code == 200)

        hr("C. Folder summaries")
        # Use the agentic-rag folder — it has data
        ar = sb.table("folders").select("id").eq("name","agentic-rag").eq("user_id",user_id).limit(1).execute().data[0]["id"]

        r = await c.get(f"{BACKEND}/api/folders/{ar}/summary")
        check("GET /api/folders/{id}/summary", r.status_code == 200)

        r = await c.get(f"{BACKEND}/api/folders/{ar}/summary/history?limit=5")
        check("GET /api/folders/{id}/summary/history", r.status_code == 200)

        r = await c.post(f"{BACKEND}/api/folders/{ar}/summary/regenerate", json={"mode": "auto"})
        check("POST regenerate mode=auto", r.status_code == 200, r.text[:150])

        r = await c.post(f"{BACKEND}/api/folders/{ar}/summary/regenerate", json={"mode": "invalid"})
        check("POST regenerate invalid mode → 400", r.status_code == 400,
              f"got {r.status_code}")

        r = await c.post(f"{BACKEND}/api/folders/{bogus}/summary/regenerate", json={"mode": "auto"})
        check("POST regenerate bogus folder → 404", r.status_code == 404)

        hr("D. Mem0 integration + memory ops")
        r = await c.get(f"{BACKEND}/api/mem0/configs")
        check("GET /api/mem0/configs", r.status_code == 200)
        ar_config = None
        for cfg in r.json():
            if cfg["root_folder_id"] == ar:
                ar_config = cfg
                break

        if ar_config:
            r = await c.post(f"{BACKEND}/api/mem0/configs/{ar_config['id']}/verify")
            check("POST verify Mem0 config", r.status_code == 200, r.text[:150])

            r = await c.get(f"{BACKEND}/api/mem0/configs/{ar_config['id']}/memories?scope=any&limit=100")
            check("GET config memories", r.status_code == 200)
            mems_before = len(r.json().get("memories", []))

            # Add memory with valid category
            unique = f"bug-hunt probe {uuid.uuid4().hex[:8]}"
            r = await c.post(f"{BACKEND}/api/mem0/memories", json={
                "root_folder_id": ar,
                "content": unique,
                "category": "note",
                "scope": "episodic",
            })
            check("POST memory valid", r.status_code == 200, r.text[:200])
            added_id = None
            if r.status_code == 200:
                added_id = (r.json().get("raw") or {}).get("results", [{}])[0].get("id")

            # Duplicate write → duplicate=True
            r2 = await c.post(f"{BACKEND}/api/mem0/memories", json={
                "root_folder_id": ar,
                "content": unique,
                "category": "note",
                "scope": "episodic",
            })
            check("POST memory duplicate returns duplicate=True",
                  r2.status_code == 200 and r2.json().get("duplicate") is True,
                  r2.text[:200])

            # Invalid category
            r = await c.post(f"{BACKEND}/api/mem0/memories", json={
                "root_folder_id": ar,
                "content": "bug-hunt bad cat",
                "category": "nonsense",
                "scope": "episodic",
            })
            check("POST memory invalid category → 422", r.status_code == 422)

            # Search
            r = await c.post(f"{BACKEND}/api/mem0/search", json={
                "root_folder_id": ar,
                "query": "package manager backend",
                "scope": "any",
                "limit": 3,
            })
            check("POST /api/mem0/search", r.status_code == 200)

            # Unified fanout search + retrieval_log write
            log_before = sb.table("retrieval_log").select("id", count="exact").execute().count or 0
            r = await c.post(f"{BACKEND}/api/mem0/unified-search", json={
                "root_folder_id": ar,
                "query": "package manager backend",
                "limit": 5,
            })
            check("POST /api/mem0/unified-search", r.status_code == 200)
            log_after = sb.table("retrieval_log").select("id", count="exact").execute().count or 0
            check("retrieval_log incremented on unified search", log_after > log_before,
                  f"before={log_before} after={log_after}")

            # Rules endpoint
            r = await c.get(f"{BACKEND}/api/mem0/memories/rules?root_folder_id={ar}")
            check("GET /api/mem0/memories/rules", r.status_code == 200)

            # Recent
            r = await c.get(f"{BACKEND}/api/mem0/memories/recent?root_folder_id={ar}&days=14&limit=10")
            check("GET /api/mem0/memories/recent", r.status_code == 200)

            # Deduplicate dry-run
            r = await c.post(f"{BACKEND}/api/mem0/configs/{ar_config['id']}/deduplicate?dry_run=true")
            check("POST deduplicate dry-run", r.status_code == 200, r.text[:150])

            # Clean up the probe memory
            if added_id:
                r = await c.delete(f"{BACKEND}/api/mem0/configs/{ar_config['id']}/memories/{added_id}")
                check("DELETE folder memory", r.status_code == 200)

            # Also delete the dedupe-detected probe (it was upserted with the same content)
            for m in (sb.table("retrieval_log").select("id").limit(0).execute().data or []):
                pass  # noop

        hr("E. GitHub integration")
        r = await c.get(f"{BACKEND}/api/github/configs")
        check("GET /api/github/configs", r.status_code == 200)

        gh_configs = r.json() if r.status_code == 200 else []
        ar_gh = next((cc for cc in gh_configs if cc["root_folder_id"] == ar), None)
        if ar_gh:
            r = await c.post(f"{BACKEND}/api/github/configs/{ar_gh['id']}/sync")
            check("POST github sync", r.status_code == 200, r.text[:200])

        # Repo picker with invalid token
        r = await c.post(f"{BACKEND}/api/github/repos", json={"token": "gho_bogus_bogus_bogus_bogus"})
        check("POST /api/github/repos invalid token → 400", r.status_code == 400,
              f"got {r.status_code}: {r.text[:200]}")

        # Connect to a public repo. Prefer gh CLI token to avoid GitHub's
        # anonymous 60/hr rate limit. Falls back to no-token which the
        # backend accepts for public repos.
        gh_token = None
        try:
            import subprocess as _sp
            gh_token = _sp.check_output(
                ["gh", "auth", "token"], stderr=_sp.DEVNULL, timeout=3
            ).decode().strip()
        except Exception:
            pass
        payload = {
            "root_folder_id": scratch_id,
            "repo_url": "sindresorhus/awesome",
            "since_days": 30,
        }
        if gh_token:
            payload["token"] = gh_token
        r = await c.post(f"{BACKEND}/api/github/connect", json=payload)
        # Treat 403 (rate limit) as a network issue, not a bug — pass
        # gracefully so the rest of the suite still runs.
        if r.status_code == 400 and "rate limit" in r.text.lower():
            print(f"  ⚠ GitHub public rate-limit hit — SKIP not FAIL")
            scratch_gh = {}
        else:
            check("POST github connect public repo", r.status_code == 200,
                  r.text[:200])
            scratch_gh = r.json() if r.status_code == 200 else {}

        # Disconnect
        if scratch_gh.get("id"):
            r = await c.delete(f"{BACKEND}/api/github/configs/{scratch_gh['id']}?delete_docs=true")
            check("DELETE github config with delete_docs", r.status_code == 200)

        hr("F. API keys")
        r = await c.get(f"{BACKEND}/api/api-keys")
        check("GET /api/api-keys", r.status_code == 200)

        # Create + delete
        r = await c.post(f"{BACKEND}/api/api-keys", json={
            "name": "bughunt-key",
            "scope_folder_id": ar,
        })
        check("POST api-keys", r.status_code == 200, r.text[:200])
        new_key = r.json() if r.status_code == 200 else {}
        if new_key.get("id"):
            r = await c.delete(f"{BACKEND}/api/api-keys/{new_key['id']}")
            check("DELETE api-keys", r.status_code == 200)

        # Bogus scope
        r = await c.post(f"{BACKEND}/api/api-keys", json={
            "name": "bughunt-bogus",
            "scope_folder_id": bogus,
        })
        check("POST api-keys bogus scope → 404", r.status_code == 404,
              f"got {r.status_code}: {r.text[:150]}")

        hr("G. Retrieval log")
        r = await c.get(f"{BACKEND}/api/retrieval-log?limit=5")
        check("GET /api/retrieval-log", r.status_code == 200)

        r = await c.get(f"{BACKEND}/api/retrieval-log/stats?since_days=30")
        check("GET /api/retrieval-log/stats", r.status_code == 200)

        hr("H. Documents content endpoint (per type)")
        # Find one doc in the agentic-rag folder
        docs = sb.table("documents").select("source_filename").eq(
            "folder_id", ar
        ).limit(1).execute().data
        if docs:
            fname = docs[0]["source_filename"]
            r = await c.get(f"{BACKEND}/api/documents/{fname}/content?folder_id={ar}")
            check("GET /api/documents/{filename}/content", r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                body = r.json()
                check("content endpoint returns viewable_as",
                      isinstance(body.get("viewable_as"), str), f"got {body.get('viewable_as')}")

        # Bogus file
        r = await c.get(f"{BACKEND}/api/documents/does-not-exist.txt/content")
        check("GET nonexistent doc content → 404", r.status_code == 404)

        # Delete the scratch folder (cascade cleans up)
        if scratch_id:
            r = await c.delete(f"{BACKEND}/api/folders/{scratch_id}")
            check("DELETE /api/folders/{id}", r.status_code == 200)

    print()
    print("═" * 78)
    print(f"REST SANITY WALK: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 78)
    for n in PASS[:5]:
        print(f"  ✓ {n}")
    if len(PASS) > 5:
        print(f"  … (+{len(PASS)-5} more passing)")
    for n, d in FAIL:
        print(f"  ✗ {n} — {d}")


if __name__ == "__main__":
    asyncio.run(main())
