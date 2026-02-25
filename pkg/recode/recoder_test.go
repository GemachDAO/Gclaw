package recode

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/config"
)

func setupTestRecoder(t *testing.T) (*Recoder, string, string) {
	t.Helper()
	dir := t.TempDir()
	workspace := filepath.Join(dir, "workspace")
	if err := os.MkdirAll(workspace, 0o755); err != nil {
		t.Fatalf("create workspace: %v", err)
	}
	cfgPath := filepath.Join(dir, "config.json")
	// Write minimal config
	cfg := config.DefaultConfig()
	if err := config.SaveConfig(cfgPath, cfg); err != nil {
		t.Fatalf("save config: %v", err)
	}
	rc := NewRecoder(cfgPath, workspace)
	return rc, cfgPath, workspace
}

func TestNewRecoder(t *testing.T) {
	rc := NewRecoder("/tmp/config.json", "/tmp/workspace")
	if rc == nil {
		t.Fatal("expected non-nil Recoder")
	}
	if rc.configPath != "/tmp/config.json" {
		t.Errorf("unexpected configPath: %s", rc.configPath)
	}
	if rc.workspace != "/tmp/workspace" {
		t.Errorf("unexpected workspace: %s", rc.workspace)
	}
}

func TestGetActionLog_Empty(t *testing.T) {
	rc := NewRecoder("/tmp/config.json", "/tmp/workspace")
	log := rc.GetActionLog()
	if len(log) != 0 {
		t.Errorf("expected empty log, got %d entries", len(log))
	}
}

func TestModifySystemPrompt(t *testing.T) {
	rc, _, workspace := setupTestRecoder(t)

	err := rc.ModifySystemPrompt("Be more concise.")
	if err != nil {
		t.Fatalf("ModifySystemPrompt failed: %v", err)
	}

	// Check the prompt addition file was created
	additionPath := filepath.Join(workspace, "recode", "prompt_additions.txt")
	data, err := os.ReadFile(additionPath)
	if err != nil {
		t.Fatalf("expected prompt_additions.txt to exist: %v", err)
	}
	if !strings.Contains(string(data), "Be more concise.") {
		t.Errorf("expected prompt addition in file, got: %s", string(data))
	}

	log := rc.GetActionLog()
	if len(log) != 1 {
		t.Fatalf("expected 1 action, got %d", len(log))
	}
	if log[0].Type != "prompt" {
		t.Errorf("expected type 'prompt', got %q", log[0].Type)
	}
	if !log[0].Approved {
		t.Error("expected action to be approved")
	}
}

func TestAddCronJob(t *testing.T) {
	rc, _, workspace := setupTestRecoder(t)

	err := rc.AddCronJob("0 * * * *", "send hourly summary")
	if err != nil {
		t.Fatalf("AddCronJob failed: %v", err)
	}

	cronPath := filepath.Join(workspace, "recode", "cron_additions.txt")
	data, err := os.ReadFile(cronPath)
	if err != nil {
		t.Fatalf("expected cron_additions.txt to exist: %v", err)
	}
	if !strings.Contains(string(data), "0 * * * *") {
		t.Errorf("expected cron schedule in file, got: %s", string(data))
	}

	log := rc.GetActionLog()
	if len(log) != 1 {
		t.Fatalf("expected 1 action, got %d", len(log))
	}
	if log[0].Type != "cron" {
		t.Errorf("expected type 'cron', got %q", log[0].Type)
	}
}

func TestInstallSkill(t *testing.T) {
	rc, _, workspace := setupTestRecoder(t)

	err := rc.InstallSkill("my-skill", "gclaw-hub")
	if err != nil {
		t.Fatalf("InstallSkill failed: %v", err)
	}

	installPath := filepath.Join(workspace, "recode", "skill_installs.txt")
	data, err := os.ReadFile(installPath)
	if err != nil {
		t.Fatalf("expected skill_installs.txt to exist: %v", err)
	}
	if !strings.Contains(string(data), "my-skill") {
		t.Errorf("expected skill slug in file, got: %s", string(data))
	}

	log := rc.GetActionLog()
	if len(log) != 1 || log[0].Type != "skill" {
		t.Fatalf("expected 1 skill action, got %v", log)
	}
}

