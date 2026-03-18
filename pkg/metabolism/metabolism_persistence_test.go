// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package metabolism

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFlushLedger_WritesJSON(t *testing.T) {
	dir := t.TempDir()
	m := NewMetabolism(100.0, Thresholds{Replicate: 10, SelfRecode: 50, SwarmLeader: 100, Architect: 200})
	m.Credit(10, "test", "unit test")

	if err := m.FlushLedger(dir); err != nil {
		t.Fatalf("FlushLedger returned error: %v", err)
	}

	stateFile := filepath.Join(dir, "metabolism_state.json")
	data, err := os.ReadFile(stateFile)
	if err != nil {
		t.Fatalf("state file not written: %v", err)
	}
	if len(data) == 0 {
		t.Fatal("state file is empty")
	}
}

func TestLoadState_RestoresBalance(t *testing.T) {
	dir := t.TempDir()
	m := NewMetabolism(250.0, Thresholds{})
	m.Credit(50, "earn", "test")
	m.AddGoodwill(30, "good job")

	if err := m.FlushLedger(dir); err != nil {
		t.Fatalf("FlushLedger: %v", err)
	}

	// Create a fresh Metabolism and restore state
	m2 := NewMetabolism(0, Thresholds{})
	if err := m2.LoadState(filepath.Join(dir, "metabolism_state.json")); err != nil {
		t.Fatalf("LoadState: %v", err)
	}

	if m2.GetBalance() != m.GetBalance() {
		t.Errorf("balance mismatch: got %.4f, want %.4f", m2.GetBalance(), m.GetBalance())
	}
	if m2.GetGoodwill() != m.GetGoodwill() {
		t.Errorf("goodwill mismatch: got %d, want %d", m2.GetGoodwill(), m.GetGoodwill())
	}
}

func TestLoadState_MissingFileReturnsError(t *testing.T) {
	m := NewMetabolism(100.0, Thresholds{})
	err := m.LoadState("/tmp/does_not_exist_gclaw_test.json")
	if err == nil {
		t.Fatal("expected error for missing file, got nil")
	}
}

func TestLoadState_CorruptedFileReturnsError(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.json")
	if err := os.WriteFile(path, []byte("not json!!!"), 0o600); err != nil {
		t.Fatal(err)
	}

	m := NewMetabolism(100.0, Thresholds{})
	if err := m.LoadState(path); err == nil {
		t.Fatal("expected error for corrupted file")
	}
}

func TestFlushThenLoad_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	m := NewMetabolism(500.0, Thresholds{Replicate: 5, SelfRecode: 10, SwarmLeader: 20, Architect: 50})
	m.Debit(100, "cost", "test") //nolint:errcheck
	m.AddGoodwill(42, "round trip test")

	if err := m.FlushLedger(dir); err != nil {
		t.Fatalf("FlushLedger: %v", err)
	}

	m2 := NewMetabolism(0, Thresholds{})
	if err := m2.LoadState(filepath.Join(dir, "metabolism_state.json")); err != nil {
		t.Fatalf("LoadState: %v", err)
	}

	if m2.GetBalance() != m.GetBalance() {
		t.Errorf("balance: got %.2f want %.2f", m2.GetBalance(), m.GetBalance())
	}
	if m2.GetGoodwill() != m.GetGoodwill() {
		t.Errorf("goodwill: got %d want %d", m2.GetGoodwill(), m.GetGoodwill())
	}
}
