"""A single :class:`JournalLine` — one leg of a double-entry journal entry."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from ..money import Money


class Side(str, Enum):
    """The side of the ledger a line posts to."""

    DEBIT = "debit"
    CREDIT = "credit"

    @property
    def opposite(self) -> "Side":
        return Side.CREDIT if self is Side.DEBIT else Side.DEBIT


class JournalLine(BaseModel):
    """One posting: an amount to a single account, on the debit or credit side.

    Amounts are always non-negative :class:`Money`; direction is carried by
    ``side`` rather than by sign, so a balanced entry is ``sum(debit amounts) ==
    sum(credit amounts)``.
    """

    model_config = ConfigDict(frozen=True)

    account: str = Field(..., description="Chart-of-accounts name this line posts to.")
    side: Side
    amount: Money
    memo: str = ""

    @classmethod
    def debit(cls, account: str, amount: Money, memo: str = "") -> "JournalLine":
        return cls(account=account, side=Side.DEBIT, amount=amount, memo=memo)

    @classmethod
    def credit(cls, account: str, amount: Money, memo: str = "") -> "JournalLine":
        return cls(account=account, side=Side.CREDIT, amount=amount, memo=memo)

    def signed_amount_minor(self, account_normal_side_is_debit: bool) -> int:
        """Return the line's effect on the account's balance in minor units.

        A line on an account's normal side increases the balance (+); a line on
        the opposite side decreases it (-).
        """
        line_is_debit = self.side is Side.DEBIT
        increases = line_is_debit == account_normal_side_is_debit
        return self.amount.amount_minor if increases else -self.amount.amount_minor
