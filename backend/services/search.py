"""Hybrid search: vector + keyword with RRF fusion and reranking."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from langsmith import traceable

from db.client import get_supabase
from services.embeddings import embed_query
from services.metrics import record, submit_with_context
from services.query import generate_multi_queries, rewrite_query
from services.rerank import rerank
from services.timing import stage

logger = logging.getLogger(__name__)

# How many code chunks may enter the joint rerank pool. They compete with doc
# chunks for the final top_k slots on equal footing (same cross-encoder), so
# irrelevant code drops out on doc questions and relevant code surfaces on
# implementation questions. Kept bounded: code chunks run up to ~120 lines.
CODE_BLEND_TOP_N = 8
# Over-fetch factor before junk filtering (see _is_code_junk).
CODE_BLEND_FETCH = 25


def _is_code_junk(row: dict) -> bool:
    """Chunks that pollute blended retrieval without ever answering anything.

    The index contains non-source files (json schemas, READMEs, lockfiles —
    language NULL) and one-to-two-line fragments (a package.json version line,
    a bare type alias). Measured on the real corpus: ~1.7k NULL-language
    chunks, more than half of them under two lines. They embed close to prose
    queries and leak past the reranker, so they never reach the pool.
    """
    if not row.get("language"):
        return True
    span = (row.get("end_line") or 0) - (row.get("start_line") or 0)
    return span < 2


def _code_candidates(
    query_text: str,
    user_id: str | None,
    folder_ids: list[str] | None,
    root_folder_id: str | None = None,
    top_n: int = CODE_BLEND_TOP_N,
) -> list[dict]:
    """Top code chunks for the query, shaped like doc rows so they can join
    the rerank pool.

    Purely additive and best-effort: any failure (no code index, embed error)
    returns [] and the doc pipeline proceeds untouched. The chunk content
    already carries its own '[repo …] [file …] [symbol …]' header from
    indexing, so the cross-encoder scores it with full context.
    """
    if not query_text or not user_id:
        return []
    try:
        from services.embeddings import embed_code_query

        embedding = embed_code_query(query_text)
        sb = get_supabase()
        scope_ids = folder_ids
        if not scope_ids and root_folder_id:
            from services.scope import descendant_folder_ids

            scope_ids = descendant_folder_ids(sb, root_folder_id, user_id)
        params: dict = {
            "query_embedding": embedding,
            "match_count": CODE_BLEND_FETCH,
            "filter_user_id": user_id,
        }
        if scope_ids:
            params["filter_folder_ids"] = scope_ids
        rows = sb.rpc("code_search", params).execute().data or []
    except Exception:
        logger.warning("code candidate search failed", exc_info=True)
        return []
    out: list[dict] = []
    for r in rows:
        if len(out) >= top_n:
            break
        if _is_code_junk(r):
            continue
        location = f"{r.get('file')}:{r.get('start_line')}-{r.get('end_line')}"
        out.append(
            {
                "id": str(r.get("id")),
                "content": r.get("content") or "",
                "similarity": r.get("similarity"),
                "source_type": "code",
                "created_at": r.get("created_at"),
                "metadata": {
                    "source_filename": location,
                    "source_type": "code",
                    "code_symbol": r.get("symbol"),
                    "code_language": r.get("language"),
                    "folder_id": r.get("folder_id"),
                },
            }
        )
    return out


def _vector_search(
    query_embedding: list[float],
    user_id: str | None,
    top_k: int,
    topic: str | None,
    keyword: str | None,
    root_folder_id: str | None = None,
    folder_ids: list[str] | None = None,
    source_filename: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> list[dict]:
    """Search documents by cosine similarity."""
    sb = get_supabase()
    params: dict = {"query_embedding": query_embedding, "match_count": top_k}
    if user_id:
        params["filter_user_id"] = user_id
    if topic:
        params["filter_topic"] = topic
    if keyword:
        params["filter_keyword"] = keyword
    if root_folder_id:
        params["filter_root_folder_id"] = root_folder_id
    if folder_ids:
        params["filter_folder_ids"] = folder_ids
    if source_filename:
        params["filter_source_filename"] = source_filename
    if created_after:
        params["filter_created_after"] = created_after
    if created_before:
        params["filter_created_before"] = created_before

    result = sb.rpc("match_documents", params).execute()
    return result.data


def _keyword_search(
    query: str,
    user_id: str | None,
    top_k: int,
    topic: str | None,
    keyword: str | None,
    root_folder_id: str | None = None,
    folder_ids: list[str] | None = None,
    source_filename: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> list[dict]:
    """Search documents by full-text keyword matching."""
    sb = get_supabase()
    params: dict = {"search_query": query, "match_count": top_k}
    if user_id:
        params["filter_user_id"] = user_id
    if topic:
        params["filter_topic"] = topic
    if keyword:
        params["filter_keyword"] = keyword
    if root_folder_id:
        params["filter_root_folder_id"] = root_folder_id
    if folder_ids:
        params["filter_folder_ids"] = folder_ids
    if source_filename:
        params["filter_source_filename"] = source_filename
    if created_after:
        params["filter_created_after"] = created_after
    if created_before:
        params["filter_created_before"] = created_before

    result = sb.rpc("keyword_search", params).execute()
    return result.data


def _reciprocal_rank_fusion(
    vector_results: list[dict],
    keyword_results: list[dict],
    k: int = 60,
) -> list[dict]:
    """Merge two ranked lists using Reciprocal Rank Fusion (RRF).

    Score for each document = sum of 1/(k + rank) across both lists.
    """
    scores: dict[str, float] = {}
    docs_by_id: dict[str, dict] = {}

    for rank, doc in enumerate(vector_results):
        doc_id = doc["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
        docs_by_id[doc_id] = doc

    for rank, doc in enumerate(keyword_results):
        doc_id = doc["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
        docs_by_id[doc_id] = doc

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [docs_by_id[doc_id] for doc_id in sorted_ids]


def _run_hybrid_search(
    query_embedding: list[float],
    query_text: str,
    user_id: str | None,
    fetch_k: int,
    topic: str | None,
    keyword: str | None,
    root_folder_id: str | None,
    folder_ids: list[str] | None = None,
    source_filename: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Run vector + keyword search for a single query, in parallel.

    Both calls are independent network round-trips against Supabase RPCs and
    do not depend on each other, so we issue them concurrently and join.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        vec_future = submit_with_context(
            pool,
            _vector_search,
            query_embedding,
            user_id,
            fetch_k,
            topic,
            keyword,
            root_folder_id,
            folder_ids,
            source_filename,
            created_after,
            created_before,
        )
        kw_future = (
            submit_with_context(
                pool,
                _keyword_search,
                query_text,
                user_id,
                fetch_k,
                topic,
                keyword,
                root_folder_id,
                folder_ids,
                source_filename,
                created_after,
                created_before,
            )
            if query_text
            else None
        )

        try:
            vector_results = vec_future.result()
        except Exception:
            logger.warning("Vector search failed", exc_info=True)
            vector_results = []
        try:
            keyword_results = kw_future.result() if kw_future else []
        except Exception:
            logger.warning("Keyword search failed", exc_info=True)
            keyword_results = []

    return vector_results, keyword_results


def _embed_and_search(
    variant_text: str,
    user_id: str | None,
    fetch_k: int,
    topic: str | None,
    keyword: str | None,
    root_folder_id: str | None,
    precomputed_embedding: list[float] | None = None,
    folder_ids: list[str] | None = None,
    source_filename: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Embed a query variant (if needed) then run parallel hybrid search."""
    embedding = precomputed_embedding
    if embedding is None:
        try:
            embedding = embed_query(variant_text)
        except Exception:
            logger.warning("Embed failed for variant %r", variant_text, exc_info=True)
            return [], []
    return _run_hybrid_search(
        embedding,
        variant_text,
        user_id,
        fetch_k,
        topic,
        keyword,
        root_folder_id,
        folder_ids,
        source_filename,
        created_after,
        created_before,
    )


