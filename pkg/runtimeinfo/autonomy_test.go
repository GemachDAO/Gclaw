package runtimeinfo

import (
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/config"
)

func TestBuildAutonomyStatus_SelectsSpotWhenHLRouteIsProvisional(t *testing.T) {
	cfg := config.DefaultConfig()
	status := BuildTradingStatus(cfg, []string{
		"gdex_buy",
		"gdex_bridge_estimate",
		"gdex_bridge_request",
		"gdex_hl_deposit",
		"gdex_hl_create_order",
	})
	status.APIKeyConfigured = true
	status.WalletAddress = "0x1234567890abcdef1234567890abcdef12345678"
	status.HasPrivateKey = true
	status.HelpersInstalled = true
	status.ManagedWallets = &ManagedWalletStatus{
		State:         "ready",
		EVMAddress:    "0x635dfc3c6241b9f3260e41f8a59855a1d06f33a3",
		SolanaAddress: "3yCvkHHnTENFk1AEg1RUwdABvK3Jh81zaeeLrXtE2GkC",
	}

	autonomy := BuildAutonomyStatus(cfg, status, 2, 1, "main")
	if autonomy == nil {
		t.Fatal("expected autonomy status")
	}
	if autonomy.Identity.Fingerprint == "" || autonomy.Identity.Signature == "" {
		t.Fatalf("expected identity fingerprint and signature, got %+v", autonomy.Identity)
	}
	if autonomy.Router.SelectedRoute != "spot_gmac_direct" {
		t.Fatalf("selected route = %q, want spot_gmac_direct", autonomy.Router.SelectedRoute)
	}
	if autonomy.Router.FallbackRoute != "hyperliquid_profit_loop" {
		t.Fatalf("fallback route = %q, want hyperliquid_profit_loop", autonomy.Router.FallbackRoute)
	}
	if autonomy.Router.State != "self-healing" {
		t.Fatalf("router state = %q, want self-healing", autonomy.Router.State)
	}
	if autonomy.KnowledgeGraph.NodeCount == 0 || autonomy.KnowledgeGraph.EdgeCount == 0 {
		t.Fatalf("expected non-empty knowledge graph, got %+v", autonomy.KnowledgeGraph)
	}
	if len(autonomy.KnowledgeGraph.KeyNodes) == 0 {
		t.Fatalf("expected key nodes, got %+v", autonomy.KnowledgeGraph)
	}
	if len(autonomy.Router.Health) == 0 {
		t.Fatalf("expected route health signals, got %+v", autonomy.Router)
	}
}

func TestBuildAutonomyStatus_BlocksWithoutGMACRoute(t *testing.T) {
	cfg := config.DefaultConfig()
	cfg.Tools.GDEX.GmacToken = config.GmacTokenConfig{}

	status := BuildTradingStatus(cfg, []string{"gdex_buy"})
	status.APIKeyConfigured = true
	status.WalletAddress = "0x1234567890abcdef1234567890abcdef12345678"
	status.HasPrivateKey = true
	status.HelpersInstalled = true

	autonomy := BuildAutonomyStatus(cfg, status, 1, 1, "main")
	if autonomy == nil {
		t.Fatal("expected autonomy status")
	}
	if autonomy.Router.SelectedRoute != "" {
		t.Fatalf("expected no selected route, got %q", autonomy.Router.SelectedRoute)
	}
	if autonomy.Router.State != "blocked" {
		t.Fatalf("router state = %q, want blocked", autonomy.Router.State)
	}
}

func TestBuildAutonomyStatus_IdentityIsDeterministic(t *testing.T) {
	cfg := config.DefaultConfig()
	status := BuildTradingStatus(cfg, []string{"gdex_buy"})
	status.APIKeyConfigured = true
	status.WalletAddress = "0x1234567890abcdef1234567890abcdef12345678"
	status.HasPrivateKey = true
	status.HelpersInstalled = true

	first := BuildAutonomyStatus(cfg, status, 1, 1, "main")
	second := BuildAutonomyStatus(cfg, status, 1, 1, "main")
	if first == nil || second == nil {
		t.Fatal("expected autonomy status")
	}
	if first.Identity.Fingerprint != second.Identity.Fingerprint ||
		first.Identity.Signature != second.Identity.Signature {
		t.Fatalf("expected deterministic identity, got %+v and %+v", first.Identity, second.Identity)
	}
}
