package api

import (
	"net/http"

	"github.com/obol/obol-gateway/internal/apierror"
	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/refunds"
)

// refundsHandler serves the refund endpoints. It is the gateway entry point for
// the end-to-end refund flow: console RefundButton -> BFF -> here ->
// processor.Refund -> refund.completed -> ledger reversal posting.
type refundsHandler struct {
	svc        *refunds.Service
	chargeRepo charges.Repository
}

func newRefundsHandler(svc *refunds.Service, chargeRepo charges.Repository) *refundsHandler {
	return &refundsHandler{svc: svc, chargeRepo: chargeRepo}
}

// create handles POST /v1/charges/{id}/refunds. An omitted amount refunds the
// full remaining balance.
func (h *refundsHandler) create(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	chargeID := r.PathValue("id")

	// Load the charge first for tenant isolation and to resolve currency/amount.
	charge, err := h.chargeRepo.Get(ctx, chargeID)
	if err != nil {
		apierror.Write(w, mapError(err))
		return
	}
	if charge.PlatformID != PlatformID(ctx) {
		apierror.Write(w, apierror.NotFound("charge not found"))
		return
	}

	var req createRefundRequest
	if _, err := decodeJSON(w, r, &req); err != nil {
		apierror.Write(w, mapError(err))
		return
	}

	// Default to the full remaining refundable balance.
	amount := charge.RemainingRefundable()
	if req.Amount != nil {
		amount = *req.Amount
		if amount.AmountMinor <= 0 {
			apierror.Write(w, apierror.InvalidRequest("amount.amount_minor must be greater than zero"))
			return
		}
	}

	refund, err := h.svc.Create(ctx, refunds.CreateInput{
		ChargeID: chargeID,
		Amount:   amount,
		Reason:   req.Reason,
	})
	if err != nil {
		apierror.Write(w, mapError(err))
		return
	}

	writeJSON(w, http.StatusCreated, toRefundResponse(refund))
}

// get handles GET /v1/refunds/{id}.
func (h *refundsHandler) get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	refund, err := h.svc.Get(r.Context(), id)
	if err != nil {
		apierror.Write(w, mapError(err))
		return
	}
	// Verify the parent charge belongs to the caller.
	charge, err := h.chargeRepo.Get(r.Context(), refund.ChargeID)
	if err != nil || charge.PlatformID != PlatformID(r.Context()) {
		apierror.Write(w, apierror.NotFound("refund not found"))
		return
	}
	writeJSON(w, http.StatusOK, toRefundResponse(refund))
}
