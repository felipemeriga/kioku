package charges

import (
	"context"
	"errors"
	"sync"
)

// ErrNotFound is returned when a charge id is unknown.
var ErrNotFound = errors.New("charges: charge not found")

// Repository persists charges. The interface keeps the service storage-agnostic.
type Repository interface {
	Create(ctx context.Context, c Charge) error
	Get(ctx context.Context, id string) (Charge, error)
	Update(ctx context.Context, c Charge) error
}

// MemoryRepository is a concurrency-safe in-memory Repository.
type MemoryRepository struct {
	mu      sync.RWMutex
	charges map[string]Charge
}

// NewMemoryRepository returns an empty in-memory charge repository.
func NewMemoryRepository() *MemoryRepository {
	return &MemoryRepository{charges: make(map[string]Charge)}
}

// Create stores a new charge, rejecting duplicate ids.
func (r *MemoryRepository) Create(_ context.Context, c Charge) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.charges[c.ID]; exists {
		return errors.New("charges: duplicate charge id")
	}
	r.charges[c.ID] = c
	return nil
}

// Get returns the charge with the given id.
func (r *MemoryRepository) Get(_ context.Context, id string) (Charge, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	c, ok := r.charges[id]
	if !ok {
		return Charge{}, ErrNotFound
	}
	return c, nil
}

// Update replaces an existing charge.
func (r *MemoryRepository) Update(_ context.Context, c Charge) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.charges[c.ID]; !ok {
		return ErrNotFound
	}
	r.charges[c.ID] = c
	return nil
}

var _ Repository = (*MemoryRepository)(nil)
