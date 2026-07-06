"""End-to-end briefing lifecycle:

  1. Init a fresh test folder as a repo
  2. Baseline: read empty briefing (all 8 sections auto)
  3. Agent (MCP) replaces ALL 8 sections in one call → persisted, pinned
  4. REST GET /briefing sees the replacement
  5. Agent updates ONE section via update_folder_briefing_section
  6. UI PATCH one section via /briefing/section/{name}
  7. UI PUT /briefing (partial replace of 3 sections)
  8. Reset one section via POST /briefing/section/{name}/reset
  9. Verify provenance across all edits (user_ui vs agent_mcp)
 10. Adversarial: unknown section name rejected (both MCP + REST)
 11. Adversarial: cross-user scope violation
 12. CLI 'briefing' output shows sections + status chips
"""

from __future__ import annotations
import asyncio, json, os, subprocess, sys, tempfile, uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

CLI = "/Users/feliperamosdasilva/personal_projects/kioku/cli/dist/index.js"
BACKEND = "http://localhost:8000"
MCP_URL = "http://localhost:8001/sse"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]

PASS, FAIL = [], []
def check(n, cond, d=""):
    (PASS if cond else FAIL).append(n)
    print(f"  {'✓' if cond else '✗'} {n}" + (f" — {d[:250]}" if not cond else ""))
def hr(t): print(); print("═" * 78); print(f"  {t}"); print("═" * 78)


def get_token():
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link({"type":"magiclink","email":"felipe.meriga@gmail.com"}).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp({"email":"felipe.meriga@gmail.com","token":otp,"type":"email"})
    return e.session.access_token, e.user.id


async def mcp_call(api_key: str, tool: str, args: dict) -> str:
    async with sse_client(MCP_URL, headers={"Authorization": f"Bearer {api_key}"}) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            r = await s.call_tool(tool, args)
            return "\n".join(b.text for b in r.content if hasattr(b, "text"))


