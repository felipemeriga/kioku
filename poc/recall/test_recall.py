"""Behavioral checks for original-only retrieval boundaries."""

import unittest
from recall import Index, valid_citations


def record(identity, text):
    return {
        "event_id": identity,
        "session_id": "session",
        "event_at": "2026-11-06",
        "role": "tool",
        "event_type": "tool_result",
        "object_id": "segment",
        "byte_offset": 0,
        "byte_length": len(text),
        "text": text,
    }


class RecallTests(unittest.TestCase):
    def test_exact_configuration_survives_unrelated_material(self):
        index = Index(
            [
                record("noise", "memory " + ("unrelated " * 100)),
                record("setting", "Environment=GOMEMLIMIT=4GiB"),
            ]
        )
        self.assertEqual(index.retrieve(["GOMEMLIMIT 4GiB"])[0]["event_id"], "setting")

    def test_long_original_search_preserves_source_and_finds_late_content(self):
        index = Index(
            [
                record(
                    "long",
                    "ordinary " * 1000 + " TiledmediaCore_CreatePlayer unresolved",
                )
            ]
        )
        hit = index.retrieve(["TiledmediaCore_CreatePlayer unresolved"])[0]
        self.assertGreater(hit["excerpt_offset"], 0)
        self.assertIn("TiledmediaCore_CreatePlayer", hit["text"])
        self.assertEqual(hit["object_id"], "segment")
        self.assertEqual(len(index.retrieve(["ordinary unresolved"], 5)), 1)

    def test_absent_term_does_not_manufacture_results(self):
        self.assertEqual(
            Index([record("one", "Go heap budget")]).retrieve(["PostgreSQL migration"]),
            [],
        )


class CitationTests(unittest.TestCase):
    def test_cross_question_source_is_rejected(self):
        self.assertFalse(
            valid_citations(
                {"citations": [{"event_id": "other", "quote": "measured"}]},
                {"one": "measured"},
            )
        )

    def test_quote_must_be_an_exact_source_span(self):
        source = {"one": "RSS = 4.02 GiB; not a hard cap"}
        self.assertTrue(
            valid_citations(
                {"citations": [{"event_id": "one", "quote": "not a hard cap"}]}, source
            )
        )
        self.assertFalse(
            valid_citations(
                {
                    "citations": [
                        {"event_id": "one", "quote": "RSS = 4.02 GiB; a hard cap"}
                    ]
                },
                source,
            )
        )


if __name__ == "__main__":
    unittest.main()


class ImprovedContextTests(unittest.TestCase):
    def test_call_pair_is_scoped_to_session_and_budget(self):
        from improved import packet

        def source(identity, text, sequence, kind, call=None, session="session"):
            return {
                **record(identity, text),
                "record_sequence": sequence,
                "event_type": kind,
                "call_id": call,
                "session_id": session,
            }

        records = [
            source("command", "inspect_unique_sdk_version", 1, "tool_call", "call"),
            source(
                "result",
                "observed version vendor build identifier",
                2,
                "tool_result",
                "call",
            ),
            source(
                "unrelated",
                "private unrelated thread",
                1,
                "tool_result",
                "call",
                "different-session",
            ),
        ]
        sources = packet(
            Index(records), records, ["inspect_unique_sdk_version"], budget=2000
        )
        self.assertIn("result", [s["event_id"] for s in sources])
        self.assertNotIn("unrelated", [s["event_id"] for s in sources])
        self.assertLessEqual(sum(len(s["text"]) for s in sources), 2000)
        for s in sources:
            original = next(r for r in records if r["event_id"] == s["event_id"])
            self.assertEqual(
                s["text"],
                original["text"][
                    s["excerpt_offset"] : s["excerpt_offset"] + s["excerpt_length"]
                ],
            )

    def test_model_cannot_invent_or_modify_resolved_quote(self):
        from improved import resolve, span

        evidence = span(
            record("one", "Observed 4 GiB target; not a hard process cap."), 0
        )
        answer = {
            "status": "supported",
            "answer": "A soft target.",
            "citations": [evidence["source_id"]],
        }
        resolved = resolve(answer, [evidence])
        self.assertTrue(resolved["usable"])
        self.assertEqual(resolved["resolved_citations"][0]["text"], evidence["text"])
        self.assertFalse(
            resolve({**answer, "citations": ["other-question-source"]}, [evidence])[
                "usable"
            ]
        )
        self.assertFalse(resolve({**answer, "citations": []}, [evidence])["usable"])
