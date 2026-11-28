"""Production smoke must not repeat original queries for duplicate journal hints."""

import unittest

from production_replay import unique_sessions


class DistinctSessions(unittest.TestCase):
    def test_deduplicates_before_applying_session_budget(self):
        hints = [{"session_id": s} for s in ["a", "a", "a", "b", "c", "d"]]
        self.assertEqual(unique_sessions(hints), ["a", "b", "c"])

    def test_empty_discovery_does_not_search_originals(self):
        self.assertEqual(unique_sessions([]), [])


if __name__ == "__main__":
    unittest.main()
