"""Request/response schemas for the HTTP API (distinct from domain models)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..balances.derive import AccountBalance, StatementEntry
from ..models.payout_batch import PayoutBatch
from ..money import Money


class EventAck(BaseModel):
    """Response to ``POST /internal/events``."""

    event_id: str
    event_type: str
    status: str = Field(..., description="posted | ignored | duplicate")
    result_id: str | None = None


class BalanceResponse(BaseModel):
    """Response to ``GET /v1/accounts/{account_id}/balance``."""

    account: str
    currency: str
    balance: Money
    debit_total: Money
    credit_total: Money
    line_count: int

    @classmethod
    def from_derived(cls, derived: AccountBalance) -> "BalanceResponse":
        return cls(**derived.model_dump())


class StatementResponse(BaseModel):
    """Response to ``GET /v1/accounts/{account_id}/statement``."""

    account: str
    currency: str
    closing_balance: Money
    entries: list[StatementEntry]


class CreatePayoutBatchRequest(BaseModel):
    """Body for ``POST /v1/payout-batches``.

    With no ``amount``, the full available payable balance is paid out.
    """

    seller_id: str
    amount: Money | None = None


class PayoutBatchResponse(BaseModel):
    """Serialized :class:`PayoutBatch`."""

    id: str
    seller_id: str
    amount: Money
    status: str
    scheduled_for: datetime
    processor_ref: str | None
    settlement_journal_id: str | None
    created_at: datetime

    @classmethod
    def from_batch(cls, batch: PayoutBatch) -> "PayoutBatchResponse":
        data: dict[str, Any] = batch.model_dump()
        data["status"] = batch.status.value
        return cls(**data)
