"""Protect independence and paired-case selection in audit uncertainty estimates."""

import pytest

from eval.memory_audit.uncertainty import paired_cluster_interval, percentile


def observation(key, cluster, left, right, stratum="factual"):
    return {"case_id": key, "cluster": cluster, "left": left, "right": right, "stratum": stratum}


def test_histories_stay_paired_and_weighted_by_their_question_counts():
    rows = [observation(str(i), "long", True, False) for i in range(9)]
    rows += [observation("short", "short", False, True)]
    score = paired_cluster_interval(rows, repeats=1000)
    assert score["cases"] == 10
    assert score["resampling_clusters"] == 2
    assert score["difference"] == 0.8
    assert score["interval_95"] == [-1, 1]
    assert score["left_only"] == 9
    assert score["right_only"] == 1


def test_stratification_preserves_single_history_strata():
    rows = [
        observation("a", "a", True, False, "update"),
        observation("b", "b", False, True, "temporal"),
    ]
    score = paired_cluster_interval(rows, repeats=100, stratify=True)
    assert score["difference"] == 0
    assert score["interval_95"] == [0, 0]


def test_mixed_question_types_do_not_authorize_splitting_a_dialogue():
    rows = [
        observation("a", "dialogue", True, False, "update"),
        observation("b", "dialogue", True, False, "temporal"),
    ]
    with pytest.raises(ValueError, match="split an independent history"):
        paired_cluster_interval(rows, repeats=10, stratify=True)
    assert paired_cluster_interval(rows, repeats=10)["resampling_clusters"] == 1


def test_missing_outcomes_and_duplicate_cases_are_rejected():
    with pytest.raises(ValueError, match="eligible booleans"):
        paired_cluster_interval([observation("a", "a", None, False)])
    with pytest.raises(ValueError, match="Duplicate"):
        paired_cluster_interval([observation("a", "a", True, False)] * 2)
    with pytest.raises(ValueError, match="No eligible"):
        paired_cluster_interval([])


def test_bootstrap_seed_is_reproducible_and_percentiles_are_explicit():
    rows = [observation(str(i), str(i), bool(i % 2), False) for i in range(8)]
    assert paired_cluster_interval(rows, repeats=100) == paired_cluster_interval(rows, repeats=100)
    assert percentile(list(range(1, 21)), 0.95) == 19
    with pytest.raises(ValueError):
        percentile([], 0.95)
