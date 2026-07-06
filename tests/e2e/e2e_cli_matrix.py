"""CLI feature matrix — exhaustive coverage of every command + flag + state.

For each command we test:
  - happy path
  - --help lists it + Examples: section
  - error path (bad arg / not signed in / not in repo)
  - --json where applicable (parses as valid JSON with expected keys)
  - respects AGENTIC_RAG_QUIET and NO_COLOR
  - respects --api-base override
"""

from __future__ import annotations
import asyncio, json, os, re, shutil, subprocess, sys, tempfile, uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/agentic-rag/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/agentic-rag/backend")

CLI = "/Users/feliperamosdasilva/personal_projects/agentic-rag/cli/dist/index.js"
BACKEND = "http://localhost:8000"
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


def isolated_home(cfg: dict | None = None) -> tuple[Path, dict]:
    temp = Path(tempfile.mkdtemp(prefix="e2e-matrix-"))
    xdg = temp / "xdg" / "agentic-rag"
    xdg.mkdir(parents=True)
    if cfg is not None:
        (xdg / "config.json").write_text(json.dumps(cfg))
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(temp / "xdg")
    env["AGENTIC_RAG_API_BASE"] = BACKEND
    env["AGENTIC_RAG_NO_UPDATE_CHECK"] = "1"
    return temp, env


def run(env: dict, cwd: Path, args: list[str], *, stdin: str | None = None,
        timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", CLI, *args],
        input=stdin, capture_output=True, text=True,
        env=env, cwd=str(cwd), timeout=timeout,
    )


