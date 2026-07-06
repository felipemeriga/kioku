"""GitHub integration routes — connect/disconnect + on-demand sync."""

from __future__ import annotations

import logging
import os

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase
from services.crypto import encrypt_secret
from services.github_sync import GitHubClient, parse_repo_url

router = APIRouter(prefix="/api/github")
log = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


_NEW_MODEL_COLUMNS = (
    "sync_mode",
    "local_clone_path",
    "last_fetched_at",
    "deploy_key_public",
    "deploy_key_private_encrypted",
)


def _upsert_config_downgrade_safe(sb, payload: dict) -> dict | None:
    """Upsert into github_sync_configs, tolerant of pre-migration DBs.

    If the local-clone-era columns (sync_mode, local_clone_path,
    last_fetched_at, deploy_key_*) don't exist yet, retry the upsert
    with those keys stripped. Keeps the endpoint working during a
    partial rollout.
    """
    try:
        r = (
            sb.table("github_sync_configs")
            .upsert(payload, on_conflict="user_id,root_folder_id")
            .execute()
            .data
        )
        return r[0] if r else None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        # Postgres tells us which column it doesn't recognise; if it
        # matches one of our new-model keys, drop them all and retry.
        if any(col in msg for col in _NEW_MODEL_COLUMNS):
            trimmed = {k: v for k, v in payload.items() if k not in _NEW_MODEL_COLUMNS}
            log.warning(
                "github/connect: DB missing new-model columns; "
                "retrying upsert without %s",
                sorted(set(payload) & set(_NEW_MODEL_COLUMNS)),
            )
            r = (
                sb.table("github_sync_configs")
                .upsert(trimmed, on_conflict="user_id,root_folder_id")
                .execute()
                .data
            )
            return r[0] if r else None
        raise


