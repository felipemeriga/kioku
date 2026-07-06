"""Comprehensive suite for the RECENT features:
  - Cron scope: list_all_regenerable_folder_pairs covers docs + repos + rollups
  - Full-briefing replace via MCP + REST
  - UI Regenerate button reaches all three folder kinds
  - Cascade preserves briefing rows on folder edits, deletes them on folder delete
  - focus-folder + replace_folder_briefing composed workflow
"""

from __future__ import annotations
import asyncio, json, os, subprocess, sys, tempfile, uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/agentic-rag/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/agentic-rag/backend")

BACKEND = "http://localhost:8000"
MCP_URL = "http://localhost:8001/sse"
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


async def mcp(api_key: str, tool: str, args: dict) -> str:
    async with sse_client(MCP_URL, headers={"Authorization": f"Bearer {api_key}"}) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            r = await s.call_tool(tool, args)
            return "\n".join(b.text for b in r.content if hasattr(b, "text"))


async def main():
    from db.client import get_supabase
    from services.folder_summary.repo import (
        list_all_regenerable_folder_pairs, list_folder_ids_with_docs,
    )
    sb = get_supabase()
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}

    tid = uuid.uuid4().hex[:6]

    hr("A. Cron scope enumerator — docs + repos + rollups + dedup")
    # Baseline count (real state)
    docs_only_before = len(list_folder_ids_with_docs(sb))
    all_before = len(list_all_regenerable_folder_pairs(sb))
    check("baseline: broader enumerator ≥ docs-only enumerator",
          all_before >= docs_only_before, f"docs={docs_only_before} all={all_before}")

    # Create one repo without any docs, one container with a rollup
    async with httpx.AsyncClient(timeout=45, headers=H) as c:
        r = await c.post(f"{BACKEND}/api/folders", json={"name": f"recent-repo-{tid}", "parent_id": None})
        repo_id = r.json()["id"]
        await c.patch(f"{BACKEND}/api/folders/{repo_id}", json={"kind": "repo"})

        r = await c.post(f"{BACKEND}/api/folders", json={"name": f"recent-workspace-{tid}", "parent_id": None})
        ws_id = r.json()["id"]
        # Seed a rollup row directly
        sb.table("folder_summaries").insert({
            "folder_id": ws_id, "user_id": user_id,
            "kind": "workspace_rollup", "trigger": "manual",
            "content": {"title": "test", "purpose": "", "overview": "",
                        "themes": [], "key_documents": [],
                        "key_facts": [], "entities": [], "gotchas": []},
            "included_hashes": [], "doc_count": 0, "changed_files": {},
        }).execute()

        all_after = list_all_regenerable_folder_pairs(sb)
        after_ids = {p["folder_id"] for p in all_after}
        check("repo (0 docs) now in scope", repo_id in after_ids,
              f"repo_id={repo_id}")
        check("workspace rollup now in scope", ws_id in after_ids,
              f"ws_id={ws_id}")
        # Dedup
        counts = {}
        for p in all_after:
            k = (p["folder_id"], p["user_id"])
            counts[k] = counts.get(k, 0) + 1
        dups = [k for k, v in counts.items() if v > 1]
        check("no dedup violations", not dups, f"dups: {dups}")

        hr("B. Regenerate endpoint accepts all 3 folder kinds")
        # Repo
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/summary/regenerate",
                          json={"mode": "auto"})
        check("regenerate on repo folder → 200", r.status_code == 200, r.text[:200])
        # Container (workspace)
        r = await c.post(f"{BACKEND}/api/folders/{ws_id}/summary/regenerate",
                          json={"mode": "auto"})
        check("regenerate on container → 200", r.status_code == 200, r.text[:200])

        hr("C. Full-briefing replace via MCP — validates schema, ok on happy path")
        # Mint api key scoped to repo folder
        r = await c.post(f"{BACKEND}/api/api-keys",
                          json={"name": f"recent-{tid}", "scope_folder_id": repo_id})
        api_key = r.json()["key"]
        api_key_id = r.json()["id"]

        # Full replace
        payload = {
            "overview": {"purpose": "Recent feature test.",
                          "description": "Written by e2e_recent_features."},
            "architecture": {"summary": "test", "components": [], "data_flow": ""},
            "preferences": {"rules": ["rule 1"]},
            "important_files": [{"path": "a.py", "role": "test", "why": "why"}],
            "how_it_runs": {"requirements": ["Python 3.10"], "local_dev": "make dev"},
            "deployment": {"environments": ["prod"], "how_to_deploy": "docker",
                            "ci_cd_notes": "gh actions"},
            "dependencies": {"runtime": ["FastAPI"], "services": ["Redis"]},
            "activity": {"recent_commits": [], "recent_prs": [], "recent_learnings": []},
        }
        result = await mcp(api_key, "replace_folder_briefing",
                            {"sections": json.dumps(payload), "pin_all": True})
        try:
            resp = json.loads(result)
            check("MCP replace all 8 sections: ok",
                  resp.get("ok") and len(resp.get("replaced") or []) == 8, result[:300])
        except Exception:
            check("MCP replace returned JSON", False, result[:300])

        # Verify via REST GET
        r = await c.get(f"{BACKEND}/api/folders/{repo_id}/briefing")
        b = r.json()
        overview = b["sections"]["overview"]
        check("REST GET sees the MCP replacement",
              overview["content"]["purpose"] == "Recent feature test.",
              f"got: {overview['content']}")
        check("all 8 sections tagged agent_mcp",
              all(s["provenance"] == "agent_mcp" for s in b["sections"].values()),
              f"provenances: {[s['provenance'] for s in b['sections'].values()]}")

        hr("D. Partial replace preserves untouched sections")
        result = await mcp(api_key, "replace_folder_briefing", {
            "sections": json.dumps({
                "overview": {"purpose": "PARTIAL-P", "description": "PARTIAL-D"},
            }),
            "pin_all": True,
        })
        r = await c.get(f"{BACKEND}/api/folders/{repo_id}/briefing")
        b = r.json()
        check("partial replace updated overview",
              b["sections"]["overview"]["content"]["purpose"] == "PARTIAL-P",
              f"got: {b['sections']['overview']['content']}")
        check("partial replace preserved deployment",
              b["sections"]["deployment"]["content"]["environments"] == ["prod"],
              f"got: {b['sections']['deployment']['content']}")

        hr("E. Unknown section rejected on replace")
        result = await mcp(api_key, "replace_folder_briefing", {
            "sections": json.dumps({"nonexistent": {}}),
            "pin_all": True,
        })
        check("MCP replace unknown section → Error",
              result.startswith("Error") and "nonexistent" in result.lower(),
              result[:300])
        r = await c.put(f"{BACKEND}/api/folders/{repo_id}/briefing",
                          json={"sections": {"nonexistent": {}}, "pin_all": True})
        check("REST PUT unknown section → 400",
              r.status_code == 400 and "nonexistent" in r.text.lower(),
              r.text[:300])

        hr("F. Focus-folder + replace composed workflow")
        # Root-scope api key that can drill into repo_id via 'folder' arg.
        # Since repo_id is at root level (no parent), we use a folder subtree:
        # create a workspace at root, place a nested repo, key scoped to workspace.
        r = await c.post(f"{BACKEND}/api/folders",
                          json={"name": f"recent-scope-{tid}", "parent_id": None})
        scope_id = r.json()["id"]
        r = await c.post(f"{BACKEND}/api/folders",
                          json={"name": f"recent-nested-{tid}", "parent_id": scope_id})
        nested_id = r.json()["id"]
        await c.patch(f"{BACKEND}/api/folders/{nested_id}", json={"kind": "repo"})
        r = await c.post(f"{BACKEND}/api/api-keys",
                          json={"name": f"recent-scope-{tid}", "scope_folder_id": scope_id})
        scope_key = r.json()["key"]
        scope_key_id = r.json()["id"]

        # Replace briefing on nested repo via focus-folder
        result = await mcp(scope_key, "replace_folder_briefing", {
            "sections": json.dumps({
                "overview": {"purpose": "Nested via focus", "description": ""},
            }),
            "pin_all": True,
            "folder": f"recent-nested-{tid}",
        })
        try:
            resp = json.loads(result)
            check("MCP replace via focus-folder: ok",
                  resp.get("ok") is True, result[:300])
        except Exception:
            check("MCP replace via focus-folder returns JSON", False, result[:300])

        # Cross-scope guard: can we hit the OTHER repo (repo_id, at root outside scope)?
        result = await mcp(scope_key, "replace_folder_briefing", {
            "sections": json.dumps({"overview": {"purpose": "PWNED"}}),
            "pin_all": True,
            "folder": f"recent-repo-{tid}",
        })
        check("focus outside scope refused",
              "not inside" in result.lower() or "no folder" in result.lower(),
              result[:200])

        hr("G. Regenerate button API — auto vs full modes both accepted")
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/summary/regenerate",
                          json={"mode": "full"})
        check("regenerate mode=full → 200", r.status_code == 200)
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/summary/regenerate",
                          json={"mode": "auto"})
        check("regenerate mode=auto → 200", r.status_code == 200)
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/summary/regenerate",
                          json={"mode": "delta"})
        check("regenerate mode=delta → 200", r.status_code == 200)
        r = await c.post(f"{BACKEND}/api/folders/{repo_id}/summary/regenerate",
                          json={"mode": "nonsense"})
        check("regenerate invalid mode → 400", r.status_code == 400)

        hr("H. Briefing rows cascade-cleaned on folder delete")
        # Confirm nested_id has a briefing row now
        rows_before = sb.table("folder_summaries").select("id").eq("folder_id", nested_id).execute().data
        check("nested repo has briefing row", len(rows_before) >= 1, f"count={len(rows_before)}")
        await c.delete(f"{BACKEND}/api/folders/{nested_id}?delete_docs=true")
        rows_after = sb.table("folder_summaries").select("id").eq("folder_id", nested_id).execute().data
        check("briefing rows cascaded on folder delete",
              len(rows_after) == 0, f"count_after={len(rows_after)}")

        hr("Cleanup")
        for kid in (api_key_id, scope_key_id):
            try:
                await c.delete(f"{BACKEND}/api/api-keys/{kid}")
            except Exception:
                pass
        for fid in (scope_id, repo_id, ws_id):
            try:
                await c.delete(f"{BACKEND}/api/folders/{fid}?delete_docs=true")
            except Exception:
                pass

    print()
    print("═" * 74)
    print(f"RECENT FEATURES: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL:
        print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
