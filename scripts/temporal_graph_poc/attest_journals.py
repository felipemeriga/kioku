"""Read and attest raw journal objects, then attach their publication timestamps.

Database/Storage access is read-only; only the private local projection and its
disposable graph gain publication metadata. Authentication stays on the SSH host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import tarfile
from pathlib import Path

from corpus import timestamp
from graph import connect, execute

REMOTE = r"""
import hashlib,io,json,sys,tarfile
from pathlib import Path
from db.client import get_supabase
from services import agent_journal,history_search
request=json.load(sys.stdin)
rows=request["days"]
assert rows and len(rows)<=1000
assert all(row["user_id"]==request["user_id"] and row["folder_id"]==request["folder_id"] for row in rows)
bucket=get_supabase().storage.from_("agent-journals")
receipt={"verified":0,"entries":0,"parser_hashes":{m.__name__:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in [agent_journal,history_search]}}
with tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz") as out:
    def write(name,data):
        item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o600;out.addfile(item,io.BytesIO(data))
    for row in rows:
        raw=bucket.download(row["storage_path"])
        assert len(raw)<=5*1024*1024 and hashlib.sha256(raw).hexdigest()==row["content_sha256"]
        entries=history_search.search_entries(raw.decode())
        assert len(entries)==row["entry_count"] and row["search_sha256"]==row["content_sha256"]
        write("days/"+row["journal_date"]+".md",raw)
        write("index/"+row["journal_date"]+".json",json.dumps(entries).encode())
        receipt["verified"]+=1;receipt["entries"]+=len(entries)
    write("receipt.json",json.dumps(receipt).encode())
"""


def attest(args):
    days = json.loads(args.days.read_text())
    if not all(
        row["user_id"] == args.user_id and row["folder_id"] == args.folder_id
        for row in days
    ):
        raise ValueError("Mixed journal scope")
    command = shlex.join(
        ["docker", "exec", "-i", args.container, "python", "-c", REMOTE]
    )
    with os.fdopen(
        os.open(args.archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    ) as out:
        subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=6",
                args.host,
                command,
            ],
            input=json.dumps(
                {"days": days, "user_id": args.user_id, "folder_id": args.folder_id}
            ).encode(),
            stdout=out,
            check=True,
            timeout=120,
        )
    expected_days = {row["journal_date"]: row for row in days}
    db = sqlite3.connect(args.corpus)
    db.row_factory = sqlite3.Row
    existing = {row["id"]: dict(row) for row in db.execute("SELECT * FROM journals")}
    observed = set()
    verified = 0
    remote_receipt = None
    with tarfile.open(args.archive, "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                raise ValueError("Nonregular journal archive member")
            data = archive.extractfile(member).read()
            path = Path(member.name)
            if member.name == "receipt.json":
                remote_receipt = json.loads(data)
                continue
            if path.stem not in expected_days:
                raise ValueError("Unexpected journal date")
            meta = expected_days[path.stem]
            if path.parent.as_posix() == "days" and path.suffix == ".md":
                if hashlib.sha256(data).hexdigest() != meta["content_sha256"]:
                    raise ValueError("Journal bytes changed")
                verified += 1
            elif path.parent.as_posix() == "index" and path.suffix == ".json":
                for item in json.loads(data):
                    old = existing.get(item["entry_id"])
                    if not old:
                        raise ValueError("Raw journal has an unknown entry")
                    for field in [
                        "agent",
                        "session_id",
                        "title",
                        "summary",
                        "body",
                        "captured_at",
                    ]:
                        expected = (
                            old["summary_snapshot"]
                            if field == "summary"
                            else old.get(field)
                        )
                        # The local journal cache omits agent; it is present in
                        # the frozen entry inventory and its compound entry ID.
                        if field == "agent":
                            expected = (
                                item["agent"]
                                if old["id"].startswith(item["agent"] + ":")
                                else None
                            )
                        actual = (
                            timestamp(item[field])
                            if field == "captured_at"
                            else item[field]
                        )
                        if actual != expected:
                            raise ValueError(
                                "Journal/index projection mismatch: " + field
                            )
                    observed.add(item["entry_id"])
            else:
                raise ValueError("Unexpected journal archive member")
    if (
        verified != len(days)
        or observed != set(existing)
        or not remote_receipt
        or remote_receipt["verified"] != len(days)
    ):
        raise ValueError("Incomplete journal attestation")
    db.execute(
        "CREATE TABLE IF NOT EXISTS journal_publications(day TEXT PRIMARY KEY,published_at TEXT,revision INTEGER,sha256 TEXT)"
    )
    with db:
        db.executemany(
            "INSERT OR REPLACE INTO journal_publications VALUES(?,?,?,?)",
            [
                (
                    r["journal_date"],
                    timestamp(r["synced_at"]),
                    r["revision"],
                    r["content_sha256"],
                )
                for r in days
            ],
        )
        db.execute(
            "INSERT OR REPLACE INTO metadata VALUES(?,?)",
            (
                "journal_publication_sha256",
                json.dumps(hashlib.sha256(args.days.read_bytes()).hexdigest()),
            ),
        )
    rows = [
        {
            "id": j["id"],
            "published_at": timestamp(expected_days[j["day"]]["synced_at"]),
            "publication_revision": expected_days[j["day"]]["revision"],
            "publication_sha256": expected_days[j["day"]]["content_sha256"],
        }
        for j in existing.values()
    ]
    with connect(args.env_file) as driver:
        execute(
            driver,
            "UNWIND $rows AS row MATCH(j:Journal {id:row.id}) SET j.published_at=row.published_at,j.publication_revision=row.publication_revision,j.publication_sha256=row.publication_sha256",
            rows=rows,
        )
    db.close()
    return {
        "status": "ok",
        "verified_days": verified,
        "verified_entries": len(observed),
        "publication_sha256": hashlib.sha256(args.days.read_bytes()).hexdigest(),
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "remote_parser_hashes": remote_receipt["parser_hashes"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ["days", "archive", "corpus", "env-file", "output"]:
        parser.add_argument("--" + field, type=Path, required=True)
    for field in ["host", "user-id", "folder-id"]:
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--container", default="kioku-backend")
    args = parser.parse_args()
    result = attest(args)
    with os.fdopen(
        os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as out:
        json.dump(result, out, indent=2)
    print(json.dumps(result))
