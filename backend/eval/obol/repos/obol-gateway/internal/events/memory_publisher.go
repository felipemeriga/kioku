package events

import (
	"context"
	"sync"
)

// MemoryPublisher records published envelopes in memory instead of delivering
// them over HTTP. It is used in tests and local runs where no ledger is wired
// up, and lets tests assert exactly which events a flow emitted.
type MemoryPublisher struct {
	mu        sync.Mutex
	published []Envelope
}

// NewMemoryPublisher returns an empty in-memory publisher.
func NewMemoryPublisher() *MemoryPublisher { return &MemoryPublisher{} }

// Publish records the envelope. It never fails.
func (p *MemoryPublisher) Publish(_ context.Context, env Envelope) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.published = append(p.published, env)
	return nil
}

// Published returns a copy of all envelopes published so far, in order.
func (p *MemoryPublisher) Published() []Envelope {
	p.mu.Lock()
	defer p.mu.Unlock()
	out := make([]Envelope, len(p.published))
	copy(out, p.published)
	return out
}

// TypesPublished returns just the event types published, in order — convenient
// for asserting causal ordering in tests.
func (p *MemoryPublisher) TypesPublished() []Type {
	p.mu.Lock()
	defer p.mu.Unlock()
	out := make([]Type, len(p.published))
	for i, e := range p.published {
		out[i] = e.Type
	}
	return out
}

var _ Publisher = (*MemoryPublisher)(nil)
