"""Event envelope + typed ``data`` payloads consumed from the gateway.

All events share the envelope ``{ id, type, ts, data }`` (SPEC "Events"). The
ledger consumes three types:

- ``payment.settled``  → posts the settlement entry
- ``refund.completed`` → posts the reversal entry
- ``payout.paid``      → marks the batch paid and debits seller_payable
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..money import Money


class PaymentSettledData(BaseModel):
    """``data`` for ``payment.settled``."""

    charge_id: str
    platform_id: str
    seller_id: str
    amount: Money
    platform_fee: Money
    processor_fee: Money


class RefundCompletedData(BaseModel):
    """``data`` for ``refund.completed``.

    The envelope carries only the refund amount; the ledger looks up the
    original settlement (via ``charge_id``) to compute the proportional fee
    give-back for the reversal.
    """

    refund_id: str
    charge_id: str
    amount: Money


class PayoutPaidData(BaseModel):
    """``data`` for ``payout.paid``."""

    batch_id: str
    seller_id: str
    amount: Money
    processor_ref: str


class EventEnvelope(BaseModel):
    """The generic inbound event envelope; ``data`` stays raw until dispatch."""

    id: str = Field(..., description="Globally unique event id — the idempotency key.")
    type: str = Field(..., description="Dotted event type, e.g. 'payment.settled'.")
    ts: datetime
    data: dict[str, Any]
