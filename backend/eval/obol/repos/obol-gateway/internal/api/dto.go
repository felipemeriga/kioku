package api

import (
	"time"

	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/money"
	"github.com/obol/obol-gateway/internal/payouts"
	"github.com/obol/obol-gateway/internal/refunds"
)

// --- charge DTOs ---

// createChargeRequest is the POST /v1/charges body.
type createChargeRequest struct {
	SellerID string      `json:"seller_id"`
	Amount   money.Money `json:"amount"`
	// CardToken is the tokenized payment instrument (mocked).
	CardToken string `json:"card_token"`
	// Descriptor is the optional statement descriptor.
	Descriptor string `json:"descriptor,omitempty"`
	// PlatformFeeBps optionally overrides the platform's default fee rate.
	PlatformFeeBps *int64 `json:"platform_fee_bps,omitempty"`
}

// chargeResponse is the JSON shape returned for a charge. It mirrors the SPEC
// Charge fields plus the derived seller_net.
type chargeResponse struct {
	ID             string      `json:"id"`
	PlatformID     string      `json:"platform_id"`
	SellerID       string      `json:"seller_id"`
	Amount         money.Money `json:"amount"`
	PlatformFee    money.Money `json:"platform_fee"`
	ProcessorFee   money.Money `json:"processor_fee"`
	SellerNet      money.Money `json:"seller_net"`
	Status         string      `json:"status"`
	ProcessorRef   string      `json:"processor_ref"`
	IdempotencyKey string      `json:"idempotency_key"`
	CreatedAt      time.Time   `json:"created_at"`
}

func toChargeResponse(c charges.Charge) chargeResponse {
	return chargeResponse{
		ID:             c.ID,
		PlatformID:     c.PlatformID,
		SellerID:       c.SellerID,
		Amount:         c.Amount,
		PlatformFee:    c.PlatformFee,
		ProcessorFee:   c.ProcessorFee,
		SellerNet:      c.SellerNet(),
		Status:         string(c.Status),
		ProcessorRef:   c.ProcessorRef,
		IdempotencyKey: c.IdempotencyKey,
		CreatedAt:      c.CreatedAt,
	}
}

// --- refund DTOs ---

// createRefundRequest is the POST /v1/charges/{id}/refunds body.
type createRefundRequest struct {
	// Amount is optional; when omitted the full remaining balance is refunded.
	Amount *money.Money `json:"amount,omitempty"`
	Reason string       `json:"reason,omitempty"`
}

// refundResponse is the JSON shape returned for a refund.
type refundResponse struct {
	ID           string      `json:"id"`
	ChargeID     string      `json:"charge_id"`
	Amount       money.Money `json:"amount"`
	Reason       string      `json:"reason,omitempty"`
	Status       string      `json:"status"`
	ProcessorRef string      `json:"processor_ref"`
	CreatedAt    time.Time   `json:"created_at"`
}

func toRefundResponse(r refunds.Refund) refundResponse {
	return refundResponse{
		ID:           r.ID,
		ChargeID:     r.ChargeID,
		Amount:       r.Amount,
		Reason:       r.Reason,
		Status:       string(r.Status),
		ProcessorRef: r.ProcessorRef,
		CreatedAt:    r.CreatedAt,
	}
}

// --- payout DTOs ---

// createPayoutRequest is the POST /v1/payouts body. It is typically called by
// the ledger's payout-batch builder, which supplies the batch_id it created.
type createPayoutRequest struct {
	BatchID      string      `json:"batch_id,omitempty"`
	SellerID     string      `json:"seller_id"`
	Amount       money.Money `json:"amount"`
	Descriptor   string      `json:"descriptor,omitempty"`
	ScheduledFor *time.Time  `json:"scheduled_for,omitempty"`
}

// payoutResponse is the JSON shape returned for a payout batch.
type payoutResponse struct {
	ID           string      `json:"id"`
	SellerID     string      `json:"seller_id"`
	Amount       money.Money `json:"amount"`
	Status       string      `json:"status"`
	ScheduledFor time.Time   `json:"scheduled_for"`
	ProcessorRef string      `json:"processor_ref"`
	CreatedAt    time.Time   `json:"created_at"`
}

func toPayoutResponse(b payouts.PayoutBatch) payoutResponse {
	return payoutResponse{
		ID:           b.ID,
		SellerID:     b.SellerID,
		Amount:       b.Amount,
		Status:       string(b.Status),
		ScheduledFor: b.ScheduledFor,
		ProcessorRef: b.ProcessorRef,
		CreatedAt:    b.CreatedAt,
	}
}
