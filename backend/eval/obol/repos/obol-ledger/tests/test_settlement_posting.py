"""Settlement posting reproduces the SPEC's fixed chg_0001 figures and balances."""

import pytest

from obol_ledger.accounts.chart import (
    PLATFORM_REVENUE,
    PROCESSOR_CLEARING,
    PROCESSOR_FEES,
    seller_payable_account,
)
from obol_ledger.errors import PostingError, UnbalancedEntryError
from obol_ledger.models.journal_line import Side
from obol_ledger.money import Money
from obol_ledger.posting import build_settlement_entry
from obol_ledger import sample_data


def _line(entry, account, side):
    for ln in entry.lines:
        if ln.account == account and ln.side == side:
            return ln
    raise AssertionError(f"missing {side} line for {account}")


def test_settlement_reproduces_spec_numbers():
    entry = build_settlement_entry("evt_1", sample_data.settled_data())

    # Exact SPEC figures for chg_0001.
    assert _line(entry, PROCESSOR_CLEARING, Side.DEBIT).amount == Money.of(12000, "EUR")
    assert _line(entry, PLATFORM_REVENUE, Side.CREDIT).amount == Money.of(348, "EUR")
    assert _line(entry, PROCESSOR_FEES, Side.CREDIT).amount == Money.of(205, "EUR")
    seller_line = _line(entry, seller_payable_account("sell_atelier"), Side.CREDIT)
    assert seller_line.amount == Money.of(11447, "EUR")


def test_settlement_balances():
    entry = build_settlement_entry("evt_1", sample_data.settled_data())
    assert entry.is_balanced()
    assert entry.total_debits() == Money.of(12000, "EUR")
    assert entry.total_credits() == Money.of(12000, "EUR")


def test_settlement_kind_and_reference():
    entry = build_settlement_entry("evt_1", sample_data.settled_data())
    assert entry.kind == "settlement"
    assert entry.reference["charge_id"] == "chg_0001"
    assert entry.reference["seller_id"] == "sell_atelier"


def test_settlement_rejects_negative_net():
    data = sample_data.settled_data().model_copy(
        update={"platform_fee": Money.of(11000, "EUR"), "processor_fee": Money.of(2000, "EUR")}
    )
    with pytest.raises(PostingError):
        build_settlement_entry("evt_bad", data)


def test_unbalanced_entry_raises():
    from obol_ledger.models.journal_entry import JournalEntry
    from obol_ledger.models.journal_line import JournalLine

    bad = JournalEntry(
        event_id="evt_x",
        kind="settlement",
        currency="EUR",
        lines=[
            JournalLine.debit(PROCESSOR_CLEARING, Money.of(100, "EUR")),
            JournalLine.credit(PLATFORM_REVENUE, Money.of(90, "EUR")),
        ],
    )
    with pytest.raises(UnbalancedEntryError):
        bad.assert_balanced()
