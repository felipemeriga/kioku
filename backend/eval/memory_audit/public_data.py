"""Freeze public benchmark corpora and independent retrieval labels as private files."""

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import ijson

from services.agent_evidence_models import event_id

from .lab import MIGRATION_DIRECTORY

BASELINE = "3636866fc7094606cc1e498ad79eaf3840d72f99"
SEED = "kioku-memory-20261127"
DATASETS = {
    "longmemeval_s": {
        "file": "longmemeval_s_cleaned.json",
        "revision": "98d7416c24c778c2fee6e6f3006e7a073259d48f",
        "sha256": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
    },
    "locomo": {
        "file": "locomo10.json",
        "revision": "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376",
        "sha256": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
    },
}
ARMS = {
    "literal": {"order": "relevance", "limit": 50},
    "product": {"order": "chronological", "limit": 10},
    "expanded": {"order": "relevance", "limit": 50},
}
READ_WINDOW = {"before_records": 1, "after_records": 1, "char_limit": 4000}
READ_COUNT = 2

# Frozen generic related forms, taken only from words present in the question.
# PostgreSQL already performs stemming. This deliberately small policy measures
# a deterministic caller, with no access to examples, corpus text or labels.
RELATED = {
    "bought": ("purchase", "buy"),
    "purchase": ("bought", "buy", "paid"),
    "cost": ("price", "paid", "expense"),
    "quit": ("resigned", "left", "departed"),
    "moved": ("relocated", "transferred"),
    "decided": ("chose", "selected", "plan"),
    "recommend": ("suggest", "advise"),
    "children": ("kids", "son", "daughter"),
    "vacation": ("holiday", "trip", "travel"),
    "finished": ("completed", "done"),
    "wedding": ("marriage", "married"),
    "birthday": ("born", "birthdate"),
    "work": ("job", "employment"),
    "attempt": ("tried", "experiment"),
    "tested": ("trial", "verification"),
    "fixed": ("resolved", "patched"),
    "outage": ("incident", "downtime"),
    "shipped": ("released", "deployed"),
    "reverted": ("rolled back", "undid"),
    "rebuild": ("cached", "reuse", "incremental"),
    "tentamos": ("tried", "experiment"),
    "corrigimos": ("fixed", "resolved"),
}


def expansions(question):
    """Only the literal question can influence the reformulated query."""
    words = dict.fromkeys(re.findall(r"[^\W_]+", question.casefold()))
    return [" ".join(RELATED[word]) for word in words if word in RELATED][:8]


def file_sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def opaque(*parts):
    value = "\0".join((SEED, *map(str, parts)))
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def uuid_for(*parts):
    return str(uuid5(NAMESPACE_URL, "kioku-memory-audit:" + opaque(*parts)))


def stable_priority(source_id):
    return hashlib.sha256(f"{SEED}:{source_id}".encode()).hexdigest()


