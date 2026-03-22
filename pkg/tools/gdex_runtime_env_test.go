package tools

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/config"
)

func TestBuildGDEXHelperEnv_UsesConfigValues(t *testing.T) {
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.json")

	cfg := config.DefaultConfig()
	cfg.Tools.GDEX.APIKey = "primary-key,secondary-key"
	cfg.Tools.GDEX.WalletAddress = "0x1234"
	cfg.Tools.GDEX.PrivateKey = "0xdeadbeef"

	data, err := json.Marshal(cfg)
	if err != nil {
		t.Fatalf("marshal config: %v", err)
	}
	if err := os.WriteFile(configPath, data, 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	t.Setenv("GCLAW_CONFIG_PATH", configPath)
	t.Setenv("GDEX_API_KEY", "")
	t.Setenv("WALLET_ADDRESS", "")
	t.Setenv("PRIVATE_KEY", "")

	env := buildGDEXHelperEnv()
	if !containsEnv(env, "GDEX_API_KEY=primary-key") {
		t.Fatalf("expected normalized GDEX_API_KEY in env: %v", env)
	}
	if !containsEnv(env, "WALLET_ADDRESS=0x1234") {
		t.Fatalf("expected wallet address in env: %v", env)
	}
	if !containsEnv(env, "PRIVATE_KEY=0xdeadbeef") {
		t.Fatalf("expected private key in env: %v", env)
	}
}

func containsEnv(env []string, target string) bool {
	for _, entry := range env {
		if strings.TrimSpace(entry) == target {
			return true
		}
	}
	return false
}
