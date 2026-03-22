package runtimeinfo

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/cron"
)

func TestBuildTradingStatus(t *testing.T) {
	cfg := config.DefaultConfig()
	cfg.Agents.Defaults.Workspace = t.TempDir()
	cfg.Tools.GDEX.WalletAddress = "0x1234567890abcdef1234567890abcdef12345678"
	cfg.Tools.GDEX.PrivateKey = "0xdeadbeef"
	cfg.Tools.GDEX.AutoTrade = true
	cfg.Tools.X402.Enabled = true

	status := BuildTradingStatus(cfg, []string{"gdex_buy", "tempo_pay", "x402_fetch", "message"})
	if !status.Enabled {
		t.Fatal("expected trading to be enabled")
	}
	if status.WalletAddress == "" {
		t.Fatal("expected wallet address")
	}
	if !status.HasPrivateKey {
		t.Fatal("expected private key presence")
	}
	if !status.AutoTradeEnabled {
		t.Fatal("expected auto trade enabled")
	}
	if status.AutoTradeRuntime == nil {
		t.Fatal("expected auto trade runtime status")
	}
	if status.AutoTradePlan == nil {
		t.Fatal("expected auto trade plan")
	}
	if status.AutoTradePlan.AssetSymbol != "GMAC" {
		t.Fatalf("expected GMAC auto trade plan, got %+v", status.AutoTradePlan)
	}
	if status.ToolCount != 3 {
		t.Fatalf("expected 3 filtered tools, got %d", status.ToolCount)
	}
}

func TestBuildTradingStatus_DefaultExpectedToolsIncludeBridgeAndHLFunding(t *testing.T) {
	cfg := config.DefaultConfig()
	cfg.Agents.Defaults.Workspace = t.TempDir()
	cfg.Tools.GDEX.APIKey = "test-key"

	status := BuildTradingStatus(cfg, nil)
	have := make(map[string]struct{}, len(status.Tools))
	for _, name := range status.Tools {
		have[name] = struct{}{}
	}
	for _, want := range []string{"gdex_bridge_estimate", "gdex_bridge_request", "gdex_bridge_orders", "gdex_hl_deposit"} {
		if _, ok := have[want]; !ok {
			t.Fatalf("expected %s in default trading tools, got %v", want, status.Tools)
		}
	}
}

func TestBuildTradingStatus_AutoTradeRuntimeFromCronStore(t *testing.T) {
	workspace := t.TempDir()
	cfg := config.DefaultConfig()
	cfg.Agents.Defaults.Workspace = workspace
	cfg.Tools.GDEX.AutoTrade = true

	if err := os.MkdirAll(filepath.Join(workspace, "cron"), 0o755); err != nil {
		t.Fatalf("mkdir cron: %v", err)
	}
	next := time.Now().Add(5 * time.Minute).UnixMilli()
	last := time.Now().Add(-1 * time.Minute).UnixMilli()
	everyMS := int64((5 * time.Minute) / time.Millisecond)
	store := cron.CronStore{
		Version: 1,
		Jobs: []cron.CronJob{{
			ID:      "job-auto",
			Name:    AutoTradeJobName,
			Enabled: true,
			Schedule: cron.CronSchedule{
				Kind:    "every",
				EveryMS: &everyMS,
			},
			Payload: cron.CronPayload{
				Message: AutoTradeCycleCommand,
			},
			State: cron.CronJobState{
				LastRunAtMS: &last,
				NextRunAtMS: &next,
				LastStatus:  "ok",
			},
		}},
	}
	data, err := json.Marshal(store)
	if err != nil {
		t.Fatalf("marshal cron store: %v", err)
	}
	if err := os.WriteFile(filepath.Join(workspace, "cron", "jobs.json"), data, 0o644); err != nil {
		t.Fatalf("write cron store: %v", err)
	}

	status := BuildTradingStatus(cfg, nil)
	if status.AutoTradeRuntime == nil {
		t.Fatal("expected auto trade runtime")
	}
	if status.AutoTradeRuntime.State != "scheduled" {
		t.Fatalf("runtime state = %q, want scheduled", status.AutoTradeRuntime.State)
	}
	if status.AutoTradeRuntime.Schedule != "every 5m" {
		t.Fatalf("runtime schedule = %q, want every 5m", status.AutoTradeRuntime.Schedule)
	}
	if !status.AutoTradeRuntime.Active {
		t.Fatal("expected active auto trade runtime")
	}
}

