"""Paired cluster uncertainty for completed, frozen retrieval replays.

Intervals describe the chosen corpus and retrieval endpoints. They do not turn
retrieval into answer accuracy, task reliability, or a production guarantee.
"""

import math
import random
from collections import defaultdict


def percentile(values, probability):
    """Nearest-rank percentile, matching the audit's latency summaries."""
    if not values or not 0 < probability <= 1:
        raise ValueError("A nonempty sample and a probability in (0, 1] are required")
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * probability) - 1]


def paired_cluster_interval(observations, *, seed=20261127, repeats=20_000, stratify=False):
    """Bootstrap supplied history clusters, retaining within-history pairs.

    Each observation has a unique case ID, cluster ID, stratum, and boolean left
    and right outcomes. Missing annotations/errors must be selected explicitly
    before calling this function; silently dropping them here is forbidden.
    For a LoCoMo-style dialogue containing several question types, stratification
    must remain false so dialogue dependence is preserved.
    Callers must check shared source material across clusters. Isolated database
    namespaces alone do not establish statistical independence; intervals must
    then be described as resampling sensitivity rather than generalization CIs.
    """
    if type(repeats) is not int or repeats < 1:
        raise ValueError("A positive integer repeat count is required")
    observations = list(observations)
    clusters = defaultdict(list)
    seen = set()
    for row in observations:
        if row["case_id"] in seen:
            raise ValueError("Duplicate paired case")
        seen.add(row["case_id"])
        if type(row["left"]) is not bool or type(row["right"]) is not bool:
            raise ValueError("Paired outcomes must be explicitly eligible booleans")
        clusters[row["cluster"]].append(row)
    if not clusters:
        raise ValueError("No eligible paired observations")
    strata = defaultdict(list)
    summaries = {}
    for cluster, rows in sorted(clusters.items()):
        groups = {row["stratum"] for row in rows}
        if stratify and len(groups) != 1:
            raise ValueError("Stratification would split an independent history")
        stratum = next(iter(groups)) if stratify else "all"
        strata[stratum].append(cluster)
        summaries[cluster] = (
            sum(int(row["left"]) - int(row["right"]) for row in rows),
            len(rows),
        )
    rng = random.Random(seed)
    draws = []
    for _ in range(repeats):
        numerator = denominator = 0
        for _, ids in sorted(strata.items()):
            for cluster in rng.choices(ids, k=len(ids)):
                effect, count = summaries[cluster]
                numerator += effect
                denominator += count
        draws.append(numerator / denominator)
    total = sum(count for _, count in summaries.values())
    return {
        "cases": total,
        "resampling_clusters": len(clusters),
        "left_only": sum(row["left"] and not row["right"] for row in observations),
        "right_only": sum(row["right"] and not row["left"] for row in observations),
        "difference": sum(effect for effect, _ in summaries.values()) / total,
        "interval_95": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "method": "paired history-cluster bootstrap; micro ratio; nearest-rank percentiles",
        "stratified": stratify,
        "seed": seed,
        "repeats": repeats,
    }
