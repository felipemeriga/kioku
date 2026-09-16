"""kioku-watcher — multi-user repo poller.

Twice a day (host cron), for every row in watched_repos:
  1. decrypt the owner's git key, ls-remote the principal branch
  2. if the SHA moved: clone/fetch the repo, seed the CLI bindings
     (.mcp.json + .claude/kioku-state.json) and run `kioku index`
     (graph + code chunks; embedding happens in the backend worker)
  3. record last_sha / last_run_at / last_error — auth failures are
     recorded, never silent (SSO revocations must surface).

Security posture: this process holds the master decryption key and the
service role, so REPO PARSING runs in a subprocess with a stripped
environment — a malicious repo exploiting the parser sees no secrets.

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, SECRETS_ENCRYPTION_KEY
     (same Fernet master key as the backend's NOTION_TOKEN_ENCRYPTION_KEY),
     KIOKU_MCP_URL (e.g. https://kioku.mcp.example.com/sse)
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from cryptography.fernet import Fernet

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
FERNET = Fernet(os.environ["SECRETS_ENCRYPTION_KEY"].encode())
MCP_URL = os.environ["KIOKU_MCP_URL"]
DATA = Path(os.environ.get("WATCHER_DATA", "/data"))

REST = f"{SUPABASE_URL}/rest/v1"
HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def rest_get(path: str, params: dict) -> list[dict]:
    r = requests.get(f"{REST}/{path}", headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def rest_patch(path: str, params: dict, body: dict) -> None:
    r = requests.patch(f"{REST}/{path}", headers=HEADERS, params=params, json=body, timeout=30)
    r.raise_for_status()


def decrypt(ciphertext: str) -> str:
    return FERNET.decrypt(ciphertext.encode()).decode()


def git_env(key_path: str) -> dict:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "GIT_SSH_COMMAND": (
            f"ssh -i {key_path} -o IdentitiesOnly=yes -o BatchMode=yes "
            "-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
        ),
        "GIT_TERMINAL_PROMPT": "0",
    }


def run_git(args: list[str], env: dict, cwd: str | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=600
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def seed_bindings(clone: Path, folder_id: str, folder_name: str, api_key: str) -> None:
    mcp = {
        "mcpServers": {
            "kioku": {
                "type": "sse",
                "url": MCP_URL,
                "headers": {"Authorization": f"Bearer {api_key}"},
            }
        }
    }
    (clone / ".mcp.json").write_text(json.dumps(mcp, indent=2) + "\n")
    claude_dir = clone / ".claude"
    claude_dir.mkdir(exist_ok=True)
    state_path = claude_dir / "kioku-state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            state = {}
    state.update({"folder_id": folder_id, "folder_name": folder_name})
    state_path.write_text(json.dumps(state, indent=2) + "\n")


def kioku_index(clone: Path) -> tuple[bool, str]:
    """Run `kioku index` with a STRIPPED environment: the parsing/upload
    subprocess must not inherit the service key or the master key."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
    }
    try:
        proc = subprocess.run(
            ["kioku", "index"],
            cwd=str(clone),
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        return False, "kioku index timed out (30m)"
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-400:]
    return proc.returncode == 0, tail


def process_repo(repo: dict, key_row: dict) -> None:
    rid = repo["id"]
    name = f"{repo['remote_url']} ({repo['branch']})"
    now = datetime.now(timezone.utc).isoformat()

    def record(patch: dict) -> None:
        rest_patch("watched_repos", {"id": f"eq.{rid}"}, {"last_run_at": now, **patch})

    tmpdir = "/dev/shm" if os.path.isdir("/dev/shm") else None
    with tempfile.NamedTemporaryFile("w", dir=tmpdir, suffix=".key", delete=True) as kf:
        kf.write(decrypt(key_row["private_key_encrypted"]))
        kf.flush()
        os.chmod(kf.name, stat.S_IRUSR | stat.S_IWUSR)
        env = git_env(kf.name)

        code, out, err = run_git(
            ["ls-remote", repo["remote_url"], f"refs/heads/{repo['branch']}"], env
        )
        if code != 0 or not out:
            msg = (err or f"branch {repo['branch']} not found")[:300]
            log(f"ERROR {name}: ls-remote failed — {msg}")
            record({"last_error": f"ls-remote: {msg}"})
            return
        remote_sha = out.split()[0]

        rest_patch(
            "user_git_keys",
            {"user_id": f"eq.{repo['user_id']}"},
            {"last_used_at": now},
        )

        if remote_sha == repo.get("last_sha"):
            log(f"{name}: up-to-date ({remote_sha[:10]})")
            record({"last_error": None})
            return

        clone = DATA / repo["user_id"] / repo["folder_id"]
        if not (clone / ".git").exists():
            clone.parent.mkdir(parents=True, exist_ok=True)
            log(f"{name}: initial clone")
            code, _, err = run_git(
                ["clone", "--branch", repo["branch"], repo["remote_url"], str(clone)], env
            )
            if code != 0:
                log(f"ERROR {name}: clone failed — {err[:300]}")
                record({"last_error": f"clone: {err[:300]}"})
                return
        else:
            code, _, err = run_git(["fetch", "origin", repo["branch"]], env, cwd=str(clone))
            if code == 0:
                code, _, err = run_git(
                    ["reset", "--hard", f"origin/{repo['branch']}"], env, cwd=str(clone)
                )
            if code != 0:
                log(f"ERROR {name}: fetch/reset failed — {err[:300]}")
                record({"last_error": f"fetch: {err[:300]}"})
                return

    folder = rest_get(
        "folders", {"id": f"eq.{repo['folder_id']}", "select": "name", "limit": "1"}
    )
    folder_name = folder[0]["name"] if folder else "repo"
    if not repo.get("api_key_encrypted"):
        log(f"ERROR {name}: no api key registered — re-run kioku init in the repo")
        record({"last_error": "no api key registered"})
        return
    seed_bindings(clone, repo["folder_id"], folder_name, decrypt(repo["api_key_encrypted"]))

    ok, tail = kioku_index(clone)
    if ok:
        log(f"{name}: indexed {remote_sha[:10]}")
        record({"last_sha": remote_sha, "last_error": None})
    else:
        log(f"ERROR {name}: kioku index failed — {tail[-200:]}")
        record({"last_error": f"index: {tail[-300:]}"})


def main() -> int:
    repos = rest_get("watched_repos", {"select": "*", "order": "created_at"})
    if not repos:
        log("no watched repos")
        return 0
    keys = {
        k["user_id"]: k
        for k in rest_get("user_git_keys", {"select": "user_id,private_key_encrypted"})
    }
    log(f"watching {len(repos)} repo(s) across {len({r['user_id'] for r in repos})} user(s)")
    failures = 0
    for repo in repos:
        key_row = keys.get(repo["user_id"])
        if not key_row:
            log(f"ERROR {repo['remote_url']}: user has no watcher key")
            continue
        try:
            process_repo(repo, key_row)
        except Exception as exc:  # noqa: BLE001 — one repo must never kill the run
            failures += 1
            log(f"ERROR {repo['remote_url']}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
