// Package idempotency is the ground-truth location for Obol's idempotency
// handling. The public API requires an `Idempotency-Key` header on mutating
// requests (notably POST /v1/charges). This package stores the first response
// produced for a given key and replays it for any retry, so a client that
// retries after a network blip never double-charges a buyer.
//
// The store is checked BEFORE any processor call (SPEC.md > cross-repo
// relationship #3): a hit short-circuits the handler and replays the saved
// response; a miss reserves the key, runs the operation, then records the
// result under that key.
package idempotency

import (
	"context"
	"errors"
	"sync"
	"time"
)

// ErrKeyInFlight is returned when a request arrives for a key whose original
// request is still being processed (a concurrent duplicate). Callers should
// respond 409 Conflict and let the client retry.
var ErrKeyInFlight = errors.New("idempotency: key already in flight")

// Record is the persisted outcome of a completed idempotent operation. The
// stored response body and status are replayed verbatim on a retry.
type Record struct {
	Key          string
	RequestHash  string // fingerprint of the request payload, to detect key reuse
	StatusCode   int    // HTTP status of the original response
	ResponseBody []byte // serialized original response
	CreatedAt    time.Time
}

// Store persists idempotency records keyed by the Idempotency-Key header,
// scoped per platform so keys never collide across tenants.
type Store interface {
	// Reserve attempts to claim a key for a new operation. It returns:
	//   - (existing, true, nil)   when a completed record already exists (replay),
	//   - (nil, false, nil)       when the key was newly reserved (proceed),
	//   - (nil, false, ErrKeyInFlight) when another request holds the key.
	Reserve(ctx context.Context, platformID, key, requestHash string) (*Record, bool, error)

	// Complete stores the final response for a previously-reserved key.
	Complete(ctx context.Context, platformID, key string, rec Record) error

	// Release drops a reservation without recording a result (used when an
	// operation fails before producing a replayable response).
	Release(ctx context.Context, platformID, key string) error
}

// ErrRequestMismatch is returned when a key is reused with a different request
// payload than the original. Per convention this is a client error (422).
var ErrRequestMismatch = errors.New("idempotency: key reused with different request")

// scopedKey namespaces keys by platform.
func scopedKey(platformID, key string) string { return platformID + ":" + key }

// entry is the internal state machine for a single key.
type entry struct {
	inFlight    bool
	requestHash string
	record      *Record
}

// MemoryStore is an in-memory, concurrency-safe Store implementation suitable
// for a single-node deployment or tests. A production deployment would back
// this with Redis or Postgres, but the interface is identical.
type MemoryStore struct {
	mu      sync.Mutex
	entries map[string]*entry
}

// NewMemoryStore constructs an empty in-memory store.
func NewMemoryStore() *MemoryStore {
	return &MemoryStore{entries: make(map[string]*entry)}
}

// Reserve implements Store.
func (s *MemoryStore) Reserve(_ context.Context, platformID, key, requestHash string) (*Record, bool, error) {
	sk := scopedKey(platformID, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	e, ok := s.entries[sk]
	if !ok {
		// First time we've seen this key: reserve it in-flight.
		s.entries[sk] = &entry{inFlight: true, requestHash: requestHash}
		return nil, false, nil
	}

	// A completed record exists -> replay it, but only if the payload matches.
	if e.record != nil {
		if e.requestHash != requestHash {
			return nil, false, ErrRequestMismatch
		}
		return e.record, true, nil
	}

	// Reserved but not yet completed -> a concurrent duplicate.
	if e.inFlight {
		return nil, false, ErrKeyInFlight
	}

	// Released without a record -> treat as fresh and re-reserve.
	e.inFlight = true
	e.requestHash = requestHash
	return nil, false, nil
}

// Complete implements Store.
func (s *MemoryStore) Complete(_ context.Context, platformID, key string, rec Record) error {
	sk := scopedKey(platformID, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	e, ok := s.entries[sk]
	if !ok {
		e = &entry{}
		s.entries[sk] = e
	}
	rec.Key = key
	if rec.CreatedAt.IsZero() {
		rec.CreatedAt = time.Now().UTC()
	}
	e.inFlight = false
	e.record = &rec
	e.requestHash = rec.RequestHash
	return nil
}

// Release implements Store.
func (s *MemoryStore) Release(_ context.Context, platformID, key string) error {
	sk := scopedKey(platformID, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	if e, ok := s.entries[sk]; ok && e.record == nil {
		delete(s.entries, sk)
	}
	return nil
}
