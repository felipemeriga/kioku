"""End-to-end local archive identity and completeness checks."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from corpus import build


class ArchiveProjection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = (
            json.dumps(
                {
                    "type": "event_msg",
                    "timestamp": "2026-11-01T12:00:00Z",
                    "payload": {
                        "type": "user_message",
                        "message": "Try a staging-only experiment.",
                    },
                }
            ).encode()
            + b"\n"
        )
        self.sha = hashlib.sha256(self.raw).hexdigest()
        session = {
            "id": "s",
            "native_session_id": "native",
            "folder_id": "folder",
            "agent": "codex",
            "parent_session_id": None,
            "gaps": [],
            "ingested_at": "2026-11-02T12:00:00Z",
        }
        descriptor = {
            "first_record": 1,
            "last_record": 1,
            "record_count": 1,
            "stream_id": "stream",
            "generation": 1,
        }
        obj = {
            "object_id": "object",
            "session_id": "s",
            "kind": "segment",
            "committed_revision": 1,
            "sha256": self.sha,
            "byte_length": len(self.raw),
            "stream_id": "stream",
            "generation": 1,
            "first_record": 1,
            "descriptor": descriptor,
            "uploaded_at": "2026-11-02T12:00:00Z",
        }
        values = {
            "sessions.json": [session],
            "journals.json": [],
            "objects.json": [obj],
            "links.json": [],
        }
        files = {}
        for name, value in values.items():
            data = json.dumps(value).encode()
            (self.root / name).write_bytes(data)
            files[name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        (self.root / "snapshot.json").write_text(json.dumps({"files": files}))
        self.archive(self.raw, {"verified": 1, "failures": []})

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, raw, receipt):
        with tarfile.open(self.root / "originals.tar.gz", "w:gz") as output:
            for name, data in [
                ("objects/" + self.sha + ".jsonl", raw),
                ("receipt.json", json.dumps(receipt).encode()),
            ]:
                item = tarfile.TarInfo(name)
                item.size = len(data)
                output.addfile(item, io.BytesIO(data))

    def test_exact_object_and_byte_locator_survive_full_projection(self):
        output = self.root / "corpus.sqlite"
        result = build(self.root, output)
        self.assertEqual(result["counts"]["records_inserted"], 1)
        with sqlite3.connect(output) as db:
            row = db.execute(
                "SELECT object_id,source_sha256,byte_offset,byte_length,text FROM records"
            ).fetchone()
        self.assertEqual(
            row,
            ("object", self.sha, 0, len(self.raw), "Try a staging-only experiment."),
        )

    def test_inventory_tampering_is_rejected(self):
        (self.root / "journals.json").write_text("[{}]")
        with self.assertRaisesRegex(ValueError, "inventory hash changed"):
            build(self.root, self.root / "out.sqlite")

    def test_corrupt_object_is_rejected_before_projection(self):
        self.archive(b"corrupt\n", {"verified": 1, "failures": []})
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            build(self.root, self.root / "out.sqlite")

    def test_incomplete_export_never_becomes_a_frozen_corpus(self):
        self.archive(self.raw, {"verified": 0, "failures": [{"error": "missing"}]})
        with self.assertRaisesRegex(ValueError, "Incomplete export"):
            build(self.root, self.root / "out.sqlite")


if __name__ == "__main__":
    unittest.main()
