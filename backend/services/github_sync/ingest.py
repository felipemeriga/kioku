"""Ingest GitHub activity into the documents table.

Each commit/PR/issue becomes ONE document row (no chunking — they're already
short). Embeddings are computed with the same Voyage client used elsewhere.
Dedup via a stable `source_filename` per item:
  commits: gh_commit_{sha[:12]}.md
  prs:     gh_pr_{number}.md
  issues:  gh_issue_{number}.md
On re-ingest of the same ref, we upsert on (user_id, source_filename)
so PR body edits, issue reopens, etc. get reflected.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from services.crypto import decrypt_secret
from services.embeddings import embed_batch

from .client import Commit, GitHubClient, Issue, PullRequest, parse_repo_url

log = logging.getLogger(__name__)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _commit_doc(c: Commit, repo_slug: str) -> dict:
    content = f"# {c.title}\n\nCommit {c.sha[:12]} by {c.author} at {c.created_at}\n\n{c.body}".strip()
    return {
        "source_filename": f"gh_commit_{c.sha[:12]}.md",
        "source_type": "github_commit",
        "content": content,
        "metadata": {
            "repo": repo_slug,
            "sha": c.sha,
            "title": c.title,
            "author": c.author,
            "url": c.url,
            "created_at": c.created_at,
        },
    }


def _pr_doc(p: PullRequest, repo_slug: str) -> dict:
    content = (
        f"# PR #{p.number}: {p.title}\n\n"
        f"By {p.author} · state={p.state} "
        f"· opened {p.created_at} · updated {p.updated_at}"
        + (f" · merged {p.merged_at}" if p.merged_at else "")
        + f"\n\n{p.body or '(no description)'}"
    )
    return {
        "source_filename": f"gh_pr_{p.number}.md",
        "source_type": "github_pr",
        "content": content,
        "metadata": {
            "repo": repo_slug,
            "pr_number": p.number,
            "title": p.title,
            "state": p.state,
            "author": p.author,
            "url": p.url,
            "merged_at": p.merged_at,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        },
    }


def _issue_doc(i: Issue, repo_slug: str) -> dict:
    content = (
        f"# Issue #{i.number}: {i.title}\n\n"
        f"By {i.author} · state={i.state} "
        f"· opened {i.created_at} · updated {i.updated_at}\n\n"
        f"{i.body or '(no description)'}"
    )
    return {
        "source_filename": f"gh_issue_{i.number}.md",
        "source_type": "github_issue",
        "content": content,
        "metadata": {
            "repo": repo_slug,
            "issue_number": i.number,
            "title": i.title,
            "state": i.state,
            "author": i.author,
            "url": i.url,
            "created_at": i.created_at,
            "updated_at": i.updated_at,
        },
    }


def ingest_recent_activity(
    sb,
    *,
    config: dict,
    user_id: str,
) -> dict:
    """Fetch recent commits/PRs/issues and upsert them as documents.

    Returns a summary dict of what was pulled + written."""
    started = time.perf_counter()
    owner = config["repo_owner"]
    repo = config["repo_name"]
    folder_id = config["root_folder_id"]
    days = int(config.get("since_days") or 14)
    token_ct = config.get("token_encrypted")
    token = decrypt_secret(token_ct) if token_ct else None
    repo_slug = f"{owner}/{repo}"

    with GitHubClient(owner=owner, repo=repo, token=token) as gh:
        commits = gh.list_commits(days=days, max_items=100)
        prs = gh.list_prs(days=max(days, 30), max_items=50)
        issues = gh.list_issues(days=max(days, 30), max_items=50)

    docs = (
        [_commit_doc(c, repo_slug) for c in commits]
        + [_pr_doc(p, repo_slug) for p in prs]
        + [_issue_doc(i, repo_slug) for i in issues]
    )

    if not docs:
        log.info("github_sync: nothing new for %s (window=%dd)", repo_slug, days)
        return {
            "repo": repo_slug, "days": days,
            "commits": 0, "prs": 0, "issues": 0,
            "written": 0, "duration_ms": int((time.perf_counter() - started) * 1000),
        }

    # Embed in one Voyage call. Voyage supports up to 128 per batch — we're
    # far under that even for a busy repo.
    contents = [d["content"] for d in docs]
    embeddings = embed_batch(contents)

    rows_to_upsert: list[dict] = []
    for d, emb in zip(docs, embeddings):
        rows_to_upsert.append({
            "user_id": user_id,
            "folder_id": folder_id,
            "root_folder_id": folder_id,
            "source_filename": d["source_filename"],
            "source_type": d["source_type"],
            "content": d["content"],
            "content_hash": _hash(d["content"]),
            "metadata": d["metadata"],
            "embedding": emb,
            "status": "completed",
            "chunk_index": 0,
        })

    # The dedup unique index on documents is PARTIAL (WHERE chunk_index IS NOT
    # NULL AND notion_page_id IS NULL), which Postgres can't use for ON
    # CONFLICT. Delete-then-insert is idempotent and semantically what we
    # want anyway: each github ref (commit sha, pr number, issue number) has
    # exactly one canonical row.
    filenames = [r["source_filename"] for r in rows_to_upsert]
    # Chunk the delete since Supabase's `in_` filter has payload limits.
    for i in range(0, len(filenames), 100):
        sb.table("documents").delete().eq("user_id", user_id).in_(
            "source_filename", filenames[i:i + 100]
        ).execute()

    written = 0
    batch_size = 50
    for i in range(0, len(rows_to_upsert), batch_size):
        batch = rows_to_upsert[i:i + batch_size]
        sb.table("documents").insert(batch).execute()
        written += len(batch)

    duration = int((time.perf_counter() - started) * 1000)
    log.info(
        "github_sync: %s window=%dd commits=%d prs=%d issues=%d written=%d in %dms",
        repo_slug, days, len(commits), len(prs), len(issues), written, duration,
    )
    return {
        "repo": repo_slug, "days": days,
        "commits": len(commits), "prs": len(prs), "issues": len(issues),
        "written": written, "duration_ms": duration,
    }
