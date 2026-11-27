"""Synthetic engineering histories with independent gold anchors and control cases."""

import json
from datetime import datetime
from pathlib import Path

from services.agent_evidence_models import event_id

from .public_data import BASELINE, codex_record, file_sha256, uuid_for, write_private

ZONE = "America/New_York"
FROZEN_NOW = "2026-11-27T00:00:00-05:00"
WEEK = {"from_date": "2026-11-16", "through_date": "2026-11-22"}
NOVEMBER = {"from_date": "2026-11-01", "through_date": "2026-11-30"}


def recorded(value):
    return datetime.fromisoformat(value)


def msg(body, when, role="assistant"):
    return codex_record(role, body, recorded(when))


def claude(body, when, role="assistant"):
    return {"type": role, "timestamp": when, "message": {"content": body}}


def tool(command_or_result, when, call_id, *, result=False):
    data = (
        {"type": "function_call_output", "output": command_or_result}
        if result
        else {"type": "function_call", "name": "shell", "arguments": command_or_result}
    )
    return {"type": "response_item", "timestamp": when, "payload": {**data, "call_id": call_id}}


def label(key, record):
    return {"label": key, "record": record}


def session(folder, native, items, **options):
    return {"folder": folder, "native": native, "items": items, **options}


SESSIONS = [
    session(
        "cedar-client",
        "cache-linux",
        [
            label(
                "linux-request",
                msg(
                    "Can we avoid a full rebuild on the Linux job? Try using the layer cache.",
                    "2026-11-16T14:01:00Z",
                    "user",
                ),
            ),
            label(
                "linux-command",
                tool(
                    "Cedar cache reuse benchmark on linux-runner, cold vs warm",
                    "2026-11-16T14:02:00Z",
                    "bench-linux",
                ),
            ),
            label("linux-log-a", msg("Runner provisioned at 14:02.", "2026-11-16T14:03:00Z")),
            label("linux-log-b", msg("Waited for the checksum gate.", "2026-11-16T14:04:00Z")),
            label("linux-log-c", msg("The benchmark artifact is present.", "2026-11-16T14:05:00Z")),
            label(
                "linux-result",
                tool(
                    "linux-runner layer-cache run measured wall 2m11s warm versus 6m02s cold; "
                    "exit=0 and manifest hashes identical.",
                    "2026-11-16T14:06:00Z",
                    "bench-linux",
                    result=True,
                ),
            ),
        ],
    ),
    session(
        "cedar-client",
        "cache-mac",
        [
            label(
                "mac-request",
                msg(
                    "On macOS try persisting derived layers instead of rebuilding the binary.",
                    "2026-11-17T14:01:00Z",
                    "user",
                ),
            ),
            label(
                "mac-command",
                tool(
                    "Cedar incremental-compilation trial on local mac-runner",
                    "2026-11-17T14:02:00Z",
                    "bench-mac",
                ),
            ),
            label(
                "mac-result",
                tool(
                    "mac-runner reuse trial timed out after 9m; checksum mismatch, exit=1. "
                    "Full rebuild passed in 7m03s on this machine.",
                    "2026-11-17T14:03:00Z",
                    "bench-mac",
                    result=True,
                ),
            ),
            label(
                "mac-summary",
                msg(
                    "Linux cache reuse helped. macOS trial failed and is still open.",
                    "2026-11-17T14:04:00Z",
                ),
            ),
        ],
    ),
    session(
        "spruce-relay",
        "incident",
        [
            label(
                "incident-command",
                tool(
                    "SSE outage handover command: inspect relay counters",
                    "2026-11-12T22:00:00Z",
                    "relay-before",
                ),
            ),
            label(
                "incident-result",
                tool(
                    "SSE outage Nov 12: replay cursor lag confirmed at 243 seconds. "
                    "No remediation applied by this observation.",
                    "2026-11-12T22:02:00Z",
                    "relay-before",
                    result=True,
                ),
            ),
        ],
    ),
    session(
        "spruce-relay",
        "incident-followup",
        [
            label(
                "fix-command",
                tool(
                    "Check the SSE outage alert after applying the cursor checkpoint patch.",
                    "2026-11-17T15:11:00Z",
                    "relay-after",
                ),
            ),
            label(
                "fix-result",
                tool(
                    "SSE outage from Nov 12 is resolved. Monitor reports lag under 200ms "
                    "for ten canary requests on green; primary still has the old image.",
                    "2026-11-17T15:13:00Z",
                    "relay-after",
                    result=True,
                ),
            ),
            label(
                "real-deploy",
                tool(
                    "Observed production rollout SPRUCE_224 completed November 19. "
                    "Running image digest changed to the new cursor build; status=healthy.",
                    "2026-11-19T20:00:00Z",
                    "rollout-status",
                    result=True,
                ),
            ),
            label(
                "ci-blocked",
                tool(
                    "SPRUCE_224 CI workflow did not start. Billing permission blocked "
                    "test jobs before any runner was assigned.",
                    "2026-11-19T20:01:00Z",
                    "ci-status",
                    result=True,
                ),
            ),
            label(
                "ci-local",
                tool(
                    "SPRUCE_224 local relay unit suite: 48 passed, exit=0.",
                    "2026-11-19T20:02:00Z",
                    "unit-status",
                    result=True,
                ),
            ),
            label(
                "ci-sse",
                tool(
                    "SPRUCE_224 canary SSE checks: ten cursor replay requests passed.",
                    "2026-11-19T20:03:00Z",
                    "sse-status",
                    result=True,
                ),
            ),
        ],
    ),
    session(
        "spruce-relay",
        "rollout-rationale",
        [
            label(
                "rationale",
                claude(
                    "Cursor checkpointing was chosen because the reconnect token expired "
                    "after the relay lost its lease. Persisting the last acknowledged cursor "
                    "keeps replay inside the retention window.",
                    "2026-11-20T11:00:00Z",
                ),
            ),
        ],
        agent="claude_code",
    ),
    session(
        "cedar-client",
        "index-proposal",
        [
            label(
                "proposal",
                msg(
                    "Suggested HARBOUR_CUTOVER to compact the staging journal index. "
                    "No approval received. Await explicit sign-off before execution.",
                    "2026-11-18T10:12:00Z",
                ),
            ),
            label(
                "approval-rumor",
                msg(
                    "I think HARBOUR_CUTOVER was approved and is probably live. "
                    "I have not looked at the release gate.",
                    "2026-11-18T11:30:00Z",
                ),
            ),
            label(
                "approval-check",
                tool(
                    "HARBOUR_CUTOVER release gate owner decision: pending approval. "
                    "No execution job exists.",
                    "2026-11-18T11:35:00Z",
                    "gate-status",
                    result=True,
                ),
            ),
        ],
    ),
    session(
        "cedar-client",
        "journal-migration",
        [
            label(
                "merged",
                tool(
                    "MAPLE_MIGRATION PR #417 merge completed; Cedar adopted the new parser.",
                    "2026-11-19T16:35:00Z",
                    "merge",
                    result=True,
                ),
            ),
            label(
                "revert",
                tool(
                    "MAPLE_MIGRATION released parser caused a decoding regression in Spruce. "
                    "Revert PR #424 merged. Cedar returned to the original parser.",
                    "2026-11-28T16:35:00Z",
                    "revert",
                    result=True,
                ),
            ),
            label(
                "open",
                msg(
                    "MAPLE_MIGRATION stays open awaiting a decoder fix and cross-repo validation.",
                    "2026-11-30T21:15:00Z",
                ),
            ),
            label(
                "december-fix",
                tool(
                    "MAPLE_MIGRATION follow-up decoder fix approved and shipped on December 2. "
                    "The original incident occurred in November.",
                    "2026-12-02T15:49:00Z",
                    "later",
                    result=True,
                ),
            ),
        ],
    ),
    session(
        "spruce-relay",
        "provider-followup",
        [
            label(
                "downstream-blocked",
                claude(
                    "MAPLE_MIGRATION Cedar parser rollback left Spruce blocked at month end. "
                    "The same input fixture still fails decoding and awaits validation.",
                    "2026-11-30T20:10:00Z",
                ),
            ),
        ],
        agent="claude_code",
    ),
    session(
        "willow-tools",
        "original-only",
        [
            label(
                "original-only",
                tool(
                    "Willow original-only November 21 runtime validated the offline lease command. "
                    "Exit=0; artifact SHA matched original bytes.",
                    "2026-11-21T23:40:00Z",
                    "willow-check",
                    result=True,
                ),
            ),
        ],
    ),
    session(
        "cedar-client",
        "times",
        [
            label(
                "dst-first",
                msg(
                    "DST_EDGE first 01:30 local observation before the New York offset changed.",
                    "2026-11-01T01:30:00-04:00",
                ),
            ),
            label(
                "dst-second",
                msg(
                    "DST_EDGE second 01:30 local observation after the New York offset changed.",
                    "2026-11-01T01:30:00-05:00",
                ),
            ),
            label(
                "midnight-command",
                tool(
                    "MIDNIGHT_EDGE began checking the checksum before local midnight",
                    "2026-11-20T23:59:59-05:00",
                    "midnight-check",
                ),
            ),
            label(
                "midnight-result",
                tool(
                    "MIDNIGHT_EDGE checksum only observed after local midnight, exit=0.",
                    "2026-11-21T00:00:00-05:00",
                    "midnight-check",
                    result=True,
                ),
            ),
        ],
    ),
    session(
        "cedar-client",
        "times",
        [
            label(
                "boundary-exact",
                msg(
                    "EXACT_CUTOFF observed the checksum change at the cutoff.",
                    "2026-11-21T01:00:00.000000-05:00",
                ),
            ),
            label(
                "boundary-late",
                msg(
                    "EXACT_CUTOFF first later result arrived one microsecond after cutoff.",
                    "2026-11-21T01:00:00.000001-05:00",
                ),
            ),
        ],
        append=True,
    ),
    session(
        "willow-tools",
        "attachment",
        [
            label(
                "attachment-msg",
                msg(
                    "I saved the supplemental benchmark log as the attached report.",
                    "2026-11-22T13:05:00Z",
                ),
            ),
        ],
        attachments={"lab-output.txt": "fixture-only attachment: ATTACHMENT_AZUL_SECRETNEY\n"},
    ),
    session(
        "willow-tools",
        "deep",
        [
            label(
                "deep-record",
                msg(
                    ("Açaí 🐈 fixture detail. " * 410)
                    + " DEEP_AZURE checkpoint took 87 ms. "
                    + ("Continuation bytes preserved. " * 240),
                    "2026-11-22T14:22:00Z",
                ),
            ),
        ],
    ),
    session(
        "cedar-client",
        "owner-collision",
        [
            label(
                "scope-public",
                msg("SCOPE_COBALT Cedar workspace value is cobalt-31.", "2026-11-23T15:03:00Z"),
            ),
        ],
    ),
    session(
        "willow-tools",
        "sibling-collision",
        [
            label(
                "scope-sibling",
                msg("SCOPE_COBALT sibling workspace value is amber-87.", "2026-11-23T15:04:00Z"),
            ),
        ],
    ),
    session(
        "foreign-relay",
        "foreign-collision",
        [
            label(
                "scope-foreign",
                msg("SCOPE_COBALT other tenant value is quartz-52.", "2026-11-23T15:05:00Z"),
            ),
        ],
    ),
    session(
        "cedar-client",
        "active-parent",
        [
            label(
                "parent-context",
                msg("PARENT_NIMBUS parent started the packet audit.", "2026-11-25T12:00:00Z"),
            ),
        ],
    ),
    session(
        "cedar-client",
        "active-child",
        [
            label("inherit-mark", {"type": "session_meta", "payload": {"id": "active-parent"}}),
            label(
                "inherited",
                msg(
                    "CHILD_SHELL replayed prior transcript as inherited context.",
                    "2026-11-25T12:01:00Z",
                ),
            ),
            label("child-mark", {"type": "session_meta", "payload": {"id": "active-child"}}),
            label(
                "child-record",
                msg(
                    "CHILD_SHELL observed new worker retry once and then pass.",
                    "2026-11-25T12:03:00Z",
                ),
            ),
        ],
        parent="active-parent",
        root="active-parent",
    ),
    session(
        "birch-pending",
        "pending",
        [
            label(
                "pending-record",
                msg(
                    "PENDING_RILLO is committed but awaiting evidence parsing.",
                    "2026-11-26T12:50:00Z",
                ),
            ),
        ],
        index=False,
    ),
]

