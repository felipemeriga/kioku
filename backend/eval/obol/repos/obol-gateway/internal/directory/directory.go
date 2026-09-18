// Package directory holds the platforms and sellers the gateway needs to
// validate and price charges. In production this data would live in a database
// (or be fetched from an accounts service); here it is an in-memory directory
// seeded with the canonical SPEC.md sample data so examples line up everywhere.
package directory

import (
	"errors"
	"sync"
	"time"
)

// KYCStatus enumerates a seller's verification state.
type KYCStatus string

const (
	KYCPending  KYCStatus = "pending"
	KYCVerified KYCStatus = "verified"
	KYCRejected KYCStatus = "rejected"
)

// Platform is Obol's direct customer, the marketplace. Field names match SPEC.
type Platform struct {
	ID                    string    `json:"id"`
	Name                  string    `json:"name"`
	Country               string    `json:"country"`
	DefaultPlatformFeeBps int64     `json:"default_platform_fee_bps"`
	CreatedAt             time.Time `json:"created_at"`
}

// Seller is a sub-merchant selling on a platform. Field names match SPEC.
type Seller struct {
	ID             string    `json:"id"`
	PlatformID     string    `json:"platform_id"`
	DisplayName    string    `json:"display_name"`
	KYCStatus      KYCStatus `json:"kyc_status"`
	PayoutCurrency string    `json:"payout_currency"`
	CreatedAt      time.Time `json:"created_at"`
}

var (
	// ErrPlatformNotFound is returned when a platform id is unknown.
	ErrPlatformNotFound = errors.New("directory: platform not found")
	// ErrSellerNotFound is returned when a seller id is unknown.
	ErrSellerNotFound = errors.New("directory: seller not found")
	// ErrSellerNotOnPlatform is returned when a seller does not belong to the
	// acting platform (tenant isolation).
	ErrSellerNotOnPlatform = errors.New("directory: seller does not belong to platform")
)

// Directory is a concurrency-safe in-memory store of platforms and sellers.
type Directory struct {
	mu        sync.RWMutex
	platforms map[string]Platform
	sellers   map[string]Seller
}

// New returns an empty Directory.
func New() *Directory {
	return &Directory{
		platforms: make(map[string]Platform),
		sellers:   make(map[string]Seller),
	}
}

// NewSeeded returns a Directory pre-loaded with the SPEC.md sample data:
// plat_marisqueira and its two verified EUR sellers.
func NewSeeded() *Directory {
	d := New()
	created := time.Date(2024, 1, 15, 9, 0, 0, 0, time.UTC)

	d.PutPlatform(Platform{
		ID:                    "plat_marisqueira",
		Name:                  "Marisqueira Marketplace",
		Country:               "PT",
		DefaultPlatformFeeBps: 290,
		CreatedAt:             created,
	})
	d.PutSeller(Seller{
		ID:             "sell_atelier",
		PlatformID:     "plat_marisqueira",
		DisplayName:    "Atelier Costa",
		KYCStatus:      KYCVerified,
		PayoutCurrency: "EUR",
		CreatedAt:      created,
	})
	d.PutSeller(Seller{
		ID:             "sell_ceramica",
		PlatformID:     "plat_marisqueira",
		DisplayName:    "Cerâmica do Vale",
		KYCStatus:      KYCVerified,
		PayoutCurrency: "EUR",
		CreatedAt:      created,
	})
	return d
}

// PutPlatform inserts or replaces a platform.
func (d *Directory) PutPlatform(p Platform) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.platforms[p.ID] = p
}

// PutSeller inserts or replaces a seller.
func (d *Directory) PutSeller(s Seller) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.sellers[s.ID] = s
}

// Platform looks up a platform by id.
func (d *Directory) Platform(id string) (Platform, error) {
	d.mu.RLock()
	defer d.mu.RUnlock()
	p, ok := d.platforms[id]
	if !ok {
		return Platform{}, ErrPlatformNotFound
	}
	return p, nil
}

// Seller looks up a seller by id.
func (d *Directory) Seller(id string) (Seller, error) {
	d.mu.RLock()
	defer d.mu.RUnlock()
	s, ok := d.sellers[id]
	if !ok {
		return Seller{}, ErrSellerNotFound
	}
	return s, nil
}

// SellerOnPlatform looks up a seller and verifies it belongs to platformID.
func (d *Directory) SellerOnPlatform(platformID, sellerID string) (Seller, error) {
	s, err := d.Seller(sellerID)
	if err != nil {
		return Seller{}, err
	}
	if s.PlatformID != platformID {
		return Seller{}, ErrSellerNotOnPlatform
	}
	return s, nil
}
