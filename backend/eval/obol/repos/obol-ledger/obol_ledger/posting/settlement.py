"""Settlement posting (SPEC "Settlement posting").

On ``payment.settled`` for charge amount A, platform fee P, processor fee F,
seller net ``N = A - P - F``::

    DEBIT  processor_clearing        A
    CREDIT platform_revenue          P
    CREDIT processor_fees            F
    CREDIT seller_payable:{seller}   N

Debits (A) equal credits (P + F + N) by construction, since N is defined as the
residual A - P - F.

Worked example — charge chg_0001 (SPEC "Fixed sample data"):
    A = €120.00 (12000), P = €3.48 (348), F = €2.05 (205)
    N = 12000 - 348 - 205 = 11447  (€114.47)
    debits  = 12000
    credits = 348 + 205 + 11447 = 12000  ✓
"""

from __future__ import annotations

from ..accounts.chart import (
    PLATFORM_REVENUE,
    PROCESSOR_CLEARING,
    PROCESSOR_FEES,
    seller_payable_account,
)
from ..errors import CurrencyMismatchError, PostingError
from ..models.event import PaymentSettledData
from ..models.journal_entry import JournalEntry
from ..models.journal_line import JournalLine
from ..money import Money


def build_settlement_entry(event_id: str, data: PaymentSettledData) -> JournalEntry:
    """Build the balanced settlement :class:`JournalEntry` for a settled charge.

    Raises :class:`CurrencyMismatchError` if the amount and fees disagree on
    currency, or :class:`PostingError` if the numbers are nonsensical (negative
    net, fees exceeding the charge).
    """
    amount: Money = data.amount
    platform_fee: Money = data.platform_fee
    processor_fee: Money = data.processor_fee

    currency = amount.currency
    if not (platform_fee.currency == currency == processor_fee.currency):
        raise CurrencyMismatchError(
            "settlement amount and fees must share a currency",
            detail={
                "amount": currency,
                "platform_fee": platform_fee.currency,
                "processor_fee": processor_fee.currency,
            },
        )

    # Seller net is the residual: N = A - P - F.
    seller_net: Money = amount - platform_fee - processor_fee
    if seller_net.is_negative:
        raise PostingError(
            "seller net is negative — fees exceed the charge amount",
            detail={
                "charge_id": data.charge_id,
                "amount_minor": amount.amount_minor,
                "platform_fee_minor": platform_fee.amount_minor,
                "processor_fee_minor": processor_fee.amount_minor,
            },
        )

    seller_account = seller_payable_account(data.seller_id)

    lines = [
        JournalLine.debit(PROCESSOR_CLEARING, amount, memo="settlement: funds in transit"),
        JournalLine.credit(PLATFORM_REVENUE, platform_fee, memo="settlement: platform fee"),
        JournalLine.credit(PROCESSOR_FEES, processor_fee, memo="settlement: processor fee"),
        JournalLine.credit(seller_account, seller_net, memo="settlement: seller net"),
    ]

    entry = JournalEntry(
        event_id=event_id,
        kind="settlement",
        currency=currency,
        lines=lines,
        reference={
            "charge_id": data.charge_id,
            "platform_id": data.platform_id,
            "seller_id": data.seller_id,
        },
    )
    # Hard invariant: this must balance before it leaves the posting module.
    return entry.assert_balanced()
