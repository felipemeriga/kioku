"""Repo-mihari endpoints: per-user git deploy identity + watched-repo registry.

Auth mirrors the CLI surface: a scoped api key (Bearer rag_...). The private
SSH key is generated server-side and never leaves the backend — clients only
ever see the public half. Mihari container (a separate deployable) reads
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

router = APIRouter()


def _user_edited(section: dict) -> bool:
    return section.get("status") in ("pinned", "hybrid") or section.get("provenance") == "user_ui"


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
    comment = "kioku-mihari"
    return private_pem, f"{public} {comment}", f"SHA256:{digest}"


@router.post("/key")
async def get_or_create_key(request: Request):
    """Idempotent: returns the user's mihari public key, creating the pair on
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
    """Can the user's mihari key read this remote? Runs a real ls-remote."""
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
        raise HTTPException(status_code=404, detail="No mihari key yet — call /key first")

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
    """Fold new commits into the briefing's activity section with a bounded
    Haiku call. User-edited sections stay untouched."""
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

    from services.folder_summary.briefing_schema import snapshot_sections

    sections = snapshot_sections(latest)
    if _user_edited(sections.get("activity") or {}):
        return {"ok": True, "updated": False, "reason": "section edited by user"}
    current_activity = (sections.get("activity") or {}).get("content") or {}

    import json as _json

    from services.llm import Task, complete

    commit_lines = "\n".join(
        f"- {c.sha[:8]} {c.subject} ({c.author}, {c.date[:10]})" for c in body.commits
    )
    prompt = (
        "You maintain the `activity` section of a repository briefing. "
        "Fold the NEW commits into the existing section: keep it a narrative "
        "summary (4-8 clear sentences) plus 5-10 concrete highlight bullets, newest "
        "work first, dropping stale items as needed. Group related commits "
        "into themes, explain what changed and why it matters when supported "
        "by the subjects; never output a raw commit list or infer unmentioned "
        "behavior.\n\n"
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
    if (
        not isinstance(new_activity, dict)
        or not isinstance(new_activity.get("summary"), str)
        or not isinstance(new_activity.get("highlights"), list)
        or any(not isinstance(item, str) for item in new_activity["highlights"])
        or not new_activity["summary"].strip()
    ):
        return {"ok": True, "updated": False, "reason": "activity failed quality check"}

    from services.folder_summary.briefing_schema import new_section

    # Atomic single-section write (jsonb_set under the row lock) so a concurrent
    # section refresh in the same mihari pass can't clobber this one.
    sb.rpc(
        "set_briefing_section",
        {
            "p_folder_id": body.folder_id,
            "p_user_id": user_id,
            "p_section": "activity",
            "p_value": new_section(
                new_activity, status="auto", provenance="auto", updated_by="mihari"
            ),
        },
    ).execute()
    return {"ok": True, "updated": True, "commits": len(body.commits)}


# Concrete sections Mihari maintains from changed files. Holistic sections
# use the separate, much less frequent re-grounding path below.
MIHARI_MAINTAINED_SECTIONS = {"deployment", "how_it_runs"}


class SectionFile(BaseModel):
    path: str = Field(max_length=400)
    content: str = Field(max_length=12000)
    role: str = Field(default="changed", pattern="^(changed|context)$")


class SectionRefreshRequest(BaseModel):
    folder_id: str
    section: str = Field(max_length=40)
    head_sha: str = Field(default="", max_length=64)
    files: list[SectionFile] = Field(default_factory=list, max_length=12)


@router.post("/section")
async def refresh_section(body: SectionRefreshRequest, request: Request):
    """Fold the CURRENT content of changed files into one concrete briefing
    section (deployment/how_it_runs) via a cheap
    Haiku call — the same treatment activity gets, extended to the path-driven
    prose sections. Holistic sections (architecture/overview) are rejected;
    they need a full regen. Preserves the section's existing JSON shape."""
    if body.section not in MIHARI_MAINTAINED_SECTIONS:
        return {"ok": True, "updated": False, "reason": f"'{body.section}' not auto-maintained"}
    if not body.files:
        return {"ok": True, "updated": False, "reason": "no files"}

    user_id, scope_id, _raw = _api_key_auth(request)
    sb = get_supabase()

    from mcp_server import _descendant_folder_ids

    if body.folder_id not in _descendant_folder_ids(sb, scope_id, user_id):
        raise HTTPException(status_code=403, detail="folder_id not in api key scope")

    from services.folder_summary.repo import get_latest_summary

    latest = get_latest_summary(sb, body.folder_id, user_id)
    if not latest:
        return {"ok": True, "updated": False, "reason": "no briefing yet"}

    from services.folder_summary.briefing_schema import snapshot_sections

    sections = snapshot_sections(latest)
    current = (sections.get(body.section) or {}).get("content")
    if _user_edited(sections.get(body.section) or {}):
        return {"ok": True, "updated": False, "reason": "section edited by user"}
    if current is None:
        # Nothing to update in place — a section that was never generated needs
        # the full regen path, not a diff fold.
        return {"ok": True, "updated": False, "reason": "section not present"}
    if body.section == "how_it_runs" and isinstance(current, str):
        current = {"requirements": [], "local_dev": current}

    import json as _json

    from services.llm import Task, complete

    file_blobs = "\n\n".join(f"--- {f.role.upper()}: {f.path} ---\n{f.content}" for f in body.files)
    writing_guide = (
        "For how_it_runs, write a useful human-readable operating guide for this actual "
        "repository, within the existing {requirements, local_dev} shape. Use requirements "
        "for concrete prerequisites with a short reason for each. In local_dev, explain "
        "setup, distinct services or applications, their run commands, and how to verify "
        "or test them. Group related commands into short paragraphs with plain headings; "
        "explain what each command starts. Aim for roughly 250-450 words when the files "
        "support it. Preserve verified details in the current section when changed files "
        "do not contradict them. Do not invent commands, environment values, or services. "
        if body.section == "how_it_runs"
        else (
            "For deployment, explain the environments, release entry points, CI/CD "
            "sequence, and verification or rollback steps only where source files "
            "support them. Prefer short headed prose to a list of filenames or raw "
            "workflow YAML. Preserve still-valid details in the current section. "
        )
    )
    prompt = (
        f"You maintain the `{body.section}` section of a repository briefing. "
        "Update it to reflect the CURRENT state of the files below (they changed "
        "since the section was last written). Files marked CONTEXT are stable "
        "references, not necessarily changed. "
        f"{writing_guide}"
        "Keep it accurate and readable, and "
        "return it in EXACTLY the same JSON shape as the current section — same "
        "keys, same structure — just with updated values.\n\n"
        f"CURRENT SECTION (JSON):\n{_json.dumps(current)[:6000]}\n\n"
        f"SOURCE FILES:\n{file_blobs[:18000]}\n\n"
        "Reply with ONLY the updated section as valid JSON, same shape as CURRENT."
    )
    response = complete(
        task=Task.FOLDER_SUMMARY_ROLLUP,
        max_tokens=2400 if body.section == "how_it_runs" else 1500,
        system="You update repo briefing sections from source files. Output only valid JSON.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        new_content = _json.loads(text)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="section model returned invalid JSON")
    if body.section == "how_it_runs":
        if not isinstance(new_content, dict) or set(new_content) != set(current):
            raise HTTPException(status_code=502, detail="section model changed briefing shape")
        local_dev = new_content.get("local_dev")
        requirements = new_content.get("requirements")
        if (
            not isinstance(local_dev, str)
            or not isinstance(requirements, list)
            or any(not isinstance(item, str) for item in requirements)
        ):
            raise HTTPException(status_code=502, detail="section model changed how_it_runs types")
        if len(local_dev.strip()) < 180 or (
            local_dev.count(";") >= 3 and local_dev.count("\n") < 2
        ):
            return {"ok": True, "updated": False, "reason": "generated guide failed quality check"}
    if body.section == "deployment":
        if (
            not isinstance(new_content, dict)
            or set(new_content) != set(current)
            or not isinstance(new_content.get("environments"), list)
            or not isinstance(new_content.get("how_to_deploy"), str)
            or not isinstance(new_content.get("ci_cd_notes"), str)
            or not (new_content["how_to_deploy"].strip() or new_content["ci_cd_notes"].strip())
        ):
            return {"ok": True, "updated": False, "reason": "deployment failed quality check"}

    from services.folder_summary.briefing_schema import new_section

    # Atomic single-section write (see /activity) — never overwrite the whole
    # content, so parallel section refreshes compose instead of clobbering.
    sb.rpc(
        "set_briefing_section",
        {
            "p_folder_id": body.folder_id,
            "p_user_id": user_id,
            "p_section": body.section,
            "p_value": new_section(
                new_content,
                status="auto",
                provenance="auto",
                updated_by="mihari:guide-v2",
            ),
        },
    ).execute()
    return {"ok": True, "updated": True, "section": body.section}


class RegroundFile(BaseModel):
    path: str = Field(max_length=400)
    content: str = Field(max_length=16000)


class RegroundRequest(BaseModel):
    folder_id: str
    head_sha: str = Field(default="", max_length=64)
    files: list[RegroundFile] = Field(default_factory=list, max_length=14)
    structure: str = Field(default="", max_length=4000)


@router.post("/reground")
async def reground_holistic(body: RegroundRequest, request: Request):
    """Re-ground the HOLISTIC sections (architecture + overview) from the repo's
    current key files + structure. Mihari runs this periodically (~twice a
    month) so a repo stays fresh without a manual `kioku init --force`. Unlike
    the concrete-section folds (Haiku, diff-driven), this re-reads the actual key
    files and regenerates the prose with Sonnet, so it never drifts."""
    if not body.files:
        return {"ok": True, "updated": False, "reason": "no files"}

    user_id, scope_id, _raw = _api_key_auth(request)
    sb = get_supabase()

    from mcp_server import _descendant_folder_ids

    if body.folder_id not in _descendant_folder_ids(sb, scope_id, user_id):
        raise HTTPException(status_code=403, detail="folder_id not in api key scope")

    from services.folder_summary.repo import get_latest_summary

    latest = get_latest_summary(sb, body.folder_id, user_id)
    if not latest:
        return {"ok": True, "updated": False, "reason": "no briefing yet"}
    from services.folder_summary.briefing_schema import snapshot_sections

    sections = snapshot_sections(latest)
    cur_arch = (sections.get("architecture") or {}).get("content")
    cur_over = (sections.get("overview") or {}).get("content")

    # Reuse the AST graph that `kioku index` already uploaded. A bounded
    # symbol/edge sample complements README and manifests without re-embedding.
    symbols = (
        sb.table("repo_symbols")
        .select("file,symbol,kind")
        .eq("folder_id", body.folder_id)
        .eq("user_id", user_id)
        .limit(100)
        .execute()
        .data
        or []
    )
    edges = (
        sb.table("repo_edges")
        .select("ref_file,src_node_id,dst_node_id,relation")
        .eq("folder_id", body.folder_id)
        .eq("user_id", user_id)
        .limit(50)
        .execute()
        .data
        or []
    )

    import json as _json

    from services.llm import Task, complete

    file_blobs = "\n\n".join(f"--- {f.path} ---\n{f.content}" for f in body.files)
    prompt = (
        "You maintain a repository briefing. Regenerate the `architecture` and "
        "`overview` sections, RE-GROUNDED in the current key files and structure "
        "below (do not just copy the stale versions). Write for a developer who "
        "needs to understand this repository: describe its purpose, principal "
        "applications and packages, their responsibilities, and the actual data "
        "or control flow between them. Use real paths in component entries. "
        "Prefer several connected sentences over terse labels; avoid a raw file "
        "inventory. State uncertainty if the supplied files do not establish a "
        "relationship. Do not invent runtime behavior. Return EXACTLY this JSON "
        "object and nothing else:\n"
        '{"architecture": {"summary": "str", "components": '
        '[{"name": "str", "role": "str", "path": "str"}], "data_flow": "str"}, '
        '"overview": {"purpose": "str", "description": "str"}}\n\n'
        f"FILE STRUCTURE:\n{body.structure[:3000]}\n\n"
        f"KEY FILES:\n{file_blobs[:30000]}\n\n"
        f"INDEXED SYMBOL SAMPLE:\n{_json.dumps(symbols)[:8000]}\n\n"
        f"INDEXED RELATION SAMPLE:\n{_json.dumps(edges)[:4000]}\n\n"
        f"CURRENT architecture (reference, may be stale):\n"
        f"{_json.dumps(cur_arch)[:3000] if cur_arch else 'none'}\n\n"
        f"CURRENT overview (reference):\n"
        f"{_json.dumps(cur_over)[:1000] if cur_over else 'none'}"
    )
    response = complete(
        task=Task.FOLDER_SUMMARY_REGROUND,
        max_tokens=3200,
        system=(
            "You write accurate, concise repo architecture/overview from source. "
            "Output only valid JSON."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="reground model returned invalid JSON")

    from services.folder_summary.briefing_schema import new_section

    validated: dict[str, dict] = {}
    for sec in ("architecture", "overview"):
        if _user_edited(sections.get(sec) or {}):
            continue
        value = data.get(sec)
        if sec == "overview":
            valid = (
                isinstance(value, dict)
                and isinstance(value.get("purpose"), str)
                and isinstance(value.get("description"), str)
                and bool(value["purpose"].strip())
                and bool(value["description"].strip())
            )
        else:
            valid = (
                isinstance(value, dict)
                and isinstance(value.get("summary"), str)
                and isinstance(value.get("components"), list)
                and isinstance(value.get("data_flow"), str)
                and bool(value["summary"].strip())
                and all(
                    isinstance(component, dict)
                    and all(isinstance(component.get(key), str) for key in ("name", "role", "path"))
                    for component in value["components"]
                )
            )
        old_content = (sections.get(sec) or {}).get("content")
        if (
            valid
            and isinstance(old_content, dict)
            and len(_json.dumps(old_content)) > 350
            and len(_json.dumps(value)) < len(_json.dumps(old_content)) // 2
        ):
            valid = False  # do not replace a detailed agent briefing with a thin summary
        if not valid:
            return {"ok": True, "updated": False, "reason": f"{sec} failed quality check"}
        validated[sec] = value
    updated: list[str] = []
    for sec, value in validated.items():
        sb.rpc(
            "set_briefing_section",
            {
                "p_folder_id": body.folder_id,
                "p_user_id": user_id,
                "p_section": sec,
                "p_value": new_section(
                    value, status="auto", provenance="auto", updated_by="mihari:guide-v2"
                ),
            },
        ).execute()
        updated.append(sec)
    return {"ok": True, "updated": bool(updated), "sections": updated}


class RegisterRepoRequest(BaseModel):
    folder_id: str
    remote_url: str = Field(min_length=8, max_length=500)
    branch: str = Field(default="main", max_length=200)


@router.post("/repos")
async def register_repo(body: RegisterRepoRequest, request: Request):
    """Register (or refresh) a repo for watching. Idempotent on
    (user, remote_url) so linking the same repo from a second computer just
    re-binds. Stores the CLI's own api key (encrypted) so Mihari indexes
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
