"""In-memory store of payout batches."""

from __future__ import annotations

from ..models.payout_batch import PayoutBatch


class PayoutBatchStore:
    """Dict-backed payout batch store, keyed by batch id."""

    def __init__(self) -> None:
        self._batches: dict[str, PayoutBatch] = {}

    def save(self, batch: PayoutBatch) -> PayoutBatch:
        self._batches[batch.id] = batch
        return batch

    def get(self, batch_id: str) -> PayoutBatch | None:
        return self._batches.get(batch_id)

    def all(self) -> list[PayoutBatch]:
        return list(self._batches.values())

    def for_seller(self, seller_id: str) -> list[PayoutBatch]:
        return [b for b in self._batches.values() if b.seller_id == seller_id]
