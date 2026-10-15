"""Turn-level citation registry: stable [N] numbers per source across a chat turn.

Chunks from the same document (or the same code file) retrieved across multiple
search rounds share ONE number, so the model can cite [N] inline and the
frontend can map each N back to its source. Thread-safe — parallel tool calls
register concurrently.
"""

from __future__ import annotations

import threading


class CitationRegistry:
    def __init__(self) -> None:
        self._by_key: dict[str, int] = {}
        self._entries: list[dict] = []
        self._next = 1
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

    def entries(self) -> list[dict]:
        """The registered citations, ordered by number."""
        with self._lock:
            return list(self._entries)