JOURNALS = [
    [
        "cedar-client",
        "cache-linux",
        "2026-11-16T14:15:00Z",
        "Observed Linux cache reuse with matching hashes. Local benchmark only.",
    ],
    [
        "cedar-client",
        "cache-mac",
        "2026-11-17T14:15:00Z",
        "The macOS derived-layer trial timed out. Rebuild remains the default there.",
    ],
    [
        "cedar-client",
        "index-proposal",
        "2026-11-18T11:00:00Z",
        "Proposed HARBOUR_CUTOVER. Approval pending.",
    ],
    [
        "cedar-client",
        "index-proposal",
        "2026-11-18T11:40:00Z",
        "Checked HARBOUR_CUTOVER gate. Confirmed approval still pending.",
    ],
    [
        "spruce-relay",
        "incident-followup",
        "2026-11-19T20:10:00Z",
        "Observed SPRUCE_224 live. Canary passed; CI jobs were billing-blocked.",
    ],
    [
        "cedar-client",
        "journal-migration",
        "2026-11-19T21:00:00Z",
        "MAPLE_MIGRATION merged on Cedar.",
    ],
    [
        "cedar-client",
        "journal-migration",
        "2026-11-28T17:00:00Z",
        "MAPLE_MIGRATION reverted after the Spruce decoder issue.",
    ],
    [
        "spruce-relay",
        "provider-followup",
        "2026-11-30T20:30:00Z",
        "MAPLE_MIGRATION downstream validation remains open in Spruce.",
    ],
    [
        "cedar-client",
        "journal-migration",
        "2026-11-30T21:30:00Z",
        "MAPLE_MIGRATION pending follow-up decoder correction.",
    ],
    [
        "cedar-client",
        "journal-migration",
        "2026-12-02T16:00:00Z",
        "MAPLE_MIGRATION correction shipped on December 2.",
    ],
]


