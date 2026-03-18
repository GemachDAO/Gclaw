// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package metabolism

import (
	"testing"
)

func TestTrimLedger_KeepsRecentEntries(t *testing.T) {
	m := NewMetabolism(1000.0, Thresholds{})
	for i := 0; i < 20; i++ {
		m.Credit(1, "earn", "item")
	}
	if len(m.ledger) != 20 {
		t.Fatalf("want 20 entries before trim, got %d", len(m.ledger))
	}

	m.TrimLedger(10)
	if len(m.ledger) != 10 {
		t.Errorf("want 10 entries after trim, got %d", len(m.ledger))
	}
}

func TestTrimLedger_NoOpWhenUnderLimit(t *testing.T) {
	m := NewMetabolism(1000.0, Thresholds{})
	for i := 0; i < 5; i++ {
		m.Credit(1, "earn", "item")
	}

	m.TrimLedger(100)
	if len(m.ledger) != 5 {
		t.Errorf("want 5 entries unchanged, got %d", len(m.ledger))
	}
}

func TestTrimLedger_KeepsMostRecent(t *testing.T) {
	m := NewMetabolism(1000.0, Thresholds{})
	for i := 0; i < 10; i++ {
		m.Credit(float64(i+1), "earn", "item")
	}

	m.TrimLedger(3)
	if len(m.ledger) != 3 {
		t.Fatalf("want 3 entries, got %d", len(m.ledger))
	}
	// Most recent entries have the largest amounts (8,9,10)
	if m.ledger[0].Amount != 8 || m.ledger[1].Amount != 9 || m.ledger[2].Amount != 10 {
		t.Errorf("expected last 3 entries (8,9,10), got amounts: %.0f %.0f %.0f",
			m.ledger[0].Amount, m.ledger[1].Amount, m.ledger[2].Amount)
	}
}

func TestTrimLedger_ZeroMaxNoOp(t *testing.T) {
	m := NewMetabolism(1000.0, Thresholds{})
	for i := 0; i < 5; i++ {
		m.Credit(1, "earn", "item")
	}
	m.TrimLedger(0)
	if len(m.ledger) != 5 {
		t.Errorf("want 5 entries with maxEntries=0, got %d", len(m.ledger))
	}
}
