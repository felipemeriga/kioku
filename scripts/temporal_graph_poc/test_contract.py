"""Local-only adversarial evidence-contract checks; no production requests."""

from __future__ import annotations

import copy
import json
import sqlite3
import unittest

from corpus import SCHEMA, timestamp
from facts import validate


class EvidenceContract(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.execute(
            "INSERT INTO metadata VALUES('snapshot_sha256',?)", (json.dumps("fixture"),)
        )
        self.db.execute(
            """INSERT INTO records(id,event_at,role,event_type,inherited,displayable,text,source_sha256)
          VALUES('original',?,'assistant','message',0,1,'The experiment was reverted; production deployment was not established.','source')""",
            (timestamp("2026-11-05T12:00:00Z"),),
        )
        self.bundle = {
            "corpus_snapshot_sha256": "fixture",
            "concepts": [
                {"id": "experiment", "name": "Experiment", "aliases": ["trial"]}
            ],
            "claims": [
                {
                    "id": "reversal",
                    "concepts": ["experiment"],
                    "status": "reverted",
                    "authority": "assistant_report",
                    "text": "A reversal was reported.",
                    "review_note": "The assistant report explicitly says reverted; not independent verification.",
                    "supports": [
                        {
                            "record_id": "original",
                            "quote": "The experiment was reverted",
                        }
                    ],
                }
            ],
        }

    def tearDown(self):
        self.db.close()

    def test_retroactive_valid_time_never_backdates_knowledge(self):
        self.bundle["claims"][0]["valid_at"] = "2026-11-01T12:00:00Z"
        _, claims, _, _ = validate(self.bundle, self.db)
        self.assertEqual(claims[0]["known_at"], timestamp("2026-11-05T12:00:00Z"))
        self.assertEqual(claims[0]["valid_at"], timestamp("2026-11-01T12:00:00Z"))

    def test_fabricated_quote_is_rejected(self):
        self.bundle["claims"][0]["supports"][0]["quote"] = (
            "Production is definitely deployed"
        )
        with self.assertRaisesRegex(ValueError, "quotation"):
            validate(self.bundle, self.db)

    def test_wrong_corpus_is_rejected(self):
        self.bundle["corpus_snapshot_sha256"] = "other"
        with self.assertRaisesRegex(ValueError, "frozen corpus"):
            validate(self.bundle, self.db)

    def test_inherited_context_is_not_independent_evidence(self):
        self.db.execute("UPDATE records SET inherited=1")
        with self.assertRaisesRegex(ValueError, "inherited"):
            validate(self.bundle, self.db)

    def test_untimed_source_cannot_establish_historical_state(self):
        self.db.execute("UPDATE records SET event_at=NULL")
        with self.assertRaisesRegex(ValueError, "untimed"):
            validate(self.bundle, self.db)

    def test_internal_analysis_is_not_an_established_report(self):
        self.db.execute("UPDATE records SET channel='analysis'")
        with self.assertRaisesRegex(ValueError, "Private analysis"):
            validate(self.bundle, self.db)

    def test_assistant_report_cannot_be_promoted_to_tool_observation(self):
        self.bundle["claims"][0]["authority"] = "tool_observation"
        with self.assertRaisesRegex(ValueError, "command result"):
            validate(self.bundle, self.db)

    def test_future_plan_cannot_be_a_completed_result(self):
        self.bundle["claims"][0]["valid_at"] = "2026-12-01T12:00:00Z"
        with self.assertRaisesRegex(ValueError, "future plan"):
            validate(self.bundle, self.db)

    def test_relation_requires_its_own_original_and_review(self):
        second = copy.deepcopy(self.bundle["claims"][0])
        second["id"] = "prior"
        self.bundle["claims"].append(second)
        self.bundle["relations"] = [
            {
                "from": "reversal",
                "to": "prior",
                "type": "SUPERSEDES",
                "support": {
                    "record_id": "missing",
                    "quote": "The experiment was reverted",
                },
                "review_note": "Test",
            }
        ]
        with self.assertRaisesRegex(ValueError, "Source absent"):
            validate(self.bundle, self.db)

    def test_two_offset_representations_have_identical_cutoff(self):
        self.assertEqual(
            timestamp("2026-11-05T09:00:00-03:00"), timestamp("2026-11-05T12:00:00Z")
        )

    def test_offset_free_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Offset-free"):
            timestamp("2026-11-05T12:00:00")


if __name__ == "__main__":
    unittest.main()
