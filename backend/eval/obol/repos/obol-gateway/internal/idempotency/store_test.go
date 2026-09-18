package idempotency

import (
	"context"
	"errors"
	"testing"
)

func TestReserveThenReplay(t *testing.T) {
	ctx := context.Background()
	s := NewMemoryStore()
	hash := RequestHash([]byte(`{"amount":12000}`))

	// First request reserves the key.
	rec, replay, err := s.Reserve(ctx, "plat_marisqueira", "key-1", hash)
	if err != nil {
		t.Fatal(err)
	}
	if replay || rec != nil {
		t.Fatal("first Reserve should not be a replay")
	}

	// Operation completes and records its response.
	if err := s.Complete(ctx, "plat_marisqueira", "key-1", Record{
		RequestHash:  hash,
		StatusCode:   201,
		ResponseBody: []byte(`{"id":"chg_0001"}`),
	}); err != nil {
		t.Fatal(err)
	}

	// A retry with the same key + payload replays the saved response.
	got, replay, err := s.Reserve(ctx, "plat_marisqueira", "key-1", hash)
	if err != nil {
		t.Fatal(err)
	}
	if !replay {
		t.Fatal("second Reserve should be a replay")
	}
	if got.StatusCode != 201 || string(got.ResponseBody) != `{"id":"chg_0001"}` {
		t.Fatalf("replayed record mismatch: %+v", got)
	}
}

func TestReserveInFlightConflict(t *testing.T) {
	ctx := context.Background()
	s := NewMemoryStore()
	hash := RequestHash([]byte(`{}`))

	if _, _, err := s.Reserve(ctx, "plat_x", "k", hash); err != nil {
		t.Fatal(err)
	}
	// Second concurrent request before completion -> conflict.
	if _, _, err := s.Reserve(ctx, "plat_x", "k", hash); !errors.Is(err, ErrKeyInFlight) {
		t.Fatalf("want ErrKeyInFlight, got %v", err)
	}
}

func TestRequestMismatch(t *testing.T) {
	ctx := context.Background()
	s := NewMemoryStore()

	_, _, _ = s.Reserve(ctx, "plat_x", "k", RequestHash([]byte(`{"a":1}`)))
	_ = s.Complete(ctx, "plat_x", "k", Record{
		RequestHash: RequestHash([]byte(`{"a":1}`)),
		StatusCode:  201,
	})

	// Same key, different payload -> mismatch.
	if _, _, err := s.Reserve(ctx, "plat_x", "k", RequestHash([]byte(`{"a":2}`))); !errors.Is(err, ErrRequestMismatch) {
		t.Fatalf("want ErrRequestMismatch, got %v", err)
	}
}

func TestKeysScopedPerPlatform(t *testing.T) {
	ctx := context.Background()
	s := NewMemoryStore()
	hash := RequestHash([]byte(`{}`))

	_, _, _ = s.Reserve(ctx, "plat_a", "same-key", hash)
	// A different platform using the same key string is independent.
	if _, replay, err := s.Reserve(ctx, "plat_b", "same-key", hash); err != nil || replay {
		t.Fatalf("cross-platform key should be independent: replay=%v err=%v", replay, err)
	}
}

func TestReleaseAllowsReReserve(t *testing.T) {
	ctx := context.Background()
	s := NewMemoryStore()
	hash := RequestHash([]byte(`{}`))

	_, _, _ = s.Reserve(ctx, "plat_x", "k", hash)
	if err := s.Release(ctx, "plat_x", "k"); err != nil {
		t.Fatal(err)
	}
	if _, replay, err := s.Reserve(ctx, "plat_x", "k", hash); err != nil || replay {
		t.Fatalf("after release the key should be fresh: replay=%v err=%v", replay, err)
	}
}
