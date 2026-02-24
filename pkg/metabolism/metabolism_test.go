package metabolism

import (
	"os"
	"path/filepath"
	"testing"
)

func defaultThresholds() Thresholds {
	return Thresholds{
		Hibernate:   50,
		Replicate:   50,
		SelfRecode:  100,
		SwarmLeader: 200,
		Architect:   500,
	}
}

// --- Debit / Credit ---

func TestDebitCredit_BasicBalance(t *testing.T) {
	m := NewMetabolism(100, defaultThresholds())

	if err := m.Debit(30, "inference", "test"); err != nil {
		t.Fatalf("unexpected Debit error: %v", err)
	}
	if got := m.GetBalance(); got != 70 {
		t.Errorf("expected balance 70, got %.2f", got)
	}

	m.Credit(20, "trade_profit", "win")
	if got := m.GetBalance(); got != 90 {
		t.Errorf("expected balance 90 after credit, got %.2f", got)
	}
}

func TestDebitCredit_InsufficientBalance(t *testing.T) {
	m := NewMetabolism(10, defaultThresholds())
	err := m.Debit(50, "tool_exec", "too_expensive")
	if err == nil {
		t.Fatal("expected error for over-debit")
	}
	if got := m.GetBalance(); got != 10 {
		t.Errorf("balance should not change on failed debit, got %.2f", got)
	}
}

func TestCanAfford(t *testing.T) {
	m := NewMetabolism(10, defaultThresholds())
	if !m.CanAfford(10) {
		t.Error("expected CanAfford(10) = true")
	}
	if m.CanAfford(10.01) {
		t.Error("expected CanAfford(10.01) = false")
	}
}

// --- Survival Mode ---

func TestInSurvivalMode(t *testing.T) {
	m := NewMetabolism(100, defaultThresholds()) // hibernate threshold = 50
	if m.InSurvivalMode() {
		t.Error("should not be in survival mode with balance=100")
	}
	_ = m.Debit(60, "burn", "test")
	if !m.InSurvivalMode() {
		t.Error("should be in survival mode with balance=40 (below threshold 50)")
	}
}

// --- Goodwill Thresholds ---

func TestGoodwillThresholds(t *testing.T) {
	m := NewMetabolism(1000, defaultThresholds())

	if m.CanReplicate() {
		t.Error("should not be able to replicate with 0 goodwill")
	}

	m.AddGoodwill(50, "trades")
	if !m.CanReplicate() {
		t.Error("should be able to replicate with 50 goodwill")
	}
	if m.CanSelfRecode() {
		t.Error("should not self-recode with 50 goodwill")
	}

	m.AddGoodwill(50, "more trades")
	if !m.CanSelfRecode() {
		t.Error("should self-recode with 100 goodwill")
	}
	if m.CanLeadSwarm() {
		t.Error("should not lead swarm with 100 goodwill")
	}

	m.AddGoodwill(100, "swarm")
	if !m.CanLeadSwarm() {
		t.Error("should lead swarm with 200 goodwill")
	}
	if m.CanArchitect() {
		t.Error("should not architect with 200 goodwill")
	}

	m.AddGoodwill(300, "architect")
	if !m.CanArchitect() {
		t.Error("should architect with 500 goodwill")
	}
}

func TestAddGoodwill_ClampToZero(t *testing.T) {
	m := NewMetabolism(100, defaultThresholds())
	m.AddGoodwill(-999, "massive loss")
	if got := m.GetGoodwill(); got != 0 {
		t.Errorf("expected goodwill clamped to 0, got %d", got)
	}
}

// --- Ledger ---

func TestLedger_RecordsEntries(t *testing.T) {
	m := NewMetabolism(100, defaultThresholds())
	_ = m.Debit(10, "tool_exec", "web_search")
	m.Credit(5, "trade_profit", "win")
	m.AddGoodwill(10, "helped")

	ledger := m.GetLedger()
	if len(ledger) != 3 {
		t.Fatalf("expected 3 ledger entries, got %d", len(ledger))
	}
	if ledger[0].Action != "tool_exec" {
		t.Errorf("first entry should be tool_exec, got %q", ledger[0].Action)
	}
	if ledger[1].Amount != 5 {
		t.Errorf("credit amount should be 5, got %.2f", ledger[1].Amount)
	}
}

// --- GetStatus ---

func TestGetStatus(t *testing.T) {
	m := NewMetabolism(1000, defaultThresholds())
	m.AddGoodwill(50, "earned")

	status := m.GetStatus()
	if status.Balance != 1000 {
		t.Errorf("expected balance 1000, got %.2f", status.Balance)
	}
	if status.Goodwill != 50 {
		t.Errorf("expected goodwill 50, got %d", status.Goodwill)
	}
	if status.SurvivalMode {
		t.Error("should not be in survival mode")
	}
	if len(status.Abilities) != 1 || status.Abilities[0] != "replicate" {
		t.Errorf("expected [replicate] abilities, got %v", status.Abilities)
	}
}

