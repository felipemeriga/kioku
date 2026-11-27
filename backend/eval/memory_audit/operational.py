"""Replay engineering questions through the frozen native prefetch and memory tools."""

import argparse
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from psycopg.types.json import Jsonb
from starlette.testclient import TestClient

from services import evidence_prefetch
from services.agent_evidence import EvidenceStore
from services.agent_evidence_jobs import process_session
from services.agent_evidence_models import sha256
from services.agent_journal import sync_journal
from services.agent_memory_tools import execute_memory_tool

from .lab import Lab
from .operational_fixtures import FROZEN_NOW, ZONE, freeze_operational, msg
from .public_data import BASELINE, expansions, file_sha256, json_text, uuid_for, write_private
from .replay import SourceRecord, code, fixture_text, payload
from .score_public import distribution, score_groups


class AuditClock(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = datetime.fromisoformat(FROZEN_NOW)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


class MonthEndClock(AuditClock):
    @classmethod
    def now(cls, tz=None):
        instant = datetime.fromisoformat("2026-12-03T00:00:00-05:00")
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


def seed_journals(lab, owner, folders, journals):
    groups = defaultdict(list)
    for repo, native, captured_at, body in journals:
        groups[repo, captured_at[:10]].append((native, captured_at, body))
    receipts = []
    with lab.service_role():
        for (repo, day), entries in groups.items():
            markdown = f"# Kioku agent journal — {day}\n\n"
            for position, (native, captured_at, body) in enumerate(entries):
                metadata = {
                    "agent": "codex",
                    "id": f"audit-{day}-{position}",
                    "session_id": native,
                    "captured_at": captured_at,
                    "source_ref": "synthetic-native-corpus",
                }
                markdown += (
                    f"## {captured_at[11:16]} — archived operation\n"
                    f"<!-- kioku-entry: {json_text(metadata)} -->\n{body}\n\n"
                )
            receipt = sync_journal(
                lab,
                user_id=owner,
                folder_id=folders[repo],
                journal_date=day,
                markdown=markdown,
                base_revision=0,
                content_sha256=sha256(markdown.encode()),
            )
            if receipt["status"] != "ok":
                raise RuntimeError(f"Lab journal upload failed: {receipt['status']}")
            receipts.append((repo, day, entries))
    return receipts


def publish_weekly_report(lab, folder, owner, material):
    lab.pg.execute(
        "INSERT INTO watched_repos (user_id,folder_id,report_timezone) VALUES (%s,%s,%s)",
        [owner, folder, ZONE],
    )
    sources = [
        {
            "id": "observed",
            "kind": "original",
            "event_id": material["event_id"],
            "session_id": material["session_id"],
            "text": material["source"].text,
        }
    ]
    for i, summary in enumerate(
        (
            "Spruce roll-out was under review; confirm the health observation before release.",
            "Spruce production rollout was observed on November 19.",
        )
    ):
        preparation = uuid_for(folder, "period-report", i)
        snapshot = {
            "report": {
                "kind": "weekly",
                "period_start": "2026-11-16",
                "period_end": "2026-11-22",
                "timezone": ZONE,
                "cutoff": "2026-11-23T05:00:00Z",
                "status": "final" if i else "draft",
                "source_digest": sha256(summary.encode()),
                "coverage": {"lab": "observed"},
                "expected_revision": i,
            },
            "input": {"sources": sources},
        }
        value = {
            "title": "Spruce release review",
            "summary": summary,
            "summary_source_ids": ["observed"],
            "sections": [
                {
                    "heading": "What changed",
                    "items": [{"text": summary, "source_ids": ["observed"]}],
                }
            ],
        }
        lab.pg.execute(
            "INSERT INTO maintenance_preparations "
            "(id,user_id,folder_id,operation,snapshot,request) VALUES (%s,%s,%s,'reports',%s,'{}')",
            [preparation, owner, folder, Jsonb(snapshot)],
        )
        result = (
            lab.rpc(
                "apply_period_report_result",
                {
                    "p_preparation": preparation,
                    "p_user": owner,
                    "p_job": f"audit-{i}",
                    "p_value": value,
                },
            )
            .execute()
            .data
        )
        if result["revision"] != i + 1:
            raise RuntimeError("Lab report publication did not advance revisions")


def seed(lab, data):
    start = time.perf_counter()
    folders, owners = data["folders"], data["owners"]
    for owner in owners.values():
        lab.create_owner(owner)
    for key in ("active", "foreign", "pending-root"):
        lab.create_folder(folders[key], owners["foreign" if key == "foreign" else "owner"], key)
    for repo in ("cedar-client", "spruce-relay", "willow-tools", "birch-pending", "foreign-relay"):
        parent = {"birch-pending": "pending-root", "foreign-relay": "foreign"}.get(repo, "active")
        owner = owners["foreign" if parent == "foreign" else "owner"]
        lab.create_folder(folders[repo], owner, repo, folders[parent])
    materials = {}
    for item in data["sessions"]:
        repo, native = item["folder"], item["native"]
        owner = owners["foreign" if repo == "foreign-relay" else "owner"]
        options = {
            key: item[key] for key in ("agent", "parent", "root", "index", "append") if key in item
        }
        if item.get("attachments"):
            options["attachments"] = {
                path: value.encode() for path, value in item["attachments"].items()
            }
        records = [part["record"] for part in item["items"]]
        session_id, ids = lab.capture(owner, folders[repo], native, records, **options)
        byte_offset = 0
        offset_records = sum(
            part["native"] == native and part["repo"] == repo for part in materials.values()
        )
        for i, (part, eid) in enumerate(zip(item["items"], ids, strict=True), start=1):
            record = part["record"]
            raw = (json.dumps(record, ensure_ascii=False) + "\n").encode()
            materials[part["label"]] = {
                "event_id": eid,
                "session_id": session_id,
                "native": native,
                "repo": repo,
                "raw": raw,
                "original_record": record,
                "owner": owner,
                "folder": folders[repo],
                "source": SourceRecord(
                    f"segment-{offset_records + 1}",
                    byte_offset,
                    len(raw),
                    fixture_text(record, options.get("agent", "codex")),
                ),
            }
            byte_offset += len(raw)
    receipts = seed_journals(lab, owners["owner"], folders, data["journals"])
    publish_weekly_report(lab, folders["spruce-relay"], owners["owner"], materials["real-deploy"])
    return materials, receipts, (time.perf_counter() - start) * 1000


def summarize_result(response, source_by_id):
    matches = response.get("matches", [])
    evidence = response.get("evidence", [])
    repositories = {item["id"]: item["name"] for item in response.get("scope", [])}
    return {
        "status": response.get("status"),
        "code": code(response),
        "match_ids": [item["event_id"] for item in matches],
        "read_ids": [record["event_id"] for record in evidence],
        "byte_and_text_valid": sum(
            record["event_id"] in source_by_id
            and source_by_id[record["event_id"]].validates(record)
            for record in evidence
        ),
        "total_matches": response.get("total_matches"),
        "has_more": response.get("has_more"),
        "pending_objects": response.get("index_pending_objects"),
        "time_scope": response.get("time_scope"),
        "unmatched_identifiers": response.get("unmatched_identifiers"),
        "inventory_complete": response.get("inventory_complete"),
        "overview_journal_days": [
            [
                d.get("repository") or repositories.get(d["folder_id"]),
                d["session_id"],
                d["date"],
                d["entry_count"],
            ]
            for d in (response.get("activity") or {}).get("days", [])
        ],
        "overview_original_days": [
            [d["repository"], d["native_session_id"], d["date"], d["event_count"]]
            for d in response.get("original_activity", [])
        ],
        "period_report_revisions": [
            [report["kind"], report["revision"], report.get("orientation_only")]
            for report in response.get("period_reports", [])
        ],
    }


def focused_read(execute, match, before=1, after=1, limit=4000):
    return execute(
        "read_agent_evidence",
        {
            "reference": match["reference"],
            "before_records": before,
            "after_records": after,
            "char_limit": limit,
        },
    )


def run_case(lab, data, case, source_by_id):
    owner = data["owners"]["owner"]
    folders = data["folders"]
    with lab.tools(owner, folders[case["scope"]]) as mcp:
        allowed = mcp._descendant_folder_ids(lab, folders[case["scope"]], owner)
        rows = (
            lab.table("folders")
            .select("id,name")
            .eq("user_id", owner)
            .in_("id", allowed)
            .execute()
            .data
        )

        def execute(tool_name, args):
            if tool_name == "knowledge_base_search":
                return json_text({"status": "unavailable", "code": "knowledge_not_seeded"})
            return execute_memory_tool(lab, tool_name, args, owner, allowed)

        direct = []
        arms = ("overview",) if case.get("overview") else ("relevance", "chronological", "expanded")
        if case.get("latest"):
            arms += ("latest",)
        for arm in arms:
            order = (
                "chronological" if arm == "overview" else "relevance" if arm == "expanded" else arm
            )
            kwargs = {
                "query": "" if arm == "overview" else case["question"],
                "order": order,
                **case["filters"],
            }
            if arm == "overview":
                kwargs["projection"] = "overview"
            if arm == "expanded":
                kwargs["queries"] = expansions(case["question"])
            first, elapsed, size = payload(execute, tool_name="search_agent_history", args=kwargs)
            observations = summarize_result(first, source_by_id)
            reads = []
            if arm != "overview":
                contexts = {}
                for match in first.get("matches", []):
                    contexts.setdefault(match["native_session_id"], match)
                    if len(contexts) == 2:
                        break
                for context in contexts.values():
                    started = time.perf_counter()
                    read = json.loads(focused_read(execute, context))
                    reads.append(
                        {
                            **summarize_result(read, source_by_id),
                            "ms": (time.perf_counter() - started) * 1000,
                        }
                    )
            direct.append(
                {"arm": arm, "ms": elapsed, "bytes": size, **observations, "reads": reads}
            )
        started = time.perf_counter()
        clock = MonthEndClock if case.get("after_month_end") else AuditClock
        with patch.object(evidence_prefetch, "datetime", clock):
            raw, calls = evidence_prefetch.prefetch(case["question"], ZONE, execute, folders=rows)
        parsed = json.loads(raw)
        prefetched = {
            "route": calls[0]["name"] if calls else None,
            "coverage": parsed.get("source") or parsed.get("code"),
            "calls": [
                {**summarize_result(json.loads(call["result"]), source_by_id), "tool": call["name"]}
                for call in calls
            ],
            "ms": (time.perf_counter() - started) * 1000,
            "bytes": len(raw.encode()),
        }
    return {
        "case_id": case["case_id"],
        "family": case["family"],
        "direct": direct,
        "prefetch": prefetched,
    }


def auth_http_control(lab, scopes, anchor):
    owner, active = scopes["owners"]["owner"], scopes["folders"]["active"]
    first_key = lab.create_api_key(owner, active)
    sibling_key = lab.create_api_key(owner, scopes["folders"]["willow-tools"])
    foreign_key = lab.create_api_key(scopes["owners"]["foreign"], scopes["folders"]["foreign"])

    def post(client, key, method, params, transaction, session=None):
        headers = {"Accept": "application/json, text/event-stream"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if session:
            headers["Mcp-Session-Id"] = session
            headers["Mcp-Protocol-Version"] = "2025-03-26"
        request = {"jsonrpc": "2.0", "method": method, "params": params}
        if transaction is not None:
            request["id"] = transaction
        return client.post("/mcp", json=request, headers=headers)

    def parse(response):
        line = next((line for line in response.text.splitlines() if line.startswith("data:")), None)
        rpc_message = json.loads(line.removeprefix("data:")) if line else response.json()
        return json.loads(rpc_message["result"]["content"][0]["text"])

    init = {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "memory-audit", "version": "1"},
    }
    query = {"name": "search_agent_history", "arguments": {"query": "SCOPE_COBALT"}}
    with (
        lab.tools(owner, active) as mcp,
        TestClient(mcp.build_app(), base_url="http://127.0.0.1") as client,
    ):
        none = post(client, None, "initialize", init, 1)
        invalid = post(client, "invalid-audit-key", "initialize", init, 1)
        first = post(client, first_key, "initialize", init, 1)
        sid = first.headers.get("Mcp-Session-Id")
        if not sid:
            return {
                "missing_key": none.status_code,
                "invalid_key": invalid.status_code,
                "initialize": first.status_code,
                "status": "no_mcp_session",
            }
        post(client, first_key, "notifications/initialized", {}, None, sid)
        search = post(client, first_key, "tools/call", query, 2, sid)
        sibling = post(client, sibling_key, "tools/call", query, 3, sid)
        foreign = post(client, foreign_key, "tools/call", query, 4, sid)
        visible = parse(search)
        match = next(item for item in visible["matches"] if item["event_id"] == anchor["event_id"])
        args = {"name": "read_agent_evidence", "arguments": {"reference": match["reference"]}}
        read = post(client, first_key, "tools/call", args, 5, sid)
        own = post(client, foreign_key, "initialize", init, 6)
        foreign_sid = own.headers["Mcp-Session-Id"]
        post(client, foreign_key, "notifications/initialized", {}, None, foreign_sid)
        denied = post(client, foreign_key, "tools/call", args, 7, foreign_sid)
        return {
            "missing_key": none.status_code,
            "invalid_key": invalid.status_code,
            "initialize": first.status_code,
            "search": search.status_code,
            "usable_matches": len(visible["matches"]),
            "forbidden_sibling_session": sibling.status_code,
            "forbidden_other_owner_session": foreign.status_code,
            "same_owner_read": code(parse(read)),
            "foreign_scope_read": code(parse(denied)),
        }


def late_import(lab, owner, active):
    folder = uuid_for(active, "late-import")
    native = "late-import"
    lab.create_folder(folder, owner, "late-import", active)
    _, first = lab.capture(
        owner,
        folder,
        native,
        [
            msg("LATE_IMPORT inspection A recorded at 09:00.", "2026-11-26T09:00:00-05:00"),
        ],
    )
    filters = {"timezone": ZONE, "as_of": "2026-11-26T10:00:00-05:00"}
    with lab.tools(owner, folder) as mcp:
        first_search = json.loads(mcp.search_agent_history("LATE_IMPORT", **filters))
        match = first_search["matches"][0]
        first_read = json.loads(mcp.read_agent_evidence(match["reference"]))
    _, later = lab.capture(
        owner,
        folder,
        native,
        [
            msg("LATE_IMPORT inspection B recorded before cutoff.", "2026-11-26T09:20:00-05:00"),
            msg("LATE_IMPORT observation C recorded after cutoff.", "2026-11-26T11:00:00-05:00"),
        ],
        append=True,
    )
    with lab.tools(owner, folder) as mcp:
        second_read = json.loads(mcp.read_agent_evidence(match["reference"], after_records=3))
        second_search = json.loads(mcp.search_agent_history("LATE_IMPORT", **filters))
    before = {row["event_id"] for row in first_read["evidence"]}
    after = {row["event_id"] for row in second_read["evidence"]}
    search = {row["event_id"] for row in second_search["matches"]}
    return {
        "original_initially_resolved": first[0] in before,
        "pre_cutoff_late_record_after_first_signing": later[0] not in before and later[0] in after,
        "pre_cutoff_late_record_now_searchable": later[0] in search,
        "post_cutoff_hidden_from_both": later[1] not in after | search,
    }


def controls(lab, data, materials):
    owner, folders = data["owners"]["owner"], data["folders"]
    scores = {}
    with lab.tools(owner, folders["active"]) as mcp:
        expected = materials["linux-command"]["event_id"]
        paired = materials["linux-result"]["event_id"]
        picked = json.loads(
            mcp.search_agent_history(
                "Cedar cache reuse benchmark", folder="cedar-client", order="relevance"
            )
        )
        center = next(match for match in picked["matches"] if match["event_id"] == expected)
        one = json.loads(
            mcp.read_agent_evidence(center["reference"], before_records=0, after_records=0)
        )
        scores["tool_pair_without_neighbors"] = paired in {
            row["event_id"] for row in one["evidence"]
        }
        scores["roles_provenance"] = {
            row["event_type"]: row["provenance"] for row in one["evidence"]
        }
        tamper = center["reference"][:-1] + ("a" if center["reference"][-1] != "a" else "b")
        scores["tampered_reference"] = code(json.loads(mcp.read_agent_evidence(tamper)))
        overview = json.loads(
            mcp.search_agent_history(
                "",
                projection="overview",
                from_date="2026-11-16",
                through_date="2026-11-22",
                timezone=ZONE,
            )
        )
        report = overview["period_reports"][0]
        expanded_report = json.loads(mcp.read_agent_evidence(report["reference"]))
        report_sources = expanded_report["period_reports"][0]["sources"]
        report_original = json.loads(mcp.read_agent_evidence(report_sources[0]["reference"]))
        scores["report_locator"] = {
            "revision": report["revision"],
            "source_reads": len(report_sources),
            "original_roundtrip": materials["real-deploy"]["event_id"]
            in {row["event_id"] for row in report_original["evidence"]},
        }
        journal = overview["activity"]["days"][-1]
        journal_value = json.loads(mcp.read_agent_evidence(journal["reference"]))
        scores["journal_locator"] = {
            "status": journal_value["status"],
            "kind": journal_value["source_kind"],
            "evidence_provenance": journal_value["evidence"][0]["provenance"],
        }
        deep = materials["deep-record"]
        found = json.loads(mcp.search_agent_history("DEEP_AZURE", folder="willow-tools", limit=1))
        reference = found["matches"][0]["reference"]
        original_reference = reference
        fragments = []
        pages = 0
        while reference and pages < 25:
            evidence = json.loads(
                mcp.read_agent_evidence(
                    reference,
                    before_records=0,
                    after_records=0,
                    char_limit=1000,
                )
            )["evidence"][0]
            fragments.append((evidence["char_start"], evidence["excerpt"]))
            reference = evidence["next_reference"]
            pages += 1
        scores["deep_continuation"] = {
            "pages": pages,
            "complete": reference is None
            and "".join(x[1] for x in fragments) == deep["source"].text[fragments[0][0] :],
            "offset": fragments[0][0],
            "raw_roundtrip": EvidenceStore(lab, owner, deep["folder"]).event_raw(
                deep["session_id"],
                {"object_id": "segment-1", "byte_offset": 0, "byte_length": len(deep["raw"])},
            )
            == deep["raw"],
        }
        deep_store = EvidenceStore(lab, owner, deep["folder"])
        obj = deep_store.object(deep["session_id"], "segment-1")
        bucket = lab.bucket("agent-evidence")
        object_path = obj["storage_path"]
        stored_bytes = bucket.download(object_path)
        try:
            bucket.upload(object_path, b"damaged fixture", {"upsert": "true"})
            failure = json.loads(mcp.read_agent_evidence(original_reference))
            scores["integrity_fault"] = code(failure)
        finally:
            bucket.upload(object_path, stored_bytes, {"upsert": "true"})
        attachment = materials["attachment-msg"]
        store = EvidenceStore(lab, owner, attachment["folder"])
        attachments = store.attachments(attachment["session_id"], attachment["event_id"])
        attached = store.download(store.object(attachment["session_id"], attachments[0]["id"]))
        scores["attachment_retention"] = {
            "count": len(attachments),
            "sha256_match": sha256(attached) == attachments[0]["sha256"],
        }
    scores["http_auth"] = auth_http_control(lab, data, materials["scope-public"])
    scores["late_import"] = late_import(lab, owner, folders["active"])
    pending = materials["pending-record"]
    before = lab.index_state(owner, pending["folder"])
    with lab.service_role():
        process_session(
            lab,
            {
                "user_id": owner,
                "folder_id": pending["folder"],
                "id": pending["session_id"],
            },
        )
    after = lab.index_state(owner, pending["folder"])
    with lab.tools(owner, pending["folder"]) as mcp:
        recovered = json.loads(mcp.search_agent_history("PENDING_RILLO"))
    scores["pending_recovery"] = {
        "before": before,
        "after": after,
        "found_after_index": pending["event_id"]
        in {item["event_id"] for item in recovered["matches"]},
    }
    return scores


def replay(lab, directory):
    manifest = json.loads((directory / "freeze.json").read_text())
    if manifest["baseline"] != BASELINE:
        raise ValueError("Operational manifest changed release")
    for key in ("sources.json", "queries.json"):
        if file_sha256(directory / key) != manifest["sha256"][key]:
            raise ValueError("Operational inputs changed after freeze")
    data = json.loads((directory / "sources.json").read_text())
    cases = json.loads((directory / "queries.json").read_text())
    materials, receipts, ingestion_ms = seed(lab, data)
    source_by_id = {m["event_id"]: m["source"] for m in materials.values()}
    rows = [run_case(lab, data, case, source_by_id) for case in cases]
    try:
        measurements = controls(lab, data, materials)
    except Exception as exc:
        logging.getLogger(__name__).exception("Operational controls stopped")
        measurements = {"completed": False, "error": type(exc).__name__}
    return {
        "gold_sha256": manifest["sha256"]["gold.json"],
        "cases": rows,
        "controls": measurements,
        "ingest_ms": ingestion_ms,
        "journal_days": len(receipts),
        "source_records": len(materials),
    }


def grade(directory, raw):
    if raw["gold_sha256"] != file_sha256(directory / "gold.json"):
        raise ValueError("Scoring labels changed after freeze")
    labels = json.loads((directory / "gold.json").read_text())["cases"]
    cases = {case["case_id"]: case for case in json.loads((directory / "queries.json").read_text())}
    output = []
    for item in raw["cases"]:
        gold = labels[item["case_id"]]
        result = {"case_id": item["case_id"], "family": item["family"], "arms": {}}
        case = cases[item["case_id"]]
        for key, calls in [
            *((arm["arm"], [arm, *arm["reads"]]) for arm in item["direct"]),
            ("prefetch", item["prefetch"]["calls"]),
        ]:
            search_hits = list(
                dict.fromkeys(event for call in calls for event in call["match_ids"])
            )
            read_hits = list(dict.fromkeys(event for call in calls for event in call["read_ids"]))
            combined = list(dict.fromkeys(search_hits + read_hits))
            forbidden = bool(set(combined).intersection(gold["forbidden"]))
            finding = score_groups(combined, gold["required"], len(combined))
            result["arms"][key] = {
                "calls": len(calls),
                "codes": [c["code"] for c in calls],
                "search_hits": len(search_hits),
                "originals_returned": len(read_hits),
                "forbidden_hit": forbidden,
                "required": finding,
                "required_groups": len(gold["required"]),
            }
            first = calls[0] if calls else {}
            if case.get("overview"):
                result["arms"][key]["inventory"] = {
                    "complete_flag": first.get("inventory_complete"),
                    "journal_days": len(first.get("overview_journal_days", [])),
                    "original_days": len(first.get("overview_original_days", [])),
                    "original_repositories": sorted(
                        {value[0] for value in first.get("overview_original_days", [])}
                    ),
                    "any_original_only_repository": any(
                        value[0] == "willow-tools"
                        for value in first.get("overview_original_days", [])
                    ),
                    "published_reports": first.get("period_report_revisions", []),
                    "bounds": first.get("time_scope"),
                }
            if case.get("expected_error"):
                result["arms"][key]["expected_error"] = first.get("code") == case["expected_error"]
            if case.get("pending"):
                result["arms"][key]["pending_objects"] = first.get("pending_objects")
            if case.get("absent"):
                result["arms"][key]["unmatched_identifiers"] = first.get("unmatched_identifiers")
        result["prefetch_route"] = item["prefetch"]["route"]
        output.append(result)
    return {
        "cases": output,
        "controls": raw["controls"],
        "case_count": len(output),
        "journal_days": raw["journal_days"],
        "source_records": raw["source_records"],
        "ingest_ms": raw["ingest_ms"],
        "prefetch_ms": distribution(item["prefetch"]["ms"] for item in raw["cases"]),
        "direct_search_ms": distribution(
            row["ms"] for item in raw["cases"] for row in item["direct"]
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "replay", "score"))
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        manifest = freeze_operational(args.frozen)
        print(f"Froze {manifest['cases']} operational cases.")
    elif args.phase == "replay":
        lab = Lab(args.lab)
        try:
            result = replay(lab, args.frozen)
            write_private(args.result, result)
            print(f"Replayed {len(result['cases'])} operational cases.")
        finally:
            lab.close()
    else:
        result = grade(args.frozen, json.loads(args.result.read_text()))
        write_private(args.summary, result)
        print(f"Scored {result['case_count']} operational cases.")


if __name__ == "__main__":
    main()
