"""Unit tests for services.contextual — per-chunk situating blurbs."""

import unittest
from unittest.mock import MagicMock, patch


def _resp(text: str) -> MagicMock:
    m = MagicMock()
    m.content = [MagicMock(text=text)]
    return m


class TestContextualizeChunks(unittest.TestCase):
    def test_one_context_per_chunk_with_doc_cached_in_system(self):
        from services.contextual import contextualize_chunks

        doc = "x" * 2000  # above the tiny-doc skip threshold
        chunks = ["alpha chunk", "beta chunk"]

        with patch(
            "services.contextual.complete",
            side_effect=[_resp("ctx for alpha"), _resp("ctx for beta")],
        ) as complete_mock:
            out = contextualize_chunks(doc, chunks)

        self.assertEqual(len(out), 2)
        self.assertCountEqual(out, ["ctx for alpha", "ctx for beta"])
        # Full doc rides in the (cached) system prompt; the chunk in the user msg.
        for call in complete_mock.call_args_list:
            kw = call.kwargs
            self.assertIn(doc, kw["system"])
            self.assertTrue(kw["cache_system"])
            self.assertIn("chunk", kw["messages"][0]["content"].lower())

    def test_failed_chunk_falls_back_to_empty(self):
        from services.contextual import contextualize_chunks

        doc = "y" * 2000
        chunks = ["good", "bad"]

        def _side(*args, **kwargs):
            if "bad" in kwargs["messages"][0]["content"]:
                raise RuntimeError("haiku down")
            return _resp("ok context")

        with patch("services.contextual.complete", side_effect=_side):
            out = contextualize_chunks(doc, chunks)

        self.assertEqual(out[0], "ok context")
        self.assertEqual(out[1], "")  # best-effort: failure → empty, never raises

    def test_tiny_doc_skips_llm(self):
        from services.contextual import contextualize_chunks

        with patch("services.contextual.complete") as complete_mock:
            out = contextualize_chunks("too short", ["a", "b"])

        self.assertEqual(out, ["", ""])
        complete_mock.assert_not_called()

    def test_empty_chunks(self):
        from services.contextual import contextualize_chunks

        self.assertEqual(contextualize_chunks("whatever", []), [])


if __name__ == "__main__":
    unittest.main()
