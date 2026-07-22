"""CLI stateful workflows — deep integration between commands + state.

  A. Full lifecycle: init → status → briefing → capture → status
  B. init flag combos: --root, --skip-github, --github-token, --yes
  C. init idempotency: 3 reruns don't duplicate CLAUDE.md block
  D. Repeated init after config drift (delete .mcp.json, rerun)
  E. briefing --section <name>
  F. briefing --json (parseable, has sections dict)
  G. search: proper output structure
  H. session-start with a valid .mcp.json → prints scope block
  I. capture threshold — first-fire vs subsequent
  J. Concurrent CLI calls: two `status` commands don't corrupt config
"""

from __future__ import annotations
import asyncio, json, os, re, shutil, subprocess, sys, tempfile, uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client

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
    print(f"  {'✓' if cond else '✗'} {n}" + (f" — {d[:220]}" if not cond else ""))
def hr(t): print(); print("═" * 74); print(f"  {t}"); print("═" * 74)


def get_session_data():
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link(
        {"type":"magiclink","email":"felipe.meriga@gmail.com"}
    ).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp(
        {"email":"felipe.meriga@gmail.com","token":otp,"type":"email"}
    )
    return {
        "api_base": BACKEND,
        "access_token": e.session.access_token,
        "refresh_token": e.session.refresh_token,
        "expires_at": e.session.expires_at,
        "user_id": e.user.id,
        "email": e.user.email,
    }, e.session.access_token, e.user.id


def isolated_repo(cfg: dict, remote: str = "https://github.com/felipemeriga/agentic-rag.git") -> tuple[Path, Path, dict]:
    temp = Path(tempfile.mkdtemp(prefix="e2e-stateful-"))
    xdg = temp / "xdg" / "kioku"
    xdg.mkdir(parents=True)
    (xdg / "config.json").write_text(json.dumps(cfg))
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(temp / "xdg")
    env["KIOKU_API_BASE"] = BACKEND
    env["KIOKU_NO_UPDATE_CHECK"] = "1"
    repo = temp / "repo"
    repo.mkdir()
    subprocess.run(["git","init","-b","main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git","remote","add","origin", remote],
                    cwd=repo, check=True, capture_output=True)
    return temp, repo, env


def run(env: dict, cwd: Path, args: list[str], *, stdin: str | None = None,
        timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", CLI, *args],
        input=stdin, capture_output=True, text=True,
        env=env, cwd=str(cwd), timeout=timeout,
    )


async def cleanup_api_keys(token: str):
    async with httpx.AsyncClient(timeout=15,
                                  headers={"Authorization": f"Bearer {token}"}) as c:
        keys = (await c.get(f"{BACKEND}/api/api-keys")).json()
        for k in keys:
            if k["name"].startswith("cli-"):
                await c.delete(f"{BACKEND}/api/api-keys/{k['id']}")


