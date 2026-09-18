"""Refund reversal posting balances and gives back fees proportionally."""

import pytest

from obol_ledger.accounts.chart import (
    PLATFORM_REVENUE,
    PROCESSOR_CLEARING,
    seller_payable_account,
)
from obol_ledger.errors import PostingError
from obol_ledger.models.journal_line import Side
from obol_ledger.money import Money
from obol_ledger.posting import build_refund_reversal_entry, build_settlement_entry
from obol_ledger import sample_data


def _line(entry, account, side):
    for ln in entry.lines:
        if ln.account == account and ln.side == side:
            return ln
    raise AssertionError(f"missing {side} line for {account}")


def test_full_refund_reverses_full_amount_and_fee():
    settlement = build_settlement_entry("evt_s", sample_data.settled_data())
    refund_data = sample_data.refund_envelope(amount=Money.of(12000, "EUR"))

    from obol_ledger.events.parser import parse_refund

    data = parse_refund(refund_data)
    reversal = build_refund_reversal_entry("evt_r", data, settlement)

    assert reversal.is_balanced()
    assert reversal.reverses == settlement.id
    # Full refund gives back the full platform fee (348) and full seller net.
    assert _line(reversal, PLATFORM_REVENUE, Side.DEBIT).amount == Money.of(348, "EUR")
    assert _line(reversal, seller_payable_account("sell_atelier"), Side.DEBIT).amount == Money.of(
        11652, "EUR"
    )
    assert _line(reversal, PROCESSOR_CLEARING, Side.CREDIT).amount == Money.of(12000, "EUR")


def test_partial_refund_proportional_fee_giveback():
    settlement = build_settlement_entry("evt_s", sample_data.settled_data())
    # Refund half: 6000 of 12000. Proportional fee give-back = 348 * 6000/12000 = 174.
    from obol_ledger.events.parser import parse_refund

    data = parse_refund(sample_data.refund_envelope(amount=Money.of(6000, "EUR")))
    reversal = build_refund_reversal_entry("evt_r", data, settlement)

    assert reversal.is_balanced()
    assert _line(reversal, PLATFORM_REVENUE, Side.DEBIT).amount == Money.of(174, "EUR")
    # seller clawback = 6000 - 174 = 5826
    assert _line(reversal, seller_payable_account("sell_atelier"), Side.DEBIT).amount == Money.of(
        5826, "EUR"
    )
    assert _line(reversal, PROCESSOR_CLEARING, Side.CREDIT).amount == Money.of(6000, "EUR")


def test_refund_exceeding_charge_rejected():
    settlement = build_settlement_entry("evt_s", sample_data.settled_data())
    from obol_ledger.events.parser import parse_refund

    data = parse_refund(sample_data.refund_envelope(amount=Money.of(13000, "EUR")))
    with pytest.raises(PostingError):
        build_refund_reversal_entry("evt_r", data, settlement)
