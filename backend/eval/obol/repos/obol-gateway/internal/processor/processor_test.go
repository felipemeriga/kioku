package processor

import (
	"context"
	"errors"
	"testing"

	"github.com/obol/obol-gateway/internal/money"
)

func TestChargeDeterministicRef(t *testing.T) {
	m := NewMock()
	req := ChargeRequest{ChargeID: "chg_0001", Amount: money.MustNew(12000, "EUR"), CardToken: "tok_visa"}

	r1, err := m.Charge(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	r2, _ := m.Charge(context.Background(), req)
	if r1.ProcessorRef != r2.ProcessorRef {
		t.Fatalf("processor ref not deterministic: %s vs %s", r1.ProcessorRef, r2.ProcessorRef)
	}
	if r1.Outcome != OutcomeApproved {
		t.Fatalf("expected approved, got %s", r1.Outcome)
	}
}

func TestChargeDeclineOverThreshold(t *testing.T) {
	m := &Mock{DeclineOverAmountMinor: 10000}
	_, err := m.Charge(context.Background(), ChargeRequest{
		ChargeID: "chg_big", Amount: money.MustNew(20000, "EUR"), CardToken: "tok",
	})
	if !errors.Is(err, ErrDeclined) {
		t.Fatalf("want ErrDeclined, got %v", err)
	}
}

func TestRefundRequiresOriginalRef(t *testing.T) {
	m := NewMock()
	_, err := m.Refund(context.Background(), RefundRequest{
		RefundID: "rfnd_1", Amount: money.MustNew(100, "EUR"),
	})
	if err == nil {
		t.Fatal("expected error when original ref missing")
	}
}

func TestPayoutApproves(t *testing.T) {
	m := NewMock()
	res, err := m.Payout(context.Background(), PayoutRequest{
		BatchID: "pyt_1", SellerID: "sell_atelier", Amount: money.MustNew(11447, "EUR"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.Outcome != OutcomeApproved || res.ProcessorRef == "" {
		t.Fatalf("unexpected payout result: %+v", res)
	}
}
