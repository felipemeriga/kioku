"""Account balance + statement endpoints.

``account_id`` in the path is the canonical chart-of-accounts name, e.g.
``processor_clearing`` or ``seller_payable:sell_atelier``. (Colons are valid in
path segments.)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..accounts.chart import account_type_for
from ..balances.derive import balance_for_account, statement_for_account
from ..errors import AccountNotFoundError
from ..state import LedgerState, get_state
from .schemas import BalanceResponse, StatementResponse

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])


def _validate_account(name: str) -> None:
    # Raises PostingError for names outside the chart; surface as 404.
    try:
        account_type_for(name)
    except Exception as exc:
        raise AccountNotFoundError(
            "unknown account", detail={"account_id": name}
        ) from exc


@router.get("/{account_id:path}/balance", response_model=BalanceResponse)
async def get_balance(
    account_id: str, state: LedgerState = Depends(get_state)
) -> BalanceResponse:
    """Derive and return the balance for ``account_id``."""
    _validate_account(account_id)
    pairs = state.journal.lines_for_account(account_id)
    derived = balance_for_account(
        account_id, pairs, default_currency=state.settings.default_currency
    )
    return BalanceResponse.from_derived(derived)


@router.get("/{account_id:path}/statement", response_model=StatementResponse)
async def get_statement(
    account_id: str, state: LedgerState = Depends(get_state)
) -> StatementResponse:
    """Return the ordered statement + closing balance for ``account_id``."""
    _validate_account(account_id)
    pairs = state.journal.lines_for_account(account_id)
    closing, rows = statement_for_account(
        account_id, pairs, default_currency=state.settings.default_currency
    )
    return StatementResponse(
        account=account_id,
        currency=closing.currency,
        closing_balance=closing.balance,
        entries=rows,
    )