async def main():
    from db.client import get_supabase
    sb = get_supabase()
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}

    hr("Setup: create a scratch repo folder + mint api key")
    scratch_name = f"e2e-lifecycle-{uuid.uuid4().hex[:6]}"
    async with httpx.AsyncClient(timeout=45, headers=H) as c:
        r = await c.post(f"{BACKEND}/api/folders", json={"name": scratch_name, "parent_id": None})
        folder_id = r.json()["id"]
        r = await c.patch(f"{BACKEND}/api/folders/{folder_id}", json={"kind": "repo"})
        check("scratch folder → kind=repo",
              r.json().get("kind") == "repo", r.text[:200])

        r = await c.post(f"{BACKEND}/api/api-keys", json={
            "name": "e2e-briefing-lifecycle", "scope_folder_id": folder_id,
        })
        api_key = r.json()["key"]
        print(f"  api_key: {api_key[:16]}…  folder: {folder_id}")

        hr("Step 2: baseline — read empty briefing (8 sections, all auto)")
        r = await c.get(f"{BACKEND}/api/folders/{folder_id}/briefing")
        base = r.json()
        check("baseline briefing has 8 sections",
              len(base.get("sections") or {}) == 8,
              f"got: {list((base.get('sections') or {}).keys())}")
        check("baseline sections all default status='auto'",
              all(s.get("status") == "auto" for s in base["sections"].values()),
              f"statuses: {[s.get('status') for s in base['sections'].values()]}")

        hr("Step 3: MCP replace_folder_briefing — all 8 sections at once")
        new_briefing = {
            "overview": {
                "purpose": "E2E lifecycle target.",
                "description": "This briefing was written by the E2E lifecycle test.",
            },
            "architecture": {
                "summary": "Backend + frontend + MCP.",
                "components": [
                    {"name": "backend", "role": "REST + streaming", "path": "backend/"},
                ],
                "data_flow": "User → frontend → REST → agent → tools → response.",
            },
            "preferences": {"rules": ["use uv", "never use --amend on shared branches"]},
            "important_files": [
                {"path": "backend/main.py", "role": "FastAPI entry", "why": "route wiring"},
            ],
            "how_it_runs": {
                "requirements": ["Python 3.10", "Node 20", "Redis"],
                "local_dev": "cd backend && uv run uvicorn main:app --reload",
            },
            "deployment": {
                "environments": ["prod: rag.merigafy.com"],
                "how_to_deploy": "docker compose up -d --build",
                "ci_cd_notes": ".github/workflows/deploy.yml",
            },
            "dependencies": {"runtime": ["FastAPI", "Anthropic"], "services": ["Redis", "Supabase"]},
            "activity": {"recent_commits": [], "recent_prs": [], "recent_learnings": []},
        }
        result = await mcp_call(api_key, "replace_folder_briefing", {
            "sections": json.dumps(new_briefing), "pin_all": True,
        })
        try:
            resp = json.loads(result)
            check("MCP replace returned ok + 8 replaced",
                  resp.get("ok") and len(resp.get("replaced") or []) == 8,
                  result[:300])
        except Exception:
            check("MCP replace returned JSON", False, result[:300])

        hr("Step 4: REST GET sees the MCP replacement")
        r = await c.get(f"{BACKEND}/api/folders/{folder_id}/briefing")
        b = r.json()
        ov = b["sections"]["overview"]
        check("GET sees overview from MCP replace",
              ov.get("provenance") == "agent_mcp" and ov.get("status") == "pinned",
              f"prov={ov.get('provenance')} status={ov.get('status')}")
        check("overview content matches", ov["content"]["purpose"] == "E2E lifecycle target.",
              str(ov["content"]))
        # All 8 sections should now be pinned + agent_mcp
        pinned = sum(1 for s in b["sections"].values() if s.get("status") == "pinned")
        check("all 8 sections now pinned", pinned == 8, f"got: {pinned}/8")

        hr("Step 5: MCP updates ONE section (important_files)")
        r_txt = await mcp_call(api_key, "update_folder_briefing_section", {
            "section": "important_files",
            "content": json.dumps([
                {"path": "backend/mcp_server.py", "role": "MCP surface", "why": "tool wiring"},
                {"path": "backend/routes/briefing.py", "role": "REST briefing", "why": "editor endpoints"},
            ]),
            "pin": True,
        })
        check("MCP update_folder_briefing_section landed", "Updated" in r_txt, r_txt[:200])

        r = await c.get(f"{BACKEND}/api/folders/{folder_id}/briefing")
        b = r.json()
        imp = b["sections"]["important_files"]
        check("important_files updated by agent_mcp",
              imp["provenance"] == "agent_mcp"
              and isinstance(imp["content"], list) and len(imp["content"]) == 2,
              f"content: {imp['content']}")

        hr("Step 6: UI PATCHes one section (deployment)")
        new_deployment = {
            "environments": ["prod: NEW-URL"],
            "how_to_deploy": "Updated via UI PATCH",
            "ci_cd_notes": "Also updated",
        }
        r = await c.patch(
            f"{BACKEND}/api/folders/{folder_id}/briefing/section/deployment",
            json={"content": new_deployment, "status": "pinned"},
        )
        check("UI PATCH returns ok", r.status_code == 200 and r.json().get("ok") is True,
              r.text[:200])

        r = await c.get(f"{BACKEND}/api/folders/{folder_id}/briefing")
        dep = r.json()["sections"]["deployment"]
        check("deployment updated by user_ui",
              dep["provenance"] == "user_ui"
              and dep["content"]["how_to_deploy"] == "Updated via UI PATCH",
              f"content: {dep['content']}")

        hr("Step 7: UI PUT (partial replace of 3 sections)")
        r = await c.put(f"{BACKEND}/api/folders/{folder_id}/briefing",
                         json={
                             "sections": {
                                 "overview": {"purpose": "PUT-P", "description": "PUT-D"},
                                 "preferences": {"rules": ["PUT rule 1", "PUT rule 2"]},
                                 "dependencies": {"runtime": ["PUT-A"], "services": ["PUT-B"]},
                             },
                             "pin_all": True,
                         })
        check("UI PUT partial replace: 200",
              r.status_code == 200
              and r.json().get("replaced_sections") == ["overview", "preferences", "dependencies"],
              r.text[:300])
        r = await c.get(f"{BACKEND}/api/folders/{folder_id}/briefing")
        b = r.json()
        check("PUT replaced overview",
              b["sections"]["overview"]["content"]["purpose"] == "PUT-P")
        check("PUT preserved important_files from MCP update",
              b["sections"]["important_files"]["content"][0]["path"] == "backend/mcp_server.py")

        hr("Step 8: reset a section — clears pinning, re-runs populator")
        r = await c.post(
            f"{BACKEND}/api/folders/{folder_id}/briefing/section/dependencies/reset"
        )
        check("reset returns ok", r.status_code == 200)
        r = await c.get(f"{BACKEND}/api/folders/{folder_id}/briefing")
        deps = r.json()["sections"]["dependencies"]
        check("after reset: status=auto", deps["status"] == "auto",
              f"status={deps['status']}")

        hr("Step 9: verify mixed provenance in same briefing")
        r = await c.get(f"{BACKEND}/api/folders/{folder_id}/briefing")
        b = r.json()
        by_prov: dict[str, list[str]] = {}
        for name, s in b["sections"].items():
            by_prov.setdefault(s["provenance"], []).append(name)
        print(f"    provenance breakdown: {by_prov}")
        check("has agent_mcp sections",
              "agent_mcp" in by_prov and len(by_prov["agent_mcp"]) >= 1,
              f"got: {by_prov}")
        check("has user_ui sections",
              "user_ui" in by_prov and len(by_prov["user_ui"]) >= 1,
              f"got: {by_prov}")

        hr("Step 10: unknown section name → 400 (REST) + Error (MCP)")
        r = await c.patch(
            f"{BACKEND}/api/folders/{folder_id}/briefing/section/nonsense",
            json={"content": "x"},
        )
        check("REST PATCH unknown section → 400",
              r.status_code == 400 and "nonsense" in r.text.lower(),
              r.text[:300])

        r = await c.put(f"{BACKEND}/api/folders/{folder_id}/briefing",
                         json={"sections": {"NOT_A_SECTION": {}}, "pin_all": True})
        check("REST PUT unknown section → 400",
              r.status_code == 400,
              r.text[:300])

        result = await mcp_call(api_key, "replace_folder_briefing", {
            "sections": json.dumps({"nonexistent": {}}), "pin_all": True,
        })
        check("MCP replace unknown → Error",
              result.startswith("Error"), result[:300])

        hr("Step 11: adversarial — cross-user")
        # Make a second user
        admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
        email2 = f"lifecycle-{uuid.uuid4().hex[:6]}@example.test"
        r2 = admin.auth.admin.create_user({
            "email": email2, "email_confirm": True,
            "password": "TestPass!" + uuid.uuid4().hex,
        })
        uid2 = r2.user.id
        otp = admin.auth.admin.generate_link({"type":"magiclink","email":email2}).properties.email_otp
        anon2 = create_client(SUPABASE_URL, ANON)
        e2 = anon2.auth.verify_otp({"email": email2, "token": otp, "type": "email"})
        H2 = {"Authorization": f"Bearer {e2.session.access_token}"}
        async with httpx.AsyncClient(timeout=30, headers=H2) as c2:
            r = await c2.put(
                f"{BACKEND}/api/folders/{folder_id}/briefing",
                json={"sections": {"overview": {}}, "pin_all": True},
            )
            check("user2 PUT user1 briefing → 4xx",
                  r.status_code in (400, 403, 404), r.text[:200])
        admin.auth.admin.delete_user(uid2)

        hr("Step 12: CLI 'briefing' output shows all sections")
        temp = Path(tempfile.mkdtemp(prefix="e2e-lifecycle-cli-"))
        try:
            # Isolated home with the same session
            xdg = temp / "xdg" / "agentic-rag"
            xdg.mkdir(parents=True)
            _tok, _uid = get_token()
            (xdg / "config.json").write_text(json.dumps({
                "api_base": BACKEND, "access_token": _tok,
                "refresh_token": "", "expires_at": 0,
                "user_id": _uid, "email": "felipe.meriga@gmail.com",
            }))
            # Write mcp.json + state file for the CLI to find
            repo = temp / "repo"
            repo.mkdir()
            (repo / ".mcp.json").write_text(json.dumps({
                "mcpServers": {"agentic-rag": {
                    "url": MCP_URL,
                    "headers": {"Authorization": f"Bearer {api_key}"},
                }}
            }))
            (repo / ".claude").mkdir()
            (repo / ".claude" / "agentic-rag-state.json").write_text(json.dumps({
                "folder_id": folder_id,
                "folder_name": scratch_name,
                "scope_root_name": scratch_name,
            }))
            env = os.environ.copy()
            env["XDG_CONFIG_HOME"] = str(temp / "xdg")
            env["AGENTIC_RAG_API_BASE"] = BACKEND
            r = subprocess.run(
                ["node", CLI, "briefing"],
                capture_output=True, text=True, env=env, cwd=str(repo), timeout=60,
            )
            check("CLI briefing exit 0", r.returncode == 0, r.stderr[:300])
            for section_name in [
                "Overview", "Architecture", "Preferences",
                "Important files", "How it runs", "Deployment",
                "Dependencies", "Activity",
            ]:
                check(f"CLI briefing shows '{section_name}'",
                      section_name in r.stdout, r.stdout[:400])
            check("CLI briefing shows PINNED chip on at least one section",
                  "PINNED" in r.stdout, r.stdout[-800:])
            check("CLI briefing shows provenance (agent MCP)",
                  "agent (MCP)" in r.stdout, r.stdout[-800:])
        finally:
            import shutil
            shutil.rmtree(temp)

        hr("Cleanup: api key + folder")
        keys_row = (await c.get(f"{BACKEND}/api/api-keys")).json()
        for k in keys_row:
            if k["name"] == "e2e-briefing-lifecycle":
                await c.delete(f"{BACKEND}/api/api-keys/{k['id']}")
        await c.delete(f"{BACKEND}/api/folders/{folder_id}?delete_docs=true")

    print()
    print("═" * 78)
    print(f"BRIEFING LIFECYCLE: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 78)
    for n in FAIL:
        print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
