"""Guard audit denominators and evidence budgets independently of public datasets."""

import pytest

from eval.memory_audit.score_public import (
    abstention_controls,
    distribution,
    expand_metrics,
    is_complete,
    metric,
    ranked_units,
    read_integrity,
    score_groups,
)


def labels(groups, *, abstain=False):
    return {
        "expect_abstain": abstain,
        "session_groups": groups,
        "event_groups": groups,
        "literal_turn_groups": groups,
    }


def result(case_id, events, **changes):
    return {
        "case_id": case_id,
        "events": [{"event": event, "session": session} for event, session in events],
        "status": "ok",
        "availability": True,
        "reads": [],
        **changes,
    }


def test_unannotated_questions_are_not_successes_or_misses():
    assert score_groups(["unrelated"], [], 10) is None
    assert score_groups(["unrelated"], [[], []], 10) is None
    assert metric([result("q", [("x", "s")])], {"q": labels([[]])}, "literal_turn", 10) == {
        "any_n": 0,
        "any_hit": 0,
        "all_n": 0,
        "all_hit": 0,
        "mean_group_recall": None,
        "mrr": None,
    }


def test_partial_annotations_cannot_certify_complete_evidence():
    score = score_groups(["known"], [["known"], []], 10)
    assert score == {"any": True, "all": None, "recall_resolvable": 1, "reciprocal": 1}
    rows = [result("q", [("known", "session")])]
    aggregate = metric(rows, {"q": labels([["known"], []])}, "literal_turn", 10)
    assert (aggregate["any_hit"], aggregate["any_n"]) == (1, 1)
    assert (aggregate["all_hit"], aggregate["all_n"]) == (0, 0)


def test_groups_allow_alternative_locators_but_require_each_evidence_group():
    groups = [["first-copy", "second-copy"], ["independent-evidence"]]
    partial = score_groups(["noise", "second-copy"], groups, 10)
    assert partial == {
        "any": True,
        "all": False,
        "recall_resolvable": 0.5,
        "reciprocal": 0.5,
    }
    assert score_groups(["first-copy", "independent-evidence"], groups, 1)["all"] is False
    assert score_groups(["first-copy", "independent-evidence"], groups, 2)["all"] is True


def test_abstention_labels_override_retained_positive_source_annotations():
    row = result("abs", [("distractor", "retained-positive")], arm="literal")
    gold = {
        "abs": {
            **labels([["retained-positive"]], abstain=True),
            "distractor_sessions": ["retained-positive"],
        }
    }
    assert metric([row], gold, "session", 10)["any_n"] == 0
    assert abstention_controls([row], gold) == {
        "literal": {"n": 1, "returned_matches": 1, "distractor_in_first_10": 1}
    }


def test_distinct_session_rank_does_not_equal_a_ten_event_page():
    row = result("q", [(f"noise-{i}", "one-session") for i in range(10)] + [("gold", "gold-s")])
    gold = {"q": labels([["gold-s"]])}
    assert ranked_units(row, "session") == ["one-session", "gold-s"]
    assert metric([row], gold, "session", 10)["any_hit"] == 1
    page = {**row, "events": row["events"][:10]}
    assert metric([page], gold, "session", 10)["any_hit"] == 0


def test_error_and_missing_index_are_not_conditional_successes():
    failed = result("q", [], status="error")
    pending = result("q", [("gold", "s")], availability=False)
    assert not is_complete(failed)
    assert not is_complete(pending)
    assert is_complete(result("q", []))  # a valid empty retrieval is a completed request
    assert metric([failed], {"q": labels([["gold"]])}, "literal_turn", 10)["any_hit"] == 0


@pytest.mark.parametrize("center,integrity", [(False, True), (True, False)])
def test_invalid_raw_expansions_cannot_recover_gold(center, integrity):
    read = {
        "status": "ok",
        "code": "ok",
        "center_present": center,
        "records": [{"event": "gold", "integrity": integrity, "has_more": False}],
    }
    assert not read_integrity(read)
    row = result("q", [("noise", "s")], reads=[read])
    score = expand_metrics([row], {"q": labels([["gold"]])})
    assert score["resolved"] == 1
    assert score["byte_and_text_valid"] == 0
    assert score["new_any_after_first_10"] == 0


def test_verified_read_can_recover_evidence_without_relabeling_discovery():
    read = {
        "status": "ok",
        "code": "ok",
        "center_present": True,
        "records": [{"event": "gold", "integrity": True, "has_more": True}],
    }
    row = result("q", [("noise", "s")], reads=[read])
    gold = {"q": labels([["gold"]])}
    assert metric([row], gold, "literal_turn", 10)["any_hit"] == 0
    score = expand_metrics([row], gold)
    assert score["new_any_after_first_10"] == 1
    assert score["new_all_after_first_10"] == 1
    assert score["truncated_records"] == 1


def test_latency_nearest_rank_percentile_reports_its_sample_size():
    assert distribution([]) == {"n": 0}
    assert distribution(range(1, 21)) == {"n": 20, "p50": 10.5, "p95": 19, "max": 20}
