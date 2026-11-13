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
import logging
import os
import re
import stat
import subprocess
import tempfile
from datetime import date, datetime, timezone

from anthropic import BadRequestError
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from db.client import get_supabase_thread_safe as get_supabase
from services.crypto import decrypt_secret, encrypt_secret

router = APIRouter()
logger = logging.getLogger(__name__)


def _raise_if_credit_exhausted(exc: BadRequestError) -> None:
    if "credit balance is too low" in str(exc).lower():
        raise HTTPException(
            status_code=503,
            detail=(
                "Anthropic credits exhausted for the Kioku backend key; restore billing "
                "or replace the key with one from a credited organization."
            ),
        ) from exc


def _user_edited(section: dict) -> bool:
    # Older `kioku init --force` clients pinned agent-generated sections.
    # Provenance, not the legacy pin flag, identifies a deliberate UI edit.
    return section.get("provenance") == "user_ui"


REVIEWED_SECTIONS = (
    "overview",
    "architecture",
    "how_it_runs",
    "deployment",
    "activity",
    "documentation",
)


class LearningRefreshRequest(BaseModel):
    folder_id: str
    head_sha: str = Field(min_length=40, max_length=64)
    main_commits: list[str] = Field(default_factory=list, max_length=80)


@router.post("/learnings")
def refresh_learnings(body: LearningRefreshRequest, request: Request):
    return _run_maintenance(body, request, "learnings")


class ReportCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    at: datetime
    text: str = Field(min_length=1, max_length=1600)
    url: str | None = Field(default=None, max_length=500)


class ReportPull(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(ge=1, le=2147483647)
    at: datetime
    text: str = Field(min_length=1, max_length=1600)
    url: str = Field(
        max_length=500, pattern=r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+$"
    )


class ReportRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("timezone")
    @classmethod
    def report_zone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Invalid timezone") from exc
        return value

    folder_id: str = Field(
        pattern=r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$"
    )
    head_sha: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    commits: list[ReportCommit] = Field(default_factory=list, max_length=1000)
    pull_requests: list[ReportPull] = Field(default_factory=list, max_length=200)
    github_coverage: str = Field(default="unavailable", max_length=100)
    head_at: datetime | None = None
    report_kind: str | None = Field(default=None, pattern=r"^(weekly|monthly)$")
    period_start: date | None = None

    @model_validator(mode="after")
    def valid_report_period(self):
        from services.period_reports import calendar_period

        if (self.report_kind is None) != (self.period_start is None):
            raise ValueError("Report kind and period start must be supplied together")
        if (
            self.report_kind
            and calendar_period(self.report_kind, self.period_start)[0] != self.period_start
        ):
            raise ValueError("Report period must start on Monday or the first of the month")
        stamps = [item.at for item in [*self.commits, *self.pull_requests]]
        if self.head_at:
            stamps.append(self.head_at)
        if any(stamp.tzinfo is None for stamp in stamps):
            raise ValueError("Evidence timestamps require timezone")
        return self


@router.post("/reports/plan")
def plan_reports(body: ReportRefreshRequest, request: Request):
    from services.period_reports import next_report_period

    owner, sb = _authorized_maintenance(request, body.folder_id)
    return {"period": next_report_period(sb, owner, body.folder_id, body.model_dump(mode="json"))}


@router.post("/reports")
def refresh_reports(body: ReportRefreshRequest, request: Request):
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(body.timezone)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="Invalid timezone") from exc
    if any(item.at.tzinfo is None for item in [*body.commits, *body.pull_requests]):
        raise HTTPException(status_code=422, detail="Evidence timestamps require timezone")
    return _run_maintenance(body, request, "reports")


class ReviewPlanRequest(BaseModel):
    folder_id: str
    head_sha: str = Field(min_length=40, max_length=64)
    changed_paths: list[str] = Field(default_factory=list, max_length=300)
    commits: list[str] = Field(default_factory=list, max_length=50)
    patch: str = Field(default="", max_length=18000)


