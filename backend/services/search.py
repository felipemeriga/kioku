"""Hybrid search: vector + keyword with RRF fusion and reranking."""

import logging
from concurrent.futures import ThreadPoolExecutor

from langsmith import traceable

from db.client import get_supabase
from services.embeddings import embed_query
from services.metrics import record, submit_with_context
from services.query import generate_multi_queries, rewrite_query
from services.rerank import rerank
from services.timing import stage

logger = logging.getLogger(__name__)


def _vector_search(
    query_embedding: list[float],
    user_id: str | None,
    top_k: int,
    topic: str | None,
    keyword: str | None,
    root_folder_id: str | None = None,
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

    result = sb.rpc("match_documents", params).execute()
    return result.data


def _keyword_search(
    query: str,
    user_id: str | None,
    top_k: int,
    topic: str | None,
    keyword: str | None,
    root_folder_id: str | None = None,
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
        embedding, variant_text, user_id, fetch_k, topic, keyword, root_folder_id
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
) -> list[dict]:
    """Hybrid search pipeline with optional query enhancement.

    fast_mode=False (UI chat): rewrite + multi-query + hybrid search + RRF + rerank + neighbors
    fast_mode=True (MCP): hybrid search + RRF + rerank + neighbors (skips LLM calls)
    """
    fetch_k = 20

    if fast_mode:
        with stage("search_documents (fast)", indent=2):
            # Fast path: skip query rewriting and multi-query, use original query directly
            with stage("hybrid_search (vector || keyword)", indent=3):
                vector_results, keyword_results = _run_hybrid_search(
                    query_embedding, query_text, user_id, fetch_k, topic, keyword, root_folder_id
                )

            _record_search_metrics(
                [vector_results], [keyword_results], rewrite_changed=False, n_variants=1
            )

            if not vector_results and not keyword_results:
                return []

            if not keyword_results:
                fused = vector_results
            elif not vector_results:
                fused = keyword_results
            else:
                fused = _reciprocal_rank_fusion(vector_results, keyword_results)

            with stage("rerank", indent=3):
                reranked = rerank(query_text or "query", fused, top_k=top_k)
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

        # Phase 2: run all variants in parallel.
        per_variant_vec: list[list[dict]] = []
        per_variant_kw: list[list[dict]] = []
        all_vector: list[dict] = []
        all_keyword: list[dict] = []
        with stage(f"phase2: {len(variant_specs)} variants (parallel)", indent=3):
            with ThreadPoolExecutor(max_workers=max(len(variant_specs), 1)) as pool:
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

        _record_search_metrics(
            per_variant_vec,
            per_variant_kw,
            rewrite_changed=rewrite_changed,
            n_variants=len(variant_specs),
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

        if not deduped_vector and not deduped_keyword:
            return []

        # Step 4: RRF fusion
        if not deduped_keyword:
            fused = deduped_vector
        elif not deduped_vector:
            fused = deduped_keyword
        else:
            fused = _reciprocal_rank_fusion(deduped_vector, deduped_keyword)

        # Step 5: Rerank with score threshold filtering
        with stage("rerank", indent=3):
            reranked = rerank(query_text or "query", fused, top_k=top_k)

        # Step 6: Parent document retrieval — expand each result with adjacent chunks
        with stage("neighbor_expansion (parallel)", indent=3):
            return _expand_with_neighbors(reranked)


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
    rewrite_changed: bool,
    n_variants: int,
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

    if unique_vec_ids and unique_kw_ids:
        overlap = len(unique_vec_ids & unique_kw_ids)
        denom = len(unique_vec_ids | unique_kw_ids)
        overlap_pct = round(100 * overlap / denom) if denom else 0
        record(
            "rrf_fusion",
            n_in=len(unique_vec_ids) + len(unique_kw_ids),
            n_out=denom,
            overlap_pct=overlap_pct,
        )
