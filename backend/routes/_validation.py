"""Shared request-validation helpers for route handlers."""

import uuid as _uuid

from fastapi import HTTPException


def is_uuid(value: str) -> bool:
    """True iff `value` is a well-formed UUID string."""
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def require_uuid(value: str, detail: str = "Not found") -> None:
    """Guard an id path/query param before it reaches a uuid DB column.

    A non-UUID id can never match a real row, and passing it into Postgres's
    uuid type raises 22P02 ('invalid input syntax for type uuid') which
    surfaces as an uncaught 500. Raise 404 instead — the same result a
    well-formed-but-nonexistent id produces.
    """
    if not is_uuid(value):
        raise HTTPException(status_code=404, detail=detail)
