"""Payout batch building — ground-truth payout logic.

- :class:`GatewayClient` — thin httpx wrapper over gateway ``POST /v1/payouts``.
- :class:`PayoutBuilder` — builds a batch from a seller's ``seller_payable``
  balance, submits it to the gateway, and (on ``payout.paid``) posts the
  balancing journal entry that debits ``seller_payable``.
"""

from .gateway_client import GatewayClient, PayoutRequest, PayoutResponse
from .builder import PayoutBuilder

__all__ = ["GatewayClient", "PayoutRequest", "PayoutResponse", "PayoutBuilder"]
