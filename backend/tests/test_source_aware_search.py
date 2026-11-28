"""Source-role regressions: vendor definitions must survive copied code hits."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from services.search import (
    _apply_recency_decay,
    _deduplicate_code,
    _rerank_sources,
    _source_intent,
    search_documents,
)


def hit(name, score, kind="pdf", folder="repo-a", body=None):
    return {
        "id": name,
        "source_type": kind,
        "content": body if body is not None else name,
        "rerank_score": score,
        "metadata": {"source_filename": name, "folder_id": folder, "code_language": "rust"},
    }


def ranked(_query, rows, top_k):
    return sorted(rows, key=lambda r: r["rerank_score"], reverse=True)[:top_k]


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("difference between fast and live streams", "documentation"),
        ("What is fast.com.clean?", "documentation"),
        ("Explain the vendor stream definitions", "documentation"),
        ("Qual a diferença entre fast e live?", "documentation"),
        ("Where do we retry failed original uploads?", "implementation"),
        ("How is StreamType implemented in types.rs?", "implementation"),
        ("What does get_stream_name return?", "implementation"),
        ("How does the parse_delivery_mode function read suffixes?", "implementation"),
        ("How does the custom_event_decoder function read suffixes?", "implementation"),
        ("What is the scientific method?", "documentation"),
        ("What is the class definition for a comparison-based sorting algorithm?", "documentation"),
        ("Explain how this function is described in the vendor guide.", "documentation"),
        ("Where can I learn more about the methods?", "balanced"),
        ("O que é o método científico?", "documentation"),
        ("Verify executable behavior rather than comments in the route", "implementation"),
        ("Check runtime behavior of the payment handler", "implementation"),
        ("Em qual arquivo acontece o retry?", "implementation"),
        ("Compare our implementation with vendor documentation", "balanced"),
        ("How do these services interact?", "balanced"),
        ("How does an order flow from the site through the API to fulfillment?", "cross_component"),
        ("Trace the payment request across the web app and billing service", "cross_component"),
        (
            "Trace a registration across the browser and scheduler. Show the actual functions.",
            "cross_component",
        ),
        (
            "Trace the vendor guide across services. Which functions does it describe?",
            "documentation",
        ),
        ("Show the end-to-end path for a device registration", "cross_component"),
        ("Show executable retry handling from all three repositories.", "cross_component"),
        ("Where is the session wired across multiple services?", "cross_component"),
        ("Mostre o código dos três repositórios.", "cross_component"),
        ("Mostre os pontos de entrada em vários serviços.", "cross_component"),
        ("Explain the vendor guide across multiple services.", "documentation"),
        ("Compare source code with the vendor guide from both repositories.", "balanced"),
        ("Qual é o fluxo entre o aplicativo e o serviço de cobrança?", "cross_component"),
        ("Where is sales tax computed versus recorded?", "cross_component"),
        ("What is the difference between live and fast event delivery?", "documentation"),
        ("What happens in the ledger when a settlement event is received?", "implementation"),
        ("When a callback is rejected, what does the gateway do?", "implementation"),
        ("What happens in the vendor guide when a refund is completed?", "documentation"),
        ("What happens to a stream when a client connects?", "balanced"),
        ("Trace the request across services as described in the vendor guide", "documentation"),
        (
            "Explain the vendor docs on the flow from alerts through the relay to storage",
            "documentation",
        ),
        ("What is the interest calculation and the entry that records it?", "cross_component"),
    ],
)
def test_source_role_is_conservative(question, intent):
    assert _source_intent(question) == intent


def test_real_failure_shape_keeps_definition_and_removes_duplicate_locations():
    # Scores/order reproduced from the failing first turn. Bodies are synthetic.
    docs = [
        hit("subscribe-examples", 0.6092),
        hit("stream-definitions", 0.5909),
        hit("prerequisites", 0.5427),
    ]
    code = [
        hit(
            "shared/types.rs",
            0.6370,
            "code",
            body="[repo a] [file shared/types.rs]\nfn name() { live_or_fast() }",
        ),
        hit(
            "ingester/types.rs",
            0.6365,
            "code",
            body="[repo a] [file ingester/types.rs]\nfn name() { live_or_fast() }",
        ),
        hit("ingester/ids.rs", 0.6015, "code", body="fn id() { stream_id() }"),
        hit("shared/ids.rs", 0.5998, "code", body="fn id() { stream_id() }"),
    ]
    with patch("services.search.rerank", side_effect=ranked) as reranker:
        result = _rerank_sources("difference between fast and live streams", docs, code, 5)
    assert [r["id"] for r in result[:2]] == ["subscribe-examples", "stream-definitions"]
    assert sum(r["source_type"] == "code" for r in result) == 2
    assert len(reranker.call_args.args[1]) == 5
    assert reranker.call_count == 1


def test_conceptual_search_can_recover_docs_below_multiple_distinct_code_mentions():
    docs = [hit("definition", 0.70), hit("limitations", 0.69), hit("examples", 0.68)]
    code = [hit(f"consumer-{i}", 0.80 - i * 0.01, "code") for i in range(6)]
    with patch("services.search.rerank", side_effect=ranked):
        result = _rerank_sources("explain this concept", docs, code, 5)
    assert [r["id"] for r in result[:3]] == ["definition", "limitations", "examples"]


def test_source_preference_never_forces_unrelated_documents():
    docs = [hit("unrelated-guide", 0.25)]
    code = [hit(f"matching-code-{i}", 0.90 - i * 0.01, "code") for i in range(5)]
    with patch("services.search.rerank", side_effect=ranked):
        result = _rerank_sources("what is this concept", docs, code, 5)
    assert all(r["source_type"] == "code" for r in result)


def test_implementation_returns_only_eligible_code_and_keeps_document_fallback():
    docs = [hit(f"doc-{i}", 0.95 - i * 0.01) for i in range(5)]
    code = [hit(f"code-{i}", 0.60 - i * 0.01, "code") for i in range(5)]
    with patch("services.search.rerank", side_effect=ranked):
        implementation = _rerank_sources("where is retry implemented", docs, code, 5)
        balanced = _rerank_sources("compare our implementation with vendor docs", docs, code, 5)
        code[-1]["rerank_score"] = 0.44
        implementation_with_weak_hit = _rerank_sources("where is retry implemented", docs, code, 5)
        weak_code = [hit("weak", 0.44, "code")]
        fallback = _rerank_sources("where is retry implemented", docs, weak_code, 5)
    assert len(implementation) == 5
    assert len(implementation_with_weak_hit) == 4
    assert all(r["source_type"] == "code" for r in implementation + implementation_with_weak_hit)
    assert fallback == docs
    assert all(r["source_type"] != "code" for r in balanced)


def test_cross_component_prioritizes_distinct_repositories_with_eligible_code():
    docs = [hit(f"guide-{i}", 0.95 - i * 0.01) for i in range(18)]
    code = [
        *[hit(f"api-{i}", 0.75 - i * 0.01, "code", folder="api") for i in range(4)],
        hit("site-client", 0.65, "code", folder="site"),
        hit("warehouse-worker", 0.61, "code", folder="warehouse"),
        hit("unrelated", 0.25, "code", folder="other"),
    ]
    query = "How does an order flow from the site through the API to fulfillment?"
    with patch("services.search.rerank", side_effect=ranked) as reranker:
        result = _rerank_sources(query, docs, code, 5)
    assert [row["id"] for row in result] == [
        "api-0",
        "api-1",
        "api-2",
        "site-client",
        "warehouse-worker",
    ]
    reranker.assert_called_once()


def test_cross_component_keeps_production_handoffs_and_adjacent_context():
    code = [
        hit("web/route.py:1-40", 0.83, "code", folder="web"),
        hit("web/client.py:1-70", 0.82, "code", folder="web"),
        hit("gateway/create.go:101-170", 0.8, "code", folder="gateway"),
        hit("tests/test_ledger.py:1-60", 0.79, "code", folder="ledger"),
        hit("gateway/create.go:1-110", 0.74, "code", folder="gateway"),
        hit("ledger/dispatch.py:1-100", 0.73, "code", folder="ledger"),
    ]
    docs = [hit("overview", 0.9)]
    with patch("services.search.rerank", side_effect=ranked):
        result = _rerank_sources("Trace the request across multiple repos", docs, code, 5)
    assert [row["id"] for row in result] == [
        "web/route.py:1-40",
        "web/client.py:1-70",
        "gateway/create.go:101-170",
        "gateway/create.go:1-110",
        "ledger/dispatch.py:1-100",
    ]


@pytest.mark.parametrize(
    ("query", "weak_production"),
    [
        ("Show tests for request handling across multiple repositories", False),
        ("Show request handling from all three repositories", True),
    ],
)
def test_cross_component_preserves_requested_or_substantially_more_relevant_tests(
    query, weak_production
):
    code = [
        hit("api/handler.py:51-100", 0.84, "code", folder="api"),
        hit("api/client.py:1-40", 0.83, "code", folder="api"),
        hit("tests/test_worker.py:1-40", 0.82, "code", folder="worker"),
        hit("api/handler.py:51-100", 0.81, "code", folder="web", body="other revision"),
        hit("api/handler.py:1-60", 0.75, "code", folder="api"),
        hit("api/handler.py:1-60", 0.7, "code", folder="worker", body="unrelated overlap"),
        hit("worker/consumer.py:1-60", 0.7 if weak_production else 0.8, "code", folder="worker"),
    ]
    with patch("services.search.rerank", side_effect=ranked):
        result = _rerank_sources(query, [hit("overview", 0.9)], code, 5)
    assert {row["id"] for row in result} == {
        "api/handler.py:51-100",
        "api/client.py:1-40",
        "tests/test_worker.py:1-40",
        "worker/consumer.py:1-60" if not weak_production else "api/handler.py:1-60",
    }
    assert {row["metadata"]["folder_id"] for row in result if row["source_type"] == "code"} == {
        "api",
        "web",
        "worker",
    }


def test_event_behavior_does_not_backfill_remaining_slots_with_prose():
    docs = [hit(f"guide-{i}", 0.87 - i * 0.01) for i in range(5)]
    dispatcher = hit("dispatcher", 0.84, "code")
    body = hit("handler-body", 0.81, "code")
    with patch("services.search.rerank", side_effect=ranked):
        results = _rerank_sources(
            "What happens in the backend when a callback is processed?",
            docs,
            [dispatcher, body],
            5,
        )
    assert [r["id"] for r in results] == [
        "dispatcher",
        "handler-body",
    ]


def test_original_source_role_preserves_implementation_through_conceptual_rephrasing():
    docs = [hit(f"guide-{i}", 0.9 - i * 0.01) for i in range(5)]
    code = [hit(f"code-{i}", 0.84 - i * 0.01, "code") for i in range(5)]
    rephrased = "What is the vendor callback convention?"
    with patch("services.search.rerank", side_effect=ranked):
        ordinary = _rerank_sources(rephrased, docs, code, 5)
        runtime = _rerank_sources(rephrased, docs, code, 5, source_role="implementation")
        explicit_mixed = _rerank_sources(
            "What is the callback implementation?", docs, code, 5, source_role="balanced"
        )

    assert ordinary[0]["id"] == "guide-0"
    assert all(row["source_type"] == "code" for row in runtime)
    assert explicit_mixed[0]["id"] == "guide-0"


def test_document_choices_cover_three_facets_even_when_company_code_is_available():
    question = "Which storage engine, query index, and ranking approach would you choose?"
    constraints, storage, index, option, rank = [
        hit(name, score)
        for name, score in [
            ("constraints", 0.85),
            ("storage", 0.8),
            ("index", 0.7),
            ("secondary-index", 0.63),
            ("rank", 0.72),
        ]
    ]
    docs = [constraints, storage, index, option, rank]
    code = [hit("runtime.py", 0.3, "code")]
    ranked_queries = {
        question: [constraints, storage, code[0], index, rank],
        "storage engine": [storage],
        "query index": [index, option],
        "ranking approach": [rank],
    }
    with patch(
        "services.search.rerank", side_effect=lambda q, _pool, top_k: ranked_queries[q]
    ) as rr:
        result = _rerank_sources(question, docs, code, 5)
    assert result == [constraints, storage, index, rank, option]
    assert rr.call_count == 4
    assert {call.args[0]: {r["id"] for r in call.args[1]} for call in rr.call_args_list} == {
        query: {r["id"] for r in (docs + code if query == question else docs)}
        for query in ranked_queries
    }


@pytest.mark.parametrize("bad_score", [None, 0.44, "error"])
def test_document_choices_keep_whole_query_when_a_facet_lacks_evidence(bad_score):
    question = "Which storage engine, query index, and ranking approach would you use?"
    legacy = [hit("legacy", 0.75), hit("fallback", 0.7)]

    def rank(query, _docs, top_k):
        if query == question:
            return legacy
        if query != "query index":
            return [hit(query, 0.8)]
        if bad_score == "error":
            raise RuntimeError("facet failed")
        row = hit("weak", bad_score)
        if bad_score is None:
            row.pop("rerank_score")
        return [row]

    with (
        patch("services.search.rerank", side_effect=rank) as reranker,
        patch("services.search.record") as metrics,
    ):
        assert _rerank_sources(question, legacy, [], 5) == legacy
    assert reranker.call_count == 4
    assert metrics.call_args.kwargs["degraded"] is True


@pytest.mark.parametrize(
    "query",
    [
        "What differs between a table scan, a sorted lookup, and a hash lookup?",
        "Which storage engine, and ranking approach would you choose?",
        "Which storage engine, storage engine, and ranking approach would you choose?",
        "Which source code module, query index, and ranking approach would you choose?",
        "Which vendor guide, implementation, and ranking approach would you choose?",
    ],
)
def test_explicit_facet_grammar_leaves_ordinary_or_code_queries_on_one_rerank(query):
    docs = [hit("manual", 0.8)]
    with patch("services.search.rerank", side_effect=ranked) as reranker:
        assert _rerank_sources(query, docs, [], 5) == docs
    reranker.assert_called_once()


def test_freshness_keeps_implementation_evidence_ahead_of_supporting_docs():
    code = hit("implementation", 0.8, "code")
    old_doc = {**hit("old-guide", 0.87), "created_at": "2020-01-01"}
    fresh_doc = {**hit("fresh-guide", 0.86), "created_at": datetime.now(timezone.utc).isoformat()}
    result = _apply_recency_decay(
        [code, old_doc, fresh_doc],
        query_text="What happens in the backend when a job is processed?",
    )
    assert [r["id"] for r in result] == ["implementation", "fresh-guide", "old-guide"]


def test_deduplication_preserves_repo_scope_literals_and_indentation():
    rows = [
        hit("a", 0.8, "code", body='if ready:\n    value = "a  b"'),
        hit("copy", 0.7, "code", body='if ready:\n    value = "a  b"'),
        hit("other-repo", 0.7, "code", folder="repo-b", body='if ready:\n    value = "a  b"'),
        hit("different-literal", 0.7, "code", body='if ready:\n    value = "a b"'),
        hit("different-indent", 0.7, "code", body='if ready:\nvalue = "a  b"'),
    ]
    assert [r["id"] for r in _deduplicate_code(rows)] == [
        "a",
        "other-repo",
        "different-literal",
        "different-indent",
    ]


def test_old_vendor_definition_is_not_demoted_by_neutral_code_age():
    doc = {**hit("definition", 0.80), "created_at": "2020-01-01"}
    code = {**hit("consumer", 0.79, "code"), "created_at": datetime.now(timezone.utc).isoformat()}
    assert _apply_recency_decay([doc, code], query_text="difference between stream types") == [
        doc,
        code,
    ]
    fresh = {**hit("updated-definition", 0.79), "created_at": code["created_at"]}
    assert [
        r["id"]
        for r in _apply_recency_decay(
            [doc, fresh, code], query_text="latest vendor stream documentation"
        )
    ] == ["updated-definition", "definition", "consumer"]
    assert "recency_factor" not in doc


def test_empty_reranker_and_small_budgets_keep_contract():
    docs, code = [hit("definition", 0.7)], [hit("consumer", 0.75, "code")]
    with patch("services.search.rerank", return_value=[]):
        assert _rerank_sources("explain", docs, code, 5) == []
    with patch("services.search.rerank", side_effect=ranked):
        assert len(_rerank_sources("explain", docs, code, 1)) == 1


@pytest.mark.parametrize("fast_mode", [True, False])
def test_document_and_code_candidates_compete_in_both_search_modes(fast_mode):
    question = "What is the stream definition?"
    definition = hit("stream-definition", 0.7)
    consumer = hit("consumer.rs", 0.8, "code", body="fn consume() {}")
    copy = hit("copy.rs", 0.8, "code", body="fn consume() {}")

    with (
        patch("services.search._run_hybrid_search", return_value=([definition], [])),
        patch("services.search._code_candidates", return_value=[consumer, copy]),
        patch("services.search.rerank", side_effect=ranked),
        patch("services.search.rewrite_query", return_value=question),
        patch("services.search.generate_multi_queries", return_value=[]),
        patch("services.search._expand_with_neighbors", side_effect=lambda results: results),
    ):
        results = search_documents([0.1], query_text=question, fast_mode=fast_mode)

    assert [row["id"] for row in results] == ["stream-definition", "consumer.rs"]