@traceable(name="search_documents", run_type="retriever")
def search_documents(
    query_embedding: list[float],
    query_text: str = "",
    user_id: str | None = None,
    top_k: int = 5,
    topic: str | None = None,
    keyword: str | None = None,
    root_folder_id: str | None = None,
    fast_mode: bool = False,
    folder_ids: list[str] | None = None,
    source_filename: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    include_code: bool = True,
) -> list[dict]:
    """Hybrid search pipeline with optional query enhancement.

    fast_mode=False (UI chat): rewrite + multi-query + hybrid search + RRF + rerank + neighbors
    fast_mode=True (MCP): hybrid search + RRF + rerank + neighbors (skips LLM calls)

    include_code=True blends top code chunks into the rerank pool so answers
    can draw on source code alongside documents. Skipped automatically when
    retrieval is narrowed to a single file or a date window — those filters
    describe documents, not code.
    """
    fetch_k = 20
    blend_code = include_code and not source_filename and not created_after and not created_before

    if fast_mode:
        with stage("search_documents (fast)", indent=2):
            # Fast path: skip query rewriting and multi-query, use original query
            # directly. Code candidates fetch in parallel with the hybrid search.
            with stage("hybrid_search (vector || keyword || code)", indent=3):
                code_future = None
                pool = ThreadPoolExecutor(max_workers=1) if blend_code else None
                if pool:
                    code_future = submit_with_context(
                        pool, _code_candidates, query_text, user_id, folder_ids, root_folder_id
                    )
                vector_results, keyword_results = _run_hybrid_search(
                    query_embedding,
                    query_text,
                    user_id,
                    fetch_k,
                    topic,
                    keyword,
                    root_folder_id,
                    folder_ids,
                    source_filename,
                    created_after,
                    created_before,
                )
                code_results: list[dict] = []
                if code_future is not None:
                    try:
                        code_results = code_future.result()
                    except Exception:
                        logger.warning("code candidates failed", exc_info=True)
                    finally:
                        pool.shutdown(wait=False)

            _record_search_metrics([vector_results], [keyword_results])

            if not vector_results and not keyword_results and not code_results:
                return []

            if not keyword_results:
                fused = vector_results
            elif not vector_results:
                fused = keyword_results
            else:
                fused = _reciprocal_rank_fusion(vector_results, keyword_results)

            with stage("rerank", indent=3):
                reranked = rerank(query_text or "query", fused + code_results, top_k=top_k)
            reranked = _apply_recency_decay(reranked)
            with stage("neighbor_expansion (parallel)", indent=3):
                return _expand_with_neighbors(reranked)

    with stage("search_documents (full)", indent=2):
        # Full path: query rewriting + multi-query for better recall.
        # Phase 1: rewrite_query and generate_multi_queries are independent LLM
        # calls — fan them out in parallel and join.
        rewritten = query_text
        variants: list[str] = []
        if query_text:
            with stage("phase1: rewrite + multi_query (parallel)", indent=3):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    rewrite_future = submit_with_context(pool, rewrite_query, query_text)
                    multi_future = submit_with_context(pool, generate_multi_queries, query_text)
                    try:
                        rewritten = rewrite_future.result()
                    except Exception:
                        logger.warning("rewrite_query failed", exc_info=True)
                        rewritten = query_text
                    try:
                        variants = multi_future.result()
                    except Exception:
                        logger.warning("generate_multi_queries failed", exc_info=True)
                        variants = []

        rewrite_changed = rewritten != query_text
        record(
            "query_expansion",
            n_variants=1 + len(variants),
            rewrite_changed_text=rewrite_changed,
        )

        # Variant 0 reuses the precomputed embedding only if rewriting didn't
        # change the text; otherwise it must be re-embedded.
        variant_specs: list[tuple[str, list[float] | None]] = [
            (rewritten, query_embedding if rewritten == query_text else None)
        ]
        for v in variants:
            variant_specs.append((v, None))

        # Phase 2: run all variants in parallel; code candidates ride the same
        # pool (they only need one worker and the original query text).
        per_variant_vec: list[list[dict]] = []
        per_variant_kw: list[list[dict]] = []
        all_vector: list[dict] = []
        all_keyword: list[dict] = []
        code_results: list[dict] = []
        with stage(f"phase2: {len(variant_specs)} variants (parallel)", indent=3):
            with ThreadPoolExecutor(max_workers=max(len(variant_specs), 1) + 1) as pool:
                code_future = (
                    submit_with_context(
                        pool, _code_candidates, query_text, user_id, folder_ids, root_folder_id
                    )
                    if blend_code
                    else None
                )
                futures = [
                    submit_with_context(
                        pool,
                        _embed_and_search,
                        vt,
                        user_id,
                        fetch_k,
                        topic,
                        keyword,
                        root_folder_id,
                        emb,
                        folder_ids,
                        source_filename,
                        created_after,
                        created_before,
                    )
                    for vt, emb in variant_specs
                ]
                for f in futures:
                    try:
                        vec, kw = f.result()
                    except Exception:
                        logger.warning("Variant search failed", exc_info=True)
                        per_variant_vec.append([])
                        per_variant_kw.append([])
                        continue
                    per_variant_vec.append(vec)
                    per_variant_kw.append(kw)
                    all_vector.extend(vec)
                    all_keyword.extend(kw)
                if code_future is not None:
                    try:
                        code_results = code_future.result()
                    except Exception:
                        logger.warning("code candidates failed", exc_info=True)

        _record_search_metrics(
            per_variant_vec,
            per_variant_kw,
        )

        # Deduplicate by document id (keep first occurrence)
        seen: set[str] = set()
        deduped_vector: list[dict] = []
        for doc in all_vector:
            if doc["id"] not in seen:
                seen.add(doc["id"])
                deduped_vector.append(doc)

        seen_kw: set[str] = set()
        deduped_keyword: list[dict] = []
        for doc in all_keyword:
            if doc["id"] not in seen_kw:
                seen_kw.add(doc["id"])
                deduped_keyword.append(doc)

        if not deduped_vector and not deduped_keyword and not code_results:
            return []

        # Step 4: RRF fusion
        if not deduped_keyword:
            fused = deduped_vector
        elif not deduped_vector:
            fused = deduped_keyword
        else:
            fused = _reciprocal_rank_fusion(deduped_vector, deduped_keyword)

        # Step 5: Rerank with score threshold filtering — code candidates join
        # the pool here and compete with doc chunks on the same cross-encoder.
        with stage("rerank", indent=3):
            reranked = rerank(query_text or "query", fused + code_results, top_k=top_k)
        reranked = _apply_recency_decay(reranked)

        # Step 6: Parent document retrieval — expand each result with adjacent chunks
        with stage("neighbor_expansion (parallel)", indent=3):
            return _expand_with_neighbors(reranked)