async def main():
    cfg, token, user_id = get_session_data()
    H = {"Authorization": f"Bearer {token}"}

    hr("A. Full lifecycle: init → status → briefing → status")
    temp, repo, env = isolated_repo(cfg)
    try:
        # init
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        check("A.1 init exit 0", r.returncode == 0, r.stderr[:300])
        check("A.1 init writes .mcp.json", (repo / ".mcp.json").exists())
        check("A.1 init writes settings", (repo / ".claude" / "settings.json").exists())
        check("A.1 init writes CLAUDE.md", (repo / "CLAUDE.md").exists())
        check("A.1 init writes state file",
              (repo / ".claude" / "kioku-state.json").exists())

        # status
        r = run(env, repo, ["status"])
        check("A.2 status shows all green after init",
              ".mcp.json wired" in r.stdout
              and "SessionStart hook installed" in r.stdout
              and "CLAUDE.md present" in r.stdout,
              r.stdout[-800:])

        # briefing — the just-inited repo should have a fresh briefing
        r = run(env, repo, ["briefing"])
        check("A.3 briefing exit 0", r.returncode == 0, r.stderr[:300])
        for section in ["Overview","Architecture","Preferences",
                         "Important files","How it runs","Deployment",
                         "Dependencies","Activity"]:
            check(f"A.3 briefing shows {section}",
                  section in r.stdout, r.stdout[:400])

        # status again — same result
        r = run(env, repo, ["status"])
        check("A.4 status idempotent",
              ".mcp.json wired" in r.stdout, r.stdout[-400:])
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    hr("B. init flag combos")
    # B.1 --skip-github still wires everything except GitHub
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        check("B.1 --skip-github: exit 0", r.returncode == 0)
        check("B.1 --skip-github: no 'GitHub sync configured'",
              "GitHub sync configured" not in r.stdout, r.stdout[-500:])
        check("B.1 --skip-github: .mcp.json still written",
              (repo / ".mcp.json").exists())
    finally:
        shutil.rmtree(temp)

    # B.2 explicit --github-token (invalid PAT) on a public repo — auth is skipped
    temp, repo, env = isolated_repo(cfg,
        "https://github.com/felipemeriga/agentic-rag.git")
    try:
        r = run(env, repo, [
            "init", "--yes", "--root", "personal",
            "--github-token", "ghp_thisisnotarealtoken1111111111111111"
        ])
        check("B.2 explicit token on public repo: exit 0",
              r.returncode == 0, r.stderr[:200])
    finally:
        shutil.rmtree(temp)

    # B.3 --root by ID (need to grab a real root ID)
    async with httpx.AsyncClient(timeout=15, headers=H) as c:
        w = (await c.get(f"{BACKEND}/api/cli/whoami")).json()
    root_ids = [f["id"] for f in w["root_folders"]]
    if root_ids:
        temp, repo, env = isolated_repo(cfg)
        try:
            r = run(env, repo, [
                "init", "--yes", "--root", root_ids[0], "--skip-github",
            ])
            check("B.3 --root by UUID: exit 0", r.returncode == 0, r.stderr[:300])
        finally:
            shutil.rmtree(temp)

    # B.4 --root by nonexistent name → non-zero
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, [
            "init", "--yes", "--root", "no-such-root-abc123", "--skip-github",
        ])
        check("B.4 --root nonexistent: non-zero exit",
              r.returncode != 0, f"exit={r.returncode}")
        check("B.4 --root nonexistent: helpful error",
              "no root folder" in (r.stdout + r.stderr).lower()
              or "no such" in (r.stdout + r.stderr).lower(),
              (r.stdout + r.stderr)[:400])
    finally:
        shutil.rmtree(temp)

    hr("C. init idempotency — 3 reruns don't duplicate CLAUDE.md block")
    temp, repo, env = isolated_repo(cfg)
    try:
        for i in range(3):
            r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
            check(f"C.{i+1} rerun exit 0", r.returncode == 0, r.stderr[:200])
        md = (repo / "CLAUDE.md").read_text()
        count = md.count("BEGIN kioku second-brain")
        check("C.final CLAUDE.md has exactly 1 second-brain block",
              count == 1, f"got {count}")
        # Same for hook — no duplicate SessionStart entries
        settings = json.loads((repo / ".claude" / "settings.json").read_text())
        hooks = settings.get("hooks", {}).get("SessionStart", [])
        cli_hooks = [h for h in hooks if "kioku" in h.get("command", "")]
        check("C.final SessionStart hook not duplicated",
              len(cli_hooks) == 1, f"got {len(cli_hooks)}")
        stop_hooks = [h for h in settings.get("hooks", {}).get("Stop", [])
                      if "kioku" in h.get("command", "")]
        check("C.final Stop hook not duplicated",
              len(stop_hooks) == 1, f"got {len(stop_hooks)}")
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    hr("D. Repeated init after config drift — user deletes .mcp.json")
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        assert (repo / ".mcp.json").exists()
        # User deletes .mcp.json (maybe accidentally)
        (repo / ".mcp.json").unlink()
        # Rerun init — should re-create it
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        check("D.1 init after .mcp.json delete: exit 0",
              r.returncode == 0, r.stderr[:200])
        check("D.1 init recreated .mcp.json",
              (repo / ".mcp.json").exists())
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    hr("E. briefing --section <name>")
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        assert r.returncode == 0
        r = run(env, repo, ["briefing", "--section", "preferences"])
        check("E.1 briefing --section preferences: exit 0",
              r.returncode == 0, r.stderr[:200])
        check("E.1 briefing --section shows only Preferences header",
              "Preferences" in r.stdout, r.stdout[:400])
        # Should NOT show the other section titles
        check("E.1 briefing --section shows exactly one section title",
              sum(1 for s in ["Overview","Architecture","Preferences",
                                "Important files","How it runs","Deployment",
                                "Dependencies","Activity"]
                  if s in r.stdout) == 1,
              r.stdout[:400])
        # Invalid section
        r = run(env, repo, ["briefing", "--section", "nonexistent"])
        check("E.2 briefing --section nonexistent: non-zero exit",
              r.returncode != 0, f"exit={r.returncode}")
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    hr("F. briefing --json (parseable)")
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        assert r.returncode == 0
        r = run(env, repo, ["briefing", "--json"])
        check("F.1 briefing --json: exit 0", r.returncode == 0, r.stderr[:200])
        try:
            body = json.loads(r.stdout)
            check("F.1 briefing --json has sections",
                  "sections" in body and len(body["sections"]) == 8,
                  f"got keys: {list(body.get('sections',{}).keys())}")
            check("F.1 briefing --json has folder",
                  "folder" in body and "name" in body["folder"],
                  str(body.get("folder"))[:200])
            check("F.1 briefing --json has schema_version",
                  "schema_version" in body,
                  str(body)[:200])
        except Exception as ex:
            check("F.1 briefing --json parses", False, str(ex))
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    hr("G. search command — output structure")
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        assert r.returncode == 0
        # Try search with --json
        r = run(env, repo, ["search", "--json", "--limit", "3", "backend", "python"])
        check("G.1 search --json exit 0", r.returncode == 0, r.stderr[:200])
        try:
            body = json.loads(r.stdout)
            check("G.1 search --json has hits array",
                  "hits" in body and isinstance(body["hits"], list),
                  str(body)[:200])
            check("G.1 search --json has query echoed",
                  body.get("query", "") == "backend python",
                  f"query: {body.get('query')}")
        except Exception as ex:
            check("G.1 search --json parses", False, str(ex))
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    hr("H. session-start with a valid .mcp.json → prints scope block")
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        assert r.returncode == 0
        r = run(env, repo, ["session-start"])
        check("H.1 session-start exit 0", r.returncode == 0, r.stderr[:200])
        check("H.1 session-start shows scope block",
              "kioku second-brain" in r.stdout, r.stdout[:400])
        check("H.1 session-start mentions Scope:",
              "Scope:" in r.stdout, r.stdout[:400])
        check("H.1 session-start mentions Tools available",
              "Tools available" in r.stdout, r.stdout[:400])
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    hr("I. capture threshold — first-fire needs 5 turns")
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        assert r.returncode == 0
        # Simulate a 3-turn transcript — should NOT fire (below threshold)
        env["KIOKU_DEBUG"] = "1"
        transcript = temp / "transcript.jsonl"
        transcript.write_text("\n".join(json.dumps({
            "type": "user" if i % 2 == 0 else "assistant",
            "message": {"role": "user" if i % 2 == 0 else "assistant",
                          "content": [{"type": "text", "text": f"turn {i}"}]}
        }) for i in range(3)))
        hook_payload = json.dumps({
            "session_id": f"cli-stateful-{uuid.uuid4().hex[:6]}",
            "transcript_path": str(transcript),
            "cwd": str(repo),
        })
        r = run(env, repo, ["capture"], stdin=hook_payload)
        check("I.1 capture below threshold: exit 0", r.returncode == 0)
        log_path = repo / ".claude" / "kioku-capture.log"
        if log_path.exists():
            log = log_path.read_text()
            check("I.1 log says threshold not met",
                  "threshold not met" in log or "no new turns" in log,
                  log[-400:])
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    hr("J. Concurrent CLI calls — two 'status' commands don't corrupt config")
    temp, repo, env = isolated_repo(cfg)
    try:
        r = run(env, repo, ["init", "--yes", "--root", "personal", "--skip-github"])
        assert r.returncode == 0
        # Fire 5 concurrent status calls
        cmds = [subprocess.Popen(
            ["node", CLI, "status"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, cwd=str(repo),
        ) for _ in range(5)]
        results = [c.wait() for c in cmds]
        check("J.1 all 5 concurrent status calls exit 0",
              all(rc == 0 for rc in results), f"returncodes: {results}")
        # Verify config is still valid JSON
        cfg_after = json.loads((temp / "xdg" / "kioku" / "config.json").read_text())
        check("J.1 config.json still valid after concurrent calls",
              cfg_after.get("access_token", "").startswith("ey")
              or cfg_after.get("access_token") == cfg["access_token"],
              str(cfg_after)[:200])
    finally:
        shutil.rmtree(temp)
        await cleanup_api_keys(token)

    print()
    print("═" * 74)
    print(f"CLI STATEFUL: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL: print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