def _validate_folder(sb, folder_id: str, user_id: str) -> None:
    """Only checks ownership. Both root and sub-folders can host GitHub configs."""
    row = (
        sb.table("folders")
        .select("id")
        .eq("id", folder_id).eq("user_id", user_id)
        .limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")


class ConnectGitHubRequest(BaseModel):
    root_folder_id: str
    repo_url: str
    token: str | None = None
    since_days: int = Field(default=14, ge=1, le=365)


@router.get("/configs")
async def list_configs(user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    rows = (
        sb.table("github_sync_configs")
        .select("id, root_folder_id, repo_owner, repo_name, since_days, last_synced_at, last_error, created_at, updated_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute().data
    )
    folder_ids = [r["root_folder_id"] for r in rows]
    name_by_id = {}
    if folder_ids:
        # Defensive user_id filter — folder_ids came from a user-scoped query
        # but adding this makes the isolation self-evident and refactor-safe.
        fr = (
            sb.table("folders").select("id, name")
            .in_("id", folder_ids).eq("user_id", user_id)
            .execute().data
        )
        name_by_id = {f["id"]: f["name"] for f in fr}
    for r in rows:
        r["root_folder_name"] = name_by_id.get(r["root_folder_id"], "?")
        r["has_token"] = True  # we don't leak the token but expose whether one is stored
    return rows


@router.post("/connect")
async def connect(body: ConnectGitHubRequest, user_id: str = Depends(get_current_user)):
    """Connect a folder to a PUBLIC GitHub repo.

    UI callers should NOT pass a token — the endpoint clones the repo
    via HTTPS with no auth. Private/org repos need the deploy-key flow
    (POST /api/github/prepare-clone → CLI adds the key → POST
    /finalize-clone). We still accept `token` on the request body for
    backward compatibility with older CLIs but log a deprecation.

    On success the repo is cloned once to $KIOKU_REPOS_DIR/<owner>-<repo>
    (default ~/.local/share/kioku/repos). Subsequent briefing generations
    fetch from that clone — no more per-call API traffic.
    """
    sb = get_supabase()
    _validate_folder(sb, body.root_folder_id, user_id)

    try:
        owner, repo = parse_repo_url(body.repo_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from services.github_sync.local_repo import (
        LocalRepoClient,
        clone_public,
        GitError,
    )

    # Verify + clone. clone_public is idempotent — repeated calls no-op
    # if the clone already exists.
    if body.token:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "github/connect: token supplied for %s/%s — token path is "
            "deprecated. Public HTTPS clone will be attempted anyway.",
            owner, repo,
        )
    try:
        clone_path = clone_public(owner, repo, depth=30)
    except GitError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Couldn't clone {owner}/{repo}: {exc}. "
                f"If this is a private/org repo, connect via the Kioku CLI "
                f"which sets up a deploy key."
            ),
        )

    # Verify the clone actually holds a git history.
    ok, err = LocalRepoClient(owner=owner, repo=repo, clone_path=clone_path).ping()
    if not ok:
        raise HTTPException(status_code=400, detail=f"Clone check failed: {err}")

    from datetime import datetime, timezone as _tz
    payload = {
        "user_id": user_id,
        "root_folder_id": body.root_folder_id,
        "repo_owner": owner,
        "repo_name": repo,
        "since_days": body.since_days,
        "last_error": None,
        # New-model fields — column-adds land in the migration; if we're
        # running against a pre-migration DB, the .upsert below will
        # ignore unknown keys.
        "sync_mode": "public",
        "local_clone_path": str(clone_path),
        "last_fetched_at": datetime.now(_tz.utc).isoformat(),
    }
    row = _upsert_config_downgrade_safe(sb, payload)
    # Phase 1: flip the folder into a repo. Defensive — if the migration
    # hasn't landed yet, this update silently no-ops on unknown column and
    # the folder stays kind='folder'.
    try:
        sb.table("folders").update({"kind": "repo"}).eq(
            "id", body.root_folder_id
        ).eq("user_id", user_id).execute()
    except Exception:  # noqa: BLE001
        pass
    return row if row else {"ok": True}


@router.delete("/configs/{config_id}")
async def disconnect(
    config_id: str,
    delete_docs: bool = False,
    user_id: str = Depends(get_current_user),
):
    sb = get_supabase()
    # Find folder + owner before delete for optional doc cleanup.
    row = (
        sb.table("github_sync_configs").select("*")
        .eq("id", config_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Config not found")
    folder_id = row[0]["root_folder_id"]

    # Nuke the local clone if there is one. Best-effort — if the clone
    # was on a different host or is already gone, log and continue.
    try:
        from services.github_sync.local_repo import remove_clone
        remove_clone(row[0]["repo_owner"], row[0]["repo_name"])
    except Exception as exc:  # noqa: BLE001
        log.warning("github/disconnect: couldn't remove clone: %s", exc)

    sb.table("github_sync_configs").delete().eq("id", config_id).eq("user_id", user_id).execute()
    if delete_docs:
        sb.table("documents").delete().eq("user_id", user_id).eq("folder_id", folder_id).in_(
            "source_type", ["github_commit", "github_pr", "github_issue"],
        ).execute()
    # Phase 1: flip the folder back to a plain folder. Mem0 configs
    # attached to it stay — we don't force-disconnect Mem0, but it will
    # be hidden in the UI and blocked from new writes until the folder
    # becomes a repo again.
    try:
        sb.table("folders").update({"kind": "folder"}).eq(
            "id", folder_id
        ).eq("user_id", user_id).execute()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


class PrepareCloneRequest(BaseModel):
    root_folder_id: str
    repo_url: str  # 'owner/repo' or a full HTTPS/SSH URL
    since_days: int = Field(default=14, ge=1, le=365)


class PrepareCloneResponse(BaseModel):
    config_id: str
    public_key: str
    # A ready-to-paste terminal command for users who prefer manual
    # setup over gh CLI.
    manual_setup_hint: str


@router.post("/prepare-clone", response_model=PrepareCloneResponse)
async def prepare_clone(
    body: PrepareCloneRequest, user_id: str = Depends(get_current_user)
):
    """Step 1 of the deploy-key flow (CLI-invoked).

    Backend generates an Ed25519 SSH keypair, stores the private key
    encrypted at rest, returns the public key so the caller (CLI) can
    install it on the repo via `gh repo deploy-key add`. No cloning
    happens here — the clone attempt is a separate `finalize-clone`
    call so a failed key installation doesn't leave a half-cloned
    directory around.
    """
    sb = get_supabase()
    _validate_folder(sb, body.root_folder_id, user_id)

    try:
        owner, repo = parse_repo_url(body.repo_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from services.github_sync.local_repo import generate_deploy_keypair

    public_openssh, private_openssh = generate_deploy_keypair(
        comment=f"kioku-{owner}-{repo}"
    )

    payload = {
        "user_id": user_id,
        "root_folder_id": body.root_folder_id,
        "repo_owner": owner,
        "repo_name": repo,
        "since_days": body.since_days,
        "last_error": None,
        "sync_mode": "deploy_key",
        "deploy_key_public": public_openssh,
        "deploy_key_private_encrypted": encrypt_secret(private_openssh),
        # local_clone_path stays null until finalize-clone succeeds.
        "local_clone_path": None,
    }
    row = _upsert_config_downgrade_safe(sb, payload)
    if not row:
        raise HTTPException(status_code=500, detail="Failed to persist config")

    return PrepareCloneResponse(
        config_id=row["id"],
        public_key=public_openssh,
        manual_setup_hint=(
            f"gh repo deploy-key add - --repo {owner}/{repo} "
            f'--title "Kioku sync (read-only)" <<< "{public_openssh}"'
        ),
    )


class FinalizeCloneRequest(BaseModel):
    config_id: str


@router.post("/finalize-clone")
async def finalize_clone(
    body: FinalizeCloneRequest, user_id: str = Depends(get_current_user)
):
    """Step 2 of the deploy-key flow (CLI-invoked).

    After the user (or the CLI on their behalf) has installed the
    public key on the repo, this endpoint tries the SSH clone. Success
    persists `local_clone_path` and `last_fetched_at`; failure returns
    the git error verbatim so the CLI can render an actionable message
    ('deploy key not accepted — re-run prepare-clone', etc.).
    """
    sb = get_supabase()
    row = (
        sb.table("github_sync_configs").select("*")
        .eq("id", body.config_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Config not found")
    cfg = row[0]
    if cfg.get("sync_mode") != "deploy_key":
        raise HTTPException(
            status_code=400,
            detail=f"Config is in sync_mode={cfg.get('sync_mode')}, expected 'deploy_key'",
        )
    enc = cfg.get("deploy_key_private_encrypted")
    if not enc:
        raise HTTPException(
            status_code=400,
            detail="No deploy key on file — call /prepare-clone first",
        )

    from services.github_sync.local_repo import (
        LocalRepoClient,
        clone_via_ssh,
        GitError,
    )
    from services.crypto import decrypt_secret

    try:
        private_key = decrypt_secret(enc)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Couldn't decrypt stored private key — key material is corrupted",
        )

    try:
        clone_path = clone_via_ssh(
            cfg["repo_owner"],
            cfg["repo_name"],
            private_key_pem=private_key,
            depth=30,
        )
    except GitError as exc:
        # Persist the error so the UI can render it. Don't tear the
        # config down — the user may want to retry after re-adding the
        # deploy key.
        _upsert_config_downgrade_safe(sb, {
            "id": cfg["id"],
            "user_id": user_id,
            "root_folder_id": cfg["root_folder_id"],
            "repo_owner": cfg["repo_owner"],
            "repo_name": cfg["repo_name"],
            "last_error": str(exc)[:400],
        })
        raise HTTPException(
            status_code=400,
            detail=(
                f"Clone failed: {exc}. Make sure the deploy key is installed "
                f"on {cfg['repo_owner']}/{cfg['repo_name']}."
            ),
        )

    ok, err = LocalRepoClient(
        owner=cfg["repo_owner"],
        repo=cfg["repo_name"],
        clone_path=clone_path,
    ).ping()
    if not ok:
        raise HTTPException(status_code=500, detail=f"Post-clone health check failed: {err}")

    from datetime import datetime, timezone as _tz
    updated = _upsert_config_downgrade_safe(sb, {
        "user_id": user_id,
        "root_folder_id": cfg["root_folder_id"],
        "repo_owner": cfg["repo_owner"],
        "repo_name": cfg["repo_name"],
        "since_days": cfg.get("since_days") or 14,
        "sync_mode": "deploy_key",
        "local_clone_path": str(clone_path),
        "last_fetched_at": datetime.now(_tz.utc).isoformat(),
        "last_error": None,
        # Preserve keypair
        "deploy_key_public": cfg.get("deploy_key_public"),
        "deploy_key_private_encrypted": enc,
    })

    # Flip the folder into a repo (idempotent).
    try:
        sb.table("folders").update({"kind": "repo"}).eq(
            "id", cfg["root_folder_id"]
        ).eq("user_id", user_id).execute()
    except Exception:  # noqa: BLE001
        pass

    return updated if updated else {"ok": True}


class ListReposRequest(BaseModel):
    token: str = Field(min_length=8)


@router.post("/repos")
async def list_repos(body: ListReposRequest, user_id: str = Depends(get_current_user)):
    """Fetch the user's accessible repos (sorted by most recently pushed)
    so the connect dialog can render them as a picker instead of asking the
    user to paste a URL. Token is used only for this request and NOT persisted.
    """
    from services.github_sync import GitHubClient
    try:
        repos = GitHubClient.list_user_repos(body.token, max_items=200)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"GitHub rejected the token: {e}")
    return repos


@router.post("/configs/{config_id}/sync")
async def sync_now(config_id: str, user_id: str = Depends(get_current_user)):
    """Enqueue a github_sync_task."""
    sb = get_supabase()
    row = (
        sb.table("github_sync_configs").select("id, root_folder_id")
        .eq("id", config_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Config not found")
    pool = await create_pool(_redis_settings())
    try:
        # Deterministic job_id per config so multiple concurrent 'Sync now'
        # clicks collapse to a single in-flight job. Prevents the
        # delete-then-insert race in ingest_recent_activity where two
        # concurrent syncs on the same repo can erase each other's writes.
        job = await pool.enqueue_job(
            "github_sync_task",
            {"config_id": config_id, "user_id": user_id},
            _job_id=f"github_sync:{config_id}",
        )
    finally:
        await pool.close()
    return {"ok": True, "job_id": job.job_id if job else None}
