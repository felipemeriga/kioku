package api

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"

	"github.com/obol/obol-gateway/internal/apierror"
	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/idempotency"
)

// chargesHandler serves the charge endpoints.
type chargesHandler struct {
	svc  *charges.Service
	idem idempotency.Store
}

func newChargesHandler(svc *charges.Service, idem idempotency.Store) *chargesHandler {
	return &chargesHandler{svc: svc, idem: idem}
}

// create handles POST /v1/charges. It enforces idempotency BEFORE any processor
// call: the Idempotency-Key header is reserved/checked in the idempotency store,
// and on a hit the original response is replayed verbatim.
func (h *chargesHandler) create(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	platformID := PlatformID(ctx)

	key := r.Header.Get("Idempotency-Key")
	if key == "" {
		apierror.Write(w, apierror.InvalidRequest("Idempotency-Key header is required"))
		return
	}

	// decodeJSON fills req and also returns the raw bytes we need for the
	// idempotency request hash.
	var req createChargeRequest
	raw, err := decodeJSON(w, r, &req)
	if err != nil {
		apierror.Write(w, mapError(err))
		return
	}

	if verr := validateCreateCharge(req); verr != nil {
		apierror.Write(w, verr)
		return
	}

	reqHash := idempotency.RequestHash(canonicalize(raw))

	// Idempotency gate — before the processor is ever touched.
	existing, replay, err := h.idem.Reserve(ctx, platformID, key, reqHash)
	if err != nil {
		apierror.Write(w, mapError(err))
		return
	}
	if replay {
		replayRecord(w, existing)
		return
	}

	// Run the charge. On any failure, release the reservation so a corrected
	// retry can proceed (unless it's a business decline, which we record).
	charge, err := h.svc.Create(ctx, charges.CreateInput{
		PlatformID:             platformID,
		SellerID:               req.SellerID,
		Amount:                 req.Amount,
		CardToken:              req.CardToken,
		Descriptor:             req.Descriptor,
		IdempotencyKey:         key,
		PlatformFeeBpsOverride: req.PlatformFeeBps,
	})
	if err != nil && !errors.Is(err, charges.ErrDeclined) {
		_ = h.idem.Release(ctx, platformID, key)
		apierror.Write(w, mapError(err))
		return
	}

	status := http.StatusCreated
	var payload any = toChargeResponse(charge)
	if errors.Is(err, charges.ErrDeclined) {
		// Declines are a deterministic outcome; record them so a retry replays.
		status = http.StatusPaymentRequired
		payload = apierror.PaymentDeclined("the card processor declined this charge")
	}

	body := mustJSON(payload)
	_ = h.idem.Complete(ctx, platformID, key, idempotency.Record{
		RequestHash:  reqHash,
		StatusCode:   status,
		ResponseBody: body,
	})

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// get handles GET /v1/charges/{id}.
func (h *chargesHandler) get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	c, err := h.svc.Get(r.Context(), id)
	if err != nil {
		apierror.Write(w, mapError(err))
		return
	}
	// Tenant isolation: a platform can only read its own charges.
	if c.PlatformID != PlatformID(r.Context()) {
		apierror.Write(w, apierror.NotFound("charge not found"))
		return
	}
	writeJSON(w, http.StatusOK, toChargeResponse(c))
}

func validateCreateCharge(req createChargeRequest) *apierror.Error {
	details := map[string]string{}
	if req.SellerID == "" {
		details["seller_id"] = "required"
	}
	if req.CardToken == "" {
		details["card_token"] = "required"
	}
	if req.Amount.AmountMinor <= 0 {
		details["amount.amount_minor"] = "must be greater than zero"
	}
	if req.Amount.Currency == "" {
		details["amount.currency"] = "required"
	}
	if req.PlatformFeeBps != nil && *req.PlatformFeeBps < 0 {
		details["platform_fee_bps"] = "must be >= 0"
	}
	if len(details) > 0 {
		return apierror.InvalidRequest("invalid charge request").WithDetails(details)
	}
	return nil
}

// replayRecord writes a previously-stored idempotent response verbatim.
func replayRecord(w http.ResponseWriter, rec *idempotency.Record) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Idempotent-Replayed", "true")
	w.WriteHeader(rec.StatusCode)
	_, _ = w.Write(rec.ResponseBody)
}

// canonicalize normalizes a JSON body so semantically-equal requests hash the
// same (e.g. key ordering, insignificant whitespace).
func canonicalize(raw []byte) []byte {
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return raw
	}
	out, err := json.Marshal(v)
	if err != nil {
		return raw
	}
	return out
}

func mustJSON(v any) []byte {
	var buf bytes.Buffer
	if err := json.NewEncoder(&buf).Encode(v); err != nil {
		return []byte(`{"error":{"code":"internal_error","message":"encode failed"}}`)
	}
	return bytes.TrimRight(buf.Bytes(), "\n")
}
