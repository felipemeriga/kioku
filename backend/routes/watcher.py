"""Repo-watcher endpoints: per-user git deploy identity + watched-repo registry.

Auth mirrors the CLI surface: a scoped api key (Bearer rag_...). The private
SSH key is generated server-side and never leaves the backend — clients only
ever see the public half. The watcher container (a separate deployable) reads
watched_repos/user_git_keys directly with the service role and decrypts with
the same master key.
"""

from __future__ import annotations

import base64
import hashlib
import os
import stat
import subprocess
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db.client import get_supabase
from services.crypto import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api/watcher")


def _api_key_auth(request: Request) -> tuple[str, str, str]:
    """(user_id, scope_folder_id, raw_key) from the Bearer api key."""
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer rag_"):
        raise HTTPException(status_code=401, detail="Bearer api key required")
    raw_key = auth[len("Bearer ") :]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    sb = get_supabase()
    row = (
        sb.table("api_keys")
        .select("user_id, scope_folder_id")
        .eq("key_hash", key_hash)
        .limit(1)
        .execute()
        .data
    )
    if not row or not row[0].get("scope_folder_id"):
        raise HTTPException(status_code=401, detail="Invalid or unscoped api key")
    return row[0]["user_id"], row[0]["scope_folder_id"], raw_key


def _generate_ed25519() -> tuple[str, str, str]:
    """(private_openssh, public_openssh, fingerprint) for a fresh ed25519 key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )
    blob = base64.b64decode(public.split()[1])
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    comment = "kioku-watcher"
    return private_pem, f"{public} {comment}", f"SHA256:{digest}"


@router.post("/key")
async def get_or_create_key(request: Request):
    """Idempotent: returns the user's watcher public key, creating the pair on
    first call. The same key serves every repo and every computer the user
    links from."""
    user_id, _scope, _raw = _api_key_auth(request)
    sb = get_supabase()
    existing = (
        sb.table("user_git_keys")
        .select("public_key, fingerprint, created_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    if existing:
        return {**existing[0], "created": False}

    private_pem, public_key, fingerprint = _generate_ed25519()
    sb.table("user_git_keys").insert(
        {
            "user_id": user_id,
            "private_key_encrypted": encrypt_secret(private_pem),
            "public_key": public_key,
            "fingerprint": fingerprint,
        }
    ).execute()
    return {
        "public_key": public_key,
        "fingerprint": fingerprint,
        "created": True,
    }


class TestAccessRequest(BaseModel):
    remote_url: str = Field(min_length=8, max_length=500)
    branch: str = Field(default="main", max_length=200)


def _ls_remote_with_key(private_pem: str, remote_url: str, branch: str) -> tuple[str | None, str]:
    """(sha, error). Runs git ls-remote with the decrypted key from a private
    tmpfs file; the key file lives only for the duration of the call."""
    tmpdir = "/dev/shm" if os.path.isdir("/dev/shm") else None
    with tempfile.NamedTemporaryFile("w", dir=tmpdir, suffix=".key", delete=True) as f:
        f.write(private_pem)
        f.flush()
        os.chmod(f.name, stat.S_IRUSR | stat.S_IWUSR)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "GIT_SSH_COMMAND": (
                f"ssh -i {f.name} -o IdentitiesOnly=yes -o BatchMode=yes "
                "-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
            ),
            "GIT_TERMINAL_PROMPT": "0",
        }
        try:
            proc = subprocess.run(
                ["git", "ls-remote", remote_url, f"refs/heads/{branch}"],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            return None, "timed out contacting the git remote"
        except FileNotFoundError:
            return None, "git is not installed in this environment"
    if proc.returncode != 0:
        return None, (proc.stderr or "ls-remote failed").strip()[:300]
    line = (proc.stdout or "").strip()
    if not line:
        return None, f"branch '{branch}' not found on remote"
    return line.split()[0], ""


@router.post("/test-access")
async def test_access(body: TestAccessRequest, request: Request):
    """Can the user's watcher key read this remote? Runs a real ls-remote."""
    user_id, _scope, _raw = _api_key_auth(request)
    sb = get_supabase()
    row = (
        sb.table("user_git_keys")
        .select("private_key_encrypted, public_key, fingerprint")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="No watcher key yet — call /key first")

    sha, error = _ls_remote_with_key(
        decrypt_secret(row[0]["private_key_encrypted"]), body.remote_url, body.branch
    )
    if sha:
        sb.table("user_git_keys").update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("user_id", user_id).execute()
        return {"ok": True, "sha": sha}
    return {
        "ok": False,
        "error": error,
        "public_key": row[0]["public_key"],
        "fingerprint": row[0]["fingerprint"],
    }


