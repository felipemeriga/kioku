package api

import (
	"net/http"
	"time"

	"github.com/obol/obol-gateway/internal/apierror"
	"github.com/obol/obol-gateway/internal/payouts"
)

// payoutsHandler serves the payout endpoints. POST /v1/payouts is typically
// called by the ledger's payout-batch builder to actually move a seller's funds
// via the processor; on success the service emits payout.paid.
type payoutsHandler struct {
	svc *payouts.Service
}

func newPayoutsHandler(svc *payouts.Service) *payoutsHandler {
	return &payoutsHandler{svc: svc}
}

// create handles POST /v1/payouts.
func (h *payoutsHandler) create(w http.ResponseWriter, r *http.Request) {
	var req createPayoutRequest
	if _, err := decodeJSON(w, r, &req); err != nil {
		apierror.Write(w, mapError(err))
		return
	}

	if verr := validateCreatePayout(req); verr != nil {
		apierror.Write(w, verr)
		return
	}

	var scheduledFor time.Time
	if req.ScheduledFor != nil {
		scheduledFor = *req.ScheduledFor
	}

	batch, err := h.svc.Execute(r.Context(), payouts.ExecuteInput{
		BatchID:      req.BatchID,
		SellerID:     req.SellerID,
		Amount:       req.Amount,
		Descriptor:   req.Descriptor,
		ScheduledFor: scheduledFor,
	})
	if err != nil {
		apierror.Write(w, mapError(err))
		return
	}

	writeJSON(w, http.StatusCreated, toPayoutResponse(batch))
}

// get handles GET /v1/payouts/{id}.
func (h *payoutsHandler) get(w http.ResponseWriter, r *http.Request) {
	batch, err := h.svc.Get(r.Context(), r.PathValue("id"))
	if err != nil {
		apierror.Write(w, mapError(err))
		return
	}
	writeJSON(w, http.StatusOK, toPayoutResponse(batch))
}

func validateCreatePayout(req createPayoutRequest) *apierror.Error {
	details := map[string]string{}
	if req.SellerID == "" {
		details["seller_id"] = "required"
	}
	if req.Amount.AmountMinor <= 0 {
		details["amount.amount_minor"] = "must be greater than zero"
	}
	if req.Amount.Currency == "" {
		details["amount.currency"] = "required"
	}
	if len(details) > 0 {
		return apierror.InvalidRequest("invalid payout request").WithDetails(details)
	}
	return nil
}
