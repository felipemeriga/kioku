"""Execute frozen recall arms without opening the gold manifest."""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from services.agent_evidence_models import BUCKET

from .lab import Lab
from .public_data import (
    ARMS,
    BASELINE,
    DATASETS,
    READ_COUNT,
    READ_WINDOW,
    expansions,
    file_sha256,
    freeze_public,
    gold_event,
    json_text,
    stable_priority,
)


@dataclass(frozen=True)
class SourceRecord:
    object_id: str
    byte_offset: int
    byte_length: int
    text: str

    def validates(self, evidence):
        locator = evidence.get("raw_record", {})
        start = evidence["char_start"]
        actual = evidence["excerpt"]
        return (
            locator.get("object_id") == self.object_id
            and locator.get("byte_offset") == self.byte_offset
            and locator.get("byte_length") == self.byte_length
            and 0 <= start < len(self.text)
            and self.text[start : start + len(actual)] == actual
            and evidence["has_more"] == (start + len(actual) < len(self.text))
        )


def archive_fixture(lab, scope, histories):
    expected = {}
    lab.create_owner(scope["owner"])
    lab.create_folder(scope["root"], scope["owner"], "benchmark")
    lab.create_folder(scope["folder"], scope["owner"], "history", scope["root"])
    start = time.perf_counter()
    previous = lab.index_state(scope["owner"], scope["folder"])
    if previous["committed_segments"] not in (0, len(histories)):
        raise RuntimeError("Partially seeded public namespace needs a fresh audit database")
    reused = bool(previous["committed_segments"])
    committed = previous["committed_segments"]
    errors = []
    for row in histories:
        native = row["native"]
        records = row["records"]
        offset = 0
        for position, record in enumerate(records, start=1):
            raw = (json.dumps(record, ensure_ascii=False) + "\n").encode()
            expected[gold_event(scope, native, position)] = SourceRecord(
                "segment-1", offset, len(raw), record["payload"]["content"]
            )
            offset += len(raw)
        if reused:
            continue
        try:
            lab.capture(scope["owner"], scope["folder"], native, records)
            committed += 1
        except Exception as exc:
            errors.append(getattr(exc, "detail", {}).get("code") or type(exc).__name__)
    state = lab.index_state(scope["owner"], scope["folder"])
    return expected, {
        **state,
        "records_expected": len(expected),
        "raw_bytes_expected": sum(record.byte_length for record in expected.values()),
        "sessions_expected": len(histories),
        "capture_calls_completed": committed,
        "capture_errors": errors,
        "reused": reused,
        "ingest_ms": (time.perf_counter() - start) * 1000,
        "available": state["indexed_segments"] == len(histories)
        and state["displayable_events"] == len(expected),
    }


def payload(call, **kwargs):
    started = time.perf_counter()
    raw = call(**kwargs)
    elapsed = (time.perf_counter() - started) * 1000
    return json.loads(raw), elapsed, len(raw.encode())


def code(response):
    detail = response.get("detail")
    return response.get("code") or (detail or {}).get("code") or response.get("status")


def snapshot(lab):
    bucket = lab.bucket(BUCKET)
    return {
        "db_rpc_ms": lab.db_wall["rpc"] * 1000,
        "db_table_ms": lab.db_wall["table"] * 1000,
        "db_rpc_calls": lab.db_calls["rpc"],
        "db_table_calls": lab.db_calls["table"],
        "storage_reads": bucket.download_count,
        "storage_bytes": bucket.downloaded_bytes,
    }


def run_arm(lab, mcp, case, arm, expected):
    parameters = {**case["filters"], **ARMS[arm]}
    rewrite_start = time.perf_counter()
    reformulations = expansions(case["question"]) if arm == "expanded" else []
    rewrite_ms = (time.perf_counter() - rewrite_start) * 1000
    if reformulations:
        parameters["queries"] = reformulations
    before = snapshot(lab)
    answer, search_ms, search_bytes = payload(
        mcp.search_agent_history, query=case["question"], **parameters
    )
    matched_events = answer.get("matches", [])
    contexts = {}
    for event in matched_events:
        contexts.setdefault(event["native_session_id"], event)
        if len(contexts) == READ_COUNT:
            break
    reads = []
    for event in contexts.values():
        expanded, elapsed, size = payload(
            mcp.read_agent_evidence, reference=event["reference"], **READ_WINDOW
        )
        checks = [
            {
                "event": evidence["event_id"],
                "integrity": evidence["event_id"] in expected
                and expected[evidence["event_id"]].validates(evidence),
                "has_more": evidence.get("has_more", False),
            }
            for evidence in expanded.get("evidence", [])
        ]
        reads.append(
            {
                "status": expanded.get("status"),
                "code": code(expanded),
                "session": event["native_session_id"],
                "center": event["event_id"],
                "center_present": any(check["event"] == event["event_id"] for check in checks),
                "ms": elapsed,
                "bytes": size,
                "records": checks,
            }
        )
    after = snapshot(lab)
    return {
        "case_id": case["case_id"],
        "cluster": case["cluster"],
        "family": case["family"],
        "stratum": case["stratum"],
        "split": case["split"],
        "arm": arm,
        "status": answer.get("status"),
        "code": code(answer),
        "reformulations": len(reformulations),
        "search_ms": search_ms,
        "rewrite_ms": rewrite_ms,
        "search_bytes": search_bytes,
        "reads": reads,
        "total_matches": answer.get("total_matches"),
        "has_more": answer.get("has_more"),
        "pending_objects": answer.get("index_pending_objects"),
        "events": [
            {"event": e["event_id"], "session": e["native_session_id"], "role": e["role"]}
            for e in matched_events
        ],
        "transport": {key: after[key] - value for key, value in before.items()},
    }


