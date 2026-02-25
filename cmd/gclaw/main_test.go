// Gclaw - Ultra-lightweight personal AI agent
// License: MIT

package main

import (
	"os"
	"strings"
	"testing"
)

func TestFormatVersion_DevDefault(t *testing.T) {
	// version is initialized to "dev" by default in tests
	v := formatVersion()
	if v == "" {
		t.Error("formatVersion() should not return empty string")
	}
}

func TestFormatVersion_WithCommit(t *testing.T) {
	origVersion := version
	origCommit := gitCommit
	defer func() {
		version = origVersion
		gitCommit = origCommit
	}()

	version = "v1.2.3"
	gitCommit = "abc1234"
	v := formatVersion()
	if !strings.Contains(v, "v1.2.3") {
		t.Errorf("formatVersion() = %q, want to contain 'v1.2.3'", v)
	}
	if !strings.Contains(v, "abc1234") {
		t.Errorf("formatVersion() = %q, want to contain 'abc1234'", v)
	}
}

func TestFormatVersion_NoCommit(t *testing.T) {
	origVersion := version
	origCommit := gitCommit
	defer func() {
		version = origVersion
		gitCommit = origCommit
	}()

	version = "v1.0.0"
	gitCommit = ""
	v := formatVersion()
	if v != "v1.0.0" {
		t.Errorf("formatVersion() = %q, want 'v1.0.0'", v)
	}
}

func TestFormatBuildInfo_Empty(t *testing.T) {
	origBuildTime := buildTime
	origGoVersion := goVersion
	defer func() {
		buildTime = origBuildTime
		goVersion = origGoVersion
	}()

	buildTime = ""
	goVersion = ""
	build, goVer := formatBuildInfo()
	if build != "" {
		t.Errorf("formatBuildInfo() build = %q, want empty", build)
	}
	// When goVersion is empty, it falls back to runtime.Version()
	if goVer == "" {
		t.Error("formatBuildInfo() goVer should not be empty (falls back to runtime.Version)")
	}
}

func TestFormatBuildInfo_WithValues(t *testing.T) {
	origBuildTime := buildTime
	origGoVersion := goVersion
	defer func() {
		buildTime = origBuildTime
		goVersion = origGoVersion
	}()

	buildTime = "2026-01-01T00:00:00+00:00"
	goVersion = "go1.22.0"
	build, goVer := formatBuildInfo()
	if build != "2026-01-01T00:00:00+00:00" {
		t.Errorf("formatBuildInfo() build = %q, want '2026-01-01T00:00:00+00:00'", build)
	}
	if goVer != "go1.22.0" {
		t.Errorf("formatBuildInfo() goVer = %q, want 'go1.22.0'", goVer)
	}
}

func TestGetConfigPath(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	path := getConfigPath()
	if path == "" {
		t.Error("getConfigPath() should not return empty string")
	}
	if !strings.HasSuffix(path, "config.json") {
		t.Errorf("getConfigPath() = %q, want path ending in config.json", path)
	}
	if !strings.Contains(path, ".gclaw") {
		t.Errorf("getConfigPath() = %q, want path containing .gclaw", path)
	}
}

func TestCopyEmbeddedToTarget(t *testing.T) {
	tmpDir := t.TempDir()

	if err := copyEmbeddedToTarget(tmpDir); err != nil {
		t.Fatalf("copyEmbeddedToTarget() error: %v", err)
	}

	// Verify core files are present
	files := []string{"AGENT.md", "IDENTITY.md", "SOUL.md", "USER.md"}
	for _, f := range files {
		path := tmpDir + "/" + f
		if _, err := os.Stat(path); err != nil {
			t.Errorf("expected file %s to exist after copyEmbeddedToTarget: %v", f, err)
		}
	}
}

func TestCopyEmbeddedToTarget_Idempotent(t *testing.T) {
	tmpDir := t.TempDir()

	// Running twice should not error (idempotent)
	if err := copyEmbeddedToTarget(tmpDir); err != nil {
		t.Fatalf("first copyEmbeddedToTarget() error: %v", err)
	}
	if err := copyEmbeddedToTarget(tmpDir); err != nil {
		t.Fatalf("second copyEmbeddedToTarget() error: %v", err)
	}
}
