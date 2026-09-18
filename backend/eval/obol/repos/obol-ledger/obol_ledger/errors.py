"""Typed errors and FastAPI exception handlers.

Every domain failure is a subclass of :class:`LedgerError` carrying a stable
``code`` and an HTTP ``status_code``. :func:`register_exception_handlers`
translates them into a consistent JSON envelope::

    { "error": { "code": "...", "message": "...", "detail": {...} } }
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class LedgerError(Exception):
    """Base class for all ledger domain errors."""

    code: str = "ledger_error"
    status_code: int = 400

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


# -- money -------------------------------------------------------------------


class InvalidMoneyError(LedgerError):
    code = "invalid_money"
    status_code = 422


class CurrencyMismatchError(LedgerError):
    code = "currency_mismatch"
    status_code = 422


# -- ledger posting ----------------------------------------------------------


class UnbalancedEntryError(LedgerError):
    """Raised when a journal entry's debits do not equal its credits.

    This is the ledger's core safety net — it should be impossible to persist an
    entry that trips it. If it fires, posting logic has a bug.
    """

    code = "unbalanced_entry"
    status_code = 500


class PostingError(LedgerError):
    code = "posting_error"
    status_code = 422


# -- events ------------------------------------------------------------------


class UnknownEventTypeError(LedgerError):
    code = "unknown_event_type"
    status_code = 422


class EventValidationError(LedgerError):
    code = "event_validation_error"
    status_code = 422


# -- accounts / balances -----------------------------------------------------


class AccountNotFoundError(LedgerError):
    code = "account_not_found"
    status_code = 404


# -- payouts -----------------------------------------------------------------


class InsufficientBalanceError(LedgerError):
    code = "insufficient_balance"
    status_code = 409


class PayoutBatchNotFoundError(LedgerError):
    code = "payout_batch_not_found"
    status_code = 404


class GatewayError(LedgerError):
    """The upstream gateway rejected or failed a payout request."""

    code = "gateway_error"
    status_code = 502


# -- handlers ----------------------------------------------------------------


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the JSON error envelope for :class:`LedgerError` and generic errors."""

    @app.exception_handler(LedgerError)
    async def _ledger_error_handler(_: Request, exc: LedgerError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(ValueError)
    async def _value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "value_error", "message": str(exc), "detail": {}}},
        )
