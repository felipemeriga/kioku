"""LocalRepoClient — read repo state from a local git clone.

Same duck-typed interface as GitHubClient (list_dir, fetch_file,
list_commits, ping) but backed by filesystem + git plumbing instead of
GitHub's REST API. Zero network traffic per call. Fresh data comes
from an explicit `git fetch --all` performed before summary generation.

Why: kills token-lifetime issues (org policies that force 1-day PATs
break every 24h), removes rate-limit constraints, and makes summary
generation deterministic and inspectable — you can `cat` the clone.

Missing vs GitHubClient by design:
  - list_prs / list_issues (PRs/issues live in GitHub's DB, not git).
    We compensate by exposing branches — same signal quality (in-flight
    work), zero API traffic.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


# ── Data classes — parity with client.py ──────────────────────────────

@dataclass
class Commit:
    sha: str
    title: str
    body: str
    author: str
    created_at: str
    url: str


@dataclass
class Branch:
    name: str
    last_commit_sha: str
    last_commit_title: str
    last_commit_date: str
    is_default: bool


# ── Repos root — where clones live on disk ────────────────────────────

def repos_dir() -> Path:
    """Root directory holding every clone. Env override for containers."""
    override = os.environ.get("KIOKU_REPOS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".local" / "share" / "kioku" / "repos"


def clone_path_for(owner: str, repo: str) -> Path:
    """Deterministic per-repo directory. `.` in repo name is normalized
    to `-` because filesystems dislike leading dots and dots-in-names."""
    safe = f"{owner.lower()}-{repo.lower().replace('.', '-')}"
    return repos_dir() / safe


# ── Git helpers ───────────────────────────────────────────────────────

class GitError(RuntimeError):
    """Anything git returned non-zero for."""


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
    env: dict | None = None,
) -> str:
    """Run git and return stdout. Raises GitError on failure so callers
    can decide whether to log-and-continue or fail hard."""
    full_env = os.environ.copy()
    # Non-interactive: never prompt for credentials, never open editor.
    full_env["GIT_TERMINAL_PROMPT"] = "0"
    full_env["GIT_ASKPASS"] = "/bin/true"
    if env:
        full_env.update(env)
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full_env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc

    if result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} → exit {result.returncode}: "
            f"{result.stderr.strip()[:400]}"
        )
    return result.stdout


def clone_public(owner: str, repo: str, *, depth: int = 30) -> Path:
    """Clone via HTTPS with shallow + partial fetches to keep sizes small.

    depth=30 means the last 30 commits per branch — enough for the
    activity window we surface in briefings. Partial (blob:none) skips
    file contents until needed, then git fetches blobs lazily on
    `git show`/`cat`/`log --patch`. `--no-single-branch` ensures we
    fetch every remote branch, not just the default — the briefing
    surfaces in-flight branches as a signal.
    """
    dst = clone_path_for(owner, repo)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        log.info("local_repo: %s/%s already cloned, skipping", owner, repo)
        return dst
    url = f"https://github.com/{owner}/{repo}.git"
    _run_git(
        ["clone", "--depth", str(depth), "--filter=blob:none",
         "--no-single-branch", url, str(dst)],
        timeout=120,
    )
    log.info("local_repo: cloned %s/%s → %s", owner, repo, dst)
    return dst


def clone_via_ssh(
    owner: str,
    repo: str,
    *,
    private_key_pem: str,
    depth: int = 30,
) -> Path:
    """Clone via git+ssh using a deploy key. Private key is passed
    inline via GIT_SSH_COMMAND so it never touches disk permanently."""
    dst = clone_path_for(owner, repo)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return dst

    # Write the private key to a temp path with 0600 perms — sshd
    # refuses to use keys with looser modes.
    key_dir = dst.parent / f".{dst.name}.ssh"
    key_dir.mkdir(parents=True, exist_ok=True)
    key_path = key_dir / "id_deploy"
    key_path.write_text(
        private_key_pem if private_key_pem.endswith("\n") else private_key_pem + "\n"
    )
    key_path.chmod(0o600)

    try:
        ssh_cmd = (
            f'ssh -i {key_path} -o IdentitiesOnly=yes '
            f'-o StrictHostKeyChecking=accept-new '
            f'-o UserKnownHostsFile=/dev/null'
        )
        url = f"git@github.com:{owner}/{repo}.git"
        _run_git(
            ["clone", "--depth", str(depth), "--filter=blob:none",
             "--no-single-branch", url, str(dst)],
            timeout=120,
            env={"GIT_SSH_COMMAND": ssh_cmd},
        )
        # Persist the key inside the clone's config so subsequent fetch
        # calls don't need the caller to re-inject it.
        _persist_ssh_command(dst, key_path)
    except Exception:
        # If clone failed we should leave nothing behind that pretends
        # to be a valid repo — otherwise later "clone if missing" logic
        # will incorrectly skip.
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        raise
    log.info("local_repo: cloned %s/%s via SSH → %s", owner, repo, dst)
    return dst


def _persist_ssh_command(clone: Path, key_path: Path) -> None:
    """Bake the ssh command into the clone's git config so fetch works
    without the caller having to re-set GIT_SSH_COMMAND every time."""
    ssh_cmd = (
        f'ssh -i {key_path} -o IdentitiesOnly=yes '
        f'-o StrictHostKeyChecking=accept-new '
        f'-o UserKnownHostsFile=/dev/null'
    )
    _run_git(["config", "core.sshCommand", ssh_cmd], cwd=clone)


def fetch(clone: Path, *, timeout: int = 30) -> bool:
    """Best-effort git fetch. Returns True on success, False on any
    failure — callers should treat False as 'work with stale data'."""
    if not clone.exists() or not (clone / ".git").exists():
        log.warning("local_repo: fetch on non-existent clone %s", clone)
        return False
    try:
        _run_git(["fetch", "--all", "--prune"], cwd=clone, timeout=timeout)
        return True
    except GitError as exc:
        log.warning("local_repo: fetch failed for %s: %s", clone, exc)
        return False


def remove_clone(owner: str, repo: str) -> None:
    """Wipe a clone. Used when a folder's GitHub config is deleted."""
    dst = clone_path_for(owner, repo)
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    # Also nuke the SSH key dir if we made one.
    key_dir = dst.parent / f".{dst.name}.ssh"
    if key_dir.exists():
        shutil.rmtree(key_dir, ignore_errors=True)


