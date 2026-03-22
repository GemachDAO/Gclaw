package tools

import (
	"context"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/dashboard"
)

// --- DashboardTool ---

func TestDashboardTool_Name(t *testing.T) {
	tool := NewDashboardTool(nil)
	if tool.Name() != "dashboard" {
		t.Errorf("expected name 'dashboard', got %q", tool.Name())
	}
}

func TestDashboardTool_Description(t *testing.T) {
	tool := NewDashboardTool(nil)
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
}

func TestDashboardTool_Parameters(t *testing.T) {
	tool := NewDashboardTool(nil)
	params := tool.Parameters()
	if params == nil {
		t.Error("expected non-nil parameters")
	}
	if params["type"] != "object" {
		t.Errorf("expected type 'object', got %v", params["type"])
	}
}

func TestDashboardTool_Execute_NilDash(t *testing.T) {
	tool := NewDashboardTool(nil)
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when dashboard is nil")
	}
}

func TestDashboardTool_Execute_Sections(t *testing.T) {
	dash := dashboard.NewDashboard(dashboard.DashboardOptions{AgentID: "test-agent"})

	tool := NewDashboardTool(dash)
	sections := []string{"all", "metabolism", "trading", "funding", "autonomy", "family", "telepathy", "swarm", "registration", "system", ""}
	for _, section := range sections {
		args := map[string]any{"section": section}
		result := tool.Execute(context.Background(), args)
		if result == nil {
			t.Errorf("expected non-nil result for section %q", section)
		}
	}
}

// --- SpawnTool ---

func TestSpawnTool_Name(t *testing.T) {
	tool := NewSpawnTool(nil)
	if tool.Name() != "spawn" {
		t.Errorf("expected name 'spawn', got %q", tool.Name())
	}
}

func TestSpawnTool_Description(t *testing.T) {
	tool := NewSpawnTool(nil)
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
}

func TestSpawnTool_Parameters(t *testing.T) {
	tool := NewSpawnTool(nil)
	params := tool.Parameters()
	if params == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestSpawnTool_SetContext(t *testing.T) {
	tool := NewSpawnTool(nil)
	tool.SetContext("telegram", "12345")
	if tool.originChannel != "telegram" {
		t.Errorf("expected channel 'telegram', got %q", tool.originChannel)
	}
	if tool.originChatID != "12345" {
		t.Errorf("expected chatID '12345', got %q", tool.originChatID)
	}
}

func TestSpawnTool_Execute_MissingTask(t *testing.T) {
	tool := NewSpawnTool(nil)
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when task is missing")
	}
}

func TestSpawnTool_Execute_AllowlistDenied(t *testing.T) {
	tool := NewSpawnTool(nil)
	tool.SetAllowlistChecker(func(agentID string) bool { return false })
	result := tool.Execute(context.Background(), map[string]any{
		"task":     "do something",
		"agent_id": "restricted-agent",
	})
	if !result.IsError {
		t.Error("expected error when allowlist denies agent")
	}
}

func TestSpawnTool_SetCallback(t *testing.T) {
	tool := NewSpawnTool(nil)
	var called bool
	tool.SetCallback(func(ctx context.Context, result *ToolResult) {
		called = true
	})
	if tool.callback == nil {
		t.Error("expected callback to be set")
	}
	_ = called
}

// --- MessageTool (extra) ---

func TestMessageTool_HasSentInRound(t *testing.T) {
	tool := NewMessageTool()
	if tool.HasSentInRound() {
		t.Error("expected HasSentInRound=false initially")
	}
	tool.SetContext("cli", "direct")
	if tool.HasSentInRound() {
		t.Error("expected HasSentInRound=false after SetContext reset")
	}
}

// --- ReadFileTool ---

func TestReadFileTool_Name(t *testing.T) {
	tool := NewReadFileTool(t.TempDir(), false)
	if tool.Name() != "read_file" {
		t.Errorf("expected 'read_file', got %q", tool.Name())
	}
}

func TestReadFileTool_Description(t *testing.T) {
	tool := NewReadFileTool(t.TempDir(), false)
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
}

func TestReadFileTool_Parameters(t *testing.T) {
	tool := NewReadFileTool(t.TempDir(), false)
	params := tool.Parameters()
	if params == nil {
		t.Error("expected non-nil parameters")
	}
}

// --- WriteFileTool ---

func TestWriteFileTool_Name(t *testing.T) {
	tool := NewWriteFileTool(t.TempDir(), false)
	if tool.Name() != "write_file" {
		t.Errorf("expected 'write_file', got %q", tool.Name())
	}
}

// --- ListDirTool ---

func TestListDirTool_Name(t *testing.T) {
	tool := NewListDirTool(t.TempDir(), false)
	if tool.Name() != "list_dir" {
		t.Errorf("expected 'list_dir', got %q", tool.Name())
	}
}

func TestListDirTool_Description(t *testing.T) {
	tool := NewListDirTool(t.TempDir(), false)
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
}

func TestListDirTool_Parameters(t *testing.T) {
	tool := NewListDirTool(t.TempDir(), false)
	params := tool.Parameters()
	if params == nil {
		t.Error("expected non-nil parameters")
	}
}

// --- ValidatePath ---

func TestValidatePath_EmptyWorkspace(t *testing.T) {
	_, err := validatePath("/some/path", "", false)
	if err == nil {
		t.Error("expected error for empty workspace")
	}
}

func TestValidatePath_WithinWorkspace(t *testing.T) {
	ws := t.TempDir()
	absPath, err := validatePath("subdir/file.txt", ws, true)
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if absPath == "" {
		t.Error("expected non-empty abs path")
	}
}

func TestValidatePath_OutsideWorkspace(t *testing.T) {
	ws := t.TempDir()
	_, err := validatePath("../../../etc/passwd", ws, true)
	if err == nil {
		t.Error("expected error for path outside workspace")
	}
}

func TestValidatePath_AbsoluteOutsideWorkspace(t *testing.T) {
	ws := t.TempDir()
	_, err := validatePath("/etc/passwd", ws, true)
	if err == nil {
		t.Error("expected error for absolute path outside workspace")
	}
}

func TestValidatePath_NoRestrict(t *testing.T) {
	ws := t.TempDir()
	absPath, err := validatePath("/etc/hosts", ws, false)
	if err != nil {
		t.Fatalf("expected no error for unrestricted path, got: %v", err)
	}
	if absPath != "/etc/hosts" {
		t.Errorf("expected '/etc/hosts', got %q", absPath)
	}
}
