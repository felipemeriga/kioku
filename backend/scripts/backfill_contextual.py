"""One-off backfill: re-embed existing `documents` chunks with the contextual
retrieval shape (header + situating blurb + raw chunk).

Existing rows were embedded as the raw chunk only. This reconstructs each
document from its ordered chunks, generates a per-chunk situating blurb (Haiku +
cached doc), re-embeds the contextualized shape, and updates each row's
`embedding` + `metadata.context`. The `content` column is left untouched.

Run AFTER the contextual-retrieval code is deployed:

    cd backend
    uv run python -m scripts.backfill_contextual --dry-run      # count + cost, no API calls
    uv run python -m scripts.backfill_contextual --limit 3      # a few docs, for a smoke test
    uv run python -m scripts.backfill_contextual                # the whole corpus (~$2)

Idempotent enough to re-run: it always regenerates from current `content`.
"""

from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_contextual")


def _doc_key(row: dict) -> tuple:
    """A stable identity for the source document a chunk belongs to."""
    if row.get("notion_page_id"):
        return ("notion", row["notion_page_id"])
    return ("file", row.get("source_filename"), row.get("folder_id"))


def _fetch_all(sb) -> list[dict]:
    rows: list[dict] = []
    step = 1000
    off = 0
    while True:
        res = (
            sb.table("documents")
            .select(
                "id, content, metadata, chunk_index, source_filename, folder_id, notion_page_id"
            )
            .eq("status", "completed")
            .range(off, off + step - 1)
            .execute()
        )
        if not res.data:
            break
        rows.extend(res.data)
        if len(res.data) < step:
            break
        off += step
    return rows


def _group(rows: list[dict]) -> list[list[dict]]:
    """Group rows by document and order each group by chunk_index."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(_doc_key(r), []).append(r)
    ordered = []
    for g in groups.values():
        g.sort(key=lambda r: r.get("chunk_index") if r.get("chunk_index") is not None else 0)
        ordered.append(g)
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="count + cost only, no API calls")
    parser.add_argument("--limit", type=int, default=None, help="process at most N documents")
    args = parser.parse_args()

    load_dotenv()
    from db.client import get_supabase
    from services.chunker import contextualized_text
    from services.contextual import contextualize_chunks
    from services.embeddings import embed_batch

    sb = get_supabase()
    rows = _fetch_all(sb)
    docs = _group(rows)
    if args.limit is not None:
        docs = docs[: args.limit]

    n_docs = len(docs)
    n_chunks = sum(len(g) for g in docs)
    total_chars = sum(len(r["content"] or "") for g in docs for r in g)
    logger.info("documents: %d | chunks: %d | ~%d tokens", n_docs, n_chunks, total_chars // 4)

    if args.dry_run:
        # Rough: Haiku contextual ~ $0.002/chunk (cached doc), voyage-3 ~ $0.06/1M tokens.
        est = n_chunks * 0.002 + (total_chars / 4) / 1_000_000 * 0.06
        logger.info("dry-run — no API calls. est cost ~ $%.2f", est)
        return

    done_docs = 0
    done_chunks = 0
    for group in docs:
        contents = [r["content"] or "" for r in group]
        doc_text = "\n\n".join(contents)
        contexts = contextualize_chunks(doc_text, contents)

        embed_inputs: list[str] = []
        new_metas: list[dict] = []
        for r, ctx, content in zip(group, contexts, contents, strict=True):
            meta = dict(r.get("metadata") or {})
            if ctx:
                meta["context"] = ctx
            else:
                meta.pop("context", None)
            new_metas.append(meta)
            embed_inputs.append(contextualized_text(meta, ctx, content))

        embeddings = embed_batch(embed_inputs)
        for r, emb, meta in zip(group, embeddings, new_metas, strict=True):
            sb.table("documents").update({"embedding": emb, "metadata": meta}).eq(
                "id", r["id"]
            ).execute()

        done_docs += 1
        done_chunks += len(group)
        logger.info("  [%d/%d docs] %d chunks re-embedded", done_docs, n_docs, done_chunks)

    logger.info("done — %d docs, %d chunks", done_docs, done_chunks)


if __name__ == "__main__":
    main()
