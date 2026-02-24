package metabolism

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// persistState is a serializable snapshot of the Metabolism for disk storage.
type persistState struct {
	Balance    float64    `json:"balance"`
	Goodwill   int        `json:"goodwill"`
	Generation int        `json:"generation"`
	ParentID   string     `json:"parent_id,omitempty"`
	Thresholds Thresholds `json:"thresholds"`
	SavedAt    time.Time  `json:"saved_at"`
}

// SaveToFile serializes metabolism state to disk at path.
// The ledger is appended separately to a .jsonl file alongside the state file.
func (m *Metabolism) SaveToFile(path string) error {
	m.mu.RLock()
	ps := persistState{
		Balance:    m.balance,
		Goodwill:   m.goodwill,
		Generation: m.generation,
		ParentID:   m.parentID,
		Thresholds: m.thresholds,
		SavedAt:    time.Now(),
	}
	newEntries := make([]LedgerEntry, len(m.ledger))
	copy(newEntries, m.ledger)
	m.mu.RUnlock()

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("metabolism: mkdir: %w", err)
	}

	data, err := json.MarshalIndent(ps, "", "  ")
	if err != nil {
		return fmt.Errorf("metabolism: marshal state: %w", err)
	}

	// Atomic write: temp file + rename
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return fmt.Errorf("metabolism: write temp: %w", err)
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("metabolism: rename: %w", err)
	}

	// Append new ledger entries to ledger.jsonl
	ledgerPath := filepath.Join(filepath.Dir(path), "ledger.jsonl")
	lf, err := os.OpenFile(ledgerPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("metabolism: open ledger: %w", err)
	}
	defer lf.Close()

	enc := json.NewEncoder(lf)
	for _, entry := range newEntries {
		if err := enc.Encode(entry); err != nil {
			return fmt.Errorf("metabolism: encode ledger entry: %w", err)
		}
	}

	return nil
}

// LoadFromFile restores a Metabolism from a previously saved state file.
func LoadFromFile(path string) (*Metabolism, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("metabolism: read state: %w", err)
	}

	var ps persistState
	if err := json.Unmarshal(data, &ps); err != nil {
		return nil, fmt.Errorf("metabolism: unmarshal state: %w", err)
	}

	m := &Metabolism{
		balance:    ps.Balance,
		goodwill:   ps.Goodwill,
		generation: ps.Generation,
		parentID:   ps.ParentID,
		thresholds: ps.Thresholds,
		ledger:     []LedgerEntry{},
	}
	return m, nil
}
