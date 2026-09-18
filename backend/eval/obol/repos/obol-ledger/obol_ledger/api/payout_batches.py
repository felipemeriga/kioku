"""Payout batch endpoints.

- ``POST /v1/payout-batches`` builds a batch from a seller's payable balance and
  submits it to the gateway.
- ``GET  /v1/payout-batches/{batch_id}`` fetches a batch.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..state import LedgerState, get_state
from .schemas import CreatePayoutBatchRequest, PayoutBatchResponse

router = APIRouter(prefix="/v1/payout-batches", tags=["payouts"])


@router.post("", response_model=PayoutBatchResponse, status_code=201)
async def create_payout_batch(
    body: CreatePayoutBatchRequest, state: LedgerState = Depends(get_state)
) -> PayoutBatchResponse:
    """Build a payout batch from the seller's payable balance and submit it.

    Delegates to gateway ``POST /v1/payouts`` to actually move money; the batch
    is returned in ``processing`` until a ``payout.paid`` event settles it.
    """
    batch = await state.payout_builder.build_and_submit(
        seller_id=body.seller_id, amount=body.amount
    )
    return PayoutBatchResponse.from_batch(batch)


@router.get("/{batch_id}", response_model=PayoutBatchResponse)
async def get_payout_batch(
    batch_id: str, state: LedgerState = Depends(get_state)
) -> PayoutBatchResponse:
    """Fetch a payout batch by id."""
    batch = state.payout_builder.get_batch(batch_id)
    return PayoutBatchResponse.from_batch(batch)
