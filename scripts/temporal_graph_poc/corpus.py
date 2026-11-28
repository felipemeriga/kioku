"""Build a private, reproducible SQLite evidence projection from a frozen export.

SQLite is both the source cache and the nongraph lexical baseline. Native records
are parsed by Kioku's existing parser, with full text retained privately. The
archive must finish successfully before it can be called a frozen corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tarfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from services.agent_evidence_parser import iter_segment


def timestamp(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Offset-free evidence timestamp")
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def native_channel(raw, event, agent):
    try:
        native = json.loads(
            raw[event["byte_offset"] : event["byte_offset"] + event["byte_length"]]
        )
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(native, dict):
        return None
    payload = native.get("payload") if agent == "codex" else native.get("message")
    return payload.get("channel") if isinstance(payload, dict) else None


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE sessions(id TEXT PRIMARY KEY, native_id TEXT, agent TEXT,
 parent_id TEXT, gaps TEXT, archived_at TEXT);
CREATE TABLE journals(id TEXT PRIMARY KEY, session_id TEXT, captured_at TEXT,
 day TEXT, title TEXT, body TEXT, summary_snapshot TEXT);
CREATE VIRTUAL TABLE journal_fts USING fts5(id UNINDEXED,title,body);
CREATE TABLE objects(id TEXT, session_id TEXT, sha256 TEXT,
 stream_id TEXT, generation INTEGER, first_record INTEGER, last_record INTEGER,
 archived_at TEXT, PRIMARY KEY(session_id,id));
CREATE TABLE records(id TEXT PRIMARY KEY, session_id TEXT, stream_id TEXT,
 generation INTEGER, sequence INTEGER, event_at TEXT, role TEXT, event_type TEXT, channel TEXT,
 native_id TEXT, turn_id TEXT, call_id TEXT, inherited INTEGER, displayable INTEGER,
 source_truncated INTEGER, source_sha256 TEXT, byte_offset INTEGER,
 byte_length INTEGER, text TEXT);
CREATE INDEX records_session ON records(session_id,event_at);
CREATE INDEX records_call ON records(session_id,call_id);
CREATE INDEX records_stream ON records(session_id,stream_id,generation,sequence);
CREATE VIRTUAL TABLE record_fts USING fts5(id UNINDEXED,text);
CREATE TABLE journal_links(journal_id TEXT PRIMARY KEY, session_id TEXT,
 start_id TEXT, end_id TEXT);
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
"""


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build(private: Path, output: Path):
    inventory = json.loads((private / "snapshot.json").read_text())
    for name, descriptor in inventory["files"].items():
        if digest(private / name) != descriptor["sha256"]:
            raise ValueError(f"Frozen inventory hash changed: {name}")
    sessions = {
        row["id"]: row for row in json.loads((private / "sessions.json").read_text())
    }
    journals = json.loads((private / "journals.json").read_text())
    links = json.loads((private / "links.json").read_text())
    objects = json.loads((private / "objects.json").read_text())
    descriptors = [
        row
        for row in objects
        if row["kind"] == "segment" and row["committed_revision"] is not None
    ]
    archive = private / "originals.tar.gz"
    # Strict extraction whitelist; never trust archive paths or extract symlinks.
    cache = private / "verified-objects"
    cache.mkdir(mode=0o700, exist_ok=True)
    seen = set()
    with tarfile.open(archive, "r|gz") as source:
        receipt = None
        for member in source:
            if not member.isfile():
                raise ValueError("Nonregular archive member")
            data = source.extractfile(member).read()
            if member.name == "receipt.json":
                receipt = json.loads(data)
                continue
            name = Path(member.name)
            checksum = name.stem
            if name.parent.as_posix() != "objects" or len(checksum) != 64:
                raise ValueError("Unexpected archive member")
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError("Local archive object hash mismatch")
            target = cache / (checksum + ".jsonl")
            if not target.exists():
                with os.fdopen(
                    os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
                ) as f:
                    f.write(data)
            elif digest(target) != checksum:
                raise ValueError("Existing private object was modified")
            seen.add(checksum)
    if not receipt or receipt["failures"] or receipt["verified"] != len(descriptors):
        raise ValueError("Incomplete export: cannot freeze source coverage")
    if seen != {row["sha256"] for row in descriptors}:
        raise ValueError("Archive differs from frozen object inventory")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    db = sqlite3.connect(output)
    db.executescript(SCHEMA)
    db.executemany(
        "INSERT INTO sessions VALUES(?,?,?,?,?,?)",
        [
            (
                row["id"],
                row["native_session_id"],
                row["agent"],
                row["parent_session_id"],
                json.dumps(row["gaps"]),
                timestamp(row["ingested_at"]),
            )
            for row in sessions.values()
        ],
    )
    for row in journals:
        db.execute(
            "INSERT INTO journals VALUES(?,?,?,?,?,?,?)",
            (
                row["entry_id"],
                row["session_id"],
                timestamp(row["captured_at"]),
                row["journal_date"],
                row["title"],
                row["body"],
                row["summary"],
            ),
        )
        db.execute(
            "INSERT INTO journal_fts VALUES(?,?,?)",
            (row["entry_id"], row["title"], row["body"]),
        )
    for row in links:
        db.execute(
            "INSERT INTO journal_links VALUES(?,?,?,?)",
            (
                row["journal_entry_id"],
                row["session_id"],
                row["start_event_id"],
                row["end_event_id"],
            ),
        )
    counts = Counter()
    states = defaultdict(dict)
    for obj in sorted(
        descriptors,
        key=lambda row: (
            row["session_id"],
            row["stream_id"],
            row["generation"],
            row["first_record"],
        ),
    ):
        session = sessions[obj["session_id"]]
        raw = (cache / (obj["sha256"] + ".jsonl")).read_bytes()
        if len(raw) != obj["byte_length"]:
            raise ValueError("Object length differs from inventory")
        db.execute(
            "INSERT INTO objects VALUES(?,?,?,?,?,?,?,?)",
            (
                obj["object_id"],
                obj["session_id"],
                obj["sha256"],
                obj["stream_id"],
                obj["generation"],
                obj["descriptor"]["first_record"],
                obj["descriptor"]["last_record"],
                timestamp(obj["uploaded_at"]),
            ),
        )
        state = states[(obj["session_id"], obj["stream_id"], obj["generation"])]
        for event in iter_segment(
            raw, obj["descriptor"], session, state, include_content=True
        ):
            content = event.get("_content", "")
            channel = native_channel(raw, event, session["agent"])
            values = (
                event["event_id"],
                obj["session_id"],
                obj["stream_id"],
                obj["generation"],
                event["record_sequence"],
                timestamp(event.get("event_at")),
                event["role"],
                event["event_type"],
                channel,
                event.get("native_id"),
                event.get("turn_id"),
                event.get("call_id"),
                event.get("inherited", False),
                event["displayable"],
                event.get("source_truncated", False),
                obj["sha256"],
                event["byte_offset"],
                event["byte_length"],
                content,
            )
            inserted = db.execute(
                "INSERT OR IGNORE INTO records VALUES("
                + ",".join("?" for _ in values)
                + ")",
                values,
            ).rowcount
            if inserted and event["displayable"] and not event.get("inherited"):
                db.execute(
                    "INSERT INTO record_fts VALUES(?,?)",
                    (event["event_id"], content[:12000]),
                )
            counts["records_seen"] += 1
            counts["records_inserted"] += inserted
            counts["parse_errors"] += event["event_type"] == "parse_error"
            counts["untimed"] += not event.get("event_at")
            counts["inherited"] += bool(event.get("inherited"))
        db.commit()
    counts["linked_journals"] = db.execute(
        "SELECT count(*) FROM journal_links l JOIN records r ON r.id=l.start_id"
    ).fetchone()[0]
    metadata = {
        "counts": dict(counts),
        "archive_sha256": digest(archive),
        "snapshot_sha256": digest(private / "snapshot.json"),
        "parser_sha256": digest(
            Path(__file__).resolve().parents[2]
            / "backend/services/agent_evidence_parser.py"
        ),
    }
    db.executemany(
        "INSERT INTO metadata VALUES(?,?)",
        [(k, json.dumps(v)) for k, v in metadata.items()],
    )
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.private_dir, args.output), sort_keys=True))
