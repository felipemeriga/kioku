"""Score retrieval against independent annotations without opening indexed histories."""

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .public_data import file_sha256, write_private

GOLD_FIELDS = {
    "session": "session_groups",
    "event_per_session": "event_groups",
    "literal_turn": "literal_turn_groups",
}


def json_lines(path):
    with path.open() as stream:
        for line in stream:
            yield json.loads(line)


def ranked_units(row, unit):
    key = "session" if unit == "session" else "event"
    return list(dict.fromkeys(event[key] for event in row["events"]))


def score_groups(ranked, groups, k):
    resolvable = [set(group) for group in groups if group]
    if not resolvable:
        return None
    top = ranked[:k]
    hit = 0
    for group in resolvable:
        hit += bool(group.intersection(top))
    has_unresolved = len(resolvable) < len(groups)
    union = set().union(*resolvable)
    rank = next((i for i, value in enumerate(top, start=1) if value in union), None)
    return {
        "any": bool(hit),
        "all": None if has_unresolved else hit == len(groups),
        "recall_resolvable": hit / len(resolvable),
        "reciprocal": 1 / rank if rank else 0.0,
    }


def metric(rows, gold, unit, k):
    values = []
    for row in rows:
        labels = gold[row["case_id"]]
        if labels["expect_abstain"]:
            continue
        item = score_groups(ranked_units(row, unit), labels[GOLD_FIELDS[unit]], k)
        if item is not None:
            values.append(item)
    complete = [value for value in values if value["all"] is not None]
    return {
        "any_n": len(values),
        "any_hit": sum(value["any"] for value in values),
        "all_n": len(complete),
        "all_hit": sum(value["all"] for value in complete),
        "mean_group_recall": average(value["recall_resolvable"] for value in values),
        "mrr": average(value["reciprocal"] for value in values),
    }


def average(values):
    values = list(values)
    return statistics.mean(values) if values else None


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "p50": statistics.median(values),
        "p95": values[math.ceil(len(values) * 0.95) - 1],
        "max": values[-1],
    }


def is_complete(row):
    return row["status"] == "ok" and row["availability"]


def read_integrity(row):
    return bool(row["center_present"] and all(record["integrity"] for record in row["records"]))


def expand_metrics(rows, gold):
    recovered_after_read = 0
    all_after_read = 0
    eligible = 0
    eligible_all = 0
    reads = []
    for row in rows:
        reads.extend(row["reads"])
        groups = gold[row["case_id"]]["literal_turn_groups"]
        if not groups or gold[row["case_id"]]["expect_abstain"]:
            continue
        direct = ranked_units(row, "literal_turn")[:10]
        expanded = [
            record["event"]
            for read in row["reads"]
            for record in read["records"]
            if read_integrity(read)
        ]
        augmented = list(dict.fromkeys([*direct, *expanded]))
        before = score_groups(direct, groups, len(direct))
        after = score_groups(augmented, groups, len(augmented))
        if before is None:
            continue
        eligible += 1
        recovered_after_read += not before["any"] and after["any"]
        if before["all"] is not None:
            eligible_all += 1
            all_after_read += not before["all"] and after["all"]
    return {
        "calls": len(reads),
        "resolved": sum(read["status"] == "ok" for read in reads),
        "byte_and_text_valid": sum(read_integrity(read) for read in reads),
        "errors": dict(Counter(read["code"] for read in reads if read["status"] != "ok")),
        "truncated_records": sum(
            record["has_more"] for read in reads for record in read["records"]
        ),
        "any_eligible": eligible,
        "new_any_after_first_10": recovered_after_read,
        "all_eligible": eligible_all,
        "new_all_after_first_10": all_after_read,
    }


