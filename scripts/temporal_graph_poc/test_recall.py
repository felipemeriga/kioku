"""Query-boundary regressions found by the real-corpus replay."""

import json
import sqlite3
import unittest
from unittest.mock import patch

from corpus import SCHEMA
from recall import (
    concept_seeds,
    graph_facts,
    journal_hints,
    relevance_patterns,
    text_relevance,
)


class RecallBoundaries(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE metadata(key TEXT,value TEXT)")
        self.db.execute(
            "INSERT INTO metadata VALUES(?,?)",
            ("snapshot_sha256", json.dumps("fixture")),
        )
        self.db.execute("CREATE TABLE concepts(revision TEXT,id TEXT,payload TEXT)")
        self.db.execute(
            "INSERT INTO concepts VALUES(?,?,?)",
            (
                "r",
                "stream",
                json.dumps(
                    {"name": "NBA stream", "aliases": ["SSE", "consumer group"]}
                ),
            ),
        )

    def tearDown(self):
        self.db.close()

    def test_acronym_inside_an_unrelated_word_does_not_match(self):
        self.assertEqual(
            concept_seeds(self.db, "r", "Have we used WebAssembly for decoding?"), []
        )

    def test_specific_identifier_beats_generic_recent_text(self):
        patterns = relevance_patterns(
            "Was GOMEMLIMIT=512MiB tested on the full player?"
        )
        old = "An isolated SDK comparison used GOMEMLIMIT=512MiB; not a full player budget."
        newer = "The latest full player memory settings were updated."
        self.assertGreater(
            text_relevance(old, patterns), text_relevance(newer, patterns)
        )
        self.assertEqual(text_relevance("WebAssembly", relevance_patterns("SSE")), 0)

    def test_real_acronym_and_hyphenated_phrase_match(self):
        self.assertEqual(concept_seeds(self.db, "r", "SSE reconnection"), ["stream"])
        self.assertEqual(
            concept_seeds(self.db, "r", "consumer-group isolation"), ["stream"]
        )

    def test_journal_revision_is_hidden_until_publication(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        db.execute(
            "INSERT INTO journals VALUES(?,?,?,?,?,?,?)",
            (
                "j",
                "s",
                "2026-11-01T10:00:00.000000+00:00",
                "2026-11-01",
                "bandwidth",
                "updated result",
                "",
            ),
        )
        db.execute(
            "INSERT INTO journal_fts VALUES(?,?,?)",
            ("j", "bandwidth", "updated result"),
        )
        before = "2026-11-01T11:00:00.000000+00:00"
        published = "2026-11-01T12:00:00.000000+00:00"
        self.assertEqual(journal_hints(db, "bandwidth", published), [])
        db.execute(
            "INSERT INTO journal_publications VALUES(?,?,?,?)",
            ("2026-11-01", published, 2, "hash"),
        )
        self.assertEqual(journal_hints(db, "bandwidth", before), [])
        self.assertEqual(len(journal_hints(db, "bandwidth", published)), 1)
        db.close()

    def test_empty_graph_uses_parameterized_journal_fallback(self):
        calls = []

        def execute(driver, query, **parameters):
            calls.append((query, parameters))
            return []

        with patch("recall.execute", execute):
            result = graph_facts(
                None,
                self.db,
                "r",
                "home bandwidth",
                "2026-11-01T12:00:00.000000+00:00",
                8,
            )
        self.assertEqual(result["claims"], [])
        self.assertEqual(calls[-1][1]["corpus"], "fixture")
        self.assertIn("node.published_at<=$cutoff", calls[-1][0])
        self.assertIn("text_query", calls[-1][1])
        self.assertNotIn("query", calls[-1][1])


if __name__ == "__main__":
    unittest.main()
