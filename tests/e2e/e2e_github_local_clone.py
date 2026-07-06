"""E2E: GitHub sync via local clones — every path.

  A. Public connect via API → clone on disk, DB has sync_mode=public +
     local_clone_path + last_fetched_at
  B. Reconnect same repo → idempotent, no duplicate clone
  C. Disconnect → clone wiped from disk + row deleted
  D. Deploy-key prepare → keypair generated, private encrypted, public
     returned
  E. Deploy-key finalize with clone already present → succeeds, sync_mode
     stays deploy_key
  F. LocalRepoClient reads real data — commits, branches, files from
     the clone
  G. Briefing regeneration hits _refresh_local_clone → last_fetched_at
     bumps forward
  H. Populator picks LocalRepoClient over PAT fallback when both are
     available
  I. Bad repo URL → 400
  J. Cross-user prepare-clone → still succeeds (each user gets their
     own config) but a user CANNOT finalize another user's config
  K. Legacy PAT-only config still routes through GitHubClient (backward
     compat)
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

BACKEND = "http://localhost:8000"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]

# Repo we test against — the just-renamed public kioku repo.
TEST_OWNER = "felipemeriga"
TEST_REPO = "kioku"

PASS, FAIL = [], []


def check(n, cond, d=""):
    (PASS if cond else FAIL).append(n)
    print(f"  {'✓' if cond else '✗'} {n}" + (f" — {d[:220]}" if not cond else ""))


def hr(t):
    print()
    print("═" * 74)
    print(f"  {t}")
    print("═" * 74)


def get_token(email: str = "felipe.meriga@gmail.com"):
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    for attempt in range(3):
        try:
            otp = admin.auth.admin.generate_link(
                {"type": "magiclink", "email": email}
            ).properties.email_otp
            anon = create_client(SUPABASE_URL, ANON)
            e = anon.auth.verify_otp(
                {"email": email, "token": otp, "type": "email"}
            )
            return e.session.access_token, e.user.id
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


async def cleanup_test_folders(c: httpx.AsyncClient, prefix: str):
    """Best-effort teardown."""
    try:
        folders = (await c.get(f"{BACKEND}/api/folders")).json()
        for f in folders:
            if f["name"].startswith(prefix):
                await c.delete(f"{BACKEND}/api/folders/{f['id']}?delete_docs=true")
    except Exception:
        pass


async def main():
    from db.client import get_supabase
    from services.github_sync.local_repo import clone_path_for, repos_dir

    sb = get_supabase()
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}
    tid = uuid.uuid4().hex[:6]
    prefix = f"e2e-gh-clone-{tid}"

    expected_clone = clone_path_for(TEST_OWNER, TEST_REPO)

    # Nuke any pre-existing clone so we test from scratch each run.
    if expected_clone.exists():
        shutil.rmtree(expected_clone, ignore_errors=True)

    async with httpx.AsyncClient(timeout=90, headers=H) as c:

        hr("A. Public connect via API — clone lands on disk + full DB row")
        r = await c.post(
            f"{BACKEND}/api/folders",
            json={"name": f"{prefix}-A", "parent_id": None},
        )
        folder_a = r.json()["id"]
        r = await c.post(
            f"{BACKEND}/api/github/connect",
            json={
                "root_folder_id": folder_a,
                "repo_url": f"{TEST_OWNER}/{TEST_REPO}",
                "since_days": 14,
            },
        )
        check(
            "A.1 POST /connect → 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )
        cfg_a = r.json()
        check(
            "A.2 clone directory exists on disk",
            expected_clone.exists() and (expected_clone / ".git").exists(),
            f"expected {expected_clone}",
        )
        # DB introspection
        row = (
            sb.table("github_sync_configs")
            .select("*")
            .eq("id", cfg_a["id"])
            .execute()
            .data
        )
        row = row[0] if row else {}
        check("A.3 sync_mode = 'public'", row.get("sync_mode") == "public",
              f"got: {row.get('sync_mode')}")
        check(
            "A.4 local_clone_path set",
            (row.get("local_clone_path") or "") == str(expected_clone),
            f"got: {row.get('local_clone_path')}",
        )
        check(
            "A.5 last_fetched_at set",
            bool(row.get("last_fetched_at")),
            f"got: {row.get('last_fetched_at')}",
        )
        check(
            "A.6 no PAT stored",
            not row.get("token_encrypted"),
            f"got: {row.get('token_encrypted')}",
        )
        check(
            "A.7 folder flipped to kind='repo'",
            (
                sb.table("folders")
                .select("kind")
                .eq("id", folder_a)
                .execute()
                .data[0]["kind"]
                == "repo"
            ),
        )

        hr("B. Reconnect — idempotent, no duplicate clones")
        r = await c.post(
            f"{BACKEND}/api/github/connect",
            json={
                "root_folder_id": folder_a,
                "repo_url": f"{TEST_OWNER}/{TEST_REPO}",
            },
        )
        check("B.1 second /connect → 200", r.status_code == 200, r.text[:200])
        check(
            "B.2 same clone path (no duplicate)",
            expected_clone.exists(),
            "clone missing after reconnect",
        )
        rows_now = (
            sb.table("github_sync_configs")
            .select("id")
            .eq("root_folder_id", folder_a)
            .eq("user_id", user_id)
            .execute()
            .data
            or []
        )
        check(
            "B.3 exactly ONE config row for this folder",
            len(rows_now) == 1,
            f"got {len(rows_now)}",
        )

        hr("C. Disconnect — clone wiped + row deleted")
        r = await c.delete(f"{BACKEND}/api/github/configs/{cfg_a['id']}")
        check("C.1 DELETE /configs → 200", r.status_code == 200)
        check(
            "C.2 clone removed from disk",
            not expected_clone.exists(),
            f"still there: {expected_clone}",
        )
        rows_after = (
            sb.table("github_sync_configs")
            .select("id")
            .eq("id", cfg_a["id"])
            .execute()
            .data
            or []
        )
        check("C.3 DB row gone", not rows_after, f"got {len(rows_after)} rows")

        hr("D. Deploy-key prepare — keypair generated + persisted encrypted")
        r = await c.post(
            f"{BACKEND}/api/folders",
            json={"name": f"{prefix}-D", "parent_id": None},
        )
        folder_d = r.json()["id"]
        r = await c.post(
            f"{BACKEND}/api/github/prepare-clone",
            json={
                "root_folder_id": folder_d,
                "repo_url": f"{TEST_OWNER}/{TEST_REPO}",
            },
        )
        check("D.1 POST /prepare-clone → 200", r.status_code == 200,
              r.text[:200])
        prep = r.json()
        check(
            "D.2 response has config_id + public_key + manual_setup_hint",
            all(k in prep for k in ("config_id", "public_key", "manual_setup_hint")),
            str(prep)[:200],
        )
        check(
            "D.3 public key looks like a valid ed25519 OpenSSH key",
            prep["public_key"].startswith("ssh-ed25519 "),
            prep["public_key"][:60],
        )
        check(
            "D.4 manual_setup_hint contains gh command",
            "gh repo deploy-key add" in prep["manual_setup_hint"],
            prep["manual_setup_hint"][:120],
        )
        # DB check
        row = (
            sb.table("github_sync_configs")
            .select("sync_mode, deploy_key_public, deploy_key_private_encrypted, local_clone_path")
            .eq("id", prep["config_id"])
            .execute()
            .data[0]
        )
        check(
            "D.5 DB sync_mode = 'deploy_key'",
            row.get("sync_mode") == "deploy_key",
            f"got: {row.get('sync_mode')}",
        )
        check(
            "D.6 DB deploy_key_public matches response",
            row.get("deploy_key_public") == prep["public_key"],
        )
        check(
            "D.7 DB deploy_key_private_encrypted is Fernet ciphertext",
            (row.get("deploy_key_private_encrypted") or "").startswith("gAAA"),
            (row.get("deploy_key_private_encrypted") or "")[:20],
        )
        check(
            "D.8 local_clone_path NOT set yet (finalize hasn't run)",
            not row.get("local_clone_path"),
            f"got: {row.get('local_clone_path')}",
        )

        hr("E. Deploy-key finalize on public repo — succeeds via SSH")
        # Public repos allow anonymous SSH clone; deploy-key auth is
        # technically not exercised, but the finalize flow (decrypt
        # private key, write to disk, invoke clone_via_ssh, ping) IS.
        if expected_clone.exists():
            shutil.rmtree(expected_clone, ignore_errors=True)
        r = await c.post(
            f"{BACKEND}/api/github/finalize-clone",
            json={"config_id": prep["config_id"]},
        )
        check(
            "E.1 POST /finalize-clone → 200",
            r.status_code == 200,
            r.text[:300],
        )
        row = (
            sb.table("github_sync_configs")
            .select("sync_mode, local_clone_path, last_fetched_at")
            .eq("id", prep["config_id"])
            .execute()
            .data[0]
        )
        check(
            "E.2 sync_mode stays 'deploy_key'",
            row.get("sync_mode") == "deploy_key",
        )
        check(
            "E.3 local_clone_path now set",
            (row.get("local_clone_path") or "") == str(expected_clone),
        )
        check(
            "E.4 last_fetched_at set on finalize",
            bool(row.get("last_fetched_at")),
        )
        check(
            "E.5 clone actually cloned",
            expected_clone.exists() and (expected_clone / ".git").exists(),
        )
        # Verify SSH command is baked into the clone's config
        try:
            import subprocess as _sp
            gitcfg = _sp.run(
                ["git", "config", "core.sshCommand"],
                cwd=expected_clone,
                capture_output=True,
                text=True,
                timeout=5,
            )
            check(
                "E.6 core.sshCommand baked into clone config",
                "IdentitiesOnly=yes" in gitcfg.stdout,
                gitcfg.stdout[:200],
            )
        except Exception as exc:
            check("E.6 core.sshCommand baked into clone config", False, str(exc))

        hr("F. LocalRepoClient reads real data from the clone")
        from services.github_sync.local_repo import LocalRepoClient
        lrc = LocalRepoClient(
            owner=TEST_OWNER, repo=TEST_REPO, clone_path=expected_clone
        )
        ok, err = lrc.ping()
        check("F.1 ping ok", ok, f"err: {err}")
        readme = lrc.fetch_file("README.md", max_bytes=200)
        check("F.2 README.md readable", bool(readme), f"got: {readme!r}")
        entries = lrc.list_dir("")
        check("F.3 root listing non-empty", len(entries) > 0, f"got: {len(entries)}")
        check(
            "F.4 root listing excludes .git",
            not any(e["name"].startswith(".git") for e in entries),
            f"got: {[e['name'] for e in entries[:5]]}",
        )
        commits = lrc.list_commits(days=180, max_items=5)
        check("F.5 commits parsed", len(commits) > 0, f"got: {len(commits)}")
        if commits:
            check(
                "F.6 commit has sha + title + author + date",
                all(
                    getattr(commits[0], f)
                    for f in ("sha", "title", "author", "created_at")
                ),
            )
        branches = lrc.list_branches(max_items=20)
        check("F.7 branches parsed", len(branches) > 0, f"got: {len(branches)}")
        check(
            "F.8 exactly one branch marked default",
            sum(1 for b in branches if b.is_default) == 1,
            f"defaults: {sum(1 for b in branches if b.is_default)}",
        )

        hr("G. Briefing regen bumps last_fetched_at forward")
        before_ts = row.get("last_fetched_at")
        await asyncio.sleep(2)  # ensure timestamp strictly moves
        # Trigger regen synchronously by calling _refresh_local_clone
        # directly (arq path would work too but is async + noisy).
        from services.folder_summary.briefing import _refresh_local_clone
        _refresh_local_clone(sb, folder_d, user_id)
        row_after = (
            sb.table("github_sync_configs")
            .select("last_fetched_at")
            .eq("id", prep["config_id"])
            .execute()
            .data[0]
        )
        check(
            "G.1 last_fetched_at advanced",
            (row_after.get("last_fetched_at") or "") > (before_ts or ""),
            f"before={before_ts} after={row_after.get('last_fetched_at')}",
        )

        hr("H. Populator picks LocalRepoClient over PAT fallback")
        from services.folder_summary.llm_populators import _github_client_for_folder
        client = _github_client_for_folder(sb, folder_d, user_id)
        check(
            "H.1 populator client is LocalRepoClient",
            client is not None
            and client.__class__.__name__ == "LocalRepoClient",
            f"got: {client.__class__.__name__ if client else 'None'}",
        )

        hr("I. Bad repo URL → 400")
        r = await c.post(
            f"{BACKEND}/api/github/connect",
            json={"root_folder_id": folder_d, "repo_url": "not-a-valid-repo"},
        )
        check(
            "I.1 malformed URL → 400",
            r.status_code == 400,
            f"got {r.status_code}: {r.text[:200]}",
        )
        r = await c.post(
            f"{BACKEND}/api/github/prepare-clone",
            json={"root_folder_id": folder_d, "repo_url": "http://not-github.com/x"},
        )
        check(
            "I.2 prepare-clone with bogus URL → 400",
            r.status_code == 400,
            f"got {r.status_code}: {r.text[:200]}",
        )

        hr("J. Cross-user isolation — user2 can't finalize user1's config")
        admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
        email2 = f"e2e-clone-{uuid.uuid4().hex[:6]}@example.test"
        u2 = admin.auth.admin.create_user({
            "email": email2,
            "email_confirm": True,
            "password": "Passw0rd!" + uuid.uuid4().hex,
        })
        try:
            otp = admin.auth.admin.generate_link(
                {"type": "magiclink", "email": email2}
            ).properties.email_otp
            anon = create_client(SUPABASE_URL, ANON)
            e = anon.auth.verify_otp(
                {"email": email2, "token": otp, "type": "email"}
            )
            H2 = {"Authorization": f"Bearer {e.session.access_token}"}
            async with httpx.AsyncClient(timeout=30, headers=H2) as c2:
                r = await c2.post(
                    f"{BACKEND}/api/github/finalize-clone",
                    json={"config_id": prep["config_id"]},
                )
                check(
                    "J.1 user2 finalize-clone on user1's config → 404",
                    r.status_code == 404,
                    f"got {r.status_code}: {r.text[:200]}",
                )
                # user2 should be able to prepare-clone on their own folder
                r = await c2.post(
                    f"{BACKEND}/api/folders",
                    json={"name": f"{prefix}-u2", "parent_id": None},
                )
                folder_u2 = r.json()["id"]
                r = await c2.post(
                    f"{BACKEND}/api/github/prepare-clone",
                    json={
                        "root_folder_id": folder_u2,
                        "repo_url": f"{TEST_OWNER}/{TEST_REPO}",
                    },
                )
                check(
                    "J.2 user2 prepare-clone on their own folder → 200",
                    r.status_code == 200,
                    r.text[:200],
                )
                # user2 keys should be independent from user1's
                prep2 = r.json() if r.status_code == 200 else {}
                check(
                    "J.3 user2 gets a DIFFERENT public key",
                    prep2.get("public_key")
                    and prep2["public_key"] != prep["public_key"],
                )
        finally:
            admin.auth.admin.delete_user(u2.user.id)

        hr("K. Legacy PAT-only config still routes through GitHubClient")
        # Manually insert a legacy config with only token_encrypted + no clone
        r = await c.post(
            f"{BACKEND}/api/folders",
            json={"name": f"{prefix}-K-legacy", "parent_id": None},
        )
        folder_k = r.json()["id"]
        from services.crypto import encrypt_secret
        sb.table("github_sync_configs").insert({
            "user_id": user_id,
            "root_folder_id": folder_k,
            "repo_owner": TEST_OWNER,
            "repo_name": TEST_REPO,
            "token_encrypted": encrypt_secret("ghp_fake_legacy_token_" + uuid.uuid4().hex),
            "since_days": 14,
            "sync_mode": "token",
            "local_clone_path": None,
        }).execute()
        # Populator on this folder should fall back to GitHubClient
        legacy_client = _github_client_for_folder(sb, folder_k, user_id)
        check(
            "K.1 legacy config gets GitHubClient (not None)",
            legacy_client is not None
            and legacy_client.__class__.__name__ == "GitHubClient",
            f"got: {legacy_client.__class__.__name__ if legacy_client else 'None'}",
        )

        hr("Cleanup")
        await cleanup_test_folders(c, prefix)
        if expected_clone.exists():
            shutil.rmtree(expected_clone, ignore_errors=True)

    print()
    print("═" * 74)
    print(f"GITHUB LOCAL CLONE: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL:
        print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