def latency(rows):
    reads = [read for row in rows for read in row["reads"]]
    return {
        "search_ms": distribution(row["search_ms"] for row in rows),
        "read_ms": distribution(read["ms"] for read in reads),
        "service_ms": distribution(
            row["rewrite_ms"] + row["search_ms"] + sum(read["ms"] for read in row["reads"])
            for row in rows
        ),
        "postgres_rpc_wall_ms": distribution(row["transport"]["db_rpc_ms"] for row in rows),
        "postgres_table_wall_ms": distribution(row["transport"]["db_table_ms"] for row in rows),
        "postgres_calls": distribution(
            row["transport"]["db_table_calls"] + row["transport"]["db_rpc_calls"] for row in rows
        ),
        "search_response_bytes": distribution(row["search_bytes"] for row in rows),
        "expanded_response_bytes": distribution(read["bytes"] for read in reads),
        "storage_bytes": distribution(row["transport"]["storage_bytes"] for row in rows),
    }


def score_arm(rows, gold, arm):
    completed = [row for row in rows if is_complete(row)]
    top = [10] if arm == "product" else [1, 5, 10]
    all_attempt_metrics = {
        unit: {f"at_{k}": metric(rows, gold, unit, k) for k in top} for unit in GOLD_FIELDS
    }
    if arm == "product":
        # The returned selected set is chronological, independent of a relevance rank.
        for metric_family in all_attempt_metrics.values():
            metric_family["at_10"].pop("mrr")
    equal_page_sessions = metric(
        [{**row, "events": row["events"][:10]} for row in rows], gold, "session", 10
    )
    if arm == "product":
        equal_page_sessions.pop("mrr")
    return {
        "attempts": len(rows),
        "completed": len(completed),
        "availability_incomplete": sum(not row["availability"] for row in rows),
        "errors": dict(Counter(row["code"] for row in rows if row["status"] != "ok")),
        "no_match": sum(row["status"] == "ok" and not row["events"] for row in rows),
        "coverage_pending": sum(bool(row.get("pending_objects")) for row in rows),
        "distinct_sessions": distribution(len(ranked_units(row, "session")) for row in rows),
        "total_matches": distribution(
            row["total_matches"] for row in completed if row["total_matches"] is not None
        ),
        "has_next_page": sum(row.get("has_more", False) is True for row in rows),
        "metrics_all_attempts": all_attempt_metrics,
        "session_metrics_within_first_10_events": equal_page_sessions,
        "conditional_metrics": {unit: metric(completed, gold, unit, 10) for unit in GOLD_FIELDS}
        if len(rows) != len(completed)
        else None,
        "expansion": expand_metrics(completed, gold),
        "latency": latency(rows),
    }


def paired(rows, gold):
    trials = defaultdict(dict)
    for row in rows:
        trials[row["case_id"]][row["arm"]] = row
    results = defaultdict(Counter)
    for case_id, arms in trials.items():
        literal = arms.get("literal")
        expanded = arms.get("expanded")
        if not (literal and expanded and is_complete(literal) and is_complete(expanded)):
            continue
        labels = gold[case_id]
        if labels["expect_abstain"]:
            continue
        populations = ["all"]
        if expanded["reformulations"]:
            populations.append("reformulated")
        for unit, key in GOLD_FIELDS.items():
            before = score_groups(ranked_units(literal, unit), labels[key], 10)
            after = score_groups(ranked_units(expanded, unit), labels[key], 10)
            if before is None or after is None:
                continue
            direction = (
                "gained"
                if after["any"] > before["any"]
                else ("lost" if after["any"] < before["any"] else "unchanged")
            )
            for population in populations:
                results[f"{unit}_{population}"][direction] += 1
    return {key: dict(value) for key, value in sorted(results.items())}


def abstention_controls(rows, gold):
    controls = defaultdict(Counter)
    for row in rows:
        labels = gold[row["case_id"]]
        if not labels["expect_abstain"]:
            continue
        control = controls[row["arm"]]
        control["n"] += 1
        control["returned_matches"] += bool(row["events"])
        control["distractor_in_first_10"] += bool(
            set(ranked_units(row, "session")[:10]) & set(labels.get("distractor_sessions", []))
            or set(ranked_units(row, "literal_turn")[:10])
            & set(labels.get("distractor_events", []))
        )
    return {key: dict(value) for key, value in sorted(controls.items())}


