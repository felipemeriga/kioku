// Package events defines the event envelope and payloads the gateway publishes
// and the obol-ledger consumes. The gateway is the sole producer; it never does
// accounting itself — it emits facts and lets the ledger post journal entries.
//
// Every event shares the envelope { id, type, ts, data } (SPEC.md > Events).
// Consumers must be idempotent on event.id, and events for a single charge are
// emitted in causal order (authorized -> settled -> refunded).
package events

import (
	"encoding/json"
	"time"

	"github.com/obol/obol-gateway/internal/ids"
	"github.com/obol/obol-gateway/internal/money"
)

// Type is the discriminator for the event's data payload.
type Type string

// The event types the gateway emits, matching SPEC.md exactly.
const (
	TypePaymentAuthorized Type = "payment.authorized"
	TypePaymentSettled    Type = "payment.settled"
	TypeRefundCompleted   Type = "refund.completed"
	TypePayoutScheduled   Type = "payout.scheduled"
	TypePayoutPaid        Type = "payout.paid"
)

// Envelope is the outer shape shared by all events: { id, type, ts, data }.
type Envelope struct {
	ID   string          `json:"id"`
	Type Type            `json:"type"`
	TS   time.Time       `json:"ts"`
	Data json.RawMessage `json:"data"`
}

// --- data payloads, one struct per event type ---

// PaymentData is the payload for payment.authorized and payment.settled.
type PaymentData struct {
	ChargeID     string      `json:"charge_id"`
	PlatformID   string      `json:"platform_id"`
	SellerID     string      `json:"seller_id"`
	Amount       money.Money `json:"amount"`
	PlatformFee  money.Money `json:"platform_fee"`
	ProcessorFee money.Money `json:"processor_fee"`
}

// RefundData is the payload for refund.completed.
type RefundData struct {
	RefundID string      `json:"refund_id"`
	ChargeID string      `json:"charge_id"`
	Amount   money.Money `json:"amount"`
}

// PayoutScheduledData is the payload for payout.scheduled.
type PayoutScheduledData struct {
	BatchID      string      `json:"batch_id"`
	SellerID     string      `json:"seller_id"`
	Amount       money.Money `json:"amount"`
	ScheduledFor time.Time   `json:"scheduled_for"`
}

// PayoutPaidData is the payload for payout.paid.
type PayoutPaidData struct {
	BatchID      string      `json:"batch_id"`
	SellerID     string      `json:"seller_id"`
	Amount       money.Money `json:"amount"`
	ProcessorRef string      `json:"processor_ref"`
}

// newEnvelope marshals a data payload into an envelope with a fresh event id
// and the current UTC timestamp.
func newEnvelope(t Type, data any) (Envelope, error) {
	raw, err := json.Marshal(data)
	if err != nil {
		return Envelope{}, err
	}
	return Envelope{
		ID:   ids.Event(),
		Type: t,
		TS:   time.Now().UTC(),
		Data: raw,
	}, nil
}

// --- constructors: one per event type ---

// PaymentAuthorized builds a payment.authorized event.
func PaymentAuthorized(d PaymentData) (Envelope, error) {
	return newEnvelope(TypePaymentAuthorized, d)
}

// PaymentSettled builds a payment.settled event (ledger posts the settlement).
func PaymentSettled(d PaymentData) (Envelope, error) {
	return newEnvelope(TypePaymentSettled, d)
}

// RefundCompleted builds a refund.completed event (ledger posts the reversal).
func RefundCompleted(d RefundData) (Envelope, error) {
	return newEnvelope(TypeRefundCompleted, d)
}

// PayoutScheduled builds a payout.scheduled event.
func PayoutScheduled(d PayoutScheduledData) (Envelope, error) {
	return newEnvelope(TypePayoutScheduled, d)
}

// PayoutPaid builds a payout.paid event (ledger marks the batch paid).
func PayoutPaid(d PayoutPaidData) (Envelope, error) {
	return newEnvelope(TypePayoutPaid, d)
}