// --- Persistence ---

func TestPersistence_SaveLoadRoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "metabolism", "state.json")

	m := NewMetabolism(250, defaultThresholds())
	_ = m.Debit(50, "tool_exec", "exec")
	m.Credit(30, "trade_profit", "win")
	m.AddGoodwill(75, "good work")

	if err := m.SaveToFile(path); err != nil {
		t.Fatalf("SaveToFile failed: %v", err)
	}

	// Verify ledger file exists
	ledgerPath := filepath.Join(dir, "metabolism", "ledger.jsonl")
	if _, err := os.Stat(ledgerPath); os.IsNotExist(err) {
		t.Error("expected ledger.jsonl to be created")
	}

	m2, err := LoadFromFile(path)
	if err != nil {
		t.Fatalf("LoadFromFile failed: %v", err)
	}

	if m2.GetBalance() != m.GetBalance() {
		t.Errorf("balance mismatch: want %.2f, got %.2f", m.GetBalance(), m2.GetBalance())
	}
	if m2.GetGoodwill() != m.GetGoodwill() {
		t.Errorf("goodwill mismatch: want %d, got %d", m.GetGoodwill(), m2.GetGoodwill())
	}
}

func TestLoadFromFile_NotFound(t *testing.T) {
	_, err := LoadFromFile("/nonexistent/path/state.json")
	if err == nil {
		t.Error("expected error loading non-existent file")
	}
}

// --- GoodwillTracker ---

func TestGoodwillTracker_RecordTradeResult(t *testing.T) {
	m := NewMetabolism(1000, defaultThresholds())
	gt := NewGoodwillTracker(m)

	gt.RecordTradeResult(10)
	if m.GetGoodwill() != GoodwillProfitableTrade {
		t.Errorf("expected +%d goodwill for profitable trade, got %d", GoodwillProfitableTrade, m.GetGoodwill())
	}

	gt.RecordTradeResult(-15)
	expected := GoodwillProfitableTrade + GoodwillBadTrade
	if expected < 0 {
		expected = 0
	}
	if m.GetGoodwill() != expected {
		t.Errorf("expected goodwill %d after bad trade, got %d", expected, m.GetGoodwill())
	}
}

func TestGoodwillTracker_RecordTaskResult(t *testing.T) {
	m := NewMetabolism(1000, defaultThresholds())
	gt := NewGoodwillTracker(m)

	gt.RecordTaskResult(true)
	if m.GetGoodwill() != GoodwillTaskComplete {
		t.Errorf("expected %d goodwill for completed task, got %d", GoodwillTaskComplete, m.GetGoodwill())
	}

	gt.RecordTaskResult(false)
	expected := GoodwillTaskComplete + GoodwillFailedTask
	if expected < 0 {
		expected = 0
	}
	if m.GetGoodwill() != expected {
		t.Errorf("expected goodwill %d after failed task, got %d", expected, m.GetGoodwill())
	}
}

func TestGoodwillTracker_RecordUserFeedback(t *testing.T) {
	m := NewMetabolism(1000, defaultThresholds())
	gt := NewGoodwillTracker(m)
	gt.RecordUserFeedback(true)
	if m.GetGoodwill() != GoodwillUserThanks {
		t.Errorf("expected %d goodwill for user thanks, got %d", GoodwillUserThanks, m.GetGoodwill())
	}
}

func TestGoodwillTracker_RecordSelfFunding(t *testing.T) {
	m := NewMetabolism(1000, defaultThresholds())
	gt := NewGoodwillTracker(m)
	gt.RecordSelfFunding()
	if m.GetGoodwill() != GoodwillSelfFundInference {
		t.Errorf("expected %d goodwill for self-funding, got %d", GoodwillSelfFundInference, m.GetGoodwill())
	}
}

func TestGoodwillTracker_GetAbilities(t *testing.T) {
	m := NewMetabolism(1000, defaultThresholds())
	gt := NewGoodwillTracker(m)

	if abilities := gt.GetAbilities(); len(abilities) != 0 {
		t.Errorf("expected no abilities at 0 goodwill, got %v", abilities)
	}

	m.AddGoodwill(50, "earned")
	if abilities := gt.GetAbilities(); len(abilities) != 1 || abilities[0] != "replicate" {
		t.Errorf("expected [replicate] at 50 goodwill, got %v", abilities)
	}
}