@router.post("/review-plan")
def review_plan(body: ReviewPlanRequest, request: Request):
    return _run_maintenance(body, request, "review_plan")


class ReviewCompleteRequest(BaseModel):
    folder_id: str
    head_sha: str = Field(min_length=40, max_length=64)
    reviewed: list[str] = Field(default_factory=list, max_length=len(REVIEWED_SECTIONS))


@router.post("/review-complete")
def review_complete(body: ReviewCompleteRequest, request: Request):
    """Record inspection separately from content changes and generation dates."""
    user_id, scope_id, _ = _api_key_auth(request)
    sb = get_supabase()
    from mcp_server import _descendant_folder_ids

    if body.folder_id not in _descendant_folder_ids(sb, scope_id, user_id):
        raise HTTPException(status_code=403, detail="folder_id not in api key scope")
    if any(name not in REVIEWED_SECTIONS for name in body.reviewed):
        raise HTTPException(status_code=422, detail="invalid section")
    from services.maintenance.execution import native_enabled

    if native_enabled(user_id):
        passes = (
            sb.table("maintenance_review_passes")
            .select("head_sha,selected,acknowledged")
            .eq("folder_id", body.folder_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if (
            not passes
            or passes[0]["head_sha"] != body.head_sha
            or not (set(passes[0]["selected"]) - {"documentation"}).issubset(
                passes[0]["acknowledged"]
            )
        ):
            raise HTTPException(
                status_code=409, detail="maintenance pass is not fully acknowledged"
            )
        return {"ok": True, "reviewed": body.reviewed}
    existing = (
        sb.table("repo_freshness")
        .select("section_reviews")
        .eq("folder_id", body.folder_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    reviews = (existing[0].get("section_reviews") or {}) if existing else {}
    marker = {"reviewed_at": datetime.now(timezone.utc).isoformat(), "head_sha": body.head_sha}
    reviews.update({name: marker for name in body.reviewed})
    sb.table("repo_freshness").upsert(
        {"folder_id": body.folder_id, "user_id": user_id, "section_reviews": reviews},
        on_conflict="folder_id",
    ).execute()
    return {"ok": True, "reviewed": body.reviewed}


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
def get_or_create_key(request: Request):
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
def test_access(body: TestAccessRequest, request: Request):
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
def refresh_activity(body: ActivityRefreshRequest, request: Request):
    return _run_maintenance(body, request, "activity")


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
def refresh_section(body: SectionRefreshRequest, request: Request):
    return _run_maintenance(body, request, body.section)


class RegroundFile(BaseModel):
    path: str = Field(max_length=400)
    content: str = Field(max_length=16000)


class RegroundRequest(BaseModel):
    folder_id: str
    head_sha: str = Field(default="", max_length=64)
    files: list[RegroundFile] = Field(default_factory=list, max_length=14)
    structure: str = Field(default="", max_length=4000)
    selected: list[str] = Field(default_factory=lambda: ["architecture", "overview"])


@router.post("/reground")
def reground_holistic(body: RegroundRequest, request: Request):
    return _run_maintenance(body, request, "reground")


class DocumentationRefreshRequest(BaseModel):
    folder_id: str
    head_sha: str = Field(min_length=40, max_length=64)
    files: list[RegroundFile] = Field(default_factory=list, max_length=12)
    patch: str = Field(default="", max_length=12000)


@router.post("/documentation")
def refresh_documentation(body: DocumentationRefreshRequest, request: Request):
    return _run_maintenance(body, request, "documentation")


class RegisterRepoRequest(BaseModel):
    folder_id: str
    remote_url: str = Field(min_length=8, max_length=500)
    branch: str = Field(default="main", max_length=200)


@router.post("/repos")
def register_repo(body: RegisterRepoRequest, request: Request):
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


def _authorized_maintenance(request, folder, *, require_repo=True):
    owner, scope, _ = _api_key_auth(request)
    sb = get_supabase()
    from mcp_server import _descendant_folder_ids

    if folder not in _descendant_folder_ids(sb, scope, owner):
        raise HTTPException(status_code=403, detail="folder_id not in api key scope")
    if require_repo:
        rows = (
            sb.table("folders")
            .select("kind")
            .eq("id", folder)
            .eq("user_id", owner)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows or rows[0].get("kind") != "repo":
            raise HTTPException(status_code=404, detail="Repository not found")
    return owner, sb


def _run_maintenance(body, request, operation):
    from services.maintenance.execution import execute_api, native_enabled

    owner, sb = _authorized_maintenance(request, body.folder_id, require_repo=False)
    try:
        if native_enabled(owner):
            raise HTTPException(status_code=409, detail="direct maintenance execution required")
        payload = body.model_dump(mode="json")
        payload["head_sha"] = payload.get("head_sha") or "legacy"
        if operation == "learnings":
            total = {"ok": True, "processed_entries": 0, "updated_learnings": 0}
            for _ in range(3):
                result = execute_api(sb, owner, body.folder_id, operation, payload)
                for key in ("processed_entries", "updated_learnings"):
                    total[key] += result.get(key, 0)
                if not result.get("processed_entries"):
                    break
            return total
        return execute_api(sb, owner, body.folder_id, operation, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        detail = "invalid briefing review plan" if operation == "review_plan" else str(exc)
        raise HTTPException(status_code=502, detail=detail) from exc
    except BadRequestError as exc:
        _raise_if_credit_exhausted(exc)
        raise


class MaintenancePrepareRequest(BaseModel):
    operation: str
    payload: dict


class MaintenancePublishRequest(BaseModel):
    folder_id: str
    preparation_id: str
    job_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


@router.post("/execution/prepare")
def prepare_maintenance(body: MaintenancePrepareRequest, request: Request):
    from services.maintenance.execution import native_enabled, prepare

    models = {
        "review_plan": ReviewPlanRequest,
        "activity": ActivityRefreshRequest,
        "how_it_runs": SectionRefreshRequest,
        "deployment": SectionRefreshRequest,
        "reground": RegroundRequest,
        "documentation": DocumentationRefreshRequest,
        "learnings": LearningRefreshRequest,
        "reports": ReportRefreshRequest,
    }
    if body.operation not in models:
        raise HTTPException(status_code=422, detail="invalid maintenance operation")
    try:
        parsed = models[body.operation].model_validate(body.payload)
        owner, sb = _authorized_maintenance(request, parsed.folder_id)
        if not native_enabled(owner):
            return {"ok": True, "engine": "api"}
        if body.operation == "reports":
            from zoneinfo import ZoneInfo

            ZoneInfo(parsed.timezone)
            if any(item.at.tzinfo is None for item in [*parsed.commits, *parsed.pull_requests]):
                raise ValueError("Evidence timestamps require timezone")
        payload = parsed.model_dump(mode="json")
        head = payload.get("head_sha", "")
        if not re.fullmatch(r"[0-9a-f]{40,64}", head):
            raise HTTPException(status_code=422, detail="native maintenance requires HEAD")
        if (
            body.operation in ("how_it_runs", "deployment")
            and payload.get("section") != body.operation
        ):
            raise HTTPException(status_code=422, detail="section/operation mismatch")
        return prepare(sb, owner, parsed.folder_id, body.operation, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/execution/publish")
def publish_maintenance(body: MaintenancePublishRequest, request: Request):
    from postgrest.exceptions import APIError

    from services.ai.client import ExecutionError
    from services.maintenance.execution import native_enabled, publish

    owner, sb = _authorized_maintenance(request, body.folder_id)
    try:
        if not native_enabled(owner):
            raise HTTPException(status_code=409, detail="native maintenance is disabled")
        return publish(sb, owner, body.folder_id, body.preparation_id, body.job_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ExecutionError as exc:
        raise HTTPException(status_code=502, detail="maintenance execution: " + exc.code) from exc
    except APIError as exc:
        if exc.code in ("P0001", "23505"):
            raise HTTPException(
                status_code=409, detail="stale or duplicate maintenance publication"
            ) from exc
        raise
