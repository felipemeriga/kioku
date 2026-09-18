"""Balance derivation — the ledger's ground-truth read model.

Balances are never stored; they are *derived* by replaying journal lines. This
module folds the immutable journal into per-account, per-currency balances and
into ordered statements.
"""

from .derive import (
    AccountBalance,
    StatementEntry,
    balance_for_account,
    derive_all_balances,
    statement_for_account,
)

__all__ = [
    "AccountBalance",
    "StatementEntry",
    "balance_for_account",
    "derive_all_balances",
    "statement_for_account",
]
