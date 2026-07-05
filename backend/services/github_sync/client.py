"""Thin GitHub REST client. No 3rd-party lib — just httpx + the public API.

Scope is intentionally minimal:
  - list_commits(since)  → last N days of commits (title + first line of message)
  - list_prs(since)      → recent PRs (title, body, state)
  - list_issues(since)   → recent issues (title, body, state)

Pagination is bounded (max 100 per resource) to keep ingestion cheap. If you
need more history, sync more often.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)


GITHUB_API_BASE = "https://api.github.com"
DEFAULT_UA = "agentic-rag-github-sync/1.0"


_REPO_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?/?$"
)


def parse_repo_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a github URL or 'owner/repo' shortcut."""
    if "/" in url and "github.com" not in url and url.count("/") == 1:
        owner, repo = url.split("/", 1)
        return owner.strip(), repo.strip()
    m = _REPO_URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"Not a recognizable GitHub repo url: {url!r}")
    return m.group(1), m.group(2)


@dataclass
class Commit:
    sha: str
    title: str
    body: str
    author: str
    created_at: str
    url: str


@dataclass
class PullRequest:
    number: int
    title: str
    body: str
    state: str
    author: str
    created_at: str
    updated_at: str
    merged_at: str | None
    url: str


@dataclass
class Issue:
    number: int
    title: str
    body: str
    state: str
    author: str
    created_at: str
    updated_at: str
    url: str


class GitHubClient:
    def __init__(self, owner: str, repo: str, token: str | None = None):
        self.owner = owner
        self.repo = repo
        self.token = token
        self._client = httpx.Client(
            base_url=GITHUB_API_BASE,
            headers=self._headers(),
            timeout=15.0,
            follow_redirects=True,
        )

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": DEFAULT_UA,
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()

    # ── Raw content fetchers (used by the briefing LLM populators) ────────

    def fetch_file(self, path: str, *, max_bytes: int = 100_000) -> str | None:
        """Fetch a single file by path. Returns None on 404 / error.

        Uses the /repos/{owner}/{repo}/contents API with the raw accept
        header — one round-trip regardless of default branch, and it works
        for private repos via the same token.
        """
        try:
            r = self._client.get(
                f"/repos/{self.owner}/{self.repo}/contents/{path}",
                headers={"Accept": "application/vnd.github.raw"},
            )
        except Exception:  # noqa: BLE001
            return None
        if r.status_code == 200:
            body = r.text or ""
            # Cap so a monster README doesn't blow the LLM budget.
            return body[:max_bytes]
        return None

    def list_dir(self, path: str = "") -> list[dict]:
        """List a directory. Each entry: {name, path, type: 'file'|'dir', size}."""
        try:
            r = self._client.get(
                f"/repos/{self.owner}/{self.repo}/contents/{path}",
                headers={"Accept": "application/vnd.github+json"},
            )
        except Exception:  # noqa: BLE001
            return []
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return [
            {
                "name": e.get("name"),
                "path": e.get("path"),
                "type": e.get("type"),
                "size": e.get("size", 0),
            }
            for e in data
        ]

    def ping(self) -> tuple[bool, str | None]:
        try:
            r = self._client.get(f"/repos/{self.owner}/{self.repo}")
            if r.status_code == 200:
                return True, None
            if r.status_code == 401:
                return False, "GitHub rejected the token (401)."
            if r.status_code == 404:
                return False, "Repo not found (private without a token? typo?)."
            return False, f"GitHub returned {r.status_code}: {r.text[:200]}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def _since_iso(self, days: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def list_commits(self, days: int = 14, max_items: int = 100) -> list[Commit]:
        r = self._client.get(
            f"/repos/{self.owner}/{self.repo}/commits",
            params={"since": self._since_iso(days), "per_page": min(max_items, 100)},
        )
        r.raise_for_status()
        out: list[Commit] = []
        for c in r.json():
            msg = (c.get("commit") or {}).get("message") or ""
            title, _, body = msg.partition("\n")
            out.append(
                Commit(
                    sha=c["sha"],
                    title=title.strip() or "(no message)",
                    body=body.strip(),
                    author=((c.get("commit") or {}).get("author") or {}).get("name") or "?",
                    created_at=((c.get("commit") or {}).get("author") or {}).get("date") or "",
                    url=c.get("html_url") or "",
                )
            )
        return out

    def list_prs(self, days: int = 30, max_items: int = 50) -> list[PullRequest]:
        # We list all state=all sorted by updated_at desc, then time-window client-side.
        r = self._client.get(
            f"/repos/{self.owner}/{self.repo}/pulls",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": min(max_items, 100)},
        )
        r.raise_for_status()
        cutoff = self._since_iso(days)
        out: list[PullRequest] = []
        for pr in r.json():
            if (pr.get("updated_at") or "") < cutoff:
                break
            out.append(
                PullRequest(
                    number=pr["number"],
                    title=pr.get("title") or "",
                    body=pr.get("body") or "",
                    state=pr.get("state") or "?",
                    author=(pr.get("user") or {}).get("login") or "?",
                    created_at=pr.get("created_at") or "",
                    updated_at=pr.get("updated_at") or "",
                    merged_at=pr.get("merged_at"),
                    url=pr.get("html_url") or "",
                )
            )
        return out

    @staticmethod
    def list_user_repos(token: str, max_items: int = 100) -> list[dict]:
        """List repos accessible to the token (paginated up to max_items).

        Sorted by most recently pushed so the picker shows active repos first.
        """
        if not token:
            return []
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": DEFAULT_UA,
        }
        out: list[dict] = []
        page = 1
        with httpx.Client(base_url=GITHUB_API_BASE, headers=headers, timeout=15.0) as c:
            while len(out) < max_items:
                r = c.get(
                    "/user/repos",
                    params={
                        "sort": "pushed",
                        "direction": "desc",
                        "per_page": 100,
                        "page": page,
                    },
                )
                r.raise_for_status()
                batch = r.json() or []
                if not batch:
                    break
                for repo in batch:
                    out.append({
                        "owner": (repo.get("owner") or {}).get("login") or "?",
                        "name": repo.get("name") or "?",
                        "full_name": repo.get("full_name") or "?",
                        "private": bool(repo.get("private")),
                        "description": repo.get("description") or "",
                        "pushed_at": repo.get("pushed_at"),
                        "url": repo.get("html_url"),
                    })
                    if len(out) >= max_items:
                        break
                page += 1
                if page > 5:
                    break
        return out

    def list_issues(self, days: int = 30, max_items: int = 50) -> list[Issue]:
        r = self._client.get(
            f"/repos/{self.owner}/{self.repo}/issues",
            params={
                "state": "all", "sort": "updated", "direction": "desc",
                "per_page": min(max_items, 100),
                "since": self._since_iso(days),
            },
        )
        r.raise_for_status()
        out: list[Issue] = []
        for it in r.json():
            # GitHub's /issues endpoint returns PRs too — skip them.
            if it.get("pull_request"):
                continue
            out.append(
                Issue(
                    number=it["number"],
                    title=it.get("title") or "",
                    body=it.get("body") or "",
                    state=it.get("state") or "?",
                    author=(it.get("user") or {}).get("login") or "?",
                    created_at=it.get("created_at") or "",
                    updated_at=it.get("updated_at") or "",
                    url=it.get("html_url") or "",
                )
            )
        return out
