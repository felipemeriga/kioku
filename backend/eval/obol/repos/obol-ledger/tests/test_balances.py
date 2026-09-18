"""Balance derivation after settle, then settle+refund."""

from obol_ledger.accounts.chart import (
    PLATFORM_REVENUE,
    PROCESSOR_CLEARING,
    seller_payable_account,
)
from obol_ledger.balances import balance_for_account, derive_all_balances
from obol_ledger.money import Money
from obol_ledger.posting import build_refund_reversal_entry, build_settlement_entry
from obol_ledger.events.parser import parse_refund
from obol_ledger import sample_data


def _balance(journal, account):
    pairs = journal.lines_for_account(account)
    return balance_for_account(account, pairs, default_currency="EUR").balance


def test_balances_after_settlement(journal):
    journal.append(build_settlement_entry("evt_s", sample_data.settled_data()))

    seller_acct = seller_payable_account("sell_atelier")
    # Liability grows on credit: seller is owed the net.
    assert _balance(journal, seller_acct) == Money.of(11447, "EUR")
    # Revenue grows on credit: platform earned its fee.
    assert _balance(journal, PLATFORM_REVENUE) == Money.of(348, "EUR")
    # Asset grows on debit: money in transit == the full charge.
    assert _balance(journal, PROCESSOR_CLEARING) == Money.of(12000, "EUR")


def test_balances_after_settle_then_full_refund(journal):
    journal.append(build_settlement_entry("evt_s", sample_data.settled_data()))
    settlement = journal.settlement_for_charge("chg_0001")
    data = parse_refund(sample_data.refund_envelope(amount=Money.of(12000, "EUR")))
    journal.append(build_refund_reversal_entry("evt_r", data, settlement))

    seller_acct = seller_payable_account("sell_atelier")
    # Per SPEC's three-account refund model, a full refund debits the full
    # platform fee (348) back out of platform_revenue -> 0, and credits the full
    # R (12000) back to processor_clearing -> 0. The seller clawback is
    # R - fee_giveback = 12000 - 348 = 11652, but the seller was only ever
    # credited their net (11447), so seller_payable lands at 11447 - 11652 = -205
    # — exactly the processor fee, which the SPEC refund entry never returns.
    assert _balance(journal, PLATFORM_REVENUE) == Money.of(0, "EUR")
    assert _balance(journal, PROCESSOR_CLEARING) == Money.of(0, "EUR")
    assert _balance(journal, seller_acct) == Money.of(-205, "EUR")


def test_debits_equal_credits_across_all_accounts(journal):
    # The real ledger-wide invariant: total debits == total credits across every
    # entry, independent of each account's normal side (which is what a per-
    # account balance sign reflects).
    journal.append(build_settlement_entry("evt_s", sample_data.settled_data()))
    settlement = journal.settlement_for_charge("chg_0001")
    data = parse_refund(sample_data.refund_envelope(amount=Money.of(6000, "EUR")))
    journal.append(build_refund_reversal_entry("evt_r", data, settlement))

    total_debits = 0
    total_credits = 0
    for entry in journal.all():
        total_debits += entry.total_debits().amount_minor
        total_credits += entry.total_credits().amount_minor
    assert total_debits == total_credits

    # And the settlement identity still holds: clearing debit == sum of credits.
    balances = {
        b.account: b.balance.amount_minor
        for b in derive_all_balances(journal.all(), default_currency="EUR")
    }
    # After a €60 partial refund: clearing 12000-6000=6000; revenue 348-174=174;
    # processor_fees credit-only -> -205; seller 11447-(6000-174)=5621.
    assert balances[PROCESSOR_CLEARING] == 6000
    assert balances[PLATFORM_REVENUE] == 174
    assert balances["processor_fees"] == -205
    assert balances[seller_payable_account("sell_atelier")] == 5621
