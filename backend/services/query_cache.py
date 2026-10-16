"""Best-effort Redis cache for query embeddings.

A query embedding is deterministic from (model, text), so caching it lets
repeated questions — and the per-variant fan-out within a single search — skip
redundant Voyage calls. Keyed by a hash of the text; the stored value is just a
vector. Purely an optimization: a slow or down Redis never blocks a search, it
just falls through to a live embed (and disables itself for the process after
the first failure so it can't add latency on every call).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

_TTL_SECONDS = 7 * 24 * 3600
_client = None
_broken = False


def _redis():
    """Lazily build a sync Redis client with tight timeouts, or None if unusable."""
    global _client, _broken
    if _broken:
        return None
    if _client is None:
        try:
            import redis

            _client = redis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
        except Exception:  # noqa: BLE001
            logger.warning("query-embedding cache unavailable", exc_info=True)
            _broken = True
            return None
    return _client


def _key(model: str, text: str) -> str:
    return f"qemb:{model}:" + hashlib.sha256(text.encode()).hexdigest()


def get_cached(model: str, text: str) -> list[float] | None:
    global _broken
    r = _redis()
    if r is None:
        return None
    try:
        raw = r.get(_key(model, text))
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001 — best-effort; stop trying this process
        logger.warning("query-embedding cache read failed; disabling", exc_info=True)
        _broken = True
        return None


def set_cached(model: str, text: str, embedding: list[float]) -> None:
    global _broken
    r = _redis()
    if r is None:
        return
    try:
        r.set(_key(model, text), json.dumps(embedding), ex=_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("query-embedding cache write failed; disabling", exc_info=True)
        _broken = True