# Recency half-life (days) per source_type. Episodic content (meetings, voice
# recordings) loses relevance over time and decays; reference material (docs,
# notion pages, code) ranks purely on relevance and is absent from this map.
RECENCY_HALF_LIFE_DAYS: dict[str, float] = {
    "meeting": 90.0,
    "audio": 180.0,
}

# Cap on how much freshness can move the final ranking. Relevance keeps 80%
# of the say — recency is a tiebreaker, never a gate.
RECENCY_WEIGHT = 0.2


def _recency_factor(doc: dict, now: datetime | None = None) -> float:
    """0..1 decay multiplier: 1.0 for undated or non-decaying content, halving
    every RECENCY_HALF_LIFE_DAYS for episodic source types."""
    half_life = RECENCY_HALF_LIFE_DAYS.get(doc.get("source_type") or "")
    ts = doc.get("created_at")
    if not half_life or not ts:
        return 1.0
    try:
        created = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return 1.0
    now = now or datetime.now(timezone.utc)
    age_days = max((now - created).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / half_life)


def _apply_recency_decay(docs: list[dict]) -> list[dict]:
    """Downrank stale episodic chunks: multiply the rerank score by a per-type
    time decay and re-sort. Decay is COHORT-RELATIVE — factors are normalized
    by the best factor in this result set — so freshness only matters when the
    results actually differ in age. A corpus (or folder) whose only relevant
    material is old keeps its pure relevance order; nothing is ever dropped,
    only reordered. Reference docs (no half-life entry) are untouched."""
    if not docs:
        return docs
    out = []
    for doc in docs:
        d = doc.copy()
        d["recency_factor"] = _recency_factor(doc)
        out.append(d)

    best = max(d["recency_factor"] for d in out)
    if best <= 0:
        return out
    for d in out:
        d["recency_factor"] = round(d["recency_factor"] / best, 4)

    any_decayed = any(d["recency_factor"] < 1.0 for d in out)
    if any_decayed and any("rerank_score" in d for d in out):
        # Weighted ADDITIVE blend, not a multiplier: freshness contributes at
        # most RECENCY_WEIGHT, so one marginally-relevant fresh chunk can
        # never bury a highly-relevant old one (relevance gaps larger than
        # the weight always win); equal-relevance ties still break fresh.
        out.sort(
            key=lambda d: (
                (1 - RECENCY_WEIGHT) * d.get("rerank_score", 0.0)
                + RECENCY_WEIGHT * d["recency_factor"]
            ),
            reverse=True,
        )
        record("recency_decay", n_decayed=sum(1 for d in out if d["recency_factor"] < 1.0))
    return out


