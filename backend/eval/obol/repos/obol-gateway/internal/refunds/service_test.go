package refunds

import (
	"context"
	"testing"
	"time"

	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/events"
	"github.com/obol/obol-gateway/internal/money"
	"github.com/obol/obol-gateway/internal/processor"
)

func seedSettledCharge(t *testing.T, repo charges.Repository) charges.Charge {
	t.Helper()
	zero, _ := money.Zero("EUR")
	c := charges.Charge{
		ID:             "chg_0001",
		PlatformID:     "plat_marisqueira",
		SellerID:       "sell_atelier",
		Amount:         money.MustNew(12000, "EUR"),
		PlatformFee:    money.MustNew(348, "EUR"),
		ProcessorFee:   money.MustNew(205, "EUR"),
		Status:         charges.StatusSettled,
		ProcessorRef:   "pi_deadbeef",
		CreatedAt:      time.Now().UTC(),
		AmountRefunded: zero,
	}
	if err := repo.Create(context.Background(), c); err != nil {
		t.Fatal(err)
	}
	return c
}

func newService(t *testing.T, chargeRepo charges.Repository) (*Service, *events.MemoryPublisher) {
	t.Helper()
	pub := events.NewMemoryPublisher()
	svc := NewService(NewMemoryRepository(), chargeRepo, processor.NewMock(), pub, nil)
	return svc, pub
}

func TestFullRefundEmitsCompleted(t *testing.T) {
	chargeRepo := charges.NewMemoryRepository()
	seedSettledCharge(t, chargeRepo)
	svc, pub := newService(t, chargeRepo)

	r, err := svc.Create(context.Background(), CreateInput{
		ChargeID: "chg_0001",
		Amount:   money.MustNew(12000, "EUR"),
		Reason:   "customer_request",
	})
	if err != nil {
		t.Fatalf("Create error: %v", err)
	}
	if r.Status != StatusCompleted {
		t.Errorf("status = %s, want completed", r.Status)
	}
	if r.ProcessorRef == "" {
		t.Error("expected processor_ref from mock")
	}

	// refund.completed emitted.
	types := pub.TypesPublished()
	if len(types) != 1 || types[0] != events.TypeRefundCompleted {
		t.Fatalf("events = %v, want [refund.completed]", types)
	}

	// Charge flipped to fully refunded.
	c, _ := chargeRepo.Get(context.Background(), "chg_0001")
	if c.Status != charges.StatusRefunded {
		t.Errorf("charge status = %s, want refunded", c.Status)
	}
}

func TestPartialRefund(t *testing.T) {
	chargeRepo := charges.NewMemoryRepository()
	seedSettledCharge(t, chargeRepo)
	svc, _ := newService(t, chargeRepo)

	if _, err := svc.Create(context.Background(), CreateInput{
		ChargeID: "chg_0001", Amount: money.MustNew(5000, "EUR"), Reason: "partial",
	}); err != nil {
		t.Fatal(err)
	}

	c, _ := chargeRepo.Get(context.Background(), "chg_0001")
	if c.Status != charges.StatusPartiallyRefunded {
		t.Errorf("status = %s, want partially_refunded", c.Status)
	}
	if c.AmountRefunded.AmountMinor != 5000 {
		t.Errorf("amount_refunded = %d, want 5000", c.AmountRefunded.AmountMinor)
	}
}

func TestRefundExceedingRemainingRejected(t *testing.T) {
	chargeRepo := charges.NewMemoryRepository()
	seedSettledCharge(t, chargeRepo)
	svc, _ := newService(t, chargeRepo)

	// First refund 8000, then try 5000 (only 4000 left).
	_, _ = svc.Create(context.Background(), CreateInput{
		ChargeID: "chg_0001", Amount: money.MustNew(8000, "EUR"),
	})
	_, err := svc.Create(context.Background(), CreateInput{
		ChargeID: "chg_0001", Amount: money.MustNew(5000, "EUR"),
	})
	if err == nil {
		t.Fatal("expected ErrExceedsRefundable")
	}
}
