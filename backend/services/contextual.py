"""Contextual Retrieval: a short standalone blurb situating each chunk within
its parent document, generated at index time and prepended before embedding.

Based on Anthropic's contextual-retrieval technique. The full document goes in
the (cached) system prompt so it is paid for once per document and reused across
all of that document's chunk calls; only the per-chunk user message varies. Runs
the per-chunk calls concurrently and is best-effort — a chunk whose call fails
falls back to an empty context (the header + raw chunk still get embedded).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from services.llm import Task, complete
from services.metrics import record, submit_with_context

logger = logging.getLogger(__name__)

# Keep the blurb short — it is a retrieval signal prepended to every chunk, not
# a summary. ~60 tokens is plenty for "this chunk is X, from section Y of doc Z".
_MAX_TOKENS = 120
_MAX_WORKERS = 8
# Below this the "document" barely differs from the chunk — situating adds noise,
# not signal, so skip the LLM call entirely.
_MIN_DOC_CHARS = 500

_SYSTEM = (
    "You are given a document. For each chunk a user sends, write a SHORT "
    "standalone context (one sentence, ~60 tokens max) that situates the chunk "
    "within the overall document to improve search retrieval. Answer with ONLY "
    "that context — no preamble, no quotes, no labels.\n\n"
    "<document>\n{document}\n</document>"
)

_USER = (
    "Here is a chunk from the document:\n\n<chunk>\n{chunk}\n</chunk>\n\n"
    "Give the short standalone context situating this chunk within the document."
)


def contextualize_chunk(doc_text: str, chunk: str) -> str:
    """Return a one-sentence situating context for ``chunk`` within ``doc_text``.

    Returns "" on any failure (best-effort) so the caller can fall back to the
    header + raw chunk without the contextual signal.
    """
    try:
        resp = complete(
            task=Task.CONTEXTUAL,
            system=_SYSTEM.format(document=doc_text),
            messages=[{"role": "user", "content": _USER.format(chunk=chunk)}],
            max_tokens=_MAX_TOKENS,
            cache_system=True,
        )
        return (resp.content[0].text or "").strip()
    except Exception:  # noqa: BLE001 — best-effort; never break ingestion
        logger.warning("contextualize_chunk failed", exc_info=True)
        return ""


def contextualize_chunks(doc_text: str, chunks: list[str]) -> list[str]:
    """Generate a situating context for each chunk, concurrently.

    Returns a list parallel to ``chunks`` (same length, same order). Tiny
    documents skip the LLM entirely and return empty contexts. The full document
    rides in the cached system prompt, so across a document's chunks it is a
    cache read, not a re-send.
    """
    if not chunks:
        return []
    if not doc_text or len(doc_text) < _MIN_DOC_CHARS:
        return [""] * len(chunks)

    results: list[str] = [""] * len(chunks)
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            submit_with_context(pool, contextualize_chunk, doc_text, chunk): i
            for i, chunk in enumerate(chunks)
        }
        for future in futures:
            i = futures[future]
            try:
                results[i] = future.result()
            except Exception:  # noqa: BLE001
                logger.warning("contextualize_chunks worker failed", exc_info=True)
                results[i] = ""

    n_filled = sum(1 for r in results if r)
    record("contextualize", n_chunks=len(chunks), n_contexts=n_filled)
    return results