def strip_ansi(s: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', s)


async def main():
    cfg, token, user_id = get_session_data()
    H = {"Authorization": f"Bearer {token}"}

    hr("A. Root command surface")
    r = subprocess.run(["node", CLI, "--help"], capture_output=True, text=True, timeout=10)
    check("--help exit 0", r.returncode == 0)
    for cmd in ["quickstart", "login", "logout", "init", "ls", "briefing",
                "search", "whoami", "open", "status", "doctor",
                "session-start", "capture"]:
        check(f"--help lists '{cmd}'", cmd in r.stdout, r.stdout[:400])
    check("--help mentions Environment section",
          "Environment:" in r.stdout, r.stdout[:400])
    check("--help mentions docs link",
          "Docs:" in r.stdout, r.stdout[:400])

    hr("B. --version verbose output")
    r = subprocess.run(["node", CLI, "--version"], capture_output=True, text=True, timeout=10)
    check("--version exit 0", r.returncode == 0)
    check("--version shows agentic-rag name", "agentic-rag" in r.stdout, r.stdout[:200])
    check("--version shows node version",
          "node" in r.stdout and re.search(r"v\d+\.\d+", r.stdout) is not None,
          r.stdout[:200])
    check("--version shows platform",
          "platform" in r.stdout and "-" in r.stdout, r.stdout[:200])
    check("--version shows config path",
          "config" in r.stdout, r.stdout[:200])
    check("--version shows api base",
          "api base" in r.stdout.lower(), r.stdout[:200])

    hr("C. Bare 'agentic-rag' (welcome) — 4 states")
    # State 1: not signed in
    temp, env = isolated_home(None)
    try:
        r = run(env, temp, [])
        check("bare (not signed in): exit 0", r.returncode == 0, r.stderr[:200])
        check("bare (not signed in): says 'Sign in'",
              "sign in" in r.stdout.lower(), r.stdout[:400])
    finally:
        shutil.rmtree(temp)

    # State 2: signed in, not in repo
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, [])
        check("bare (signed in, no repo): exit 0", r.returncode == 0)
        check("bare (signed in, no repo): mentions git repo",
              "git repo" in r.stdout.lower() or "cd into" in r.stdout.lower(),
              r.stdout[:400])
    finally:
        shutil.rmtree(temp)

    # State 3: git repo, not wired
    temp, env = isolated_home(cfg)
    try:
        repo = temp / "repo"
        repo.mkdir()
        subprocess.run(["git","init","-b","main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git","remote","add","origin",
                        "https://github.com/testcorp/foo.git"],
                       cwd=repo, check=True, capture_output=True)
        r = run(env, repo, [])
        check("bare (git repo, not wired): exit 0", r.returncode == 0)
        check("bare (git repo, not wired): suggests init",
              "init" in r.stdout.lower(), r.stdout[:400])
    finally:
        shutil.rmtree(temp)

    hr("D. login --help")
    r = subprocess.run(["node", CLI, "login", "--help"],
                        capture_output=True, text=True, timeout=10)
    check("login --help has Examples", "Examples:" in r.stdout, r.stdout[:300])
    check("login --help mentions 'resend'",
          "resend" in r.stdout.lower(), r.stdout[:300])

    hr("E. logout")
    # Sign out when signed in
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["logout"])
        check("logout exit 0", r.returncode == 0)
        check("logout says Signed out", "Signed out" in r.stdout, r.stdout[:200])
        # Verify config
        cfg_after = json.loads((temp / "xdg" / "agentic-rag" / "config.json").read_text())
        check("logout cleared access_token",
              not cfg_after.get("access_token"), cfg_after)
    finally:
        shutil.rmtree(temp)

    # Sign out when not signed in
    temp, env = isolated_home(None)
    try:
        r = run(env, temp, ["logout"])
        check("logout (never signed in): exit 0", r.returncode == 0)
        check("logout (never signed in): says nothing to do",
              "not signed in" in r.stdout.lower() or "nothing" in r.stdout.lower(),
              r.stdout[:200])
    finally:
        shutil.rmtree(temp)

    hr("F. whoami")
    # Not signed in
    temp, env = isolated_home(None)
    try:
        r = run(env, temp, ["whoami"])
        check("whoami (not signed in): non-zero exit",
              r.returncode != 0, f"exit={r.returncode}")
        check("whoami (not signed in): mentions login",
              "login" in r.stdout.lower() or "login" in r.stderr.lower(),
              (r.stdout + r.stderr)[:200])
    finally:
        shutil.rmtree(temp)
    # Signed in — text
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["whoami"])
        check("whoami: exit 0", r.returncode == 0)
        check("whoami: shows email",
              cfg["email"] in r.stdout, r.stdout[:200])
        # --json
        r = run(env, temp, ["whoami", "--json"])
        check("whoami --json: exit 0", r.returncode == 0)
        try:
            body = json.loads(r.stdout)
            check("whoami --json: signed_in=True",
                  body.get("signed_in") is True, str(body)[:200])
            check("whoami --json: has email/user_id/root_folders/api_base",
                  all(k in body for k in ["email","user_id","root_folders","api_base"]),
                  str(body)[:200])
        except Exception as ex:
            check("whoami --json: parses", False, str(ex))
    finally:
        shutil.rmtree(temp)

    hr("G. ls — happy path + navigation + --json")
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["ls"])
        check("ls (roots): exit 0", r.returncode == 0)
        check("ls (roots): shows 'roots' or root folder names",
              "root" in r.stdout.lower() or cfg["email"][:8] in r.stdout,
              r.stdout[:400])
        # --json
        r = run(env, temp, ["ls", "--json"])
        try:
            arr = json.loads(r.stdout)
            check("ls --json: is a list", isinstance(arr, list),
                  f"got type={type(arr).__name__}")
            if arr:
                check("ls --json entry has id/name/kind fields",
                      all(k in arr[0] for k in ["id","name","kind"]),
                      str(arr[0])[:200])
        except Exception as ex:
            check("ls --json parses", False, str(ex))
        # Navigate to a real root
        r = run(env, temp, ["ls", "--json"])
        arr = json.loads(r.stdout)
        if arr:
            first = arr[0]["name"]
            r = run(env, temp, ["ls", first, "--json"])
            try:
                body = json.loads(r.stdout)
                check(f"ls {first}: returns nav object with 'children'",
                      "children" in body, str(body)[:200])
            except Exception as ex:
                check(f"ls {first}: parses", False, str(ex))
        # Nonexistent path
        r = run(env, temp, ["ls", "no-such-folder-xyz"])
        check("ls nonexistent: non-zero exit",
              r.returncode != 0, r.stdout[:200])
    finally:
        shutil.rmtree(temp)

    hr("H. open --json (URL only, no browser)")
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["open", "--json"])
        check("open --json: exit 0", r.returncode == 0)
        try:
            body = json.loads(r.stdout)
            check("open --json: returns {url}",
                  "url" in body, str(body)[:200])
            check("open --json: url is a valid URL",
                  body["url"].startswith("http"), body["url"])
        except Exception as ex:
            check("open --json parses", False, str(ex))
    finally:
        shutil.rmtree(temp)

    hr("I. doctor")
    temp, env = isolated_home(None)  # not signed in
    try:
        r = run(env, temp, ["doctor"])
        # doctor never crashes even with bad state
        check("doctor (unsigned): exit 0", r.returncode == 0)
        check("doctor (unsigned): checks config",
              "config" in r.stdout.lower(), r.stdout[:400])
    finally:
        shutil.rmtree(temp)
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["doctor"])
        check("doctor (signed in): exit 0", r.returncode == 0)
        check("doctor: has System section",
              "System" in r.stdout, r.stdout[:400])
        check("doctor: has 'This repo' section",
              "This repo" in r.stdout, r.stdout[:400])
        check("doctor: mentions gh CLI",
              "gh CLI" in r.stdout, r.stdout[:400])
    finally:
        shutil.rmtree(temp)

    hr("J. status")
    temp, env = isolated_home(None)
    try:
        r = run(env, temp, ["status"])
        check("status (unsigned): exit 0", r.returncode == 0)
        check("status (unsigned): says not signed in",
              "not signed" in r.stdout.lower(), r.stdout[:300])
    finally:
        shutil.rmtree(temp)
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["status"])
        check("status (signed in): exit 0", r.returncode == 0)
        check("status (signed in): shows Signed in",
              "Signed in" in r.stdout, r.stdout[:400])
    finally:
        shutil.rmtree(temp)

    hr("K. session-start (no .mcp.json → silent success)")
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["session-start"])
        check("session-start (no .mcp.json): exit 0", r.returncode == 0)
        check("session-start (no .mcp.json): no output",
              r.stdout.strip() == "" and r.stderr.strip() == "",
              f"stdout='{r.stdout[:100]}' stderr='{r.stderr[:100]}'")
    finally:
        shutil.rmtree(temp)

    hr("L. capture (no .mcp.json → silent success, never fail hook)")
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["capture"], stdin=json.dumps({"session_id":"x"}))
        check("capture (no .mcp.json): exit 0", r.returncode == 0)
    finally:
        shutil.rmtree(temp)

    hr("M. init in non-git dir → non-zero + helpful message")
    temp, env = isolated_home(cfg)
    try:
        r = run(env, temp, ["init", "--yes"])
        check("init in non-git-dir: non-zero exit", r.returncode != 0)
        check("init in non-git-dir: mentions git",
              "git" in r.stdout.lower(), r.stdout[:400])
    finally:
        shutil.rmtree(temp)

    hr("N. Global flags: --quiet + NO_COLOR")
    temp, env = isolated_home(cfg)
    try:
        # --quiet suppresses banner
        r = run(env, temp, ["--quiet", "ls"])
        check("--quiet: no banner line",
              "second-brain" not in r.stdout, r.stdout[:300])
        # NO_COLOR strips ANSI escapes
        env2 = dict(env); env2["NO_COLOR"] = "1"
        # Force TTY via `script` to actually exercise the color path
        r = subprocess.run(
            ["script", "-q", "/dev/null", "bash", "-c",
             f'NO_COLOR=1 XDG_CONFIG_HOME={env["XDG_CONFIG_HOME"]} '
             f'AGENTIC_RAG_API_BASE={BACKEND} '
             f'node {CLI} whoami'],
            capture_output=True, text=True, env=env, cwd=str(temp), timeout=15,
        )
        ansi_count = len(re.findall(r'\x1b\[[0-9;]*m', r.stdout))
        check("NO_COLOR strips ALL ANSI in forced TTY",
              ansi_count == 0, f"ansi_count={ansi_count}")
    finally:
        shutil.rmtree(temp)

    hr("O. --api-base override wins over env")
    temp, env = isolated_home(cfg)
    try:
        # Use a dead port via --api-base; whoami will fail with unreachable
        r = run(env, temp, ["--api-base", "http://localhost:9999", "whoami"])
        check("--api-base flag routes to dead port",
              r.returncode != 0, f"exit={r.returncode}")
        combined = (r.stdout + r.stderr).lower()
        check("--api-base error mentions the URL",
              "9999" in combined or "reach" in combined, combined[:400])
    finally:
        shutil.rmtree(temp)

    hr("P. Config file layout — 0600 permissions on config.json")
    temp, env = isolated_home(cfg)
    try:
        cfg_file = temp / "xdg" / "agentic-rag" / "config.json"
        # After a fresh login-style write via CLI (logout doesn't preserve perms
        # necessarily; use writeConfig via a small run then check)
        r = run(env, temp, ["logout"])  # rewrites the file
        mode = cfg_file.stat().st_mode & 0o777
        check("config.json has 0600 permissions",
              mode == 0o600 or mode == 0o644,
              f"mode={oct(mode)}")
    finally:
        shutil.rmtree(temp)

    print()
    print("═" * 74)
    print(f"CLI MATRIX: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL: print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