def read_replay(path, frozen, manifest, query_path, queries):
    """Reject mixed or duplicated trials while retaining explicit partial runs."""
    stream = json_lines(path)
    header = next(stream, None)
    if header is None or header["record_type"] != "run":
        raise ValueError("Replay must start with one immutable run record")
    expected = {
        "gold_hash": manifest["sha256"]["gold.json"],
        "query_hash": file_sha256(query_path),
        "freeze_hash": file_sha256(frozen / "freeze.json"),
        "baseline": manifest["baseline"],
    }
    if any(header.get(key) != value for key, value in expected.items()):
        raise ValueError("The replay header does not match the frozen inputs")
    population = {
        case["case_id"]: case
        for case in queries
        if case["family"] == header["family"]
        and (header["split"] == "all" or case["split"] == header["split"])
    }
    if header["family"] not in manifest["datasets"] or header["expected_cases"] != len(population):
        raise ValueError("The declared replay population does not match the query manifest")
    allowed_clusters = {case["cluster"] for case in population.values()}
    allowed_arms = manifest["policy"]["arms"]
    inventory = {}
    trials = {}
    warm = {}
    completion = None
    seen_first = False
    for row in stream:
        kind = row["record_type"]
        if completion is not None:
            raise ValueError("The completion record must be the last record")
        if kind == "availability":
            key = row["cluster"]
            if key not in allowed_clusters or key in inventory:
                raise ValueError("Invalid or duplicate replay inventory")
            inventory[key] = row
        elif kind in {"trial", "warm"}:
            case = population.get(row["case_id"])
            if case is None or row["arm"] not in allowed_arms:
                raise ValueError("Replay contains a trial outside its frozen population")
            for field in ("family", "stratum", "split", "cluster"):
                if row[field] != case[field]:
                    raise ValueError("Replay trial metadata differs from its frozen question")
            if row["cluster"] not in inventory:
                raise ValueError("Replay trial is missing its source availability")
            if row["availability"] != inventory[row["cluster"]]["available"]:
                raise ValueError("Replay trial disagrees with its source availability")
            key = (row["case_id"], row["arm"])
            if kind == "trial":
                if key in trials:
                    raise ValueError("Duplicate scored trial")
                trials[key] = row
                if row["cache"] == "first_in_process":
                    if seen_first or len(trials) != 1:
                        raise ValueError("There must be only one first invocation")
                    seen_first = True
            else:
                warm_key = (*key, row["trial"])
                if warm_key in warm or key not in trials:
                    raise ValueError("Invalid or duplicate warm trial")
                warm[warm_key] = row
        elif kind == "completion":
            completion = row
        else:
            raise ValueError("Unknown replay record")
    if completion is not None:
        required_trials = {(case_id, arm) for case_id in population for arm in allowed_arms}
        if (
            completion["cases"] != len(population)
            or completion["arms"] != len(required_trials)
            or required_trials != set(trials)
            or allowed_clusters != set(inventory)
        ):
            raise ValueError("Completion record does not account for every frozen trial")
    return header, completion, inventory, trials, warm