func TestAdjustTradingParams(t *testing.T) {
	rc, _, _ := setupTestRecoder(t)

	params := map[string]any{
		"max_trade_size_sol": 1.5,
		"auto_trade":         true,
		"default_chain_id":   float64(1),
	}
	err := rc.AdjustTradingParams(params)
	if err != nil {
		t.Fatalf("AdjustTradingParams failed: %v", err)
	}

	log := rc.GetActionLog()
	if len(log) != 1 || log[0].Type != "trading_param" {
		t.Fatalf("expected 1 trading_param action, got %v", log)
	}
}

func TestAdjustTradingParams_IntValues(t *testing.T) {
	rc, _, _ := setupTestRecoder(t)

	params := map[string]any{
		"max_trade_size_sol": int(2),
		"default_chain_id":   int64(137),
	}
	err := rc.AdjustTradingParams(params)
	if err != nil {
		t.Fatalf("AdjustTradingParams with int values failed: %v", err)
	}
}

func TestRollback_Valid(t *testing.T) {
	rc, _, _ := setupTestRecoder(t)
	// Add a couple of actions
	rc.mu.Lock()
	rc.logAction("prompt", "first addition")
	rc.logAction("cron", "scheduled job")
	rc.mu.Unlock()

	err := rc.Rollback(0)
	if err != nil {
		t.Fatalf("Rollback failed: %v", err)
	}

	log := rc.GetActionLog()
	// Original 2 + 1 rollback entry
	if len(log) != 3 {
		t.Fatalf("expected 3 entries after rollback, got %d", len(log))
	}
	if log[0].Approved {
		t.Error("expected first action to be un-approved after rollback")
	}
	if log[2].Type != "rollback" {
		t.Errorf("expected rollback entry, got %q", log[2].Type)
	}
}

func TestRollback_InvalidIndex(t *testing.T) {
	rc, _, _ := setupTestRecoder(t)

	err := rc.Rollback(0)
	if err == nil {
		t.Error("expected error for empty log")
	}

	err = rc.Rollback(-1)
	if err == nil {
		t.Error("expected error for negative index")
	}
}

func TestModifySystemPrompt_MultipleAppends(t *testing.T) {
	rc, _, workspace := setupTestRecoder(t)

	_ = rc.ModifySystemPrompt("first")
	_ = rc.ModifySystemPrompt("second")

	additionPath := filepath.Join(workspace, "recode", "prompt_additions.txt")
	data, err := os.ReadFile(additionPath)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if !strings.Contains(string(data), "first") || !strings.Contains(string(data), "second") {
		t.Errorf("expected both additions, got: %s", string(data))
	}
}

func TestAppendToFile_CreatesDirectory(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nested", "dir", "file.txt")

	err := appendToFile(path, "content")
	if err != nil {
		t.Fatalf("appendToFile failed: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "content" {
		t.Errorf("expected 'content', got %q", string(data))
	}
}

func TestToFloat64(t *testing.T) {
	tests := []struct {
		input    any
		expected float64
		ok       bool
	}{
		{float64(1.5), 1.5, true},
		{int(2), 2.0, true},
		{int64(3), 3.0, true},
		{"not a float", 0.0, false},
	}

	for _, tt := range tests {
		got, ok := toFloat64(tt.input)
		if ok != tt.ok {
			t.Errorf("toFloat64(%v): ok=%v, want %v", tt.input, ok, tt.ok)
		}
		if ok && got != tt.expected {
			t.Errorf("toFloat64(%v) = %v, want %v", tt.input, got, tt.expected)
		}
	}
}
