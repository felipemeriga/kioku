"""The :class:`PayoutBatch` model — a scheduled movement of a seller's balance."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from ..ids import payout_batch_id
from ..money import Money


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PayoutBatchStatus(str, Enum):
    """Lifecycle of a payout batch (SPEC: scheduled|processing|paid|failed)."""

    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"


class PayoutBatch(BaseModel):
    """A batch that moves a seller's ``seller_payable`` balance to their bank.

    The ledger builds the batch, calls gateway ``POST /v1/payouts`` to move the
    money, then marks it ``paid`` when the gateway emits ``payout.paid`` — at
    which point it posts the debit against ``seller_payable``.
    """

    id: str = Field(default_factory=payout_batch_id)
    seller_id: str
    amount: Money
    status: PayoutBatchStatus = PayoutBatchStatus.SCHEDULED
    scheduled_for: datetime = Field(default_factory=_utcnow)
    processor_ref: str | None = None
    #: Journal entry posted when the batch is marked paid (set on payout.paid).
    settlement_journal_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    def mark_processing(self, processor_ref: str | None = None) -> "PayoutBatch":
        return self.model_copy(
            update={
                "status": PayoutBatchStatus.PROCESSING,
                "processor_ref": processor_ref or self.processor_ref,
            }
        )

    def mark_paid(self, processor_ref: str, settlement_journal_id: str) -> "PayoutBatch":
        return self.model_copy(
            update={
                "status": PayoutBatchStatus.PAID,
                "processor_ref": processor_ref,
                "settlement_journal_id": settlement_journal_id,
            }
        )

    def mark_failed(self) -> "PayoutBatch":
        return self.model_copy(update={"status": PayoutBatchStatus.FAILED})
