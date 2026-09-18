"""The fixed sample data from the SPEC (used by examples + tests).

All three repos and all docs use the same figures so examples line up. See SPEC
"Fixed sample data".
"""

from __future__ import annotations

from .models.event import (
    EventEnvelope,
    PaymentSettledData,
    PayoutPaidData,
    RefundCompletedData,
)
from .money import Money

PLATFORM_ID = "plat_marisqueira"
SELLER_ATELIER = "sell_atelier"
SELLER_CERAMICA = "sell_ceramica"
DEFAULT_FEE_BPS = 290  # 2.9%

# Example charge chg_0001.
CHARGE_ID = "chg_0001"
CHARGE_AMOUNT = Money.of(12000, "EUR")  # €120.00
PLATFORM_FEE = Money.of(348, "EUR")  # €3.48
PROCESSOR_FEE = Money.of(205, "EUR")  # €2.05
SELLER_NET = Money.of(11447, "EUR")  # €114.47


def settled_data() -> PaymentSettledData:
    """The ``payment.settled`` data for chg_0001."""
    return PaymentSettledData(
        charge_id=CHARGE_ID,
        platform_id=PLATFORM_ID,
        seller_id=SELLER_ATELIER,
        amount=CHARGE_AMOUNT,
        platform_fee=PLATFORM_FEE,
        processor_fee=PROCESSOR_FEE,
    )


def settled_envelope(event_id: str = "evt_settled_0001") -> EventEnvelope:
    return EventEnvelope(
        id=event_id,
        type="payment.settled",
        ts="2026-01-01T12:00:00Z",
        data=settled_data().model_dump(),
    )


def refund_envelope(
    event_id: str = "evt_refund_0001",
    refund_id: str = "rfnd_0001",
    amount: Money | None = None,
) -> EventEnvelope:
    data = RefundCompletedData(
        refund_id=refund_id,
        charge_id=CHARGE_ID,
        amount=amount or CHARGE_AMOUNT,
    )
    return EventEnvelope(
        id=event_id,
        type="refund.completed",
        ts="2026-01-02T12:00:00Z",
        data=data.model_dump(),
    )


def payout_paid_envelope(
    batch_id: str,
    event_id: str = "evt_payout_0001",
    amount: Money | None = None,
    processor_ref: str = "po_ref_0001",
    seller_id: str = SELLER_ATELIER,
) -> EventEnvelope:
    data = PayoutPaidData(
        batch_id=batch_id,
        seller_id=seller_id,
        amount=amount or SELLER_NET,
        processor_ref=processor_ref,
    )
    return EventEnvelope(
        id=event_id,
        type="payout.paid",
        ts="2026-01-05T12:00:00Z",
        data=data.model_dump(),
    )
