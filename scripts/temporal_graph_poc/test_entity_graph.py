"""Automatic discovery must preserve source roles and temporal frequency."""

import sqlite3
import unittest

from corpus import SCHEMA
from entity_graph import identifiers
from entity_replay import sqlite_neighbors


class EntityBoundaries(unittest.TestCase):
    def test_identifiers_are_generic_and_do_not_match_acronyms_inside_words(self):
        self.assertEqual(
            identifiers("WebAssembly with SSE and `sdk/src`"), ["sdk/src", "sse"]
        )
        self.assertEqual(identifiers("`AWS_SECRET_ACCESS_KEY` `password-file`"), [])

    def test_future_mentions_do_not_change_historical_ranking(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        db.execute(
            "CREATE TABLE entity_occurrences(revision TEXT,record_id TEXT,entity TEXT,canonical_key TEXT,event_at TEXT)"
        )
        times = [
            "2026-11-01T10:00:00.000000+00:00",
            "2026-11-01T11:00:00.000000+00:00",
            "2026-11-01T12:00:00.000000+00:00",
        ]
        for i, at in enumerate(times):
            key = str(i)
            db.execute(
                "INSERT INTO records(id,session_id,event_at,role,event_type,inherited,displayable,text) VALUES(?,?,?,'assistant','message',0,1,'GOMEMLIMIT')",
                (key, key, at),
            )
            db.execute(
                "INSERT INTO entity_occurrences VALUES(?,?,?,?,?)",
                ("r", key, "gomemlimit", key, at),
            )
        self.assertEqual(sqlite_neighbors(db, "r", ["0"], times[0], 4), [])
        result = sqlite_neighbors(db, "r", ["0"], times[1], 4)
        self.assertEqual([r["record"]["id"] for r in result], ["1"])
        self.assertEqual(result[0]["score"], 0.5)
        db.close()


if __name__ == "__main__":
    unittest.main()
