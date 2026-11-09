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


class TemporalTests(unittest.TestCase):
    def test_local_day_excludes_future_records_and_includes_utc_next_day(self):
        from temporal import scoped_records
        from zoneinfo import ZoneInfo

        rows = [
            {**record("before", "x"), "event_at": "2026-11-05T02:59:59Z"},
            {**record("start", "x"), "event_at": "2026-11-05T03:00:00Z"},
            {**record("late", "x"), "event_at": "2026-11-06T02:59:59Z"},
            {**record("future", "x"), "event_at": "2026-11-06T03:00:00Z"},
        ]
        result = scoped_records(
            rows,
            {"mode": "range", "start_date": "2026-11-05", "end_date": "2026-11-05"},
            ZoneInfo("America/Sao_Paulo"),
        )
        self.assertEqual([r["event_id"] for r in result], ["start", "late"])

    def test_dst_day_uses_calendar_boundaries_not_fixed_24_hours(self):
        from temporal import day_boundary
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("America/New_York")
        self.assertEqual(
            (
                day_boundary("2026-11-01", zone, True)
                - day_boundary("2026-11-01", zone)
            ).total_seconds(),
            25 * 3600,
        )

    def test_empty_requested_interval_is_not_broadened(self):
        from temporal import scoped_records
        from zoneinfo import ZoneInfo

        result = scoped_records(
            [{**record("old", "older experiment"), "event_at": "2026-11-06T12:00:00Z"}],
            {"mode": "range", "start_date": "2026-11-07", "end_date": "2026-11-08"},
            ZoneInfo("UTC"),
        )
        self.assertEqual(result, [])

    def test_recalled_event_date_is_not_replaced_with_record_time(self):
        from temporal import resolve_timeline

        source = {
            "source_id": "known",
            "recorded_at": "2026-11-05T12:00:00Z",
            "recorded_local": "2026-11-05T09:00:00-03:00",
            "text": "October incident remained unattributed",
        }
        answer = {
            "status": "partial",
            "answer": "Later notes recalled an October incident.",
            "citations": ["known"],
            "timeline": [
                {
                    "description": "Recalled incident",
                    "described_event_time": "October 2026; exact date not established",
                    "recorded_at": "1900-01-01",
                    "citations": ["known"],
                }
            ],
        }
        resolved = resolve_timeline(answer, [source])
        self.assertEqual(resolved["timeline"][0]["recorded_at"], source["recorded_at"])
        self.assertEqual(
            resolved["timeline"][0]["described_event_time"],
            "October 2026; exact date not established",
        )
        self.assertTrue(resolved["citations_valid"])
