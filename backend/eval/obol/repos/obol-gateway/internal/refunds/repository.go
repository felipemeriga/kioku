package refunds

import (
	"context"
	"errors"
	"sync"
)

// ErrNotFound is returned when a refund id is unknown.
var ErrNotFound = errors.New("refunds: refund not found")

// Repository persists refunds.
type Repository interface {
	Create(ctx context.Context, r Refund) error
	Get(ctx context.Context, id string) (Refund, error)
	ListByCharge(ctx context.Context, chargeID string) ([]Refund, error)
}

// MemoryRepository is a concurrency-safe in-memory Repository.
type MemoryRepository struct {
	mu      sync.RWMutex
	refunds map[string]Refund
}

// NewMemoryRepository returns an empty in-memory refund repository.
func NewMemoryRepository() *MemoryRepository {
	return &MemoryRepository{refunds: make(map[string]Refund)}
}

// Create stores a new refund.
func (r *MemoryRepository) Create(_ context.Context, rf Refund) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.refunds[rf.ID]; exists {
		return errors.New("refunds: duplicate refund id")
	}
	r.refunds[rf.ID] = rf
	return nil
}

// Get returns the refund with the given id.
func (r *MemoryRepository) Get(_ context.Context, id string) (Refund, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	rf, ok := r.refunds[id]
	if !ok {
		return Refund{}, ErrNotFound
	}
	return rf, nil
}

// ListByCharge returns all refunds recorded against a charge.
func (r *MemoryRepository) ListByCharge(_ context.Context, chargeID string) ([]Refund, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	var out []Refund
	for _, rf := range r.refunds {
		if rf.ChargeID == chargeID {
			out = append(out, rf)
		}
	}
	return out, nil
}

var _ Repository = (*MemoryRepository)(nil)
