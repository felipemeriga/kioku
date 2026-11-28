"""Semantic discovery does not relax original or journal publication cutoffs."""

import hashlib
import sqlite3
import unittest

from corpus import SCHEMA
from journal_vector_replay import sql_window, vector


class VectorBoundaries(unittest.TestCase):
    def test_embedding_must_match_its_exact_input(self):
        receipt = {
            "text_sha256": hashlib.sha256(b"source").hexdigest(),
            "vector": [1.0] * 1024,
        }
        with self.assertRaisesRegex(ValueError, "frozen source"):
            vector("different source", receipt)
        receipt["vector"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "Invalid embedding"):
            vector("source", receipt)

    def test_journal_publication_and_original_cutoffs_both_apply(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        at = "2026-11-01T10:00:00.000000+00:00"
        published = "2026-11-01T11:00:00.000000+00:00"
        future = "2026-11-01T12:00:00.000000+00:00"
        db.execute("INSERT INTO sessions(id,native_id) VALUES(?,?)", ("s", "native"))
        db.execute(
            "INSERT INTO journals VALUES(?,?,?,?,?,?,?)",
            ("j", "native", at, "day", "title", "body", "summary"),
        )
        db.execute(
            "INSERT INTO journal_publications VALUES(?,?,?,?)",
            ("day", published, 1, "sha"),
        )
        for key, seq, recorded in [
            ("start", 0, at),
            ("past", 1, at),
            ("future", 2, future),
            ("end", 3, at),
        ]:
            db.execute(
                "INSERT INTO records(id,session_id,stream_id,generation,sequence,event_at,role,inherited,displayable,text) VALUES(?,'s','stream',0,?,?,'assistant',0,1,?)",
                (key, seq, recorded, key),
            )
        db.execute(
            "INSERT INTO journal_links VALUES(?,?,?,?)", ("j", "s", "start", "end")
        )
        self.assertEqual(sql_window(db, "j", at), [])
        self.assertEqual(
            {r["id"] for r in sql_window(db, "j", published)}, {"start", "past", "end"}
        )
        db.execute("UPDATE records SET stream_id='different' WHERE id='end'")
        self.assertEqual(sql_window(db, "j", published), [])
        db.close()


if __name__ == "__main__":
    unittest.main()
