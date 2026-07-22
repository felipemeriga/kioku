import unittest

from services.queue.batching import into_batches


class TestIntoBatches(unittest.TestCase):
    def test_basic_split(self):
        result = list(into_batches(list(range(10)), size=3))
        self.assertEqual(result, [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]])

    def test_empty(self):
        self.assertEqual(list(into_batches([], size=5)), [])

    def test_exact_multiple(self):
        result = list(into_batches([1, 2, 3, 4], size=2))
        self.assertEqual(result, [[1, 2], [3, 4]])

    def test_size_larger_than_input(self):
        result = list(into_batches([1, 2], size=10))
        self.assertEqual(result, [[1, 2]])

    def test_invalid_size_raises(self):
        with self.assertRaises(ValueError):
            list(into_batches([1], size=0))
