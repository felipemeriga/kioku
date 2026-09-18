"""Refund reversal posting (SPEC "Refund reversal").

On ``refund.completed`` for amount R, a mirror-image entry is posted that debits
``seller_payable`` and ``platform_revenue`` and credits ``processor_clearing``.
The original settlement entry is never deleted — the journal is immutable.

The platform fee is refunded *proportionally* to the refunded fraction of the
original charge::

    fee_giveback = round_half_even(platform_fee * R / original_amount)
    seller_clawback = R - fee_giveback

so that::

    DEBIT  platform_revenue          fee_giveback
    DEBIT  seller_payable:{seller}    seller_clawback
    CREDIT processor_clearing         R

Debits (fee_giveback + seller_clawback) equal the credit R by construction.

The proportional split needs the *original* charge amount and platform fee,
which the ``refund.completed`` envelope does not carry — so the caller supplies
the original settlement entry (looked up by ``charge_id``).
"""

from __future__ import annotations

from decimal import Decimal

from ..accounts.chart import (
    PLATFORM_REVENUE,
    PROCESSOR_CLEARING,
    seller_payable_account,
)
from ..errors import PostingError
from ..models.event import RefundCompletedData
from ..models.journal_entry import JournalEntry
from ..models.journal_line import JournalLine, Side
from ..money import Money, round_half_even


def _extract_settlement_figures(settlement: JournalEntry) -> tuple[Money, Money, str]:
    """Pull (original_amount, original_platform_fee, seller_id) off a settlement.

    Reads the amounts from the settlement's own lines so refund math is grounded
    in what was actually posted, not re-derived from the event.
    """
    amount: Money | None = None
    platform_fee: Money | None = None
    seller_id: str | None = settlement.reference.get("seller_id")

    for line in settlement.lines:
        if line.account == PROCESSOR_CLEARING and line.side is Side.DEBIT:
            amount = line.amount
        elif line.account == PLATFORM_REVENUE and line.side is Side.CREDIT:
            platform_fee = line.amount

    if amount is None or platform_fee is None or seller_id is None:
        raise PostingError(
            "cannot derive refund proportions from settlement entry",
            detail={"settlement_journal_id": settlement.id},
        )
    return amount, platform_fee, seller_id


def build_refund_reversal_entry(
    event_id: str, data: RefundCompletedData, settlement: JournalEntry
) -> JournalEntry:
    """Build the balanced refund-reversal :class:`JournalEntry`.

    ``settlement`` is the original settlement entry for ``data.charge_id``.
    Raises :class:`PostingError` if the refund exceeds the original charge or
    currencies disagree.
    """
    refund_amount: Money = data.amount
    original_amount, original_platform_fee, seller_id = _extract_settlement_figures(settlement)

    if refund_amount.currency != original_amount.currency:
        raise PostingError(
            "refund currency does not match original charge",
            detail={
                "refund": refund_amount.currency,
                "charge": original_amount.currency,
            },
        )
    if refund_amount > original_amount:
        raise PostingError(
            "refund amount exceeds original charge amount",
            detail={
                "refund_minor": refund_amount.amount_minor,
                "charge_minor": original_amount.amount_minor,
            },
        )
    if original_amount.is_zero:
        raise PostingError("original charge amount is zero", detail={"charge_id": data.charge_id})

    # Proportional platform-fee give-back, banker's rounding.
    giveback_minor = round_half_even(
        Decimal(original_platform_fee.amount_minor)
        * Decimal(refund_amount.amount_minor)
        / Decimal(original_amount.amount_minor)
    )
    fee_giveback = Money.of(giveback_minor, refund_amount.currency)
    seller_clawback = refund_amount - fee_giveback

    seller_account = seller_payable_account(seller_id)

    lines = [
        JournalLine.debit(
            PLATFORM_REVENUE, fee_giveback, memo="refund: proportional platform fee give-back"
        ),
        JournalLine.debit(
            seller_account, seller_clawback, memo="refund: seller balance clawback"
        ),
        JournalLine.credit(
            PROCESSOR_CLEARING, refund_amount, memo="refund: funds returned to buyer"
        ),
    ]

    entry = JournalEntry(
        event_id=event_id,
        kind="refund_reversal",
        currency=refund_amount.currency,
        lines=lines,
        reverses=settlement.id,
        reference={"charge_id": data.charge_id, "refund_id": data.refund_id, "seller_id": seller_id},
    )
    return entry.assert_balanced()