def verify_frozen(directory, family):
    """Check replay-safe files. Gold is only opened later by the independent scorer."""
    manifest = json.loads((directory / "freeze.json").read_text())
    if manifest["baseline"] != BASELINE:
        raise ValueError("The frozen files specify a different baseline")
    for name in ("queries.json", f"{family}.jsonl"):
        if file_sha256(directory / name) != manifest["sha256"][name]:
            raise ValueError("The replay files changed after freezing")
    if manifest["policy"]["arms"] != ARMS or manifest["policy"]["read_window"] != READ_WINDOW:
        raise ValueError("The replay policy changed after freezing")
    return manifest


def corpus_groups(path, included):
    """Stream one isolated complete history at a time."""
    current = None
    group = []
    with path.open() as corpus:
        for line in corpus:
            item = json.loads(line)
            cluster = item["scope"]["cluster"]
            if cluster not in included:
                continue
            if current and cluster != current:
                yield current, group
                group = []
            current = cluster
            group.append(item)
    if group:
        yield current, group


def open_output(path):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    return os.fdopen(fd, "w", buffering=1)


def log_line(stream, result):
    stream.write(json_text(result) + "\n")


def replay_public(lab, directory, family, split, output, warm_repeats=5):
    manifest = verify_frozen(directory, family)
    cases = [
        case
        for case in json.loads((directory / "queries.json").read_text())
        if case["family"] == family and (split == "all" or case["split"] == split)
    ]
    if not cases:
        raise ValueError("No frozen cases in the requested split")
    groups = defaultdict(list)
    for case in cases:
        groups[case["cluster"]].append(case)
    warm_case = min(cases, key=lambda case: stable_priority(case["case_id"]))
    call_counter = 0
    evaluated = 0
    with open_output(output) as stream:
        log_line(
            stream,
            {
                "record_type": "run",
                "family": family,
                "split": split,
                "baseline": BASELINE,
                "freeze_hash": file_sha256(directory / "freeze.json"),
                "query_hash": manifest["sha256"]["queries.json"],
                "gold_hash": manifest["sha256"]["gold.json"],
                "expected_cases": len(cases),
                "postgres_version": lab.pg.info.server_version,
                "boundary": "in-process MCP callable, PostgreSQL bridge, filesystem storage",
                "db_cache": "unknown",
                "warm_repeats": warm_repeats,
            },
        )
        for group_index, (cluster, histories) in enumerate(
            corpus_groups(directory / f"{family}.jsonl", groups), start=1
        ):
            scope = histories[0]["scope"]
            expected, state = archive_fixture(lab, scope, histories)
            log_line(stream, {"record_type": "availability", "cluster": cluster, **state})
            with lab.tools(scope["owner"], scope["root"]) as mcp:
                for case in groups[cluster]:
                    order = list(ARMS)
                    rotation = int(stable_priority(case["case_id"]), 16) % len(order)
                    order = order[rotation:] + order[:rotation]
                    for arm in order:
                        call_counter += 1
                        row = run_arm(lab, mcp, case, arm, expected)
                        log_line(
                            stream,
                            {
                                "record_type": "trial",
                                "trial": call_counter,
                                "cache": "first_in_process"
                                if call_counter == 1
                                else "uncontrolled",
                                "availability": state["available"],
                                **row,
                            },
                        )
                    evaluated += 1
                    if case["case_id"] == warm_case["case_id"] and warm_repeats:
                        for arm in order:
                            run_arm(lab, mcp, case, arm, expected)  # unscored warm-up
                            for trial in range(warm_repeats):
                                warm = run_arm(lab, mcp, case, arm, expected)
                                log_line(
                                    stream,
                                    {
                                        "record_type": "warm",
                                        "trial": trial + 1,
                                        "cache": "explicit_warmup",
                                        "availability": state["available"],
                                        **warm,
                                    },
                                )
            if group_index == 1 or group_index % 10 == 0 or group_index == len(groups):
                print(
                    f"{family} {split}: {group_index}/{len(groups)} histories, "
                    f"{evaluated}/{len(cases)} cases",
                    flush=True,
                )
        log_line(stream, {"record_type": "completion", "cases": evaluated, "arms": call_counter})
    if evaluated != len(cases):
        raise RuntimeError("Some selected histories were absent from the frozen corpus")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--data", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--lab", type=Path, required=True)
    replay.add_argument("--frozen", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--family", choices=sorted(DATASETS), required=True)
    replay.add_argument("--split", choices=("primary", "holdout", "all"), default="primary")
    replay.add_argument("--warm-repeats", type=int, default=5)
    arguments = parser.parse_args(argv)
    if arguments.command == "freeze":
        manifest = freeze_public(arguments.data, arguments.output)
        print(f"Froze {manifest['cases']} cases and their separate corpus and gold files.")
        return
    lab = Lab(arguments.lab)
    try:
        replay_public(
            lab,
            arguments.frozen,
            arguments.family,
            arguments.split,
            arguments.output,
            arguments.warm_repeats,
        )
    finally:
        lab.close()


if __name__ == "__main__":
    main(sys.argv[1:])