def json_text(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_private(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json_text(data) + "\n")


def codex_record(role, content, entered_at):
    return {
        "type": "response_item",
        "timestamp": entered_at.isoformat(),
        "payload": {"type": "message", "role": role, "content": content},
    }


def namespace(family, external_id):
    cluster = opaque(family, external_id)
    return {
        "cluster": cluster,
        "owner": uuid_for(family, external_id, "owner"),
        "root": uuid_for(family, external_id, "root"),
        "folder": uuid_for(family, external_id, "repo"),
    }


def meta(family, scope, source_id, stratum, question, split, **filters):
    return {
        **scope,
        "case_id": opaque(family, source_id, "case"),
        "question": question,
        "family": family,
        "stratum": stratum,
        "split": split,
        "dataset_revision": DATASETS[family]["revision"],
        "role_partition": "both",
        "filters": {"timezone": "UTC", **filters},
    }


def session_row(scope, native, records):
    return {"scope": scope, "native": native, "records": records}


def gold_event(scope, native, turn_number):
    return event_id(scope["folder"], "codex", native, "source", 1, turn_number)


def longmem_rows(path):
    with path.open("rb") as stream:
        yield from ijson.items(stream, "item")


def select_longmem(path, primary_per_type, holdout_per_type):
    strata = defaultdict(list)
    for row in longmem_rows(path):
        source_id = row["question_id"]
        key = "abstention" if source_id.endswith("_abs") else row["question_type"]
        strata[key].append(source_id)
    selected = {}
    for stratum, population in sorted(strata.items()):
        ranked = sorted(population, key=stable_priority)
        for source_id in ranked[:primary_per_type]:
            selected[source_id] = (stratum, "primary")
        stop = len(ranked) if stratum == "abstention" else primary_per_type + holdout_per_type
        for source_id in ranked[primary_per_type:stop]:
            selected[source_id] = (stratum, "holdout")
    return selected


def freeze_longmem(path, add_case, add_session, primary_per_type, holdout_per_type):
    family = "longmemeval_s"
    selected = select_longmem(path, primary_per_type, holdout_per_type)
    date_format = "%Y/%m/%d (%a) %H:%M"
    for row in longmem_rows(path):
        source_id = row["question_id"]
        if source_id not in selected:
            continue
        stratum, split = selected[source_id]
        scope = namespace(family, source_id)
        case = meta(family, scope, source_id, stratum, row["question"], split)
        question_at = datetime.strptime(row["question_date"], date_format).replace(
            tzinfo=timezone.utc
        )
        native_by_source = defaultdict(list)
        positive_by_source = defaultdict(list)
        count_after_question = 0
        for i, (sid, when, turns) in enumerate(
            zip(
                row["haystack_session_ids"],
                row["haystack_dates"],
                row["haystack_sessions"],
                strict=True,
            )
        ):
            native = opaque(scope["cluster"], "session", i)
            native_by_source[sid].append(native)
            entered_at = datetime.strptime(when, date_format).replace(tzinfo=timezone.utc)
            count_after_question += entered_at > question_at
            records = []
            for j, turn in enumerate(turns):
                # Within-session microseconds preserve up to hundreds of turns
                # without manufacturing a different minute, day or month.
                records.append(
                    codex_record(
                        turn["role"], turn["content"], entered_at + timedelta(microseconds=j)
                    )
                )
                if turn.get("has_answer"):
                    positive_by_source[sid].append(gold_event(scope, native, j + 1))
            add_session(family, session_row(scope, native, records))
        is_abstention = stratum == "abstention"
        positives = [] if is_abstention else list(dict.fromkeys(row["answer_session_ids"]))
        session_groups = [native_by_source[sid] for sid in positives]
        event_groups = [positive_by_source[sid] for sid in positives]
        add_case(
            case,
            {
                "source_id": source_id,
                "upstream_stratum": row["question_type"],
                "answer": row["answer"],
                "question_at": question_at.isoformat(),
                "later_source_sessions": count_after_question,
                "session_groups": session_groups,
                "event_groups": event_groups,
                "literal_turn_groups": [[event] for group in event_groups for event in group],
                "expect_abstain": is_abstention,
                "distractor_sessions": [
                    native for sid in row["answer_session_ids"] for native in native_by_source[sid]
                ]
                if is_abstention
                else [],
            },
        )


def locomo_slot(key):
    return int(key.split("_")[1])


def freeze_locomo(path, add_case, add_session, primary_per_dialogue_category):
    family = "locomo"
    for row in json.loads(path.read_text()):
        dialogue_id = row["sample_id"]
        dialogue = row["conversation"]
        scope = namespace(family, dialogue_id)
        anchors = {}
        duplicate_anchors = defaultdict(list)
        captioned = set()
        session_fields = sorted(
            (key for key in dialogue if re.fullmatch(r"session_\d+", key)),
            key=locomo_slot,
        )
        for key in session_fields:
            native = opaque(scope["cluster"], "session", locomo_slot(key))
            when = datetime.strptime(dialogue[key + "_date_time"], "%I:%M %p on %d %B, %Y")
            base = when.replace(tzinfo=timezone.utc)
            records = []
            for i, turn in enumerate(dialogue[key]):
                speaker = turn["speaker"]
                role = "user" if speaker == dialogue["speaker_a"] else "assistant"
                records.append(
                    codex_record(
                        role, speaker + ": " + turn["text"], base + timedelta(microseconds=i)
                    )
                )
                label = turn["dia_id"]
                if turn.get("blip_caption"):
                    captioned.add(label)
                claim = (native, gold_event(scope, native, i + 1))
                if label in anchors:
                    duplicate_anchors[label].append(claim)
                else:
                    anchors[label] = claim
            add_session(family, session_row(scope, native, records))
        strata = defaultdict(list)
        for position, item in enumerate(row["qa"]):
            strata[item["category"]].append((f"{dialogue_id}:{position}", item))
        for category, population in sorted(strata.items()):
            ranked = sorted(population, key=lambda item: stable_priority(item[0]))
            for rank, (source_id, item) in enumerate(ranked):
                split = "primary" if rank < primary_per_dialogue_category else "holdout"
                case = meta(
                    family, scope, source_id, f"category_{category}", item["question"], split
                )
                is_adversarial = category == 5
                keys = list(dict.fromkeys(item.get("evidence", [])))
                policy_keys = [] if is_adversarial else keys
                event_groups = []
                session_groups = []
                for pointer in policy_keys:
                    matching = (
                        [anchors[pointer], *duplicate_anchors[pointer]]
                        if pointer in anchors
                        else []
                    )
                    event_groups.append([eid for _, eid in matching])
                    sessions = list(dict.fromkeys(sid for sid, _ in matching))
                    if sessions not in session_groups:
                        session_groups.append(sessions)
                add_case(
                    case,
                    {
                        "source_id": source_id,
                        "answer": item.get("answer"),
                        "expect_abstain": is_adversarial,
                        "session_groups": session_groups,
                        "event_groups": event_groups,
                        "literal_turn_groups": event_groups,
                        "literal_pointer_count": len(keys),
                        "captioned_pointers": sum(pointer in captioned for pointer in keys),
                        "unresolved_pointers": [
                            pointer for pointer in keys if pointer not in anchors
                        ],
                        "distractor_events": [
                            anchors[pointer][1] for pointer in keys if pointer in anchors
                        ]
                        if is_adversarial
                        else [],
                    },
                )


def freeze_public(data_dir, output, *, long_primary=10, long_holdout=6, locomo_primary=4):
    """Write separate corpus, query-only cases and scorer-only gold, then hash them."""
    output = Path(output)
    data_dir = Path(data_dir)
    if any(value < 1 for value in (long_primary, long_holdout, locomo_primary)):
        raise ValueError("All sampling counts must be positive")
    for spec in DATASETS.values():
        if file_sha256(data_dir / spec["file"]) != spec["sha256"]:
            raise ValueError("Benchmark file differs from its pinned revision")
    # All benchmark content, including public-derived fixtures, stays outside Git.
    if output.resolve().is_relative_to(MIGRATION_DIRECTORY.parents[1]):
        raise ValueError("Audit data must stay outside the worktree")
    output.mkdir(mode=0o700, parents=False)
    cases = []
    gold = {}
    corpora = {}

    def add_case(case, labels):
        cases.append(case)
        gold[case["case_id"]] = labels

    def add_session(family, session):
        corpora[family].write(json_text(session) + "\n")

    try:
        for family in DATASETS:
            fd = os.open(output / f"{family}.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            corpora[family] = os.fdopen(fd, "w")
        freeze_longmem(
            data_dir / DATASETS["longmemeval_s"]["file"],
            add_case,
            add_session,
            long_primary,
            long_holdout,
        )
        freeze_locomo(data_dir / DATASETS["locomo"]["file"], add_case, add_session, locomo_primary)
    finally:
        for stream in corpora.values():
            stream.close()
    write_private(output / "queries.json", cases)
    write_private(output / "gold.json", gold)
    manifest = {
        "baseline": BASELINE,
        "seed": SEED,
        "datasets": DATASETS,
        "cases": len(cases),
        "sampling": {
            "long_primary_per_type": long_primary,
            "long_holdout_per_type": long_holdout,
            "locomo_primary_per_dialogue_category": locomo_primary,
        },
        "projections": {
            "longmemeval_s": "complete haystacks, both roles, no question-date cutoff",
            "locomo": "all dialogues, speaker-labeled turn text, caption/URL/image data omitted",
            "timestamps": "naive source session times treated as UTC, microseconds preserve order",
        },
        "policy": {
            "arms": ARMS,
            "related": RELATED,
            "read_window": READ_WINDOW,
            "reads": READ_COUNT,
        },
        "sha256": {path.name: file_sha256(path) for path in sorted(output.iterdir())},
    }
    write_private(output / "freeze.json", manifest)
    return manifest
