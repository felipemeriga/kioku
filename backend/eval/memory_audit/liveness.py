"""Measure isolated parser/index drains with equal work and controlled overlap."""

import argparse
import json
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.agent_evidence import EvidenceStore
from services.agent_evidence_jobs import process_session
from services.agent_evidence_models import canonical, sha256

from .lab import Lab
from .operational_fixtures import tool
from .public_data import BASELINE, codex_record, uuid_for
from .replay import log_line, open_output
from .score_public import distribution

CONDITIONS = {
    "one_serial": (1, 1, False),
    "one_overlap": (1, 2, True),
    "four_serial": (4, 1, False),
    "four_disjoint": (4, 2, False),
    "four_overlap": (4, 2, True),
}
START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def generated_records(segment, records, shape):
    result = []
    for i in range(0, records, 4):
        when = START + timedelta(days=segment, seconds=i)
        check = f"load-{segment}-{i}"
        unusual = " LOAD_ANCHOR_42." if segment == 0 and i == 0 else ""
        if shape == "messages":
            for j in range(4):
                result.append(
                    codex_record(
                        "assistant" if j else "user",
                        "Relay checkpoint checksum validation produced an observation."
                        + (unusual if j == 0 else ""),
                        when + timedelta(seconds=j),
                    )
                )
            continue
        result.extend(
            [
                codex_record("user", "Check the relay checkpoint and checksum." + unusual, when),
                tool(
                    "Relay checkpoint checksum measured.",
                    (when + timedelta(seconds=1)).isoformat(),
                    check,
                ),
                tool(
                    "Relay checkpoint done.",
                    (when + timedelta(seconds=2)).isoformat(),
                    check,
                    result=True,
                ),
                tool(
                    "Relay checkpoint checksum validation on this packet completed. "
                    "Exit zero. Runtime and byte count recorded in the synthetic workload.",
                    (when + timedelta(seconds=3)).isoformat(),
                    check if shape == "duplicate_results" else check + "-second",
                    result=True,
                ),
            ]
        )
    return result


def seed(lab, owner, folder, sessions, segments, records_per_segment, shape):
    references = {}
    for ordinal in range(segments):
        key = f"lane-{ordinal % sessions}"
        sid, _ = lab.capture(
            owner,
            folder,
            key,
            generated_records(ordinal, records_per_segment, shape),
            append=key in references,
            index=False,
        )
        references[key] = {"id": sid, "user_id": owner, "folder_id": folder}
    return list(references.values())


def still_pending(lab, session_id):
    return lab.pg.execute(
        """SELECT EXISTS(
             SELECT 1 FROM agent_evidence_objects
             WHERE session_id=%s AND kind='segment' AND committed_revision IS NOT NULL
               AND (indexed_parser_version<1 OR memory_index_version<2)
           ) AS pending""",
        [session_id],
    ).fetchone()["pending"]


def worker(lab_file, prefix, targets, barrier, stop):
    lane = Lab(lab_file, application_name=prefix)
    lane.rpc_observations = []
    code_counts = Counter()
    passes = 0
    try:
        barrier.wait(timeout=10)
        with lane.service_role():
            while not stop.is_set():
                pending = [session for session in targets if still_pending(lane, session["id"])]
                if not pending:
                    break
                passes += 1
                for session in pending:
                    if stop.is_set():
                        break
                    try:
                        process_session(lane, session)
                    except Exception as exc:
                        code = getattr(exc, "detail", {}).get("code") or type(exc).__name__
                        code_counts[code] += 1
                        # Permit a normal retry of a transient publish failure while bounded.
                        if stop.wait(0.1):
                            break
    finally:
        lane.close()
    return {"passes": passes, "errors": dict(code_counts), "observations": lane.rpc_observations}


def wait_events(lab, prefix):
    return lab.pg.execute(
        """SELECT wait_event_type,wait_event
           FROM pg_stat_activity
           WHERE datname=current_database() AND application_name=%s
             AND state='active' AND wait_event IS NOT NULL""",
        [prefix],
    ).fetchall()


def query_trials(lab, owner, folder, segments, count=5):
    query = "Have we checked the relay checkpoint checksum?"
    final_day = (START + timedelta(days=segments - 1)).date().isoformat()
    shapes = {
        "broad": {"query": query},
        "identifier": {"query": query + " LOAD_ANCHOR_42"},
        "identifier_only": {"query": "LOAD_ANCHOR_42"},
        "last_day": {"query": query, "from_date": final_day, "through_date": final_day},
    }
    measurements = defaultdict(list)
    with lab.tools(owner, folder) as mcp:
        for key, params in shapes.items():
            json.loads(mcp.search_agent_history(order="relevance", **params))  # explicit warm-up
        for repetition in range(count):
            order = list(shapes)
            shift = repetition % len(order)
            for key in order[shift:] + order[:shift]:
                start = time.perf_counter()
                previous = lab.db_wall["rpc"]
                response = json.loads(
                    mcp.search_agent_history(
                        order="relevance",
                        limit=10,
                        **shapes[key],
                    )
                )
                measurements[key].append(
                    {
                        "wall_ms": (time.perf_counter() - start) * 1000,
                        "rpc_ms": (lab.db_wall["rpc"] - previous) * 1000,
                        "status": response["status"],
                        "total_matches": response.get("total_matches"),
                        "pending": response.get("index_pending_objects"),
                    }
                )
    return {
        key: {
            "service_plus_db_ms": distribution(row["wall_ms"] for row in samples),
            "db_rpc_wall_ms": distribution(row["rpc_ms"] for row in samples),
            "results": samples,
        }
        for key, samples in measurements.items()
    }


