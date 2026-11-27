"""Exercise native citation links, accent retrieval, and journal inventory limits."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from services.agent_memory_tools import execute_memory_tool
from services.citations import CitationRegistry

from .lab import Lab
from .operational import seed_journals
from .operational_fixtures import msg
from .public_data import BASELINE, uuid_for, write_private
from .replay import code


def evidence_citations(lab, operations):
    owner = operations["owners"]["owner"]
    folder = operations["folders"]["spruce-relay"]
    registry = CitationRegistry()
    with lab.tools(owner, folder):
        result = json.loads(
            execute_memory_tool(
                lab,
                "search_agent_history",
                {"query": "SPRUCE_224", "order": "relevance", "limit": 3},
                owner,
                [folder],
                citations=registry,
            )
        )
        match = result["matches"][0]
        expanded = json.loads(
            execute_memory_tool(
                lab,
                "read_agent_evidence",
                {"reference": match["reference"]},
                owner,
                [folder],
                citations=registry,
            )
        )
    citations = registry.entries()
    index = {item["number"]: item for item in citations}

    def correct(record, session):
        token = record.get("citation") or ""
        if not (token[1:-1].isdecimal() and token.startswith("[") and token.endswith("]")):
            return False
        entry = index[int(token[1:-1])]
        url = urlsplit(entry.get("url") or "")
        return (
            url.path == f"/folders/{folder}/agent-sessions/{session}"
            and parse_qs(url.query).get("event") == [record["event_id"]]
            and entry["folder_id"] == folder
        )

    return {
        "search_urls_valid": sum(correct(row, row["session_id"]) for row in result["matches"]),
        "search_records": len(result["matches"]),
        "read_urls_valid": sum(
            correct(row, expanded["session_id"]) for row in expanded["evidence"]
        ),
        "read_records": len(expanded["evidence"]),
        "center_keeps_number": match["citation"]
        == next(
            item["citation"]
            for item in expanded["evidence"]
            if item["event_id"] == match["event_id"]
        ),
    }


def language_and_inventory(lab, output):
    owner = uuid_for(output.name, "owner")
    root = uuid_for(output.name, "root")
    repo = uuid_for(output.name, "repo")
    lab.create_owner(owner)
    lab.create_folder(root, owner, "edge-controls")
    lab.create_folder(repo, owner, "edge-notes", root)
    _, anchors = lab.capture(
        owner,
        repo,
        "portuguese-notes",
        [
            msg(
                "RECALL_PORTUGUES operação ação compactação memória revisão.",
                "2026-11-22T15:00:00Z",
            ),
        ],
    )
    epoch = datetime(2026, 11, 22, 15, tzinfo=timezone.utc)
    entries = [
        [
            "edge-notes",
            "large-journal",
            (epoch + timedelta(seconds=i)).isoformat(),
            f"Journal control observation {i}.",
        ]
        for i in range(2050)
    ]
    seed_journals(lab, owner, {"edge-notes": repo}, entries)
    with lab.tools(owner, root) as mcp:
        queries = {}
        for key, question in (
            ("accented", "operação ação compactação memória revisão"),
            ("unaccented", "operacao acao compactacao memoria revisao"),
            ("identifier", "RECALL_PORTUGUES"),
        ):
            result = json.loads(mcp.search_agent_history(question))
            queries[key] = {
                "status": code(result),
                "total_matches": result.get("total_matches"),
                "retrieved_known_record": anchors[0]
                in {row["event_id"] for row in result["matches"]},
            }
        inventory = json.loads(
            mcp.search_agent_history(
                projection="overview",
                from_date="2026-11-22",
                through_date="2026-11-22",
            )
        )
        journal = inventory["activity"]["days"][0]
        expanded = json.loads(mcp.read_agent_evidence(journal["reference"]))
    return {
        "same_language_lexical": queries,
        "journal_over_capacity": {
            "source_rows": len(entries),
            "inventory_entries": inventory["activity"]["entry_count"],
            "visible_entry_count": journal["entry_count"],
            "coverage": inventory["coverage"],
            "complete": inventory["inventory_complete"],
            "expanded_reference_status": code(expanded),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--operations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    operations = json.loads((args.operations / "sources.json").read_text())
    lab = Lab(args.lab)
    try:
        write_private(
            args.output,
            {
                "baseline": BASELINE,
                "native_citations": evidence_citations(lab, operations),
                **language_and_inventory(lab, args.output),
            },
        )
        print("Replayed native citation, language and inventory edges.")
    finally:
        lab.close()


if __name__ == "__main__":
    main()
