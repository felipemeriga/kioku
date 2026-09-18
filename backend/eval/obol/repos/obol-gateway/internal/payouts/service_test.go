package payouts

import (
	"context"
	"testing"

	"github.com/obol/obol-gateway/internal/directory"
	"github.com/obol/obol-gateway/internal/events"
	"github.com/obol/obol-gateway/internal/money"
	"github.com/obol/obol-gateway/internal/processor"
)

func TestExecuteEmitsScheduledThenPaid(t *testing.T) {
	pub := events.NewMemoryPublisher()
	svc := NewService(NewMemoryRepository(), processor.NewMock(), pub, directory.NewSeeded(), nil)

	b, err := svc.Execute(context.Background(), ExecuteInput{
		SellerID: "sell_atelier",
		Amount:   money.MustNew(11447, "EUR"),
	})
	if err != nil {
		t.Fatalf("Execute error: %v", err)
	}
	if b.Status != StatusPaid {
		t.Errorf("status = %s, want paid", b.Status)
	}
	if b.ProcessorRef == "" {
		t.Error("expected processor_ref")
	}

	types := pub.TypesPublished()
	want := []events.Type{events.TypePayoutScheduled, events.TypePayoutPaid}
	if len(types) != 2 || types[0] != want[0] || types[1] != want[1] {
		t.Fatalf("events = %v, want %v", types, want)
	}
}

func TestExecuteDeclined(t *testing.T) {
	pub := events.NewMemoryPublisher()
	svc := NewService(NewMemoryRepository(), &processor.Mock{DeclineOverAmountMinor: 1000}, pub, directory.NewSeeded(), nil)

	b, err := svc.Execute(context.Background(), ExecuteInput{
		SellerID: "sell_atelier", Amount: money.MustNew(5000, "EUR"),
	})
	if err != ErrDeclined {
		t.Fatalf("want ErrDeclined, got %v", err)
	}
	if b.Status != StatusFailed {
		t.Fatalf("status = %s, want failed", b.Status)
	}
}