def verify_drain(lab, targets):
    integrity = True
    with lab.service_role():
        for session in targets:
            store = EvidenceStore(lab, session["user_id"], session["folder_id"])
            value = store.session(session["id"])
            payload = lab.bucket("agent-evidence").download(store.prefix(value) + "/manifest.json")
            integrity &= payload == canonical(value["manifest_json"])
            segments = value["manifest_json"]["segments"]
            for descriptor in (segments[0], segments[-1]):
                obj = store.object(session["id"], descriptor["id"])
                integrity &= sha256(store.download(obj)) == descriptor["sha256"]
        for session in targets:
            process_session(lab, session)
    return integrity


def condition(lab, lab_file, key, segments, records, deadline_seconds, output, shape):
    sessions, worker_count, overlap = CONDITIONS[key]
    root = uuid_for(output.name, key, "root")
    owner = uuid_for(output.name, key, "owner")
    folder = uuid_for(output.name, key, "repo")
    lab.create_owner(owner)
    lab.create_folder(root, owner, "capacity")
    lab.create_folder(folder, owner, "relay-capacity", root)
    seed_start = time.perf_counter()
    targets = seed(lab, owner, folder, sessions, segments, records, shape)
    seed_ms = (time.perf_counter() - seed_start) * 1000
    initial = lab.index_state(owner, folder)
    assignments = [
        targets if overlap else targets[index::worker_count] for index in range(worker_count)
    ]
    prefix = "memory-audit-worker-" + key
    barrier = threading.Barrier(worker_count + 1)
    stop = threading.Event()
    snapshots = [{"elapsed_ms": 0.0, **initial}]
    waits = Counter()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        jobs = [
            pool.submit(worker, lab_file, prefix, assigned, barrier, stop)
            for assigned in assignments
        ]
        barrier.wait(timeout=10)
        start = time.perf_counter()
        next_snapshot = 1.0
        while not all(job.done() for job in jobs):
            elapsed = time.perf_counter() - start
            if elapsed >= next_snapshot:
                snapshots.append({"elapsed_ms": elapsed * 1000, **lab.index_state(owner, folder)})
                next_snapshot += 1.0
            for row in wait_events(lab, prefix):
                waits[f"{row['wait_event_type']}/{row['wait_event']}"] += 1
            if elapsed >= deadline_seconds:
                stop.set()
                break
            time.sleep(0.1)
        workers = [job.result() for job in jobs]
        drain_ms = (time.perf_counter() - start) * 1000
    final = lab.index_state(owner, folder)
    complete = final["indexed_segments"] == segments
    snapshots.append({"elapsed_ms": drain_ms, **final})
    rpcs = defaultdict(list)
    errors = Counter()
    for result in workers:
        for name, milliseconds, sqlstate in result.pop("observations"):
            rpcs[name].append(milliseconds)
            if sqlstate:
                errors[f"{name}/{sqlstate}"] += 1
    records_valid = None
    idempotent = None
    searches = {}
    if complete:
        records_valid = verify_drain(lab, targets)
        idempotent = lab.index_state(owner, folder) == final
        searches = query_trials(lab, owner, folder, segments)
    return {
        "condition": key,
        "source_records": segments * records,
        "expected_visible_after_native_tool_dedup": (
            segments * records * 3 // 4 if shape == "duplicate_results" else segments * records
        ),
        "record_shape": shape,
        "seed_ms": seed_ms,
        "drain_ms": drain_ms,
        "fully_indexed": complete,
        "file_integrity": records_valid,
        "reindex_idempotent": idempotent,
        "scheduled_workers": worker_count,
        "sessions": sessions,
        "duplicate_scheduled_scope": overlap,
        "stop_requested": stop.is_set(),
        "worker_passes": workers,
        "snapshots": snapshots,
        "physical_wait_samples": dict(waits),
        "postgres_rpc_wall_ms": {rpc: distribution(values) for rpc, values in sorted(rpcs.items())},
        "sqlstates": dict(errors),
        "query_cost": searches,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segments", type=int, default=64)
    parser.add_argument("--records-per-segment", type=int, default=64)
    parser.add_argument("--deadline", type=float, default=120)
    parser.add_argument(
        "--record-shape",
        choices=("duplicate_results", "distinct_results", "messages"),
        default="duplicate_results",
    )
    parser.add_argument(
        "--conditions", choices=sorted(CONDITIONS), nargs="+", default=list(CONDITIONS)
    )
    args = parser.parse_args()
    if (
        args.segments < 4
        or args.segments % 4
        or args.records_per_segment < 4
        or args.records_per_segment % 4
    ):
        raise ValueError("Segment and record counts must be positive multiples of four")
    lab = Lab(args.lab)
    try:
        with open_output(args.output) as stream:
            log_line(
                stream,
                {
                    "baseline": BASELINE,
                    "segments": args.segments,
                    "records_per_segment": args.records_per_segment,
                    "record_shape": args.record_shape,
                    "pg_version": lab.pg.info.server_version,
                    "deadline_seconds_per_condition": args.deadline,
                    "sample_interval_seconds": 1.0,
                    "slot_wait_sample_seconds": 0.1,
                    "execution": "scoped real process_session, separate PostgreSQL connections",
                },
            )
            for key in args.conditions:
                result = condition(
                    lab,
                    args.lab,
                    key,
                    args.segments,
                    args.records_per_segment,
                    args.deadline,
                    args.output,
                    args.record_shape,
                )
                log_line(stream, result)
                final = result["snapshots"][-1]
                print(f"{key}: {final['indexed_segments']}/{args.segments} indexed", flush=True)
    finally:
        lab.close()


if __name__ == "__main__":
    main()