def case(name, family, question, groups=(), *, forbidden=(), scope="active", **options):
    return {
        "query": {
            "case_id": name,
            "family": family,
            "question": question,
            "scope": scope,
            "filters": {"timezone": ZONE, **options.pop("filters", {})},
            **options,
        },
        "gold": {"groups": list(groups), "forbidden": list(forbidden)},
    }


CASES = [
    case(
        "weekly-work",
        "overview",
        "What did we work on last week across my repos?",
        filters=WEEK,
        overview=True,
    ),
    case(
        "weekly-shipped",
        "real-outcomes",
        "What did we actually ship last week across my repos?",
        [("real-deploy",)],
        forbidden=("december-fix",),
        filters=WEEK,
    ),
    case(
        "november-work",
        "overview",
        "What did we work on in November 2026 across my repos, and what was still open?",
        filters=NOVEMBER,
        overview=True,
        after_month_end=True,
    ),
    case(
        "month-end",
        "state-transition",
        "By the end of 2026-11-30 what had we verified and what was open after MAPLE_MIGRATION?",
        [("merged",), ("revert",), ("open", "downstream-blocked")],
        forbidden=("december-fix",),
        filters={"as_of": "2026-11-30"},
        latest=True,
        after_month_end=True,
    ),
    case(
        "ever-rebuild",
        "semantic-recall",
        "Have we ever tried avoiding a full rebuild? What happened on each machine?",
        [("linux-result",), ("mac-result",)],
    ),
    case(
        "ever-paraphrase",
        "semantic-recall",
        "Did we find a way to skip reprocessing unchanged components on different hosts?",
        [("linux-result",), ("mac-result",)],
    ),
    case(
        "ever-paraphrase-holdout",
        "semantic-recall",
        "Have we previously shortened repeat build jobs by retaining intermediate output?",
        [("linux-result",), ("mac-result",)],
        split="holdout",
    ),
    case(
        "ever-portuguese",
        "semantic-recall",
        "Já tentamos evitar uma compilação do zero? Qual foi o resultado em cada máquina?",
        [("linux-result",), ("mac-result",)],
    ),
    case(
        "trial-vs-ci",
        "real-outcomes",
        "Which SPRUCE_224 tests did we actually run, and did we ship to production?",
        [("real-deploy",), ("ci-blocked",), ("ci-local",), ("ci-sse",)],
    ),
    case(
        "incident-current",
        "date-routing",
        "Have we fixed the SSE outage from 2026-11-12?",
        [("incident-result",), ("fix-result",)],
        latest=True,
    ),
    case(
        "incident-as-of",
        "date-routing",
        "As of 2026-11-12, what had we verified about the SSE outage?",
        [("incident-result",)],
        forbidden=("fix-result", "real-deploy"),
        filters={"as_of": "2026-11-12"},
    ),
    case(
        "rationale-with-memory",
        "routing",
        "Remember why we chose cursor checkpointing?",
        [("rationale",)],
    ),
    case(
        "rationale-with-history",
        "routing",
        "What did we decide about cursor checkpointing and why?",
        [("rationale",)],
    ),
    case(
        "approval",
        "provenance",
        "Had we approved HARBOUR_CUTOVER?",
        [("approval-check",)],
        latest=True,
    ),
    case(
        "exact-boundary",
        "cutoff",
        "What did we observe for EXACT_CUTOFF?",
        [("boundary-exact",)],
        forbidden=("boundary-late",),
        filters={"as_of": "2026-11-21T01:00:00.000000-05:00"},
    ),
    case(
        "dst",
        "cutoff",
        "What did we observe for DST_EDGE on 2026-11-01?",
        [("dst-first",), ("dst-second",)],
        filters={"from_date": "2026-11-01", "through_date": "2026-11-01"},
    ),
    case(
        "midnight",
        "cutoff",
        "As of 2026-11-20, had we confirmed MIDNIGHT_EDGE?",
        [("midnight-command",)],
        forbidden=("midnight-result",),
        filters={"as_of": "2026-11-20"},
    ),
    case(
        "owner",
        "authorization",
        "What did we record about SCOPE_COBALT here?",
        [("scope-public",)],
        forbidden=("scope-sibling", "scope-foreign"),
        scope="cedar-client",
    ),
    case(
        "same-owner-other-repo",
        "authorization",
        "Did we record SCOPE_COBALT in willow-tools?",
        [("scope-sibling",)],
        forbidden=("scope-public", "scope-foreign"),
        filters={"folder": "willow-tools"},
    ),
    case(
        "other-owner",
        "authorization",
        "Have we recorded SCOPE_COBALT in foreign-relay?",
        forbidden=("scope-foreign", "scope-public", "scope-sibling"),
        filters={"folder": "foreign-relay"},
        expected_error="memory_folder_not_found_or_ambiguous",
    ),
    case(
        "pending",
        "availability",
        "Had we discussed PENDING_RILLO?",
        [("pending-record",)],
        scope="birch-pending",
        pending=True,
    ),
    case("absent", "abstention", "What did we verify about ZQ_HELIO_UNRECORDED?", absent=True),
    case(
        "attachment",
        "availability",
        "Had we read ATTACHMENT_AZUL_SECRETNEY?",
        absent=True,
        attachment=True,
        scope="willow-tools",
    ),
    case(
        "deep",
        "integrity",
        "What did we measure for DEEP_AZURE?",
        [("deep-record",)],
        continuation=True,
    ),
    case(
        "child",
        "integrity",
        "What had we found in CHILD_SHELL?",
        [("child-record",)],
        forbidden=("inherited",),
    ),
    case(
        "vendor-plus-original",
        "routing",
        "What does the vendor spec say about cursor replay, how does the code handle it, "
        "and did we test it?",
        [("ci-sse",)],
        external_controls=True,
        split="holdout",
    ),
]


