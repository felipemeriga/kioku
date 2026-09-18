"""Payout batch building: submit to gateway, then settle on payout.paid."""

import pytest

from obol_ledger.accounts.chart import seller_payable_account
from obol_ledger.balances import balance_for_account
from obol_ledger.errors import InsufficientBalanceError
from obol_ledger.models.payout_batch import PayoutBatchStatus
from obol_ledger.money import Money
from obol_ledger.posting import build_settlement_entry
from obol_ledger import sample_data


def _payable(journal, seller_id):
    account = seller_payable_account(seller_id)
    pairs = journal.lines_for_account(account)
    return balance_for_account(account, pairs, default_currency="EUR").balance


async def test_build_and_submit_full_balance(journal, payout_builder, fake_gateway):
    journal.append(build_settlement_entry("evt_s", sample_data.settled_data()))

    batch = await payout_builder.build_and_submit("sell_atelier")
    assert batch.amount == Money.of(11447, "EUR")
    assert batch.status == PayoutBatchStatus.PROCESSING
    assert batch.processor_ref == "po_ref_test"
    # Gateway was called exactly once with the batch.
    assert len(fake_gateway.requests) == 1
    assert fake_gateway.requests[0].seller_id == "sell_atelier"


async def test_no_balance_raises(payout_builder):
    with pytest.raises(InsufficientBalanceError):
        await payout_builder.build_and_submit("sell_atelier")


async def test_payout_paid_reduces_payable_to_zero(journal, payout_builder):
    journal.append(build_settlement_entry("evt_s", sample_data.settled_data()))
    batch = await payout_builder.build_and_submit("sell_atelier")
    assert _payable(journal, "sell_atelier") == Money.of(11447, "EUR")

    from obol_ledger.events.parser import parse_payout_paid

    env = sample_data.payout_paid_envelope(batch.id)
    data = parse_payout_paid(env)
    updated, entry = payout_builder.mark_paid(env.id, data)

    assert updated.status == PayoutBatchStatus.PAID
    assert entry.is_balanced()
    # Paying out the net drives the seller payable balance to zero.
    assert _payable(journal, "sell_atelier") == Money.of(0, "EUR")


async def test_requested_over_available_rejected(journal, payout_builder):
    journal.append(build_settlement_entry("evt_s", sample_data.settled_data()))
    with pytest.raises(InsufficientBalanceError):
        await payout_builder.build_and_submit("sell_atelier", amount=Money.of(99999, "EUR"))
