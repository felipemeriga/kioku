package payouts

import (
	"context"
	"errors"
	"sync"
)

// ErrNotFound is returned when a payout batch id is unknown.
var ErrNotFound = errors.New("payouts: batch not found")

// Repository persists payout batches.
type Repository interface {
	Create(ctx context.Context, b PayoutBatch) error
	Get(ctx context.Context, id string) (PayoutBatch, error)
	Update(ctx context.Context, b PayoutBatch) error
}

// MemoryRepository is a concurrency-safe in-memory Repository.
type MemoryRepository struct {
	mu      sync.RWMutex
	batches map[string]PayoutBatch
}

// NewMemoryRepository returns an empty in-memory payout repository.
func NewMemoryRepository() *MemoryRepository {
	return &MemoryRepository{batches: make(map[string]PayoutBatch)}
}

// Create stores a new batch.
func (r *MemoryRepository) Create(_ context.Context, b PayoutBatch) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.batches[b.ID]; exists {
		return errors.New("payouts: duplicate batch id")
	}
	r.batches[b.ID] = b
	return nil
}

// Get returns a batch by id.
func (r *MemoryRepository) Get(_ context.Context, id string) (PayoutBatch, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	b, ok := r.batches[id]
	if !ok {
		return PayoutBatch{}, ErrNotFound
	}
	return b, nil
}

// Update replaces an existing batch.
func (r *MemoryRepository) Update(_ context.Context, b PayoutBatch) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.batches[b.ID]; !ok {
		return ErrNotFound
	}
	r.batches[b.ID] = b
	return nil
}

var _ Repository = (*MemoryRepository)(nil)
