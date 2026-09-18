"""The :class:`Account` model and the accounting :class:`AccountType`."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from ..ids import account_id_of


class AccountType(str, Enum):
    """The five accounting classifications used by the Obol chart of accounts.

    The type determines *normal balance side*: assets and expenses increase on
    the debit side; liabilities and revenue increase on the credit side.
    """

    ASSET = "asset"
    LIABILITY = "liability"
    REVENUE = "revenue"
    EXPENSE = "expense"
    EQUITY = "equity"

    @property
    def normal_side_is_debit(self) -> bool:
        return self in (AccountType.ASSET, AccountType.EXPENSE)


class Account(BaseModel):
    """A single ledger account in the chart of accounts.

    ``name`` is the canonical, human-legible key from the SPEC (e.g.
    ``processor_clearing`` or ``seller_payable:sell_atelier``); ``id`` is the
    prefixed account id derived from it.
    """

    id: str = Field(..., description="Prefixed account id, e.g. acct_processor_clearing.")
    name: str = Field(..., description="Canonical chart-of-accounts name.")
    type: AccountType
    currency: str = Field(..., min_length=3, max_length=3)
    description: str = ""

    @classmethod
    def create(
        cls, name: str, type: AccountType, currency: str, description: str = ""
    ) -> "Account":
        return cls(
            id=account_id_of(name),
            name=name,
            type=type,
            currency=currency,
            description=description,
        )
