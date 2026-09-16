import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


class TestRecencyFactor(unittest.TestCase):
    def test_reference_content_never_decays(self):
        from services.search import _recency_factor

        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        doc = {"source_type": "notion", "created_at": old}
        self.assertEqual(_recency_factor(doc), 1.0)

    def test_meeting_halves_per_half_life(self):
        from services.search import _recency_factor

        now = datetime.now(timezone.utc)
        doc = {
            "source_type": "meeting",
            "created_at": (now - timedelta(days=90)).isoformat(),
        }
        self.assertAlmostEqual(_recency_factor(doc, now=now), 0.5, places=3)

    def test_fresh_meeting_barely_decays(self):
        from services.search import _recency_factor

        now = datetime.now(timezone.utc)
        doc = {"source_type": "meeting", "created_at": now.isoformat()}
        self.assertAlmostEqual(_recency_factor(doc, now=now), 1.0, places=3)

    def test_undated_content_never_decays(self):
        from services.search import _recency_factor

        self.assertEqual(_recency_factor({"source_type": "meeting"}), 1.0)


class TestApplyRecencyDecay(unittest.TestCase):
    def test_stale_meeting_drops_below_fresh_one(self):
        from services.search import _apply_recency_decay

        now = datetime.now(timezone.utc)
        stale = {
            "id": "stale",
            "source_type": "meeting",
            "created_at": (now - timedelta(days=360)).isoformat(),
            "rerank_score": 0.9,
        }
        fresh = {
            "id": "fresh",
            "source_type": "meeting",
            "created_at": (now - timedelta(days=3)).isoformat(),
            "rerank_score": 0.7,
        }
        out = _apply_recency_decay([stale, fresh])
        self.assertEqual([d["id"] for d in out], ["fresh", "stale"])

    def test_marginal_fresh_chunk_cannot_bury_relevant_old_one(self):
        # The anchor-pollution case: a corpus of year-old SMT docs holds the
        # real answer, and one recent chunk merely mentions 'smt'. The fresh
        # chunk anchors the cohort at factor 1.0 — but freshness is a bounded
        # additive boost (RECENCY_WEIGHT), so the highly-relevant old chunk
        # still ranks first.
        from services.search import _apply_recency_decay

        now = datetime.now(timezone.utc)
        old_relevant = {
            "id": "old-smt-doc",
            "source_type": "meeting",
            "created_at": (now - timedelta(days=365)).isoformat(),
            "rerank_score": 0.9,
        }
        fresh_marginal = {
            "id": "fresh-mention",
            "source_type": "meeting",
            "created_at": now.isoformat(),
            "rerank_score": 0.3,
        }
        out = _apply_recency_decay([old_relevant, fresh_marginal])
        self.assertEqual([d["id"] for d in out], ["old-smt-doc", "fresh-mention"])

    def test_all_old_cohort_keeps_pure_relevance_order(self):
        # Decay is cohort-relative: when every relevant chunk is old (e.g. a
        # folder whose documents all date from last year, with no updates),
        # they normalize against each other and the relevance order stands —
        # old-only answers are never suppressed.
        from services.search import _apply_recency_decay

        now = datetime.now(timezone.utc)
        best = {
            "id": "best",
            "source_type": "meeting",
            "created_at": (now - timedelta(days=370)).isoformat(),
            "rerank_score": 0.9,
        }
        weaker = {
            "id": "weaker",
            "source_type": "meeting",
            "created_at": (now - timedelta(days=350)).isoformat(),
            "rerank_score": 0.5,
        }
        out = _apply_recency_decay([best, weaker])
        self.assertEqual([d["id"] for d in out], ["best", "weaker"])
        # The most-recent chunk in the cohort anchors at factor 1.0.
        self.assertEqual(max(d["recency_factor"] for d in out), 1.0)

    def test_reference_docs_keep_relevance_order(self):
        from services.search import _apply_recency_decay

        old = {
            "id": "old-doc",
            "source_type": "pdf",
            "created_at": "2024-01-01T00:00:00+00:00",
            "rerank_score": 0.9,
        }
        new = {
            "id": "new-doc",
            "source_type": "pdf",
            "created_at": "2026-09-01T00:00:00+00:00",
            "rerank_score": 0.7,
        }
        out = _apply_recency_decay([old, new])
        self.assertEqual([d["id"] for d in out], ["old-doc", "new-doc"])


class TestTemporalFiltersReachRpc(unittest.TestCase):
    def test_vector_search_passes_created_bounds(self):
        from services.search import _vector_search

        sb = MagicMock()
        sb.rpc.return_value.execute.return_value.data = []
        with patch("services.search.get_supabase", return_value=sb):
            _vector_search(
                [0.0] * 1024,
                "u1",
                5,
                None,
                None,
                created_after="2026-01-01",
                created_before="2026-06-30",
            )
        params = sb.rpc.call_args.args[1]
        self.assertEqual(params["filter_created_after"], "2026-01-01")
        self.assertEqual(params["filter_created_before"], "2026-06-30")


class TestToolTemporalParams(unittest.TestCase):
    def test_agent_dates_reach_search_and_headers_are_dated(self):
        from services.tools import execute_tool

        results = [
            {
                "content": "we decided X",
                "metadata": {"source_filename": "sync meeting"},
                "created_at": "2026-03-14T10:00:00+00:00",
            }
        ]
        with (
            patch("services.tools.embed_query", return_value=[0.0] * 1024),
            patch("services.tools.search_documents", return_value=results) as search_mock,
        ):
            out = execute_tool(
                "knowledge_base_search",
                {"query": "q", "created_after": "2026-03-01"},
                "u1",
            )
        self.assertEqual(search_mock.call_args.kwargs["created_after"], "2026-03-01")
        self.assertIn("[Source: sync meeting — 2026-03-14]", out)