def _expand_with_neighbors(results: list[dict]) -> list[dict]:
    """Expand each result with content from adjacent chunks in the same document.

    Uses content_hash and chunk_index from metadata to find neighbors.
    Merges prev + current + next content into a single expanded content field.

    The neighbor query is scoped to the exact prev/next chunk_index values via
    a jsonb filter, so a 200-page PDF doesn't pull all ~1000 chunks just to
    locate two neighbors.

    NOTE: the match_documents RPC does not return content_hash at the top
    level (only id, content, metadata, similarity), so we backfill it via a
    single batched lookup before grouping. Without this, every vector-search
    result hits the early-return path and never gets expanded.
    """
    if not results:
        return []

    # Code chunks have no document neighbors — they pass through as-is, in rank
    # order, while doc hits expand below (order/length preserved by pool.map).
    if any(d.get("source_type") == "code" for d in results):
        doc_hits = [d for d in results if d.get("source_type") != "code"]
        expanded_docs = iter(_expand_with_neighbors(doc_hits))
        return [d if d.get("source_type") == "code" else next(expanded_docs) for d in results]

    sb = get_supabase()

    # Count missing hashes BEFORE backfill so the metric reflects the initial state.
    n_missing_hash_initial = sum(1 for d in results if not d.get("content_hash"))

    # Backfill content_hash on any row that's missing it (single batched query).
    missing_ids = [doc["id"] for doc in results if not doc.get("content_hash") and doc.get("id")]
    if missing_ids:
        try:
            backfill = (
                sb.table("documents").select("id, content_hash").in_("id", missing_ids).execute()
            )
            hash_by_id = {row["id"]: row["content_hash"] for row in backfill.data}
            for doc in results:
                if not doc.get("content_hash"):
                    doc["content_hash"] = hash_by_id.get(doc.get("id"))
        except Exception:
            logger.warning("Failed to backfill content_hash for neighbor expansion", exc_info=True)

    def _fetch_neighbors(doc: dict) -> dict:
        """Fetch this doc's prev/next chunks and return the expanded doc."""
        meta = doc.get("metadata") or {}
        chunk_index = meta.get("chunk_index")
        content_hash = doc.get("content_hash")

        if chunk_index is None or not content_hash:
            return doc

        neighbor_keys = [str(chunk_index - 1), str(chunk_index + 1)]
        try:
            neighbors = (
                sb.table("documents")
                .select("content, metadata")
                .eq("content_hash", content_hash)
                .in_("metadata->>chunk_index", neighbor_keys)
                .execute()
            )
            chunk_map: dict[int, str] = {}
            for row in neighbors.data:
                row_meta = row.get("metadata") or {}
                idx = row_meta.get("chunk_index")
                if idx is not None:
                    chunk_map[idx] = row["content"]

            parts = []
            if chunk_index - 1 in chunk_map:
                parts.append(chunk_map[chunk_index - 1])
            parts.append(doc["content"])
            if chunk_index + 1 in chunk_map:
                parts.append(chunk_map[chunk_index + 1])

            expanded_doc = doc.copy()
            expanded_doc["content"] = "\n\n".join(parts)
            expanded_doc["expanded"] = len(parts) > 1
            return expanded_doc
        except Exception:
            logger.warning("Failed to expand chunk neighbors", exc_info=True)
            return doc

    # Fan out the per-result neighbor queries in parallel — they're independent.
    with ThreadPoolExecutor(max_workers=max(len(results), 1)) as pool:
        expanded = list(pool.map(_fetch_neighbors, results))

    n_expanded = sum(1 for d in expanded if d.get("expanded"))
    record(
        "neighbor_expansion",
        n_results=len(results),
        n_expanded=n_expanded,
        n_skipped_missing_hash=n_missing_hash_initial,
    )
    return expanded


