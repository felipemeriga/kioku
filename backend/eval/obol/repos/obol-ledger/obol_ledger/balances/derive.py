"""Derive account balances and statements from the immutable journal.

A balance is the signed fold of every line on an account, where "signed" is
relative to the account's *normal side*:

- asset / expense accounts increase on debits
- liability / revenue / equity accounts increase on credits

So ``seller_payable`` (liability) grows on credit (settlement) and shrinks on
debit (refund clawback / payout), which is exactly what we want its balance to
show as "amount owed to the seller".
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ..accounts.chart import account_type_for
from ..models.journal_entry import JournalEntry
from ..models.journal_line import JournalLine
from ..money import Money


class AccountBalance(BaseModel):
    """A derived balance for one account in one currency."""

    account: str
    currency: str
    balance: Money
    debit_total: Money
    credit_total: Money
    line_count: int


class StatementEntry(BaseModel):
    """One line of an account statement, with the running balance after it."""

    journal_id: str
    event_id: str
    kind: str
    side: str
    amount: Money
    running_balance: Money
    memo: str
    created_at: datetime
    reference: dict[str, str]


def _fold_lines(
    account: str,
    currency: str,
    pairs: list[tuple[JournalEntry, JournalLine]],
) -> AccountBalance:
    normal_debit = account_type_for(account).normal_side_is_debit
    balance = Money.zero(currency)
    debit_total = Money.zero(currency)
    credit_total = Money.zero(currency)

    for _entry, line in pairs:
        signed = line.signed_amount_minor(normal_debit)
        balance = balance + Money.of(signed, currency)
        if line.side.value == "debit":
            debit_total = debit_total + line.amount
        else:
            credit_total = credit_total + line.amount

    return AccountBalance(
        account=account,
        currency=currency,
        balance=balance,
        debit_total=debit_total,
        credit_total=credit_total,
        line_count=len(pairs),
    )


def balance_for_account(
    account: str,
    pairs: list[tuple[JournalEntry, JournalLine]],
    *,
    default_currency: str,
) -> AccountBalance:
    """Derive the balance for ``account`` from its (entry, line) pairs.

    ``pairs`` is what :meth:`JournalStore.lines_for_account` returns. Currency is
    taken from the first line, falling back to ``default_currency`` when the
    account has no activity yet.
    """
    currency = pairs[0][1].amount.currency if pairs else default_currency
    return _fold_lines(account, currency, pairs)


def statement_for_account(
    account: str,
    pairs: list[tuple[JournalEntry, JournalLine]],
    *,
    default_currency: str,
) -> tuple[AccountBalance, list[StatementEntry]]:
    """Derive an ordered statement plus the closing balance for ``account``."""
    currency = pairs[0][1].amount.currency if pairs else default_currency
    normal_debit = account_type_for(account).normal_side_is_debit

    running = Money.zero(currency)
    rows: list[StatementEntry] = []
    for entry, line in pairs:
        running = running + Money.of(line.signed_amount_minor(normal_debit), currency)
        rows.append(
            StatementEntry(
                journal_id=entry.id,
                event_id=entry.event_id,
                kind=entry.kind,
                side=line.side.value,
                amount=line.amount,
                running_balance=running,
                memo=line.memo,
                created_at=entry.created_at,
                reference=entry.reference,
            )
        )

    closing = _fold_lines(account, currency, pairs)
    return closing, rows


def derive_all_balances(
    entries: list[JournalEntry], *, default_currency: str
) -> list[AccountBalance]:
    """Derive balances for every account touched by ``entries``.

    Also a useful integrity probe: because every entry balances, the signed sum
    of all balances (in a single currency) is zero.
    """
    grouped: dict[str, list[tuple[JournalEntry, JournalLine]]] = {}
    for entry in entries:
        for line in entry.lines:
            grouped.setdefault(line.account, []).append((entry, line))

    return [
        balance_for_account(account, pairs, default_currency=default_currency)
        for account, pairs in sorted(grouped.items())
    ]
