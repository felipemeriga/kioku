"""Freeze recorded STATE training trajectories and MemoryArena history prefixes."""

import argparse
import json
import tarfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from .operational_fixtures import tool
from .public_data import (
    codex_record,
    gold_event,
    json_text,
    namespace,
    opaque,
    session_row,
    stable_priority,
)
from .replay import log_line
from .supplemental import case, freeze_family

DATASETS = {
    "state_train_replay": {
        "file": "state-bench.tgz",
        "revision": "5644b1838d96bc4483da29642d058ecaa6f80f7f",
        "sha256": "746646f24ab0ebd713ae28f0e96c1cc81cdbe9598171a2f7ed37953ce7a0b96a",
        "projection": "Four public training transcripts per domain, excluding system messages.",
    },
    "memoryarena_prefix": {
        "file": "memoryarena-travel.jsonl",
        "revision": "da1a37c8b19280e18627ca01cf368195a5e1d92e",
        "sha256": "2f955d444f6f3ad3c5da2064359ab19f8fc1f90621ff9d00723a450a009c3732",
        "projection": "Published base itinerary and earlier subtask prompts, "
        "without answer labels.",
    },
}
EPOCH = datetime(2026, 10, 1, tzinfo=timezone.utc)


def query_text(value):
    """Only normalize whitespace to respect the public single-line query contract."""
    return " ".join(value.split())


def proxy_case(family, scope, qid, stratum, question, native, events, **metadata):
    return (
        case(
            family,
            scope,
            qid,
            stratum,
            query_text(question),
            "primary",
            revision=DATASETS[family]["revision"],
        ),
        {
            "source_id": qid,
            "expect_abstain": False,
            "session_groups": [[native]],
            "event_groups": [[event] for event in events],
            "literal_turn_groups": [[event] for event in events],
            **metadata,
        },
    )


def state_session(turns, when):
    records = []
    final_pair = None
    call_number = 0
    for item in turns:
        role = item["role"]
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            recorded_at = when + timedelta(seconds=len(records))
            records.append(codex_record(role, content, recorded_at))
        for call in item.get("tool_calls") or []:
            call_number += 1
            identity = f"recorded-call-{call_number}"
            timestamp = (when + timedelta(seconds=len(records))).isoformat()
            data = tool(json_text(call["arguments"]), timestamp, identity)
            data["payload"]["name"] = call["name"]
            records.append(data)
            call_position = len(records)
            timestamp = (when + timedelta(seconds=len(records))).isoformat()
            records.append(tool(json_text(call["result"]), timestamp, identity, result=True))
            final_pair = call_position, len(records)
    return records, final_pair


def load_state(path, stream, add_case):
    family = "state_train_replay"
    groups = defaultdict(list)
    with tarfile.open(path) as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            # Read data members in place. Never extract or execute repository contents.
            if (
                member.isfile()
                and name.suffix == ".json"
                and "train_task_trajectories" in name.parts
            ):
                groups[name.parent.name].append(member)
        for domain, members in sorted(groups.items()):
            selection = sorted(members, key=lambda m: stable_priority(m.name))[:4]
            scope = namespace(family, domain)
            for ordinal, member in enumerate(selection):
                source_id = PurePosixPath(member.name).name
                native = opaque(scope["cluster"], "trajectory", source_id)
                with archive.extractfile(member) as saved:
                    conversation = json.load(saved)["conversation"]
                initial_request = next(
                    turn["content"] for turn in conversation if turn["role"] == "user"
                )
                records, pair = state_session(conversation, EPOCH + timedelta(days=ordinal))
                if not pair:
                    raise ValueError(
                        "Selected STATE training transcript has no recorded tool action"
                    )
                log_line(stream, session_row(scope, native, records))
                question = (
                    "For my earlier request below, what was the final tool action and its observed "
                    f"result? Earlier request: {query_text(initial_request)[:1600]}"
                )
                anchors = [gold_event(scope, native, index) for index in pair]
                add_case(*proxy_case(family, scope, source_id, domain, question, native, anchors))


def load_arena(path, stream, add_case):
    family = "memoryarena_prefix"
    with path.open() as source:
        rows = [json.loads(line) for line in source if line.strip()]
    for item in sorted(rows, key=lambda row: stable_priority(row["id"]))[:12]:
        identifier = str(item["id"])
        scope = namespace(family, identifier)
        native = opaque(scope["cluster"], "prior-travel")
        context = item["base_person"]
        # The upstream runner supplies these starting inputs as a single observation.
        # Answers to later subtasks never become native events.
        inputs = [
            f"Original request from {context['name']}: {context['query']}",
            f"Initial itinerary: {json_text(context['daily_plans'])}",
            *item["questions"][:-1],
        ]
        records = [
            codex_record("user", text, EPOCH + timedelta(days=offset))
            for offset, text in enumerate(inputs)
        ]
        log_line(stream, session_row(scope, native, records))
        historical = [gold_event(scope, native, offset) for offset in range(1, len(inputs) + 1)]
        add_case(
            *proxy_case(
                family,
                scope,
                identifier + "-authentic",
                "authentic_final_subtask_prefix",
                item["questions"][-1],
                native,
                historical,
                task_outcome_available=False,
            )
        )
        add_case(
            *proxy_case(
                family,
                scope,
                identifier + "-direct",
                "direct_initial_context",
                "Can you remember my original travel itinerary request and initial plan?",
                native,
                historical[:2],
                task_outcome_available=False,
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=sorted(DATASETS), required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load = load_state if args.family == "state_train_replay" else load_arena
    result = freeze_family(args.family, DATASETS[args.family], args.data, args.output, load)
    print(f"Froze {result['cases']} {args.family} history probes.")


if __name__ == "__main__":
    main()
