package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/directory"
	"github.com/obol/obol-gateway/internal/events"
	"github.com/obol/obol-gateway/internal/idempotency"
	"github.com/obol/obol-gateway/internal/payouts"
	"github.com/obol/obol-gateway/internal/pricing"
	"github.com/obol/obol-gateway/internal/processor"
	"github.com/obol/obol-gateway/internal/refunds"
)

func newTestServer(t *testing.T) http.Handler {
	t.Helper()
	pricer, _ := pricing.NewPricer(290, pricing.ProcessorFeeSchedule{Bps: 150, FixedMinor: 25})
	proc := processor.NewMock()
	pub := events.NewMemoryPublisher()
	dir := directory.NewSeeded()

	chargeRepo := charges.NewMemoryRepository()
	chargeSvc := charges.NewService(chargeRepo, pricer, proc, pub, dir, nil)
	refundSvc := refunds.NewService(refunds.NewMemoryRepository(), chargeRepo, proc, pub, nil)
	payoutSvc := payouts.NewService(payouts.NewMemoryRepository(), proc, pub, dir, nil)

	return NewRouter(Deps{
		ChargeService: chargeSvc,
		ChargeRepo:    chargeRepo,
		RefundService: refundSvc,
		PayoutService: payoutSvc,
		Idempotency:   idempotency.NewMemoryStore(),
		Authenticator: NewKeyring(map[string]string{"sk_test": "plat_marisqueira"}),
	})
}

func postCharge(t *testing.T, h http.Handler, idemKey, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/v1/charges", bytes.NewBufferString(body))
	req.Header.Set("Authorization", "Bearer sk_test")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", idemKey)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestChargeCreateAndIdempotentReplay(t *testing.T) {
	h := newTestServer(t)
	body := `{"seller_id":"sell_atelier","amount":{"amount_minor":12000,"currency":"EUR"},"card_token":"tok_visa"}`

	first := postCharge(t, h, "idem-1", body)
	if first.Code != http.StatusCreated {
		t.Fatalf("first status = %d, body=%s", first.Code, first.Body.String())
	}
	var got chargeResponse
	if err := json.Unmarshal(first.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got.PlatformFee.AmountMinor != 348 || got.ProcessorFee.AmountMinor != 205 || got.SellerNet.AmountMinor != 11447 {
		t.Fatalf("fee breakdown wrong: %+v", got)
	}

	// Retry with the same key + body replays the exact same response.
	second := postCharge(t, h, "idem-1", body)
	if second.Code != http.StatusCreated {
		t.Fatalf("replay status = %d", second.Code)
	}
	if second.Header().Get("Idempotent-Replayed") != "true" {
		t.Error("expected Idempotent-Replayed: true on retry")
	}
	if first.Body.String() != second.Body.String() {
		t.Errorf("replay body differs:\n first=%s\nsecond=%s", first.Body.String(), second.Body.String())
	}
}

func TestChargeRequiresIdempotencyKey(t *testing.T) {
	h := newTestServer(t)
	req := httptest.NewRequest(http.MethodPost, "/v1/charges",
		bytes.NewBufferString(`{"seller_id":"sell_atelier","amount":{"amount_minor":100,"currency":"EUR"},"card_token":"t"}`))
	req.Header.Set("Authorization", "Bearer sk_test")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestUnauthorized(t *testing.T) {
	h := newTestServer(t)
	req := httptest.NewRequest(http.MethodGet, "/v1/charges/chg_x", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", rec.Code)
	}
}

func TestRefundFlowThroughHTTP(t *testing.T) {
	h := newTestServer(t)
	body := `{"seller_id":"sell_atelier","amount":{"amount_minor":12000,"currency":"EUR"},"card_token":"tok_visa"}`
	created := postCharge(t, h, "idem-refund", body)
	var chg chargeResponse
	_ = json.Unmarshal(created.Body.Bytes(), &chg)

	req := httptest.NewRequest(http.MethodPost, "/v1/charges/"+chg.ID+"/refunds",
		bytes.NewBufferString(`{"reason":"customer_request"}`))
	req.Header.Set("Authorization", "Bearer sk_test")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("refund status = %d, body=%s", rec.Code, rec.Body.String())
	}
	var rf refundResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &rf)
	if rf.Status != "completed" || rf.Amount.AmountMinor != 12000 {
		t.Fatalf("unexpected refund: %+v", rf)
	}
}