def _record_search_metrics(
    per_variant_vec: list[list[dict]],
    per_variant_kw: list[list[dict]],
) -> None:
    """Record per-stage metric snapshots after vector + keyword searches complete."""
    vec_counts = [len(v) for v in per_variant_vec]
    kw_counts = [len(k) for k in per_variant_kw]

    flat_vec = [d for batch in per_variant_vec for d in batch]
    flat_kw = [d for batch in per_variant_kw for d in batch]

    unique_vec_ids = {d["id"] for d in flat_vec}
    unique_kw_ids = {d["id"] for d in flat_kw}

    sims = [d.get("similarity") for d in flat_vec if d.get("similarity") is not None]
    avg_sim = round(sum(sims) / len(sims), 3) if sims else None

    record(
        "vector_search",
        per_variant=vec_counts,
        unique=len(unique_vec_ids),
        avg_sim=avg_sim,
    )
    record(
        "keyword_search",
        per_variant=kw_counts,
        unique=len(unique_kw_ids),
    )

    union_size = len(unique_vec_ids | unique_kw_ids)
    if union_size:
        overlap = len(unique_vec_ids & unique_kw_ids)
        overlap_pct = round(100 * overlap / union_size) if union_size else 0
        record(
            "rrf_fusion",
            n_in=len(unique_vec_ids) + len(unique_kw_ids),
            n_out=union_size,
            overlap_pct=overlap_pct,
        )