func TestMergeManagedWalletStatus_ReusesLastGoodAddresses(t *testing.T) {
	previous := &ManagedWalletStatus{
		ControlWallet: "0xcontrol",
		EVMAddress:    "0xevm",
		SolanaAddress: "sol",
		State:         "ready",
	}
	current := &ManagedWalletStatus{
		ControlWallet: "0xcontrol",
		State:         "error",
		Error:         "backend 400",
	}

	merged := mergeManagedWalletStatus(previous, current)
	if merged.State != "ready" {
		t.Fatalf("merged state = %q, want ready", merged.State)
	}
	if merged.EVMAddress != "0xevm" || merged.SolanaAddress != "sol" {
		t.Fatalf("expected cached addresses to be reused, got %+v", merged)
	}
	if len(merged.Warnings) == 0 {
		t.Fatal("expected warning about cached addresses")
	}
}

func TestResolveGDEXAPIKey_CommaSeparated(t *testing.T) {
	cfg := config.DefaultConfig()
	cfg.Tools.GDEX.APIKey = "first-key, second-key"

	got := ResolveGDEXAPIKey(cfg)
	if got != "first-key" {
		t.Fatalf("expected first split key, got %q", got)
	}
}

func TestBuildAutoTradeStrategy_FallsBackWhenNoGMACRoute(t *testing.T) {
	cfg := config.DefaultConfig()
	cfg.Tools.GDEX.DefaultChainID = SolanaChainID
	cfg.Tools.GDEX.GmacToken = config.GmacTokenConfig{}

	strategy := BuildAutoTradeStrategy(cfg)
	if strategy == nil {
		t.Fatal("expected auto trade strategy")
	}
	if strategy.Mode != "liquidity_fallback" {
		t.Fatalf("strategy mode = %q, want liquidity_fallback", strategy.Mode)
	}
	if strategy.ChainID != SolanaChainID {
		t.Fatalf("strategy chain = %d, want %d", strategy.ChainID, SolanaChainID)
	}
}

func TestBuildAutoTradeStrategy_UsesProfitRotationWhenGMACRouteConfigured(t *testing.T) {
	cfg := config.DefaultConfig()

	strategy := BuildAutoTradeStrategy(cfg)
	if strategy == nil {
		t.Fatal("expected auto trade strategy")
	}
	if strategy.Mode != "profit_rotation" {
		t.Fatalf("strategy mode = %q, want profit_rotation", strategy.Mode)
	}
	if strategy.SignalSource == "" || strategy.ProfitPolicy == "" {
		t.Fatalf("expected signal source and profit policy, got %+v", strategy)
	}
}

func TestBuildRegistrationStatus(t *testing.T) {
	cfg := config.DefaultConfig()
	cfg.Tools.ERC8004.Enabled = true

	status := BuildRegistrationStatus(cfg)
	if status.State != "deferred" {
		t.Fatalf("expected deferred registration, got %q", status.State)
	}

	cfg.Tools.GDEX.WalletAddress = "0x123"
	cfg.Tools.GDEX.PrivateKey = "0xabc"
	status = BuildRegistrationStatus(cfg)
	if status.State != "active" {
		t.Fatalf("expected active registration, got %q", status.State)
	}
}

func TestProbeGateway(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("/ready", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("/dashboard", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("/.well-known/agent-registration.json", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()

	cfg := config.DefaultConfig()
	cfg.Gateway.Host = "127.0.0.1"
	cfg.Gateway.Port = serverPort(t, srv.URL)

	probe := ProbeGateway(cfg, 2*time.Second)
	if !probe.Reachable || !probe.HealthOK || !probe.ReadyOK || !probe.DashboardOK || !probe.RegistrationLive {
		t.Fatalf("unexpected gateway probe: %+v", probe)
	}
}

func TestFetchTradingStatus(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/dashboard/api/funding", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(&TradingStatus{
			Enabled:          true,
			APIKeyConfigured: true,
			WalletAddress:    "0x123",
			ManagedWallets: &ManagedWalletStatus{
				State:         "ready",
				SolanaAddress: "solana123",
			},
		})
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()

	cfg := config.DefaultConfig()
	cfg.Gateway.Host = "127.0.0.1"
	cfg.Gateway.Port = serverPort(t, srv.URL)

	status, err := FetchTradingStatus(cfg, 2*time.Second)
	if err != nil {
		t.Fatalf("FetchTradingStatus returned error: %v", err)
	}
	if status == nil || status.WalletAddress != "0x123" {
		t.Fatalf("unexpected trading status: %+v", status)
	}
	if status.ManagedWallets == nil || status.ManagedWallets.SolanaAddress != "solana123" {
		t.Fatalf("expected managed solana wallet in status: %+v", status)
	}
}

func serverPort(t *testing.T, baseURL string) int {
	t.Helper()
	parsed, err := url.Parse(baseURL)
	if err != nil {
		t.Fatalf("failed to parse %q: %v", baseURL, err)
	}
	port, err := strconv.Atoi(parsed.Port())
	if err != nil {
		t.Fatalf("failed to parse port from %q: %v", baseURL, err)
	}
	return port
}
