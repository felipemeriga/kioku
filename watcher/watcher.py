"""kioku-watcher — multi-user repo poller.

Twice a day, for every row in watched_repos:
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

Two run modes:
  - one-shot (default): run a single pass and exit — for manual runs.
  - service: set WATCH_SCHEDULE to comma-separated UTC times
    ("06:00,18:00") and the process runs a pass at startup, then sleeps
    until each scheduled time, forever. This is how the Dokploy-managed
    kioku-watcher container runs it.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from cryptography.fernet import Fernet

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
FERNET = Fernet(os.environ["SECRETS_ENCRYPTION_KEY"].encode())
MCP_URL = os.environ["KIOKU_MCP_URL"]
API_URL = os.environ.get("KIOKU_API_URL", "").rstrip("/")
DATA = Path(os.environ.get("WATCHER_DATA", "/data"))

# Which briefing prose sections go stale when which paths change. Prose is
# never auto-regenerated — this only powers the staleness WARNING.
SECTION_PATH_RULES: dict[str, list[str]] = {
    "dependencies": [
        "package.json",
        "package-lock.json",
        "pyproject.toml",
        "uv.lock",
        "cargo.toml",
        "go.mod",
        "requirements",
    ],
    "deployment": [".github/workflows/", "deploy/", "dockerfile"],
    "how_it_runs": ["docker-compose", "makefile", "scripts/", "run_", ".env.example"],
}
# architecture/overview go stale on broad source churn, not specific paths.
ARCH_CHURN_THRESHOLD = 10

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
    r = requests.patch(
        f"{REST}/{path}", headers=HEADERS, params=params, json=body, timeout=30
    )
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


def rest_post(path: str, body, headers_extra: dict | None = None) -> None:
    h = {**HEADERS, **(headers_extra or {})}
    r = requests.post(f"{REST}/{path}", headers=h, json=body, timeout=30)
    r.raise_for_status()


def compute_freshness(clone: Path, repo: dict, env: dict) -> None:
    """Compare git history against briefing section timestamps and record
    which prose sections are likely stale. Warning-only — never regenerates."""
    rows = rest_get(
        "folder_summaries",
        {
            "folder_id": f"eq.{repo['folder_id']}",
            "select": "generated_at,content",
            "order": "generated_at.desc",
            "limit": "1",
        },
    )
    if not rows:
        return  # no briefing yet — nothing to be stale
    generated_at = rows[0]["generated_at"]
    content = rows[0].get("content") or {}
    sections = (
        content.get("sections")
        if isinstance(content.get("sections"), dict)
        else content
    )

    code, head, _ = run_git(["rev-parse", "HEAD"], env, cwd=str(clone))
    if code != 0:
        return
    code, behind, _ = run_git(
        ["rev-list", "--count", f"--since={generated_at}", "HEAD"], env, cwd=str(clone)
    )
    commits_behind = int(behind or 0) if code == 0 else 0

    stale: list[str] = []
    changed_total = 0
    for section, rules in SECTION_PATH_RULES.items():
        since = ((sections or {}).get(section) or {}).get("updated_at") or generated_at
        code, out, _ = run_git(
            ["log", f"--since={since}", "--name-only", "--pretty=format:"],
            env,
            cwd=str(clone),
        )
        if code != 0:
            continue
        changed = {line.strip() for line in out.split("\n") if line.strip()}
        changed_total = max(changed_total, len(changed))
        if any(any(rule in f.lower() for rule in rules) for f in changed):
            stale.append(section)

    # Architecture/overview: stale on broad source churn since their update.
    for section in ("architecture", "overview"):
        since = ((sections or {}).get(section) or {}).get("updated_at") or generated_at
        code, out, _ = run_git(
            ["log", f"--since={since}", "--name-only", "--pretty=format:"],
            env,
            cwd=str(clone),
        )
        if code != 0:
            continue
        source_changed = {
            f
            for f in (line.strip() for line in out.split("\n"))
            if f
            and not f.lower().endswith(
                (".md", ".txt", ".json", ".lock", ".yml", ".yaml")
            )
        }
        changed_total = max(changed_total, len(source_changed))
        if len(source_changed) >= ARCH_CHURN_THRESHOLD:
            stale.append(section)

    rest_post(
        "repo_freshness",
        [
            {
                "folder_id": repo["folder_id"],
                "user_id": repo["user_id"],
                "head_sha": head,
                "commits_behind": commits_behind,
                "stale_sections": stale,
                "changed_files": changed_total,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        {"Prefer": "resolution=merge-duplicates"},
    )
    if stale or commits_behind:
        log(
            f"{repo['remote_url']}: freshness — {commits_behind} commits since briefing, "
            f"stale sections: {stale or 'none'}"
        )


def refresh_activity(
    clone: Path, repo: dict, old_sha: str | None, new_sha: str, env: dict
) -> None:
    """Fold the new commit range into the briefing's activity section via the
    backend (Haiku) — the one auto-maintained section."""
    if not API_URL or not repo.get("api_key_encrypted"):
        return
    rng = f"{old_sha}..{new_sha}" if old_sha else "-20"
    code, out, _ = run_git(
        ["log", rng, "--pretty=format:%H|%s|%an|%aI", "--no-merges", "-50"],
        env,
        cwd=str(clone),
    )
    if code != 0 or not out.strip():
        return
    commits = []
    for line in out.split("\n"):
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append(
                {
                    "sha": parts[0],
                    "subject": parts[1][:300],
                    "author": parts[2],
                    "date": parts[3],
                }
            )
    if not commits:
        return
    try:
        r = requests.post(
            f"{API_URL}/api/watcher/activity",
            headers={
                "Authorization": f"Bearer {decrypt(repo['api_key_encrypted'])}",
                "Content-Type": "application/json",
            },
            json={
                "folder_id": repo["folder_id"],
                "head_sha": new_sha,
                "commits": commits,
            },
            timeout=120,
        )
        if r.ok and (r.json() or {}).get("updated"):
            log(
                f"{repo['remote_url']}: activity section refreshed ({len(commits)} commits)"
            )
        else:
            log(f"{repo['remote_url']}: activity refresh skipped — {r.text[:150]}")
    except Exception as exc:  # noqa: BLE001 — activity is best-effort
        log(f"{repo['remote_url']}: activity refresh failed — {exc}")


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
            clone = DATA / repo["user_id"] / repo["folder_id"]
            if (clone / ".git").exists():
                # Prose staleness moves when briefings regenerate, not only
                # when the branch does — keep the freshness row current.
                compute_freshness(clone, repo, git_env(kf.name))
            record({"last_error": None})
            return

        clone = DATA / repo["user_id"] / repo["folder_id"]
        if not (clone / ".git").exists():
            clone.parent.mkdir(parents=True, exist_ok=True)
            log(f"{name}: initial clone")
            code, _, err = run_git(
                ["clone", "--branch", repo["branch"], repo["remote_url"], str(clone)],
                env,
            )
            if code != 0:
                log(f"ERROR {name}: clone failed — {err[:300]}")
                record({"last_error": f"clone: {err[:300]}"})
                return
        else:
            code, _, err = run_git(
                ["fetch", "origin", repo["branch"]], env, cwd=str(clone)
            )
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
    seed_bindings(
        clone, repo["folder_id"], folder_name, decrypt(repo["api_key_encrypted"])
    )

    ok, tail = kioku_index(clone)
    plain_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
    }
    if ok:
        log(f"{name}: indexed {remote_sha[:10]}")
        record({"last_sha": remote_sha, "last_error": None})
        refresh_activity(clone, repo, repo.get("last_sha"), remote_sha, plain_env)
    else:
        log(f"ERROR {name}: kioku index failed — {tail[-200:]}")
        record({"last_error": f"index: {tail[-300:]}"})
    compute_freshness(clone, repo, plain_env)


def main() -> int:
    repos = rest_get("watched_repos", {"select": "*", "order": "created_at"})
    if not repos:
        log("no watched repos")
        return 0
    keys = {
        k["user_id"]: k
        for k in rest_get("user_git_keys", {"select": "user_id,private_key_encrypted"})
    }
    log(
        f"watching {len(repos)} repo(s) across {len({r['user_id'] for r in repos})} user(s)"
    )
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


def run_service(schedule_raw: str) -> None:
    """Run a pass now, then at each WATCH_SCHEDULE time (UTC), forever.

    A crashed pass is logged and the loop keeps going — the container's
    restart policy only matters for crashes outside a pass (e.g. bad env).
    """
    times = sorted(
        (int(h), int(m))
        for h, m in (t.strip().split(":") for t in schedule_raw.split(","))
    )
    log(
        f"service mode — schedule (UTC): {', '.join(f'{h:02d}:{m:02d}' for h, m in times)}"
    )
    while True:
        try:
            main()
        except Exception as exc:  # noqa: BLE001 — the loop must outlive any pass
            log(f"ERROR pass crashed: {exc}")
        now = datetime.now(timezone.utc)
        candidates = [
            now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=d)
            for d in (0, 1)
            for h, m in times
        ]
        nxt = min(c for c in candidates if c > now)
        log(f"next pass at {nxt.isoformat(timespec='minutes')}")
        time.sleep((nxt - now).total_seconds())


if __name__ == "__main__":
    schedule = os.environ.get("WATCH_SCHEDULE", "").strip()
    if schedule:
        run_service(schedule)
    else:
        sys.exit(main())
