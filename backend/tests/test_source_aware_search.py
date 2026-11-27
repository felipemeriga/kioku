"""Source-role regressions: vendor definitions must survive copied code hits."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from services.search import _apply_recency_decay, _deduplicate_code, _rerank_sources, _source_intent


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
        ("Em qual arquivo acontece o retry?", "implementation"),
        ("Compare our implementation with vendor documentation", "balanced"),
        ("How do these services interact?", "balanced"),
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


def test_implementation_queries_retain_code_reservation_but_balanced_queries_do_not():
    docs = [hit(f"doc-{i}", 0.95 - i * 0.01) for i in range(5)]
    code = [hit(f"code-{i}", 0.60 - i * 0.01, "code") for i in range(4)]
    with patch("services.search.rerank", side_effect=ranked):
        implementation = _rerank_sources("where is retry implemented", docs, code, 5)
        balanced = _rerank_sources("compare our implementation with vendor docs", docs, code, 5)
    assert sum(r["source_type"] == "code" for r in implementation) == 4
    assert all(r["source_type"] != "code" for r in balanced)


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
