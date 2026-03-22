package venture

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
)

func TestForgeDeployerApplyReadiness(t *testing.T) {
	deployer := NewForgeDeployer("0x1234567890abcdef1234567890abcdef12345678", "0xabc")
	deployer.LookupEnv = func(key string) (string, bool) {
		if key == "GCLAW_ARBITRUM_RPC_URL" {
			return "https://arb.example", true
		}
		return "", false
	}
	deployer.LookPath = func(name string) (string, error) {
		if name == "forge" {
			return "/usr/bin/forge", nil
		}
		return "", fmt.Errorf("missing")
	}

	v := &Venture{Chain: "Arbitrum"}
	deployer.ApplyReadiness(v)
	if v.DeploymentState != "deploy_ready" {
		t.Fatalf("deployment state = %q, want deploy_ready", v.DeploymentState)
	}
	if !v.FoundryAvailable || !v.RPCConfigured || !v.WalletReady {
		t.Fatalf("unexpected readiness %+v", v)
	}
}

func TestForgeDeployerApplyReadiness_UsesBuiltInPublicRPCFallback(t *testing.T) {
	deployer := NewForgeDeployer("0x1234567890abcdef1234567890abcdef12345678", "0xabc")
	deployer.LookupEnv = func(string) (string, bool) {
		return "", false
	}
	deployer.LookPath = func(name string) (string, error) {
		if name == "forge" {
			return "/usr/bin/forge", nil
		}
		return "", fmt.Errorf("missing")
	}

	v := &Venture{Chain: "Base"}
	deployer.ApplyReadiness(v)
	if v.DeploymentState != "deploy_ready" {
		t.Fatalf("deployment state = %q, want deploy_ready", v.DeploymentState)
	}
	if !v.RPCConfigured {
		t.Fatalf("expected RPC to be configured via built-in public fallback: %+v", v)
	}
	if v.RPCEnvVar != "builtin_public_rpc" {
		t.Fatalf("rpc env var = %q, want builtin_public_rpc", v.RPCEnvVar)
	}
}

func TestForgeDeployerDeployParsesForgeOutput(t *testing.T) {
	dir := t.TempDir()
	deployer := NewForgeDeployer("0x1234567890abcdef1234567890abcdef12345678", "0xabc")
	deployer.LookupEnv = func(key string) (string, bool) {
		if key == "GCLAW_ETHEREUM_RPC_URL" {
			return "https://eth.example", true
		}
		return "", false
	}
	deployer.LookPath = func(name string) (string, error) {
		return "/usr/bin/forge", nil
	}
	deployer.RunCommand = func(ctx context.Context, gotDir, name string, args ...string) (string, error) {
		if gotDir != dir {
			t.Fatalf("dir = %q, want %q", gotDir, dir)
		}
		if filepath.Base(name) != "forge" {
			t.Fatalf("name = %q, want forge binary", name)
		}
		if !strings.Contains(strings.Join(args, " "), "contracts/GMACBurnTreasury.sol:GMACBurnTreasury") {
			t.Fatalf("unexpected args %v", args)
		}
		return "Deployed to: 0x1111111111111111111111111111111111111111\nTransaction hash: 0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n", nil
	}

	v := &Venture{
		Chain:              "Ethereum",
		ContractSystem:     "GMACBurnTreasury",
		ContractPath:       filepath.Join(dir, "contracts", "GMACBurnTreasury.sol"),
		FoundryProjectPath: dir,
	}

	if err := deployer.Deploy(v); err != nil {
		t.Fatalf("Deploy returned error: %v", err)
	}
	if v.DeploymentState != "deployed" {
		t.Fatalf("deployment state = %q, want deployed", v.DeploymentState)
	}
	if v.DeployedAddress == "" || v.DeploymentTxHash == "" {
		t.Fatalf("expected deployed address and tx hash, got %+v", v)
	}
}
