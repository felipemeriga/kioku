"""Live Neo4j controls for automatic co-mention traversal; synthetic, not accuracy."""

import argparse
import json
import uuid
from pathlib import Path

from entity_graph import neighbors
from graph import connect, execute


def run(args):
    revision = "entity-contract-" + uuid.uuid4().hex
    times = [
        "2026-11-01T10:00:00.000000+00:00",
        "2026-11-01T11:00:00.000000+00:00",
        "2026-11-01T12:00:00.000000+00:00",
    ]
    rows = [
        {
            "id": revision + ":" + str(i),
            "session_id": revision + ":session" + str(i),
            "event_at": at,
            "inherited": 0,
            "contract_fixture": True,
        }
        for i, at in enumerate(times)
    ]
    checks = []
    with connect(args.env_file) as d:
        try:
            execute(
                d,
                'CREATE(e:RecallEntity {id:$id,revision:$revision,identifier:"fixture_identifier",degree:9999})',
                id=revision,
                revision=revision,
            )
            execute(
                d,
                "UNWIND $rows AS row CREATE(r:Record) SET r += row WITH r,row MATCH(e:RecallEntity {id:$entity}) CREATE(r)-[:MENTIONS {canonical_key:row.id,known_at:row.event_at}]->(e)",
                rows=rows,
                entity=revision,
            )
            before = neighbors(d, revision, [rows[0]["id"]], times[0], 4)
            at = neighbors(d, revision, [rows[0]["id"]], times[1], 4)
            checks.append(
                {
                    "name": "future_neighbor_excluded",
                    "ok": before == []
                    and len(at) == 1
                    and at[0]["record"]["id"] == rows[1]["id"],
                }
            )
            checks.append(
                {
                    "name": "historical_degree_ignores_future_and_stored_degree",
                    "ok": len(at) == 1 and at[0]["score"] == 0.5,
                }
            )
            execute(
                d,
                "MATCH(r:Record {id:$id})-[m:MENTIONS]->(:RecallEntity {id:$entity}) SET m.known_at=$future",
                id=rows[1]["id"],
                entity=revision,
                future=times[2],
            )
            after = neighbors(d, revision, [rows[0]["id"]], times[1], 4)
            checks.append({"name": "future_edge_proof_excluded", "ok": after == []})
        finally:
            execute(
                d,
                "MATCH(r:Record) WHERE r.id IN $ids DETACH DELETE r",
                ids=[r["id"] for r in rows],
            )
            execute(d, "MATCH(e:RecallEntity {id:$id}) DETACH DELETE e", id=revision)
    report = {
        "status": "ok" if all(c["ok"] for c in checks) else "failed",
        "checks": checks,
        "scope": "synthetic engine contracts, not corpus answer accuracy",
    }
    with args.output.open("x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    args.output.chmod(0o600)
    print(json.dumps(report))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
