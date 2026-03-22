package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
	"github.com/GemachDAO/Gclaw/pkg/utils"
)

type generatedGDEXWallet struct {
	Address    string `json:"address"`
	PrivateKey string `json:"private_key"`
}

func ensureGDEXWallet(cfg *config.Config) (address string, generated bool, err error) {
	if cfg == nil {
		return "", false, nil
	}

	address, privateKey := runtimeinfo.ResolveWalletCredentials(cfg)
	switch {
	case address != "" && privateKey != "":
		return address, false, nil
	case address != "" || privateKey != "":
		return "", false, fmt.Errorf("incomplete GDEX wallet credentials; set both wallet_address and private_key")
	}

	if !(cfg.Tools.GDEX.Enabled || cfg.Tools.ERC8004.Enabled || cfg.Tools.X402.Enabled) {
		return "", false, nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	wallet, err := generateGDEXWallet(ctx)
	if err != nil {
		return "", false, err
	}

	cfg.Tools.GDEX.WalletAddress = wallet.Address
	cfg.Tools.GDEX.PrivateKey = wallet.PrivateKey
	if err := config.SaveConfig(getConfigPath(), cfg); err != nil {
		return "", false, fmt.Errorf("save generated wallet to config: %w", err)
	}

	return wallet.Address, true, nil
}

func generateGDEXWallet(ctx context.Context) (*generatedGDEXWallet, error) {
	helperDir := utils.ResolveWorkspaceSkillDir("GDEX_HELPERS_DIR", "gdex-trading/helpers")
	if helperDir == "" {
		return nil, fmt.Errorf("GDEX helper directory not found")
	}
	if err := ensureGDEXHelperDeps(helperDir); err != nil {
		return nil, err
	}

	script := `
const { ethers } = require('ethers');
const wallet = ethers.Wallet.createRandom();
process.stdout.write(JSON.stringify({
  address: wallet.address,
  private_key: wallet.privateKey
}));
`

	cmd := exec.CommandContext(ctx, "node", "-e", script)
	cmd.Dir = helperDir
	cmd.Env = os.Environ()

	out, err := cmd.Output()
	if err != nil {
		stderr := ""
		if exitErr, ok := err.(*exec.ExitError); ok {
			stderr = strings.TrimSpace(string(exitErr.Stderr))
		}
		if stderr != "" {
			return nil, fmt.Errorf("generate GDEX wallet: %w: %s", err, stderr)
		}
		return nil, fmt.Errorf("generate GDEX wallet: %w", err)
	}

	var wallet generatedGDEXWallet
	if err := json.Unmarshal(out, &wallet); err != nil {
		return nil, fmt.Errorf("parse generated GDEX wallet: %w", err)
	}
	if wallet.Address == "" || wallet.PrivateKey == "" {
		return nil, fmt.Errorf("generated GDEX wallet is incomplete")
	}
	return &wallet, nil
}

func ensureGDEXHelperDeps(helperDir string) error {
	nodeModulesDir := filepath.Join(helperDir, "node_modules")
	if info, err := os.Stat(nodeModulesDir); err == nil && info.IsDir() {
		return nil
	}

	if _, err := exec.LookPath("node"); err != nil {
		return fmt.Errorf("node is required to generate a GDEX wallet: %w", err)
	}

	if setupScript := filepath.Join(helperDir, "setup.sh"); fileExists(setupScript) {
		cmd := exec.Command("bash", setupScript)
		cmd.Dir = helperDir
		cmd.Env = os.Environ()
		if out, err := cmd.CombinedOutput(); err == nil {
			return nil
		} else if _, lookErr := exec.LookPath("npm"); lookErr != nil {
			return fmt.Errorf("GDEX helper setup failed and npm is unavailable: %s", strings.TrimSpace(string(out)))
		}
	}

	if _, err := exec.LookPath("npm"); err != nil {
		return fmt.Errorf("npm is required to install GDEX helper dependencies: %w", err)
	}

	cmd := exec.Command("npm", "install", "--no-audit", "--no-fund")
	cmd.Dir = helperDir
	cmd.Env = os.Environ()
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("install GDEX helper dependencies: %w: %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