def score(path, frozen, split):
    manifest = json.loads((frozen / "freeze.json").read_text())
    gold_path = frozen / "gold.json"
    query_path = frozen / "queries.json"
    if file_sha256(gold_path) != manifest["sha256"]["gold.json"]:
        raise ValueError("The gold file changed after freezing")
    if file_sha256(query_path) != manifest["sha256"]["queries.json"]:
        raise ValueError("The query file changed after freezing")
    gold = json.loads(gold_path.read_text())
    queries = json.loads(query_path.read_text())
    if len({case["case_id"] for case in queries}) != len(queries):
        raise ValueError("The query manifest repeats case IDs")
    header, completion, inventory, tried, warmth = read_replay(
        path, frozen, manifest, query_path, queries
    )
    rows = [row for row in tried.values() if split == "all" or row["split"] == split]
    first = next((row for row in rows if row["cache"] == "first_in_process"), None)
    warm = defaultdict(list)
    for row in warmth.values():
        if split == "all" or row["split"] == split:
            warm[row["arm"]].append(row)
    strata = defaultdict(list)
    arms = defaultdict(list)
    by_cluster = defaultdict(list)
    for row in rows:
        strata[row["stratum"], row["arm"]].append(row)
        arms[row["arm"]].append(row)
        by_cluster[row["cluster"], row["arm"]].append(row)
    case_ids = {row["case_id"] for row in rows}
    population = [
        case
        for case in queries
        if case["family"] == header["family"]
        and (split == "all" or case["split"] == split)
        and (header["split"] == "all" or case["split"] == header["split"])
    ]
    scored_clusters = {row["cluster"] for row in rows}
    dataset_controls = [gold[case_id] for case_id in case_ids]
    return {
        "dataset": header["family"],
        "split": split,
        "baseline": header["baseline"],
        "boundary": header["boundary"],
        "postgres_version": header["postgres_version"],
        "freeze_sha256": header["freeze_hash"],
        "raw_result_sha256": file_sha256(path),
        "cases_executed": len(case_ids),
        "cases_expected": len(population),
        "execution_file_completed": completion is not None,
        "independent_histories": len(scored_clusters),
        "annotation_controls": {
            "abstention_cases": sum(labels["expect_abstain"] for labels in dataset_controls),
            "missing_event_annotations": sum(
                not labels["expect_abstain"] and not any(labels["literal_turn_groups"])
                for labels in dataset_controls
            ),
            "cases_with_unresolved_source_pointers": sum(
                bool(labels.get("unresolved_pointers")) for labels in dataset_controls
            ),
            "cases_with_caption_pointers": sum(
                bool(labels.get("captioned_pointers")) for labels in dataset_controls
            ),
            "source_sessions_after_question_date": sum(
                labels.get("later_source_sessions", 0) for labels in dataset_controls
            ),
        },
        "inventory": {
            key: sum(inventory[cluster][key] for cluster in scored_clusters)
            for key in (
                "committed_segments",
                "parsed_segments",
                "indexed_segments",
                "displayable_events",
                "chunks",
                "raw_bytes_expected",
                "sessions_expected",
                "records_expected",
            )
        },
        "ingest_ms": distribution(inventory[cluster]["ingest_ms"] for cluster in scored_clusters),
        "arms": {arm: score_arm(items, gold, arm) for arm, items in sorted(arms.items())},
        "strata": {
            f"{stratum}/{arm}": {unit: metric(items, gold, unit, 10) for unit in GOLD_FIELDS}
            for (stratum, arm), items in sorted(strata.items())
        },
        "histories": {
            f"{cluster}/{arm}": {
                unit: metric(items, gold, unit, 10) for unit in ("session", "literal_turn")
            }
            for (cluster, arm), items in sorted(by_cluster.items())
        },
        "paired_expansion": paired(rows, gold),
        "abstention_controls": abstention_controls(rows, gold),
        "first_invocation": latency([first]) if first else None,
        "warm": {
            arm: {
                **latency(items),
                "distinct_returned_rankings": len(
                    {
                        tuple((event["session"], event["event"]) for event in row["events"])
                        for row in items
                    }
                ),
            }
            for arm, items in sorted(warm.items())
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("primary", "holdout", "all"), default="primary")
    arguments = parser.parse_args(argv)
    result = score(arguments.replay, arguments.frozen, arguments.split)
    write_private(arguments.output, result)
    print(
        f"Scored {result['cases_executed']}/{result['cases_expected']} cases "
        f"from {result['independent_histories']} histories."
    )


if __name__ == "__main__":
    main(sys.argv[1:])
