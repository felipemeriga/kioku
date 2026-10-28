"""kioku-mihari — multi-user repo poller.

On each scheduled pass, for every row in watched_repos:
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
  - service: set MIHARI_SCHEDULE to comma-separated UTC times
    ("06:00,18:00") or a minute interval ("*/15"). The process runs at startup, then sleeps
    until each scheduled time, forever. This is how the Dokploy-managed
    kioku-mihari container runs it.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
from cryptography.fernet import Fernet

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
# Legacy Fernet fallback (same key value the backend calls
# NOTION_TOKEN_ENCRYPTION_KEY). Optional now — once every row is re-sealed to
# KMS, SECRETS_ENCRYPTION_KEY can be removed.
_FERNET_KEY = os.environ.get("SECRETS_ENCRYPTION_KEY")
FERNET = Fernet(_FERNET_KEY.encode()) if _FERNET_KEY else None
MCP_URL = os.environ["KIOKU_MCP_URL"]
API_URL = os.environ.get("KIOKU_API_URL", "").rstrip("/")
DATA = Path(os.environ.get("MIHARI_DATA", os.environ.get("WATCHER_DATA", "/data")))
TRIGGER_TOKEN = os.environ.get("MIHARI_TRIGGER_TOKEN", os.environ.get("WATCHER_TRIGGER_TOKEN", ""))
TRIGGER_PORT = int(
    os.environ.get("MIHARI_TRIGGER_PORT", os.environ.get("WATCHER_TRIGGER_PORT", "8787"))
)
_pass_lock = threading.Lock()

# Which files drive each retained concrete briefing section. refresh_sections folds a
# section's changed files back into it (auto-maintained, like activity); the
# holistic sections (architecture/overview) are only warned about, never folded.
SECTION_PATH_RULES: dict[str, list[str]] = {
    "preferences": ["agents.md", "claude.md", "contributing", ".editorconfig", "codeowners"],
    "deployment": [".github/workflows/", "deploy/", "dockerfile"],
    "how_it_runs": [
        "readme",
        "docker-compose",
        "compose.y",
        "makefile",
        "scripts/",
        "run_",
        ".env.example",
        "package.json",
        "pyproject.toml",
        "cargo.toml",
        "go.mod",
        "requirements",
        ".github/workflows/",
    ],
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
    r = requests.patch(f"{REST}/{path}", headers=HEADERS, params=params, json=body, timeout=30)
    r.raise_for_status()


# New secrets are KMS-encrypted (prefix below); legacy rows are Fernet.
_KMS_PREFIX = "kms:v1:"
_KMS_ENC_CONTEXT = {"app": "kioku"}
_kms_client = None


def _kms():
    global _kms_client
    if _kms_client is None:
        import boto3

        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        _kms_client = boto3.client("kms", region_name=region)
    return _kms_client


def decrypt(ciphertext: str) -> str:
    if ciphertext.startswith(_KMS_PREFIX):
        blob = base64.b64decode(ciphertext[len(_KMS_PREFIX) :])
        return (
            _kms()
            .decrypt(CiphertextBlob=blob, EncryptionContext=_KMS_ENC_CONTEXT)["Plaintext"]
            .decode()
        )
    if FERNET is None:
        raise RuntimeError("Got legacy Fernet ciphertext but SECRETS_ENCRYPTION_KEY is not set.")
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
    sections = content.get("sections") if isinstance(content.get("sections"), dict) else content

    code, head, _ = run_git(["rev-parse", "HEAD"], env, cwd=str(clone))
    if code != 0:
        return
    review_rows = rest_get(
        "repo_freshness",
        {
            "folder_id": f"eq.{repo['folder_id']}",
            "select": "section_reviews",
            "limit": "1",
        },
    )
    reviews = (review_rows[0].get("section_reviews") or {}) if review_rows else {}
    code, behind, _ = run_git(
        ["rev-list", "--count", f"--since={generated_at}", "HEAD"], env, cwd=str(clone)
    )
    commits_behind = int(behind or 0) if code == 0 else 0
    if reviews and all((item or {}).get("head_sha") == head for item in reviews.values()):
        commits_behind = 0  # inspected at HEAD; unchanged prose is not stale

    stale: list[str] = []
    changed_total = 0
    # deployment/how_it_runs are AUTO-MAINTAINED by refresh_sections
    # (the mihari folds their changed files in), so they are not warned about
    # here — only the holistic sections below, which need a full regen.

    # Architecture/overview: stale on broad source churn since their update.
    for section in ("architecture", "overview"):
        if (reviews.get(section) or {}).get("head_sha") == head:
            continue
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
            if f and not f.lower().endswith((".md", ".txt", ".json", ".lock", ".yml", ".yaml"))
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
    clone: Path, repo: dict, old_sha: str | None, new_sha: str, env: dict, strict: bool = False
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
            f"{API_URL}/api/mihari/activity",
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
        r.raise_for_status()
        body = r.json() or {}
        if strict and str(body.get("reason", "")).endswith("failed quality check"):
            raise RuntimeError(body["reason"])
        if body.get("updated"):
            log(f"{repo['remote_url']}: activity section refreshed ({len(commits)} commits)")
        else:
            log(f"{repo['remote_url']}: activity refresh skipped — {r.text[:150]}")
    except Exception as exc:  # noqa: BLE001 — activity is best-effort
        log(f"{repo['remote_url']}: activity refresh failed — {exc}")
        if strict:
            raise RuntimeError("Activity refresh failed") from exc


def refresh_sections(
    clone: Path,
    repo: dict,
    env: dict,
    strict: bool = False,
    force_guide: bool = False,
    force_all: bool = False,
    selected_sections: set[str] | None = None,
) -> None:
    """Fold changed path-driven files into their concrete briefing sections
    (deployment/how_it_runs) via the backend (cheap Haiku) — the
    same treatment activity gets. Holistic sections (architecture/overview) are
    left for a full regen; compute_freshness only warns about those."""
    if not API_URL or not repo.get("api_key_encrypted"):
        return
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
        return
    generated_at = rows[0]["generated_at"]
    content = rows[0].get("content") or {}
    sections = content.get("sections") if isinstance(content.get("sections"), dict) else content
    sections = sections or {}
    key = decrypt(repo["api_key_encrypted"])

    for section, rules in SECTION_PATH_RULES.items():
        if selected_sections is not None and section not in selected_sections:
            continue
        sec = sections.get(section) or {}
        if sec.get("provenance") == "user_ui":
            continue
        if not sec.get("content"):
            continue  # never generated — needs a full regen, not a diff fold
        since = sec.get("updated_at") or generated_at
        code, out, _ = run_git(
            ["log", f"--since={since}", "--name-only", "--pretty=format:"],
            env,
            cwd=str(clone),
        )
        if code != 0:
            continue
        changed = {line.strip() for line in out.split("\n") if line.strip()}
        matched = sorted(f for f in changed if any(r in f.lower() for r in rules))
        current_text = json.dumps(sec.get("content") or {})
        thin = len(current_text) < (350 if section == "how_it_runs" else 220)
        if section == "how_it_runs" and current_text.count(";") >= 3 and "\\n" not in current_text:
            thin = True
        guide_upgrade = force_all or (
            force_guide and thin and sec.get("updated_by") != "mihari:guide-v2"
        )
        if guide_upgrade and not matched:
            candidates = (
                ("README.md", "readme.md", "Makefile", "pyproject.toml", "package.json")
                if section == "how_it_runs"
                else (
                    ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".editorconfig")
                    if section == "preferences"
                    else ("Dockerfile", "docker-compose.yml", ".github/workflows/deploy.yml")
                )
            )
            matched = [path for path in candidates if (clone / path).is_file()]
            if section == "deployment" and not matched:
                code, tracked, _ = run_git(["ls-files"], env, cwd=str(clone))
                if code == 0:
                    matched = [
                        path
                        for path in tracked.splitlines()
                        if any(rule in path.lower() for rule in rules) and (clone / path).is_file()
                    ][:5]
        if not matched:
            continue
        files = []
        for f in matched[: 5 if section == "how_it_runs" else 8]:
            p = clone / f
            try:
                if p.is_file() and p.stat().st_size < 60_000:
                    files.append(
                        {
                            "path": f,
                            "content": p.read_text(errors="replace")[:2500],
                            "role": "changed" if f in changed else "context",
                        }
                    )
            except OSError:
                continue
        if section == "how_it_runs":
            # A diff alone rarely explains how a large repo runs. Include a
            # bounded amount of stable setup context from the same checkout.
            context_paths = [
                "README.md",
                "Makefile",
                "docker-compose.yml",
                "pyproject.toml",
                "package.json",
            ]
            for changed_path in matched[:4]:
                parent = Path(changed_path).parent
                if parent != Path("."):
                    context_paths.extend([str(parent / "README.md"), str(parent / "package.json")])
            seen = {entry["path"] for entry in files}
            for context_path in context_paths:
                if len(files) >= 12:
                    break
                if context_path in seen:
                    continue
                candidate = clone / context_path
                try:
                    if candidate.is_file() and candidate.stat().st_size < 100_000:
                        files.append(
                            {
                                "path": context_path,
                                "content": candidate.read_text(errors="replace")[:4000],
                                "role": "context",
                            }
                        )
                        seen.add(context_path)
                except OSError:
                    continue
        if not files:
            if strict:
                raise RuntimeError(f"No source files available for {section} review")
            continue
        try:
            r = requests.post(
                f"{API_URL}/api/mihari/section",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "folder_id": repo["folder_id"],
                    "section": section,
                    "files": files,
                },
                timeout=120,
            )
            r.raise_for_status()
            body = r.json() or {}
            if body.get("reason", "").endswith("failed quality check"):
                raise RuntimeError(body["reason"])
            if body.get("updated"):
                log(f"{repo['remote_url']}: {section} section refreshed ({len(files)} file(s))")
        except Exception as exc:  # noqa: BLE001 — best-effort
            log(f"{repo['remote_url']}: {section} refresh failed — {exc}")
            if strict:
                raise RuntimeError("Detail section refresh failed") from exc


# Holistic sections (architecture/overview) are RE-GROUNDED periodically from
# the repo's current key files — no manual `kioku init --force` needed. Gated so
# it runs roughly twice a month, and only when there's been real churn.
HOLISTIC_REGROUND_DAYS = 14
HOLISTIC_COMMITS_FLOOR = 3


def maybe_reground_holistic(
    clone: Path,
    repo: dict,
    env: dict,
    force: bool = False,
    selected_sections: list[str] | None = None,
) -> None:
    """Re-ground architecture/overview from key files and the indexed graph.
    Thin old auto sections get a one-time upgrade; later passes need both age
    and commit churn. A seven-day same-head attempt cooldown prevents costly
    retries after rejected model output. Explicit refresh bypasses the gates."""
    if not API_URL or not repo.get("api_key_encrypted"):
        return
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
        return
    generated_at = rows[0]["generated_at"]
    content = rows[0].get("content") or {}
    sections = content.get("sections") if isinstance(content.get("sections"), dict) else content
    sections = sections or {}

    # Legacy init pinned agent-generated sections. Only UI edits block the watcher.
    writable = [
        sections.get(name) or {}
        for name in ("architecture", "overview")
        if (sections.get(name) or {}).get("provenance") != "user_ui"
    ]
    if not writable:
        return
    last = max(
        (section.get("updated_at") or generated_at for section in writable),
        default=generated_at,
    )
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except ValueError:
        return
    upgrade_due = any(
        (sections.get(name) or {}).get("updated_by") != "mihari:guide-v2"
        and len(json.dumps((sections.get(name) or {}).get("content") or {}))
        < (450 if name == "architecture" else 300)
        for name in ("architecture", "overview")
        if (sections.get(name) or {}).get("provenance") != "user_ui"
    )
    if (
        not force
        and not upgrade_due
        and (datetime.now(timezone.utc) - last_dt).days < HOLISTIC_REGROUND_DAYS
    ):
        return  # not due yet
    code, n, _ = run_git(["rev-list", "--count", f"--since={last}", "HEAD"], env, cwd=str(clone))
    if not force and not upgrade_due and (code != 0 or int(n or 0) < HOLISTIC_COMMITS_FLOOR):
        return  # not enough churn to bother
    # Record attempts even when the model rejects the output. Otherwise a
    # stale timestamp would trigger the same expensive pass every poll.
    code, head, _ = run_git(["rev-parse", "HEAD"], env, cwd=str(clone))
    attempt_path = clone / ".git" / "kioku-reground-attempt.json"
    if not force and code == 0 and head and attempt_path.is_file():
        try:
            attempt = json.loads(attempt_path.read_text())
            attempted = datetime.fromisoformat(attempt["at"])
            if attempt.get("head") == head and (datetime.now(timezone.utc) - attempted).days < 7:
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass

    # Ground holistic refresh from durable entry points and manifests.
    paths = []
    for cand in (
        "README.md",
        "pyproject.toml",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "Makefile",
        "docker-compose.yml",
    ):
        if (clone / cand).is_file():
            paths.append(cand)
    for top in sorted(clone.iterdir()) if clone.is_dir() else []:
        if (
            not top.is_dir()
            or top.name.startswith(".")
            or top.name in {"design-system", "tests", "test", "docs", "node_modules"}
        ):
            continue
        picked = 0
        for name in (
            "README.md",
            "main.py",
            "mihari.py",
            "src/main.ts",
            "src/main.tsx",
            "src/index.ts",
            "src/index.tsx",
            "pyproject.toml",
            "package.json",
            "Cargo.toml",
        ):
            candidate = top / name
            if candidate.is_file():
                paths.append(str(candidate.relative_to(clone)))
                picked += 1
                if picked == 2:
                    break
        if len(paths) >= 12:
            break
    # Include a few package-level READMEs/manifests for monorepos. These are
    # far more informative than a root manifest alone and still have a hard cap.
    for parent in ("apps", "packages", "services", "crates"):
        base = clone / parent
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir())[:12]:
            if not child.is_dir():
                continue
            for name in ("README.md", "package.json", "Cargo.toml", "pyproject.toml"):
                candidate = child / name
                if candidate.is_file():
                    paths.append(str(candidate.relative_to(clone)))
                    break
    files = []
    for f in paths[:12]:
        p = clone / f
        try:
            if p.is_file() and p.stat().st_size < 80_000:
                files.append({"path": f, "content": p.read_text(errors="replace")[:3500]})
        except OSError:
            continue
    if not files:
        if force:
            raise RuntimeError("No source files available for holistic briefing review")
        return

    # Compact structure: top-two-level paths from the tracked tree.
    code, tree, _ = run_git(["ls-files"], env, cwd=str(clone))
    structure = ""
    if code == 0:
        tops = sorted({"/".join(line.split("/")[:2]) for line in tree.split("\n") if line.strip()})
        structure = "\n".join(tops[:200])

    key = decrypt(repo["api_key_encrypted"])
    if code == 0 and head:
        try:
            attempt_path.write_text(
                json.dumps({"head": head, "at": datetime.now(timezone.utc).isoformat()})
            )
        except OSError:
            pass  # deployment without a writable clone still functions
    try:
        r = requests.post(
            f"{API_URL}/api/mihari/reground",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "folder_id": repo["folder_id"],
                "files": files,
                "structure": structure,
                "selected": selected_sections or ["architecture", "overview"],
            },
            timeout=180,
        )
        r.raise_for_status()
        body = r.json() if r.ok else {}
        if force and str(body.get("reason", "")).endswith("failed quality check"):
            raise RuntimeError(body["reason"])
        if (body or {}).get("updated"):
            log(
                f"{repo['remote_url']}: re-grounded "
                f"{', '.join((body or {}).get('sections', []))} (Sonnet, {int(n or 0)} commits)"
            )
    except Exception as exc:  # noqa: BLE001 — best-effort
        log(f"{repo['remote_url']}: reground failed — {exc}")
        if force:
            raise RuntimeError("Architecture refresh failed") from exc


def review_new_commits(clone: Path, repo: dict, old_sha: str | None, head: str, env: dict) -> None:
    """Selectively maintain all initialized briefing areas for a new principal HEAD."""
    if not API_URL or not repo.get("api_key_encrypted"):
        raise RuntimeError("Mihari API or repository key is unavailable")
    base = old_sha if old_sha and old_sha != head else f"{head}^"
    code, paths, _ = run_git(["diff", "--name-only", base, head], env, cwd=str(clone))
    if code != 0:
        paths = ""
    code, patch, _ = run_git(["diff", base, head], env, cwd=str(clone))
    if code != 0:
        patch = ""
    code, subjects, _ = run_git(
        ["log", f"{base}..{head}", "--no-merges", "--pretty=format:%h %s", "-50"],
        env,
        cwd=str(clone),
    )
    if code != 0:
        subjects = ""
    key = decrypt(repo["api_key_encrypted"])
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    r = requests.post(
        f"{API_URL}/api/mihari/review-plan",
        headers=headers,
        json={
            "folder_id": repo["folder_id"],
            "head_sha": head,
            "changed_paths": paths.splitlines()[:300],
            "commits": subjects.splitlines()[:50],
            "patch": patch[:18000],
        },
        timeout=120,
    )
    r.raise_for_status()
    plan = r.json()
    selected = set(plan.get("selected") or [])
    reviewed = plan.get("reviewed") or []
    log(f"{repo['remote_url']}: briefing review selected {sorted(selected)}")

    if "activity" in selected:
        refresh_activity(clone, repo, old_sha, head, env, strict=True)
    concrete = selected & set(SECTION_PATH_RULES)
    if concrete:
        refresh_sections(clone, repo, env, strict=True, force_all=True, selected_sections=concrete)
    holistic = sorted(selected & {"architecture", "overview"})
    if holistic:
        maybe_reground_holistic(clone, repo, env, force=True, selected_sections=holistic)
    if "documentation" in selected:
        current_paths = list(dict.fromkeys([*paths.splitlines(), "README.md"]))[:12]
        files = []
        for path in current_paths:
            source = clone / path
            try:
                if source.is_file() and source.stat().st_size < 100_000:
                    files.append(
                        {"path": path, "content": source.read_text(errors="replace")[:2500]}
                    )
            except OSError:
                continue
        r = requests.post(
            f"{API_URL}/api/mihari/documentation",
            headers=headers,
            json={
                "folder_id": repo["folder_id"],
                "head_sha": head,
                "files": files,
                "patch": patch[:12000],
            },
            timeout=240,
        )
        r.raise_for_status()
    if reviewed:
        r = requests.post(
            f"{API_URL}/api/mihari/review-complete",
            headers=headers,
            json={"folder_id": repo["folder_id"], "head_sha": head, "reviewed": reviewed},
            timeout=30,
        )
        r.raise_for_status()


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
                review_rows = rest_get(
                    "repo_freshness",
                    {
                        "folder_id": f"eq.{repo['folder_id']}",
                        "select": "section_reviews",
                        "limit": "1",
                    },
                )
                review = (review_rows[0].get("section_reviews") or {}) if review_rows else {}
                latest = rest_get(
                    "folder_summaries",
                    {
                        "folder_id": f"eq.{repo['folder_id']}",
                        "select": "generated_at",
                        "order": "generated_at.desc",
                        "limit": "1",
                    },
                )
                newest_review = max(
                    (item.get("reviewed_at") or "" for item in review.values()), default=""
                )
                briefing_changed = bool(
                    latest and latest[0].get("generated_at", "") > newest_review
                )
                if (
                    not review
                    or briefing_changed
                    or any(item.get("head_sha") != remote_sha for item in review.values())
                ):
                    review_new_commits(clone, repo, remote_sha, remote_sha, git_env(kf.name))
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
            code, _, err = run_git(["fetch", "origin", repo["branch"]], env, cwd=str(clone))
            if code == 0:
                code, _, err = run_git(
                    ["reset", "--hard", f"origin/{repo['branch']}"], env, cwd=str(clone)
                )
            if code != 0:
                log(f"ERROR {name}: fetch/reset failed — {err[:300]}")
                record({"last_error": f"fetch: {err[:300]}"})
                return

    folder = rest_get("folders", {"id": f"eq.{repo['folder_id']}", "select": "name", "limit": "1"})
    folder_name = folder[0]["name"] if folder else "repo"
    if not repo.get("api_key_encrypted"):
        log(f"ERROR {name}: no api key registered — re-run kioku init in the repo")
        record({"last_error": "no api key registered"})
        return
    seed_bindings(clone, repo["folder_id"], folder_name, decrypt(repo["api_key_encrypted"]))

    ok, tail = kioku_index(clone)
    plain_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
    }
    if ok:
        log(f"{name}: indexed {remote_sha[:10]}")
        try:
            review_new_commits(clone, repo, repo.get("last_sha"), remote_sha, plain_env)
        except Exception as exc:  # noqa: BLE001 — retain SHA so the next pass retries
            log(f"ERROR {name}: briefing review failed — {exc}")
            record({"last_error": f"briefing review: {str(exc)[:220]}"})
            compute_freshness(clone, repo, plain_env)
            return
        record({"last_sha": remote_sha, "last_error": None})
    else:
        log(f"ERROR {name}: kioku index failed — {tail[-200:]}")
        record({"last_error": f"index: {tail[-300:]}"})
    compute_freshness(clone, repo, plain_env)


def force_refresh(repo: dict, key_row: dict, target: str) -> None:
    """On-demand refresh triggered from the web (via the backend). Syncs the
    clone to HEAD regardless of last_sha, then runs the requested target.
    Parallels process_repo's sync block on purpose so the scheduled path stays
    untouched."""
    rid = repo["id"]
    name = f"{repo['remote_url']} ({repo['branch']})"
    now = datetime.now(timezone.utc).isoformat()
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
            log(f"ERROR force {target} {name}: ls-remote failed — {(err or '')[:200]}")
            raise RuntimeError("Could not read the remote branch")
        remote_sha = out.split()[0]
        clone = DATA / repo["user_id"] / repo["folder_id"]
        if not (clone / ".git").exists():
            clone.parent.mkdir(parents=True, exist_ok=True)
            code, _, err = run_git(
                ["clone", "--branch", repo["branch"], repo["remote_url"], str(clone)],
                env,
            )
        else:
            code, _, err = run_git(["fetch", "origin", repo["branch"]], env, cwd=str(clone))
            if code == 0:
                code, _, err = run_git(
                    ["reset", "--hard", f"origin/{repo['branch']}"], env, cwd=str(clone)
                )
        if code != 0:
            log(f"ERROR force {target} {name}: sync failed — {(err or '')[:200]}")
            raise RuntimeError("Could not sync the repository")
    if not repo.get("api_key_encrypted"):
        log(f"ERROR force {target} {name}: no api key registered")
        raise RuntimeError("No repository API key registered")
    folder = rest_get("folders", {"id": f"eq.{repo['folder_id']}", "select": "name", "limit": "1"})
    folder_name = folder[0]["name"] if folder else "repo"
    seed_bindings(clone, repo["folder_id"], folder_name, decrypt(repo["api_key_encrypted"]))
    plain_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
    }
    if target == "index":
        ok, tail = kioku_index(clone)
        if ok:
            log(f"{name}: force index -> {remote_sha[:10]}")
            review_new_commits(clone, repo, repo.get("last_sha"), remote_sha, plain_env)
            rest_patch(
                "watched_repos",
                {"id": f"eq.{rid}"},
                {"last_run_at": now, "last_sha": remote_sha, "last_error": None},
            )
        else:
            log(f"ERROR force index {name}: {tail[-200:]}")
            raise RuntimeError("Code indexing failed; check mihari logs")
    elif target == "sections":
        log(f"{name}: force sections")
        review_new_commits(clone, repo, repo.get("last_sha"), remote_sha, plain_env)
    compute_freshness(clone, repo, plain_env)


def find_repo(folder_id: str) -> tuple[dict, dict] | None:
    repos = rest_get("watched_repos", {"folder_id": f"eq.{folder_id}", "select": "*", "limit": "1"})
    if not repos:
        return None
    repo = repos[0]
    keys = rest_get(
        "user_git_keys",
        {
            "user_id": f"eq.{repo['user_id']}",
            "select": "user_id,private_key_encrypted",
            "limit": "1",
        },
    )
    if not keys:
        return None
    return repo, keys[0]


def handle_run(headers, raw_body: str) -> tuple[int, dict]:
    if (
        not TRIGGER_TOKEN
        or (headers.get("X-Mihari-Token") or headers.get("X-Watcher-Token")) != TRIGGER_TOKEN
    ):
        return 401, {"error": "unauthorized"}
    try:
        body = json.loads(raw_body or "{}")
    except ValueError:
        return 400, {"error": "bad json"}
    folder_id = body.get("folder_id")
    target = body.get("target")
    if target not in ("index", "sections"):
        return 422, {"error": "target must be 'index' or 'sections'"}
    if not folder_id:
        return 422, {"error": "missing folder_id"}
    found = find_repo(folder_id)
    if not found:
        return 404, {"error": "unknown folder"}
    repo, key_row = found
    if not _pass_lock.acquire(blocking=False):
        return 409, {"error": "already running"}

    prefix = f"{target}_refresh"
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        rest_post(
            "repo_freshness",
            [
                {
                    "folder_id": folder_id,
                    "user_id": repo["user_id"],
                    f"{prefix}_started_at": started_at,
                    f"{prefix}_finished_at": None,
                    f"{prefix}_error": None,
                }
            ],
            {"Prefer": "resolution=merge-duplicates"},
        )
    except Exception as exc:
        _pass_lock.release()
        log(f"ERROR recording refresh start: {exc}")
        return 503, {"error": "could not record refresh start"}

    def job() -> None:
        error = None
        try:
            force_refresh(repo, key_row, target)
        except Exception as exc:  # noqa: BLE001 — a trigger must never crash the mihari
            log(f"ERROR force {target} {repo.get('remote_url')}: {exc}")
            # Never expose raw subprocess/HTTP exception text (may contain secrets).
            error = "Refresh failed. Check mihari logs and retry."
        finally:
            try:
                rest_patch(
                    "repo_freshness",
                    {
                        "folder_id": f"eq.{folder_id}",
                        f"{prefix}_started_at": f"eq.{started_at}",
                    },
                    {
                        f"{prefix}_finished_at": datetime.now(timezone.utc).isoformat(),
                        f"{prefix}_error": error,
                    },
                )
            except Exception as exc:
                log(f"ERROR recording refresh completion: {exc}")
            finally:
                _pass_lock.release()

    try:
        threading.Thread(target=job, daemon=True).start()
    except Exception:
        _pass_lock.release()
        return 503, {"error": "could not launch refresh"}
    return 202, {"started": True}


class _Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/run":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode() if length else ""
        status, obj = handle_run(self.headers, raw)
        self._send(status, obj)

    def log_message(self, *args) -> None:  # silence default stderr access logs
        return


def start_trigger_server() -> None:
    if not TRIGGER_TOKEN:
        log("trigger server disabled (no MIHARI_TRIGGER_TOKEN)")
        return
    srv = ThreadingHTTPServer(("0.0.0.0", TRIGGER_PORT), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"trigger server on :{TRIGGER_PORT}")


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
            log(f"ERROR {repo['remote_url']}: user has no mihari key")
            continue
        try:
            process_repo(repo, key_row)
        except Exception as exc:  # noqa: BLE001 — one repo must never kill the run
            failures += 1
            log(f"ERROR {repo['remote_url']}: {exc}")
    return 1 if failures else 0


def parse_schedule(schedule_raw: str) -> list[tuple[int, int]]:
    if schedule_raw.startswith("*/"):
        minutes = int(schedule_raw[2:])
        if minutes < 1 or minutes > 60 or 60 % minutes:
            raise ValueError("MIHARI_SCHEDULE interval must divide 60 minutes")
        return [(hour, minute) for hour in range(24) for minute in range(0, 60, minutes)]
    times = sorted(
        (int(h), int(m)) for h, m in (t.strip().split(":") for t in schedule_raw.split(","))
    )
    if any(h < 0 or h > 23 or m < 0 or m > 59 for h, m in times):
        raise ValueError("MIHARI_SCHEDULE must contain valid UTC times")
    return times


def run_service(schedule_raw: str) -> None:
    """Run a pass now, then at each MIHARI_SCHEDULE time (UTC), forever.

    A crashed pass is logged and the loop keeps going — the container's
    restart policy only matters for crashes outside a pass (e.g. bad env).
    """
    times = parse_schedule(schedule_raw)
    log(f"service mode — schedule: {schedule_raw} UTC")
    while True:
        try:
            with _pass_lock:
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
    schedule = os.environ.get("MIHARI_SCHEDULE", os.environ.get("WATCH_SCHEDULE", "")).strip()
    if schedule:
        start_trigger_server()
        run_service(schedule)
    else:
        sys.exit(main())