# ── LocalRepoClient — duck-typed to match GitHubClient ────────────────

class LocalRepoClient:
    """Read repo state from a local clone. Same shape as GitHubClient."""

    def __init__(self, owner: str, repo: str, clone_path: Path | str | None = None):
        self.owner = owner
        self.repo = repo
        self.clone = Path(clone_path) if clone_path else clone_path_for(owner, repo)

    def __enter__(self) -> "LocalRepoClient":
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def close(self) -> None:
        return None

    # ── Files ────────────────────────────────────────────────────────

    def fetch_file(self, path: str, *, max_bytes: int = 100_000) -> str | None:
        """Read a file from the working tree. Returns None if missing."""
        safe = (self.clone / path).resolve()
        # Guardrail: don't let a `../..` path escape the clone dir.
        try:
            safe.relative_to(self.clone.resolve())
        except ValueError:
            return None
        if not safe.is_file():
            return None
        try:
            with open(safe, "rb") as f:
                raw = f.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raw = raw[:max_bytes]
            return raw.decode("utf-8", errors="replace")
        except OSError:
            return None

    def list_dir(self, path: str = "") -> list[dict]:
        """Return entries at a path. Mirrors GitHubClient shape:
        [{name, type: 'file'|'dir'}, ...]"""
        target = (self.clone / path) if path else self.clone
        try:
            target = target.resolve()
            target.relative_to(self.clone.resolve())
        except (ValueError, OSError):
            return []
        if not target.is_dir():
            return []
        entries: list[dict] = []
        for e in sorted(target.iterdir()):
            if e.name.startswith(".git") and path == "":
                # `.git` internals aren't useful for briefing content.
                continue
            entries.append({
                "name": e.name,
                "type": "dir" if e.is_dir() else "file",
            })
        return entries

    # ── Commits ──────────────────────────────────────────────────────

    def list_commits(self, days: int = 14, max_items: int = 100) -> list[Commit]:
        """Parse `git log --since=<days>d`. Best-effort — returns [] on
        any git error."""
        since = f"{days}.days.ago"
        # We only want the header line per commit (no bodies) — that
        # avoids embedded newlines and makes parsing trivial. Fields
        # are separated by '|' (safe: SHAs/dates/names can't contain
        # '|' and titles rarely do).
        sep = "|"
        pretty = f"--pretty=format:%H{sep}%s{sep}%an{sep}%aI"
        try:
            out = _run_git(
                ["log", f"--since={since}", f"--max-count={max_items}", pretty],
                cwd=self.clone,
            )
        except GitError as exc:
            log.warning("local_repo: git log failed: %s", exc)
            return []
        commits: list[Commit] = []
        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(sep, 3)
            if len(parts) < 4:
                continue
            sha, title, author, date = parts[0], parts[1], parts[2], parts[3]
            commits.append(Commit(
                sha=sha,
                title=title,
                body="",  # bodies fetched on-demand via `git show`
                author=author,
                created_at=date,
                url=f"https://github.com/{self.owner}/{self.repo}/commit/{sha}",
            ))
        return commits

    # ── Branches (new — replaces PRs/issues signal) ──────────────────

    def list_branches(self, *, max_items: int = 50) -> list[Branch]:
        """List remote branches with their latest commit. Substitutes
        for the PR list — an active branch usually IS in-flight work,
        and unlike PRs we can read this from git plumbing."""
        default = self._default_branch()
        # `|` between fields — safe because refnames + SHAs + dates
        # can't contain `|`, and subject lines rarely do. Records are
        # separated by real newlines.
        # NB: don't use \x1e as a field sep — Python's splitlines()
        # treats it as a line break, corrupting downstream parsing.
        sep = "|"
        try:
            out = _run_git([
                "for-each-ref",
                f"--format=%(refname:short){sep}%(objectname){sep}"
                f"%(contents:subject){sep}%(committerdate:iso8601)",
                "--sort=-committerdate",
                f"--count={max_items}",
                "refs/remotes/",
            ], cwd=self.clone)
        except GitError as exc:
            log.warning("local_repo: for-each-ref failed: %s", exc)
            return []
        branches: list[Branch] = []
        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(sep, 3)  # max 3 splits so subject can contain '|'
            if len(parts) < 4:
                continue
            name, sha, title, date = parts[0], parts[1], parts[2], parts[3]
            # Strip the "origin/" prefix so consumers see plain names.
            local_name = name.split("/", 1)[1] if "/" in name else name
            # Skip the origin HEAD ref (bare "origin" name — the symbolic
            # ref to origin/main) and any literal HEAD.
            if name == "origin" or local_name in ("HEAD",):
                continue
            branches.append(Branch(
                name=local_name,
                last_commit_sha=sha,
                last_commit_title=title,
                last_commit_date=date,
                is_default=(local_name == default),
            ))
        return branches

    def _default_branch(self) -> str:
        """Best-guess default branch. Falls back to 'main'."""
        try:
            out = _run_git(
                ["symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=self.clone,
            )
            # Format: refs/remotes/origin/main
            return out.strip().split("/")[-1] or "main"
        except GitError:
            return "main"

    # ── Health ───────────────────────────────────────────────────────

    def ping(self) -> tuple[bool, str | None]:
        """Return (ok, error). ok=True if the clone exists + has a HEAD."""
        if not self.clone.exists():
            return False, f"clone missing at {self.clone}"
        if not (self.clone / ".git").exists():
            return False, f"not a git repo: {self.clone}"
        try:
            _run_git(["rev-parse", "HEAD"], cwd=self.clone, timeout=5)
            return True, None
        except GitError as exc:
            return False, str(exc)
