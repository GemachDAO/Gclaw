package tools

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

func resolveRuntimeConfigPath() string {
	if path := strings.TrimSpace(os.Getenv("GCLAW_CONFIG_PATH")); path != "" {
		return path
	}
	if path := strings.TrimSpace(os.Getenv("GCLAW_CONFIG")); path != "" {
		return path
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".gclaw", "config.json")
}

func buildGDEXHelperEnv() []string {
	env := os.Environ()
	configPath := resolveRuntimeConfigPath()
	if configPath == "" {
		return env
	}

	cfg, err := config.LoadConfig(configPath)
	if err != nil {
		return env
	}

	if os.Getenv("GDEX_API_KEY") == "" {
		if apiKey := runtimeinfo.ResolveGDEXAPIKey(cfg); apiKey != "" {
			env = upsertEnvVar(env, "GDEX_API_KEY", apiKey)
		}
	}

	addr, key := runtimeinfo.ResolveWalletCredentials(cfg)
	if os.Getenv("WALLET_ADDRESS") == "" && addr != "" {
		env = upsertEnvVar(env, "WALLET_ADDRESS", addr)
	}
	if os.Getenv("PRIVATE_KEY") == "" && key != "" {
		env = upsertEnvVar(env, "PRIVATE_KEY", key)
	}

	return env
}

func upsertEnvVar(env []string, key, value string) []string {
	prefix := key + "="
	replaced := false
	for i, entry := range env {
		if strings.HasPrefix(entry, prefix) {
			env[i] = prefix + value
			replaced = true
		}
	}
	if !replaced {
		env = append(env, prefix+value)
	}
	return env
}
