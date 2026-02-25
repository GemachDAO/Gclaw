package logger

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDebugF(t *testing.T) {
	SetLevel(DEBUG)
	defer SetLevel(INFO)
	// Should not panic
	DebugF("debug with fields", map[string]any{"key": "value"})
}

func TestDebugCF(t *testing.T) {
	SetLevel(DEBUG)
	defer SetLevel(INFO)
	DebugCF("component", "debug component fields", map[string]any{"x": 1})
}

func TestInfoCF(t *testing.T) {
	InfoCF("component", "info component fields", map[string]any{"field": "val"})
}

func TestWarnCF(t *testing.T) {
	WarnCF("component", "warn component fields", map[string]any{"level": "warn"})
}

func TestErrorC(t *testing.T) {
	ErrorC("component", "error component message")
}

func TestErrorCF(t *testing.T) {
	ErrorCF("component", "error component fields", map[string]any{"err": "test"})
}

func TestEnableAndDisableFileLogging(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "test.log")

	err := EnableFileLogging(logPath)
	if err != nil {
		t.Fatalf("EnableFileLogging failed: %v", err)
	}

	// Write some log entries to file
	Info("test log entry to file")
	InfoCF("component", "structured log", map[string]any{"key": "value"})

	DisableFileLogging()

	// Verify file was created and has content
	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("expected log file to exist: %v", err)
	}
	if len(data) == 0 {
		t.Error("expected non-empty log file")
	}
}

func TestEnableFileLogging_InvalidPath(t *testing.T) {
	err := EnableFileLogging("/nonexistent/directory/test.log")
	if err == nil {
		t.Error("expected error for invalid log file path")
	}
}

func TestDisableFileLogging_WithoutEnable(t *testing.T) {
	// Should not panic when file logging was not enabled
	DisableFileLogging()
}

func TestEnableFileLogging_Twice(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "test.log")

	if err := EnableFileLogging(logPath); err != nil {
		t.Fatalf("first EnableFileLogging: %v", err)
	}

	// Enable again with same path (should close old and open new)
	if err := EnableFileLogging(logPath); err != nil {
		t.Fatalf("second EnableFileLogging: %v", err)
	}

	DisableFileLogging()
}

func TestLogMessage_AllLevels(t *testing.T) {
	SetLevel(DEBUG)
	defer SetLevel(INFO)

	// Call all log functions
	Debug("debug msg")
	Info("info msg")
	Warn("warn msg")
	Error("error msg")

	// Component variants
	DebugC("comp", "debug component")
	InfoC("comp", "info component")
	WarnC("comp", "warn component")
	ErrorC("comp", "error component")

	// Field variants
	DebugF("debug fields", map[string]any{"k": "v"})
	InfoF("info fields", nil)
	WarnF("warn fields", map[string]any{"k": "v"})
	ErrorF("error fields", map[string]any{"k": "v"})
}

func TestLogMessage_WithFileLogging(t *testing.T) {
	SetLevel(DEBUG)
	defer SetLevel(INFO)

	dir := t.TempDir()
	logPath := filepath.Join(dir, "test.log")

	if err := EnableFileLogging(logPath); err != nil {
		t.Fatalf("EnableFileLogging: %v", err)
	}
	defer DisableFileLogging()

	DebugCF("comp", "file log test", map[string]any{"level": "debug"})
	InfoCF("comp", "info file log", nil)

	DisableFileLogging()

	data, _ := os.ReadFile(logPath)
	if len(data) == 0 {
		t.Error("expected content in log file")
	}
}
