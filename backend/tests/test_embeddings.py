import unittest
from unittest.mock import MagicMock, patch


class TestEmbedBatch(unittest.TestCase):
    def test_embed_batch_returns_one_vector_per_input(self):
        from services.embeddings import embed_batch

        fake_client = MagicMock()
        fake_client.embed.return_value.embeddings = [[0.1] * 1024, [0.2] * 1024]

        with patch("services.embeddings.get_voyage_client", return_value=fake_client):
            result = embed_batch(["hello", "world"])

        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), 1024)
        fake_client.embed.assert_called_once()
        call_args = fake_client.embed.call_args
        self.assertEqual(call_args.args[0], ["hello", "world"])

    def test_embed_batch_splits_over_128(self):
        from services.embeddings import embed_batch

        fake_client = MagicMock()

        def _embed(texts, **kw):
            resp = MagicMock()
            resp.embeddings = [[0.0] * 1024 for _ in texts]
            return resp

        fake_client.embed.side_effect = _embed

        with patch("services.embeddings.get_voyage_client", return_value=fake_client):
            result = embed_batch([f"chunk {i}" for i in range(200)])

        self.assertEqual(len(result), 200)
        # Two calls: 128 + 72
        self.assertEqual(fake_client.embed.call_count, 2)

    def test_embed_batch_empty_returns_empty(self):
        from services.embeddings import embed_batch

        result = embed_batch([])
        self.assertEqual(result, [])
