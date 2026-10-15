"""Turn-level citation registry: stable [N] numbers per source across a chat turn.

Chunks from the same document (or the same code file) retrieved across multiple
search rounds share ONE number, so the model can cite [N] inline and the
frontend can map each N back to its source. Thread-safe — parallel tool calls
register concurrently.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


def _github_base(remote_url: str | None) -> str | None:
    """Normalize a git remote to its https://github.com/<org>/<repo> web base.

    Handles the two forms stored in watched_repos:
      git@github.com:org/repo.git   → https://github.com/org/repo
      https://github.com/org/repo.git → https://github.com/org/repo
    Returns None for anything that isn't a recognizable GitHub remote.
    """
    if not remote_url:
        return None
    url = remote_url.strip()
    if url.startswith("git@github.com:"):
        path = url[len("git@github.com:") :]
    elif url.startswith("https://github.com/"):
        path = url[len("https://github.com/") :]
    elif url.startswith("http://github.com/"):
        path = url[len("http://github.com/") :]
    else:
        return None
    path = path.removesuffix(".git").strip("/")
    if not path or "/" not in path:
        return None
    return f"https://github.com/{path}"


def github_blob_url(
    remote_url: str | None, branch: str | None, file: str, line: int | None
) -> str | None:
    """Build a GitHub blob deep link for a code source, or None if not resolvable."""
    base = _github_base(remote_url)
    if not base or not file:
        return None
    url = f"{base}/blob/{branch or 'main'}/{file.lstrip('/')}"
    if line:
        url += f"#L{line}"
    return url


class CitationRegistry:
    def __init__(self) -> None:
        self._by_key: dict[str, int] = {}
        self._entries: list[dict] = []
        self._next = 1
        self._enriched = False
        self._lock = threading.Lock()

    def register(self, result: dict) -> int:
        """Register a retrieved result, returning its citation number (assigning
        the next one the first time this source is seen)."""
        meta = result.get("metadata") or {}
        is_code = result.get("source_type") == "code"
        range_part = ""
        sep = ""
        if is_code:
            loc = meta.get("source_filename") or "unknown"  # "file:start-end"
            file_part, sep, range_part = loc.rpartition(":")
            file_path = file_part if sep else loc
            key = f"code:{file_path}"
        else:
            source = meta.get("source_filename") or "unknown"
            file_path = None
            key = f"doc:{source}"

        with self._lock:
            existing = self._by_key.get(key)
            if existing is not None:
                return existing
            n = self._next
            self._next += 1
            self._by_key[key] = n

            if is_code:
                line: int | None = None
                if sep and range_part:
                    head = range_part.split("-", 1)[0]
                    if head.isdigit():
                        line = int(head)
                entry = {
                    "number": n,
                    "source": loc,
                    "source_type": "code",
                    "symbol": meta.get("code_symbol"),
                    "file": file_path,
                    "line": line,
                    "folder_id": meta.get("folder_id"),
                    "url": None,
                    "excerpt": (result.get("content") or "")[:300],
                }
            else:
                entry = {
                    "number": n,
                    "source": source,
                    "source_type": "document",
                    "symbol": None,
                    "file": None,
                    "line": None,
                    "folder_id": meta.get("folder_id"),
                    "url": (meta.get("file_url") or meta.get("image_url") or meta.get("audio_url")),
                    "excerpt": (result.get("content") or "")[:300],
                }
            self._entries.append(entry)
            return n

    def enrich_urls(self, sb, user_id: str) -> None:
        """Best-effort: fill `url` on code citations with a GitHub blob deep link.

        Resolves each distinct folder_id against watched_repos (one query, scoped
        to the user since the service-role client bypasses RLS) to get its
        remote_url + branch. Idempotent and never raises — a missing remote just
        leaves `url` as None and the frontend falls back to the excerpt popover.
        """
        with self._lock:
            if self._enriched:
                return
            pending = [
                e
                for e in self._entries
                if e["source_type"] == "code"
                and not e.get("url")
                and e.get("folder_id")
                and e.get("file")
            ]
            folder_ids = sorted({e["folder_id"] for e in pending})
        if not folder_ids:
            with self._lock:
                self._enriched = True
            return
        try:
            rows = (
                sb.table("watched_repos")
                .select("folder_id, remote_url, branch")
                .eq("user_id", user_id)
                .in_("folder_id", folder_ids)
                .execute()
                .data
                or []
            )
        except Exception:  # noqa: BLE001
            logger.debug("citation url enrichment query failed", exc_info=True)
            return
        repo_by_folder = {r["folder_id"]: r for r in rows}
        with self._lock:
            for e in self._entries:
                if e["source_type"] != "code" or e.get("url") or not e.get("file"):
                    continue
                repo = repo_by_folder.get(e.get("folder_id"))
                if not repo:
                    continue
                e["url"] = github_blob_url(
                    repo.get("remote_url"), repo.get("branch"), e["file"], e.get("line")
                )
            self._enriched = True

    def entries(self) -> list[dict]:
        """The registered citations, ordered by number."""
        with self._lock:
            return list(self._entries)
