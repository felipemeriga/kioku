"""HTTP client for the gateway payout endpoint.

The ledger does not touch the card network directly. To actually move money it
calls the gateway's ``POST /v1/payouts`` (SPEC cross-repo relationship #4). The
gateway executes the payout via its processor adapter and later emits
``payout.paid``, which the ledger consumes to mark the batch paid.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from ..config import Settings, get_settings
from ..errors import GatewayError
from ..money import Money


class PayoutRequest(BaseModel):
    """Body sent to gateway ``POST /v1/payouts``."""

    batch_id: str
    seller_id: str
    amount: Money


class PayoutResponse(BaseModel):
    """Relevant fields of the gateway payout response."""

    batch_id: str
    status: str
    processor_ref: str | None = None


class GatewayClient:
    """Thin async wrapper over the gateway's payout endpoint."""

    def __init__(
        self, settings: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client  # injectable for tests

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.gateway_token:
            headers["Authorization"] = f"Bearer {self._settings.gateway_token}"
        return headers

    async def create_payout(self, request: PayoutRequest) -> PayoutResponse:
        """POST a payout to the gateway; raise :class:`GatewayError` on failure."""
        payload = {
            "batch_id": request.batch_id,
            "seller_id": request.seller_id,
            "amount": {
                "amount_minor": request.amount.amount_minor,
                "currency": request.amount.currency,
            },
        }

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._settings.gateway_timeout)
        try:
            resp = await client.post(
                self._settings.payouts_url, json=payload, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise GatewayError(
                "failed to reach gateway payout endpoint",
                detail={"url": self._settings.payouts_url, "cause": str(exc)},
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        if resp.status_code >= 400:
            raise GatewayError(
                "gateway rejected payout",
                detail={"status_code": resp.status_code, "body": _safe_body(resp)},
            )

        body = resp.json()
        return PayoutResponse(
            batch_id=body.get("batch_id", request.batch_id),
            status=body.get("status", "processing"),
            processor_ref=body.get("processor_ref"),
        )


def _safe_body(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except Exception:  # pragma: no cover - defensive
        return resp.text
