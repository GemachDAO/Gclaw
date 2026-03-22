package utils

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolveWorkspaceSkillDir_EnvVarWins(t *testing.T) {
	t.Setenv("GDEX_HELPERS_DIR", "/tmp/custom-helpers")

	got := ResolveWorkspaceSkillDir("GDEX_HELPERS_DIR", "gdex-trading/helpers")
	if got != "/tmp/custom-helpers" {
		t.Fatalf("ResolveWorkspaceSkillDir() = %q, want %q", got, "/tmp/custom-helpers")
	}
}

func TestResolveWorkspaceSkillDir_UsesConfiguredWorkspace(t *testing.T) {
	home := t.TempDir()
	helpersDir := filepath.Join(home, "custom-workspace", "skills", "gdex-trading", "helpers")
	if err := os.MkdirAll(helpersDir, 0o755); err != nil {
		t.Fatalf("mkdir helpers: %v", err)
	}
	configDir := filepath.Join(home, ".gclaw")
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatalf("mkdir config dir: %v", err)
	}
	configJSON := `{"agents":{"defaults":{"workspace":"~/custom-workspace"}}}`
	if err := os.WriteFile(filepath.Join(configDir, "config.json"), []byte(configJSON), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}

	t.Setenv("HOME", home)
	t.Setenv("GCLAW_HOME", "")
	t.Setenv("GCLAW_WORKSPACE", "")
	t.Setenv("GDEX_HELPERS_DIR", "")

	got := ResolveWorkspaceSkillDir("GDEX_HELPERS_DIR", "gdex-trading/helpers")
	if got != helpersDir {
		t.Fatalf("ResolveWorkspaceSkillDir() = %q, want %q", got, helpersDir)
	}
}

func TestResolveWorkspaceSkillDir_ConfiguredWorkspaceWinsOverCurrentRepoWorkspace(t *testing.T) {
	home := t.TempDir()
	workspaceHelpers := filepath.Join(home, "custom-workspace", "skills", "gdex-trading", "helpers")
	if err := os.MkdirAll(workspaceHelpers, 0o755); err != nil {
		t.Fatalf("mkdir configured helpers: %v", err)
	}
	configDir := filepath.Join(home, ".gclaw")
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatalf("mkdir config dir: %v", err)
	}
	configJSON := `{"agents":{"defaults":{"workspace":"~/custom-workspace"}}}`
	if err := os.WriteFile(filepath.Join(configDir, "config.json"), []byte(configJSON), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}

	root := t.TempDir()
	cwdHelpers := filepath.Join(root, "workspace", "skills", "gdex-trading", "helpers")
	if err := os.MkdirAll(cwdHelpers, 0o755); err != nil {
		t.Fatalf("mkdir cwd helpers: %v", err)
	}

	t.Chdir(root)
	t.Setenv("HOME", home)
	t.Setenv("GCLAW_HOME", "")
	t.Setenv("GCLAW_WORKSPACE", "")
	t.Setenv("GDEX_HELPERS_DIR", "")

	got := ResolveWorkspaceSkillDir("GDEX_HELPERS_DIR", "gdex-trading/helpers")
	if got != workspaceHelpers {
		t.Fatalf("ResolveWorkspaceSkillDir() = %q, want configured workspace %q", got, workspaceHelpers)
	}
}

func TestResolveWorkspaceSkillDir_UsesCurrentRepoWorkspace(t *testing.T) {
	root := t.TempDir()
	helpersDir := filepath.Join(root, "workspace", "skills", "gdex-trading", "helpers")
	if err := os.MkdirAll(helpersDir, 0o755); err != nil {
		t.Fatalf("mkdir helpers: %v", err)
	}

	t.Chdir(root)
	t.Setenv("HOME", t.TempDir())
	t.Setenv("GCLAW_HOME", "")
	t.Setenv("GCLAW_WORKSPACE", "")
	t.Setenv("GDEX_HELPERS_DIR", "")

	got := ResolveWorkspaceSkillDir("GDEX_HELPERS_DIR", "gdex-trading/helpers")
	if got != helpersDir {
		t.Fatalf("ResolveWorkspaceSkillDir() = %q, want %q", got, helpersDir)
	}
}
