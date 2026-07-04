"""GitHub activity ingestion.

Reads commits, pull requests, and issues (metadata only — never code) from a
configured repo and ingests each as a `documents` row with source_type
`github_commit` / `github_pr` / `github_issue`. Same downstream pipeline as
regular ingestion: chunking → embeddings → search-indexed.

Read-only. Never writes to GitHub. Never clones code. The activity graph
is what the orientation payload surfaces at session start; code itself
is what Claude Code's file-read tools handle."""

from .client import GitHubClient, parse_repo_url
from .ingest import ingest_recent_activity

__all__ = ["GitHubClient", "ingest_recent_activity", "parse_repo_url"]
