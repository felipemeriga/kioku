"""Tests for deterministic retrieval metrics: Recall@k, MRR, nDCG@k."""

import unittest


class TestRecallAtK(unittest.TestCase):
    def test_full_recall(self):
        from eval.ir_metrics import recall_at_k

        relevant = {"a", "b", "c"}
        retrieved = ["a", "b", "c", "x", "y"]
        self.assertEqual(recall_at_k(retrieved, relevant, k=5), 1.0)

    def test_partial_recall(self):
        from eval.ir_metrics import recall_at_k

        relevant = {"a", "b", "c"}
        retrieved = ["a", "x", "y", "z", "b"]
        self.assertAlmostEqual(recall_at_k(retrieved, relevant, k=5), 2 / 3)

    def test_k_cuts_off(self):
        from eval.ir_metrics import recall_at_k

        relevant = {"a", "b", "c"}
        retrieved = ["x", "y", "a", "b", "c"]
        self.assertAlmostEqual(recall_at_k(retrieved, relevant, k=2), 0.0)

    def test_empty_retrieved(self):
        from eval.ir_metrics import recall_at_k

        self.assertEqual(recall_at_k([], {"a"}, k=5), 0.0)

    def test_empty_relevant(self):
        from eval.ir_metrics import recall_at_k

        # Convention: undefined / no relevant docs → return None so aggregation
        # can skip the question rather than scoring it 1.0 or 0.0 spuriously.
        self.assertIsNone(recall_at_k(["a", "b"], set(), k=5))


class TestMRR(unittest.TestCase):
    def test_first_position(self):
        from eval.ir_metrics import mrr

        self.assertEqual(mrr(["a", "x", "y"], {"a"}), 1.0)

    def test_second_position(self):
        from eval.ir_metrics import mrr

        self.assertEqual(mrr(["x", "a", "y"], {"a"}), 0.5)

    def test_no_hit(self):
        from eval.ir_metrics import mrr

        self.assertEqual(mrr(["x", "y", "z"], {"a"}), 0.0)


class TestNDCG(unittest.TestCase):
    def test_perfect_ranking(self):
        from eval.ir_metrics import ndcg_at_k

        # All retrieved are relevant, ranked first
        relevant = {"a", "b", "c"}
        retrieved = ["a", "b", "c", "x", "y"]
        result = ndcg_at_k(retrieved, relevant, k=5)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_no_hits(self):
        from eval.ir_metrics import ndcg_at_k

        self.assertEqual(ndcg_at_k(["x", "y"], {"a"}, k=5), 0.0)

    def test_reversed_order_lower_than_correct(self):
        from eval.ir_metrics import ndcg_at_k

        relevant = {"a", "b"}
        correct = ndcg_at_k(["a", "b", "x"], relevant, k=3)
        reversed_ = ndcg_at_k(["x", "b", "a"], relevant, k=3)
        self.assertGreater(correct, reversed_)
        self.assertAlmostEqual(correct, 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