class ActivityCommit(BaseModel):
    sha: str = Field(max_length=64)
    subject: str = Field(max_length=300)
    author: str = Field(default="", max_length=120)
    date: str = Field(default="", max_length=40)


class ActivityRefreshRequest(BaseModel):
    folder_id: str
    head_sha: str = Field(max_length=64)
    commits: list[ActivityCommit] = Field(default_factory=list, max_length=100)


@router.post("/activity")
async def refresh_activity(body: ActivityRefreshRequest, request: Request):
    """Fold new commits into the briefing's `activity` section — the one
    section that IS auto-maintained (cheap Haiku call, no agent session).
    Prose sections (overview/architecture/…) are never touched here."""
    user_id, scope_id, _raw = _api_key_auth(request)
    sb = get_supabase()

    from mcp_server import _descendant_folder_ids

    if body.folder_id not in _descendant_folder_ids(sb, scope_id, user_id):
        raise HTTPException(status_code=403, detail="folder_id not in api key scope")
    if not body.commits:
        return {"ok": True, "updated": False, "reason": "no commits"}

    from services.folder_summary.repo import get_latest_summary

    latest = get_latest_summary(sb, body.folder_id, user_id)
    if not latest:
        return {"ok": True, "updated": False, "reason": "no briefing yet"}

    sections = latest.get("sections") or ((latest.get("content") or {}).get("sections")) or {}
    current_activity = (sections.get("activity") or {}).get("content") or {}

    import json as _json

    from services.llm import Task, complete

    commit_lines = "\n".join(
        f"- {c.sha[:8]} {c.subject} ({c.author}, {c.date[:10]})" for c in body.commits
    )
    prompt = (
        "You maintain the `activity` section of a repository briefing. "
        "Fold the NEW commits into the existing section: keep it a narrative "
        "summary (4-8 sentences) plus 5-10 concrete highlight bullets, newest "
        "work first, dropping stale items as needed. Group related commits "
        "into themes; never output a raw commit list.\n\n"
        f"CURRENT SECTION (JSON):\n{_json.dumps(current_activity)[:6000]}\n\n"
        f"NEW COMMITS:\n{commit_lines}\n\n"
        'Reply with ONLY valid JSON: {"summary": "...", "highlights": ["...", ...]}'
    )
    response = complete(
        task=Task.FOLDER_SUMMARY_ROLLUP,
        max_tokens=1500,
        system="You update repo activity summaries. Output only valid JSON.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        new_activity = _json.loads(text)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="activity model returned invalid JSON")

    from services.folder_summary.briefing_schema import new_section

    sections["activity"] = new_section(
        new_activity, status="auto", provenance="auto", updated_by="watcher"
    )
    content = latest.get("content") or {}
    if "sections" in content:
        content["sections"] = sections
    else:
        content = sections
    sb.table("folder_summaries").update({"content": content}).eq("id", latest["id"]).execute()
    return {"ok": True, "updated": True, "commits": len(body.commits)}


class RegisterRepoRequest(BaseModel):
    folder_id: str
    remote_url: str = Field(min_length=8, max_length=500)
    branch: str = Field(default="main", max_length=200)


@router.post("/repos")
async def register_repo(body: RegisterRepoRequest, request: Request):
    """Register (or refresh) a repo for watching. Idempotent on
    (user, remote_url) so linking the same repo from a second computer just
    re-binds. Stores the CLI's own api key (encrypted) so the watcher indexes
    under the same identity — no key rotation surprises for the laptop."""
    user_id, scope_id, raw_key = _api_key_auth(request)
    sb = get_supabase()

    from mcp_server import _descendant_folder_ids

    if body.folder_id not in _descendant_folder_ids(sb, scope_id, user_id):
        raise HTTPException(status_code=403, detail="folder_id not in api key scope")

    existing = (
        sb.table("watched_repos")
        .select("id")
        .eq("user_id", user_id)
        .eq("remote_url", body.remote_url)
        .limit(1)
        .execute()
        .data
    )
    row = {
        "user_id": user_id,
        "folder_id": body.folder_id,
        "remote_url": body.remote_url,
        "branch": body.branch,
        "api_key_encrypted": encrypt_secret(raw_key),
        "last_error": None,
    }
    if existing:
        sb.table("watched_repos").update(row).eq("id", existing[0]["id"]).execute()
        return {"registered": True, "created": False}
    sb.table("watched_repos").insert(row).execute()
    return {"registered": True, "created": True}
