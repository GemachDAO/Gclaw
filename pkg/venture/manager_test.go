package venture

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

type fakeRecoder struct {
	prompts []string
	crons   []string
}

func (f *fakeRecoder) ModifySystemPrompt(addition string) error {
	f.prompts = append(f.prompts, addition)
	return nil
}

func (f *fakeRecoder) AddCronJob(schedule, task string) error {
	f.crons = append(f.crons, schedule+"|"+task)
	return nil
}

func TestEnsureAutonomousLaunch_RequiresThreshold(t *testing.T) {
	manager := NewManager(t.TempDir(), nil)
	venture, created, err := manager.EnsureAutonomousLaunch(LaunchContext{
		Goodwill:  200,
		Threshold: 5000,
	})
	if err != nil {
		t.Fatalf("EnsureAutonomousLaunch returned error: %v", err)
	}
	if created {
		t.Fatal("expected no venture launch below threshold")
	}
	if venture != nil {
		t.Fatalf("expected nil venture below threshold, got %+v", venture)
	}
}

func TestEnsureAutonomousLaunch_WritesArtifactsAndState(t *testing.T) {
	workspace := t.TempDir()
	recoder := &fakeRecoder{}
	manager := NewManager(workspace, recoder)

	launched, created, err := manager.EnsureAutonomousLaunch(LaunchContext{
		AgentID:      "main",
		Goodwill:     5400,
		Balance:      1900,
		Threshold:    5000,
		FamilySize:   3,
		SwarmMembers: 2,
		Trading: &runtimeinfo.TradingStatus{
			Tools: []string{"gdex_bridge_request", "gdex_hl_deposit", "gdex_hl_create_order", "gdex_buy", "gdex_sell"},
		},
		Autonomy: &runtimeinfo.AutonomyStatus{
			DNA: runtimeinfo.AgentDNA{PreferredChains: []string{"Arbitrum"}},
		},
	})
	if err != nil {
		t.Fatalf("EnsureAutonomousLaunch returned error: %v", err)
	}
	if !created {
		t.Fatal("expected venture to be created")
	}
	if launched == nil {
		t.Fatal("expected venture result")
	}
	if launched.Archetype != "cross_chain_basis_desk" {
		t.Fatalf("unexpected archetype %q", launched.Archetype)
	}

	for _, path := range []string{
		filepath.Join(workspace, "ventures", "state.json"),
		launched.ManifestPath,
		launched.PlaybookPath,
		launched.ContractPath,
		filepath.Join(workspace, "ventures", launched.ID, "foundry.toml"),
	} {
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("expected artifact %s: %v", path, err)
		}
	}
	if len(recoder.prompts) == 0 {
		t.Fatal("expected venture launch to add a prompt directive")
	}
	if len(recoder.crons) == 0 {
		t.Fatal("expected venture launch to register a review cron")
	}
}

func TestRecordProfit_TracksBurnAllocation(t *testing.T) {
	workspace := t.TempDir()
	manager := NewManager(workspace, nil)

	launched, created, err := manager.EnsureAutonomousLaunch(LaunchContext{
		AgentID:   "main",
		Goodwill:  6000,
		Balance:   2500,
		Threshold: 5000,
		Trading: &runtimeinfo.TradingStatus{
			Tools: []string{"gdex_buy", "gdex_sell"},
		},
	})
	if err != nil || !created || launched == nil {
		t.Fatalf("launch failed: created=%t venture=%v err=%v", created, launched, err)
	}

	updated, err := manager.RecordProfit(launched.ID, 125)
	if err != nil {
		t.Fatalf("RecordProfit returned error: %v", err)
	}
	if updated.BurnAllocationUSD != 12.5 {
		t.Fatalf("burn allocation = %.2f, want 12.5", updated.BurnAllocationUSD)
	}

	snap, err := manager.Snapshot(LaunchContext{Goodwill: 6000, Threshold: 5000})
	if err != nil {
		t.Fatalf("Snapshot returned error: %v", err)
	}
	if snap.TotalProfitUSD != 125 {
		t.Fatalf("snapshot profit = %.2f, want 125", snap.TotalProfitUSD)
	}
	if !strings.Contains(snap.BurnPolicy, "10%") {
		t.Fatalf("unexpected burn policy %q", snap.BurnPolicy)
	}
}

func TestEnsureAutonomousLaunch_AutoDeploysWhenReady(t *testing.T) {
	workspace := t.TempDir()
	manager := NewManager(workspace, nil)
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
	deployer.RunCommand = func(ctx context.Context, dir, name string, args ...string) (string, error) {
		return "Deployed to: 0x1111111111111111111111111111111111111111\nTransaction hash: 0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n", nil
	}
	manager.SetDeployer(deployer)

	launched, created, err := manager.EnsureAutonomousLaunch(LaunchContext{
		AgentID:   "main",
		Goodwill:  6000,
		Balance:   2500,
		Threshold: 5000,
		Trading: &runtimeinfo.TradingStatus{
			Tools: []string{"gdex_buy", "gdex_sell", "gdex_bridge_request"},
		},
		Autonomy: &runtimeinfo.AutonomyStatus{
			DNA: runtimeinfo.AgentDNA{PreferredChains: []string{"Ethereum"}},
		},
	})
	if err != nil || !created || launched == nil {
		t.Fatalf("launch failed: created=%t venture=%v err=%v", created, launched, err)
	}
	if launched.DeploymentState != "deployed" {
		t.Fatalf("deployment state = %q, want deployed", launched.DeploymentState)
	}
	if launched.DeployedAddress == "" {
		t.Fatalf("expected deployed address, got %+v", launched)
	}
}
