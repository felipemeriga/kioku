package charges

import (
	"context"
	"testing"

	"github.com/obol/obol-gateway/internal/directory"
	"github.com/obol/obol-gateway/internal/events"
	"github.com/obol/obol-gateway/internal/money"
	"github.com/obol/obol-gateway/internal/pricing"
	"github.com/obol/obol-gateway/internal/processor"
)

func newTestService(t *testing.T) (*Service, *events.MemoryPublisher) {
	t.Helper()
	pricer, err := pricing.NewPricer(290, pricing.ProcessorFeeSchedule{Bps: 150, FixedMinor: 25})
	if err != nil {
		t.Fatal(err)
	}
	pub := events.NewMemoryPublisher()
	svc := NewService(
		NewMemoryRepository(),
		pricer,
		processor.NewMock(),
		pub,
		directory.NewSeeded(),
		nil,
	)
	return svc, pub
}

func TestCreateHappyPath(t *testing.T) {
	svc, pub := newTestService(t)

	// Mirrors chg_0001 from SPEC.md.
	c, err := svc.Create(context.Background(), CreateInput{
		PlatformID:     "plat_marisqueira",
		SellerID:       "sell_atelier",
		Amount:         money.MustNew(12000, "EUR"),
		CardToken:      "tok_visa",
		IdempotencyKey: "idem-chg-0001",
	})
	if err != nil {
		t.Fatalf("Create returned error: %v", err)
	}

	if c.Status != StatusSettled {
		t.Errorf("status = %s, want settled", c.Status)
	}
	if c.PlatformFee.AmountMinor != 348 {
		t.Errorf("platform_fee = %d, want 348", c.PlatformFee.AmountMinor)
	}
	if c.ProcessorFee.AmountMinor != 205 {
		t.Errorf("processor_fee = %d, want 205", c.ProcessorFee.AmountMinor)
	}
	if net := c.SellerNet(); net.AmountMinor != 11447 {
		t.Errorf("seller_net = %d, want 11447", net.AmountMinor)
	}
	if c.ProcessorRef == "" {
		t.Error("expected a processor_ref")
	}

	// Events emitted in causal order: authorized then settled.
	types := pub.TypesPublished()
	want := []events.Type{events.TypePaymentAuthorized, events.TypePaymentSettled}
	if len(types) != 2 || types[0] != want[0] || types[1] != want[1] {
		t.Fatalf("events published = %v, want %v", types, want)
	}
}

func TestCreateRejectsUnverifiedSeller(t *testing.T) {
	svc, _ := newTestService(t)
	// Seed an unverified seller.
	svc.dir.PutSeller(directory.Seller{
		ID: "sell_new", PlatformID: "plat_marisqueira",
		DisplayName: "New Co", KYCStatus: directory.KYCPending, PayoutCurrency: "EUR",
	})
	_, err := svc.Create(context.Background(), CreateInput{
		PlatformID: "plat_marisqueira", SellerID: "sell_new",
		Amount: money.MustNew(1000, "EUR"), CardToken: "tok",
	})
	if err != ErrSellerNotVerified {
		t.Fatalf("want ErrSellerNotVerified, got %v", err)
	}
}

func TestCreateRejectsCurrencyMismatch(t *testing.T) {
	svc, _ := newTestService(t)
	_, err := svc.Create(context.Background(), CreateInput{
		PlatformID: "plat_marisqueira", SellerID: "sell_atelier",
		Amount: money.MustNew(1000, "USD"), CardToken: "tok",
	})
	if err == nil {
		t.Fatal("expected currency mismatch error")
	}
}

func TestCreateDeclined(t *testing.T) {
	pricer, _ := pricing.NewPricer(290, pricing.ProcessorFeeSchedule{Bps: 150, FixedMinor: 25})
	pub := events.NewMemoryPublisher()
	svc := NewService(
		NewMemoryRepository(),
		pricer,
		&processor.Mock{DeclineOverAmountMinor: 5000},
		pub,
		directory.NewSeeded(),
		nil,
	)
	c, err := svc.Create(context.Background(), CreateInput{
		PlatformID: "plat_marisqueira", SellerID: "sell_atelier",
		Amount: money.MustNew(9000, "EUR"), CardToken: "tok",
	})
	if err != ErrDeclined {
		t.Fatalf("want ErrDeclined, got %v", err)
	}
	if c.Status != StatusFailed {
		t.Fatalf("status = %s, want failed", c.Status)
	}
	if len(pub.TypesPublished()) != 0 {
		t.Fatalf("declined charge must not publish events, got %v", pub.TypesPublished())
	}
}
