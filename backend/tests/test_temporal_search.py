import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


class TestRecencyFactor(unittest.TestCase):
    def test_reference_content_uses_gentle_yearly_decay(self):
        from services.search import _recency_factor

        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=365)).isoformat()
        for source_type in ("pdf", "markdown", "notion"):
            with self.subTest(source_type=source_type):
                doc = {"source_type": source_type, "created_at": old}
                self.assertAlmostEqual(_recency_factor(doc, now=now), 0.5)

    def test_last_updated_takes_precedence_and_code_stays_neutral(self):
        from services.search import _recency_factor

        now = datetime.now(timezone.utc)
        for source_type in ("pdf", "markdown", "notion", "code"):
            doc = {
                "source_type": source_type,
                "created_at": (now - timedelta(days=365)).isoformat(),
                "last_updated": now.isoformat(),
            }
            self.assertEqual(_recency_factor(doc, now=now), 1.0)
        self.assertEqual(_recency_factor({"source_type": "code", "created_at": "2020-01-01"}), 1.0)

    def test_invalid_naive_and_future_timestamps_are_safe(self):
        from services.search import _recency_factor

        now = datetime.now(timezone.utc)
        self.assertEqual(_recency_factor({"source_type": "pdf", "last_updated": "bad"}), 1.0)
        self.assertAlmostEqual(
            _recency_factor({"source_type": "pdf", "last_updated": now.replace(tzinfo=None)}, now),
            1.0,
        )
        self.assertEqual(
            _recency_factor({"source_type": "pdf", "last_updated": (now + timedelta(days=2))}, now),
            1.0,
        )

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

    def test_reference_docs_no_longer_receive_neutral_factor(self):
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
        self.assertEqual([d["id"] for d in out], ["new-doc", "old-doc"])
        self.assertLess(out[1]["recency_factor"], 1.0)

    def test_all_reference_types_break_close_ties_by_last_updated(self):
        from services.search import _apply_recency_decay

        now = datetime.now(timezone.utc)
        for source_type in ("pdf", "markdown", "notion"):
            with self.subTest(source_type=source_type):
                old = {
                    "id": "old",
                    "source_type": source_type,
                    "rerank_score": 0.8,
                    "created_at": now.isoformat(),
                    "last_updated": (now - timedelta(days=365)).isoformat(),
                }
                fresh = {
                    **old,
                    "id": "fresh",
                    "rerank_score": 0.79,
                    "last_updated": now.isoformat(),
                }
                results = _apply_recency_decay([old, fresh])
                self.assertEqual([d["id"] for d in results], ["fresh", "old"])
                self.assertAlmostEqual(results[1]["recency_factor"], 0.5, places=3)
                # Ranking metadata never mutates the stored chunks or the
                # cross-encoder's relevance scores.
                self.assertNotIn("recency_factor", old)
                self.assertEqual(results[1]["rerank_score"], 0.8)

    def test_fresh_reference_mention_does_not_bury_relevant_old_doc(self):
        from services.search import _apply_recency_decay

        for source_type in ("pdf", "markdown", "notion"):
            old = {
                "id": "answer",
                "source_type": source_type,
                "last_updated": "2020-01-01",
                "rerank_score": 0.9,
            }
            fresh = {
                **old,
                "id": "mention",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "rerank_score": 0.3,
            }
            self.assertEqual(_apply_recency_decay([old, fresh])[0]["id"], "answer")


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
    def test_both_dates_reach_agent_and_citation(self):
        from services.citations import CitationRegistry
        from services.retrieval import _hits_from_docs
        from services.tools import execute_tool

        rows = [
            {
                "id": "d1",
                "content": "API uses X",
                "source_type": "pdf",
                "created_at": "2025-01-01T00:00:00Z",
                "last_updated": "2026-10-23T00:00:00Z",
                "metadata": {"source_filename": "api.pdf"},
            }
        ]
        citations = CitationRegistry()
        with (
            patch("services.tools.embed_query", return_value=[]),
            patch("services.tools.search_documents", return_value=rows),
        ):
            out = execute_tool("knowledge_base_search", {"query": "API"}, "u1", citations=citations)
        self.assertIn("2025-01-01 — last updated 2026-10-23", out)
        self.assertEqual(citations.entries()[0]["last_updated"], rows[0]["last_updated"])
        hit = _hits_from_docs(rows)[0]
        self.assertEqual(hit.metadata["created_at"], rows[0]["created_at"])
        self.assertEqual(hit.metadata["last_updated"], rows[0]["last_updated"])

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