def freeze_operational(output):
    output = Path(output)
    output.mkdir(mode=0o700)
    name = output.name
    owners = {key: uuid_for("operations", name, key) for key in ("owner", "foreign")}
    folders = {
        key: uuid_for("operations", name, key)
        for key in (
            "active",
            "foreign",
            "pending-root",
            "cedar-client",
            "spruce-relay",
            "willow-tools",
            "birch-pending",
            "foreign-relay",
        )
    }
    offsets = {}
    anchors = {}
    for capture in SESSIONS:
        folder, native = capture["folder"], capture["native"]
        origin = (folder, native)
        offset = offsets.get(origin, 0)
        for i, entry in enumerate(capture["items"], start=offset + 1):
            anchors[entry["label"]] = event_id(
                folders[folder], capture.get("agent", "codex"), native, "source", 1, i
            )
        offsets[origin] = offset + len(capture["items"])
    cases = [item["query"] for item in CASES]
    gold = {}
    for item in CASES:
        key = item["query"]["case_id"]
        gold[key] = {
            "required": [[anchors[label] for label in group] for group in item["gold"]["groups"]],
            "forbidden": [anchors[label] for label in item["gold"]["forbidden"]],
        }
    write_private(output / "queries.json", cases)
    write_private(output / "gold.json", {"cases": gold, "anchors": anchors})
    write_private(
        output / "sources.json",
        {
            "owners": owners,
            "folders": folders,
            "sessions": SESSIONS,
            "journals": JOURNALS,
        },
    )
    freeze = {
        "baseline": BASELINE,
        "cases": len(cases),
        "now": FROZEN_NOW,
        "sha256": {path.name: file_sha256(path) for path in sorted(output.iterdir())},
        "prefetch_routes": {"history": "real Kioku", "knowledge": "unavailable in lab"},
    }
    write_private(output / "freeze.json", freeze)
    return json.loads((output / "freeze.json").read_text())
