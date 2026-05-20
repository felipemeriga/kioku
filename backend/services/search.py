"""Hybrid search: vector + keyword with RRF fusion and reranking."""

import logging

from langsmith import traceable

from db.client import get_supabase
from services.embeddings import embed_query
from services.query import generate_multi_queries, rewrite_query
from services.rerank import rerank

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
    """Run vector + keyword search for a single query."""
    vector_results = _vector_search(
        query_embedding, user_id, fetch_k, topic, keyword, root_folder_id=root_folder_id
    )
    keyword_results = []
    if query_text:
        keyword_results = _keyword_search(
            query_text, user_id, fetch_k, topic, keyword, root_folder_id=root_folder_id
        )
    return vector_results, keyword_results


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
        # Fast path: skip query rewriting and multi-query, use original query directly
        vector_results, keyword_results = _run_hybrid_search(
            query_embedding, query_text, user_id, fetch_k, topic, keyword, root_folder_id
        )

        if not vector_results and not keyword_results:
            return []

        if not keyword_results:
            fused = vector_results
        elif not vector_results:
            fused = keyword_results
        else:
            fused = _reciprocal_rank_fusion(vector_results, keyword_results)

        reranked = rerank(query_text or "query", fused, top_k=top_k)
        return _expand_with_neighbors(reranked)

    # Full path: query rewriting + multi-query for better recall

    # Step 1: Rewrite the original query for better retrieval
    rewritten = query_text
    if query_text:
        try:
            rewritten = rewrite_query(query_text)
        except Exception:
            rewritten = query_text

    # Step 2: Generate multi-query variants
    query_variants = [rewritten]
    if query_text:
        try:
            variants = generate_multi_queries(query_text)
            query_variants.extend(variants)
        except Exception:
            pass

    # Step 3: Run hybrid search for each variant, collect all results
    all_vector: list[dict] = []
    all_keyword: list[dict] = []

    # First variant uses the provided embedding (rewritten query)
    rewritten_embedding = query_embedding
    if rewritten != query_text:
        try:
            rewritten_embedding = embed_query(rewritten)
        except Exception:
            rewritten_embedding = query_embedding

    vec, kw = _run_hybrid_search(
        rewritten_embedding, rewritten, user_id, fetch_k, topic, keyword, root_folder_id
    )
    all_vector.extend(vec)
    all_keyword.extend(kw)

    # Additional variants
    for variant in query_variants[1:]:
        try:
            variant_embedding = embed_query(variant)
            vec, kw = _run_hybrid_search(
                variant_embedding, variant, user_id, fetch_k, topic, keyword, root_folder_id
            )
            all_vector.extend(vec)
            all_keyword.extend(kw)
        except Exception:
            continue

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
    reranked = rerank(query_text or "query", fused, top_k=top_k)

    # Step 6: Parent document retrieval — expand each result with adjacent chunks
    return _expand_with_neighbors(reranked)


def _expand_with_neighbors(results: list[dict]) -> list[dict]:
    """Expand each result with content from adjacent chunks in the same document.

    Uses content_hash and chunk_index from metadata to find neighbors.
    Merges prev + current + next content into a single expanded content field.

    The neighbor query is scoped to the exact prev/next chunk_index values via
    a jsonb filter, so a 200-page PDF doesn't pull all ~1000 chunks just to
    locate two neighbors.
    """
    if not results:
        return []

    sb = get_supabase()
    expanded = []

    for doc in results:
        meta = doc.get("metadata") or {}
        chunk_index = meta.get("chunk_index")
        content_hash = doc.get("content_hash")

        # If we don't have chunk metadata or content_hash, return as-is
        if chunk_index is None or not content_hash:
            expanded.append(doc)
            continue

        # Only fetch the neighbors we actually need (prev + next).
        # chunk_index can be 0 → asking for -1 just won't match; still safe.
        neighbor_indices = [chunk_index - 1, chunk_index + 1]
        # metadata->>chunk_index extracts as text in Postgrest; cast to str.
        neighbor_keys = [str(n) for n in neighbor_indices]

        try:
            neighbors = (
                sb.table("documents")
                .select("content, metadata")
                .eq("content_hash", content_hash)
                .in_("metadata->>chunk_index", neighbor_keys)
                .execute()
            )

            # Build a map of chunk_index -> content
            chunk_map: dict[int, str] = {}
            for row in neighbors.data:
                row_meta = row.get("metadata") or {}
                idx = row_meta.get("chunk_index")
                if idx is not None:
                    chunk_map[idx] = row["content"]

            # Assemble expanded content: prev + current + next
            parts = []
            if chunk_index - 1 in chunk_map:
                parts.append(chunk_map[chunk_index - 1])
            parts.append(doc["content"])
            if chunk_index + 1 in chunk_map:
                parts.append(chunk_map[chunk_index + 1])

            expanded_doc = doc.copy()
            expanded_doc["content"] = "\n\n".join(parts)
            expanded_doc["expanded"] = len(parts) > 1
            expanded.append(expanded_doc)
        except Exception:
            logger.warning("Failed to expand chunk neighbors", exc_info=True)
            expanded.append(doc)

    return expanded
