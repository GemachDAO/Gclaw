package dashboard

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

// --- formatAgo ---

func TestFormatAgo(t *testing.T) {
	now := time.Now().UnixMilli()
	tests := []struct {
		name     string
		ms       int64
		contains string
	}{
		{"zero", 0, "unknown"},
		{"just now", now - 30*1000, "ago"},
		{"1 minute ago", now - 90*1000, "m ago"},
		{"2 hours ago", now - 2*3600*1000, "h ago"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := formatAgo(tt.ms)
			if !strings.Contains(got, tt.contains) {
				t.Errorf("formatAgo(%d) = %q, expected to contain %q", tt.ms, got, tt.contains)
			}
		})
	}
}

// --- centerText ---

func TestCenterText_Short(t *testing.T) {
	got := centerText("hi", 10)
	if !strings.Contains(got, "hi") {
		t.Errorf("expected 'hi' in result: %q", got)
	}
}

func TestCenterText_ExactWidth(t *testing.T) {
	got := centerText("hello", 5)
	if got != "hello" {
		t.Errorf("expected 'hello', got %q", got)
	}
}

func TestCenterText_Longer(t *testing.T) {
	got := centerText("test", 20)
	if !strings.Contains(got, "test") {
		t.Errorf("expected 'test' in result: %q", got)
	}
}

// --- htmlEscape ---

func TestHTMLEscape(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"hello", "hello"},
		{"<script>", "&lt;script&gt;"},
		{"a & b", "a &amp; b"},
		{`"quoted"`, "&#34;quoted&#34;"},
		{"it's", "it&#39;s"},
	}
	for _, tt := range tests {
		got := htmlEscape(tt.input)
		if got != tt.want {
			t.Errorf("htmlEscape(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

// --- RegisterHandlers / serveSection ---

func TestRegisterHandlers(t *testing.T) {
	d := NewDashboard(DashboardOptions{AgentID: "test"})
	mux := http.NewServeMux()
	RegisterHandlers(mux, d)

	// Test /dashboard endpoint
	req := httptest.NewRequest(http.MethodGet, "/dashboard", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Errorf("expected 200 for /dashboard, got %d", w.Code)
	}
}

func TestServeSection_ValidSection(t *testing.T) {
	d := NewDashboard(DashboardOptions{
		AgentID: "test",
		GetMetabolism: func() *MetabolismSnapshot {
			return &MetabolismSnapshot{Balance: 100}
		},
		GetFamily:    func() *FamilySnapshot { return &FamilySnapshot{} },
		GetAutonomy:  func() *runtimeinfo.AutonomyStatus { return &runtimeinfo.AutonomyStatus{} },
		GetVenture:   func() *VentureSnapshot { return &VentureSnapshot{} },
		GetTelepathy: func() *TelepathySnapshot { return &TelepathySnapshot{} },
		GetSwarm:     func() *SwarmSnapshot { return &SwarmSnapshot{} },
	})
	mux := http.NewServeMux()
	RegisterHandlers(mux, d)

	for _, path := range []string{
		"/dashboard/api",
		"/dashboard/api/metabolism",
		"/dashboard/api/trading",
		"/dashboard/api/funding",
		"/dashboard/api/autonomy",
		"/dashboard/api/venture",
		"/dashboard/api/family",
		"/dashboard/api/telepathy",
		"/dashboard/api/swarm",
		"/dashboard/api/registration",
		"/dashboard/api/system",
	} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Errorf("expected 200 for %s, got %d", path, w.Code)
		}
	}
}

func TestServeSection_MethodNotAllowed(t *testing.T) {
	d := NewDashboard(DashboardOptions{AgentID: "test"})
	mux := http.NewServeMux()
	RegisterHandlers(mux, d)

	req := httptest.NewRequest(http.MethodPost, "/dashboard/api/metabolism", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405, got %d", w.Code)
	}
}

func TestRenderHTML_FundingDepositQRCodes(t *testing.T) {
	html := renderHTML(&DashboardData{
		AgentID: "main",
		Uptime:  "1m",
		TradingAccess: &runtimeinfo.TradingStatus{
			WalletAddress:    "0xcontrol",
			APIKeyConfigured: true,
			HasPrivateKey:    true,
			AutoTradeEnabled: true,
			AutoTradePlan: &runtimeinfo.AutoTradeStrategy{
				Mode:         "profit_rotation",
				Venue:        "route_aware",
				ChainLabel:   "Ethereum",
				AssetSymbol:  "GMAC",
				Goal:         "Seek liquid opportunities, realize partial gains, and rotate the proceeds back into Gemach inventory.",
				SignalSource: "gdex_holdings + gdex_scan + gdex_trending",
			},
			AutoTradeRuntime: &runtimeinfo.AutoTradeRuntimeStatus{
				State:    "scheduled",
				Schedule: "every 5m",
			},
			ManagedWallets: &runtimeinfo.ManagedWalletStatus{
				State:         "ready",
				EVMAddress:    "0x635dfc3c6241b9f3260e41f8a59855a1d06f33a3",
				SolanaAddress: "3yCvkHHnTENFk1AEg1RUwdABvK3Jh81zaeeLrXtE2GkC",
			},
			FundingInstructions: []runtimeinfo.FundingInstruction{
				{
					Label:   "Deposit ETH",
					Asset:   "ETH",
					Network: "Ethereum / Arbitrum / Base",
					Address: "0x635dfc3c6241b9f3260e41f8a59855a1d06f33a3",
					Purpose: "Use ETH here for EVM spot trading, native bridge moves, and HyperLiquid funding.",
				},
				{
					Label:   "Deposit SOL",
					Asset:   "SOL",
					Network: "Solana",
					Address: "3yCvkHHnTENFk1AEg1RUwdABvK3Jh81zaeeLrXtE2GkC",
					Purpose: "Use SOL here for Solana spot trading and native bridge moves into other supported chains.",
				},
			},
			CapitalMobility: &runtimeinfo.CapitalMobilityStatus{
				State:               "ready",
				NativeBridgeOnly:    true,
				CanSpotTrade:        true,
				CanBridge:           true,
				CanHyperLiquidFund:  true,
				CanHyperLiquidTrade: true,
				Summary:             "The bot can move native capital across supported spot chains, route Arbitrum ETH or USDC into HyperLiquid, and rotate profits back into spot GMAC accumulation.",
				Guidance: []string{
					"Bridge flow is native-asset only today, for example ETH to SOL, SOL to ETH, or Base ETH to ETH.",
					"For HyperLiquid leverage, the fastest funding path is Arbitrum ETH on the managed EVM wallet; the agent can auto-swap ETH into USDC before depositing.",
				},
			},
		},
		Autonomy: &runtimeinfo.AutonomyStatus{
			Identity: runtimeinfo.AgentIdentityStatus{
				Fingerprint: "A1B2-C3D4-E5F6-7788",
				Signature:   "HELIX-A1B2-C3D4",
				Palette:     []string{"#38bdf8", "#f97316", "#14b8a6"},
				Traits:      []string{"adaptive stance", "22-rung spine", "wide helix"},
			},
			DNA: runtimeinfo.AgentDNA{
				Objective:            "profit_to_gmach",
				ProfitSink:           "GMAC inventory, replication capital, and self-recode budget",
				PreferredChains:      []string{"Ethereum", "Arbitrum"},
				PreferredVenues:      []string{"hyperliquid_perps", "gdex_bridge", "gdex_spot"},
				SpotSpend:            "0.01",
				PerpExecutionModel:   "position-sized HyperLiquid execution",
				ReplicationThreshold: 50,
				RecodeThreshold:      100,
				SwarmTarget:          5,
				StrategyRotation:     true,
			},
			KnowledgeGraph: runtimeinfo.KnowledgeGraphStatus{
				NodeCount: 11,
				EdgeCount: 15,
				Domains:   []string{"wallets", "routes", "venues"},
				KeyNodes: []string{
					"objective:profit_to_gmach",
					"wallet:managed_evm:0x635dfc…33a3",
					"venue:gdex_spot",
				},
			},
			Router: runtimeinfo.SelfHealingRouterStatus{
				State:         "self-healing",
				SelectedRoute: "spot_gmac_direct",
				FallbackRoute: "hyperliquid_profit_loop",
				Health: []runtimeinfo.RouteHealthSignal{
					{Name: "helpers", State: "ready", Detail: "GDEX helper runtime availability"},
					{Name: "hl_execution", State: "provisional", Detail: "HyperLiquid order leg is wired. Unfunded HL accounts still need a settled USDC deposit before orders can execute; gdex_hl_deposit can auto-fund from Arbitrum ETH first."},
				},
				Routes: []runtimeinfo.RouteCandidate{
					{
						Name:     "spot_gmac_direct",
						State:    "ready",
						Selected: true,
						Summary:  "Use direct GDEX spot buys to compound into GMAC inventory.",
						Steps:    []string{"capital", "gdex_buy", "GMAC inventory"},
					},
					{
						Name:     "hyperliquid_profit_loop",
						State:    "degraded",
						Summary:  "Bridge capital, auto-fund HyperLiquid from Arbitrum ETH or USDC, trade perps, then recycle profits into GMAC.",
						Steps:    []string{"capital", "gdex_bridge_estimate", "gdex_bridge_request", "gdex_hl_deposit", "gdex_hl_create_order", "gdex_buy", "GMAC inventory"},
						Blockers: []string{"HyperLiquid order flow needs a settled USDC deposit before the account can place orders"},
					},
				},
			},
		},
	})

	for _, want := range []string{
		"Managed EVM",
		"Managed Solana",
		"Deposit ETH",
		"Deposit SOL",
		"data:image/png;base64,",
		"Auto-Trade Runtime",
		"Auto-Trade Plan",
		"GMAC via route_aware on Ethereum",
		"Auto-Trade Goal",
		"every 5m",
		"Funding Guidance",
		"Capital Mobility",
		"Capital Router",
		"native-asset only today",
		"Arbitrum ETH",
		"Autonomy",
		"Agent DNA Signature",
		"HELIX-A1B2-C3D4",
		"A1B2-C3D4-E5F6-7788",
		"adaptive stance",
		"spot_gmac_direct",
		"Profit Sink",
		"Knowledge Graph",
		"Key Nodes",
		"objective:profit_to_gmach",
		"Route Health",
		"helpers",
		"hl_execution",
		"selected",
		"HyperLiquid order flow needs a settled USDC deposit before the account can place orders",
		"auto-fund HyperLiquid from Arbitrum ETH or USDC",
		"11 nodes / 15 edges",
	} {
		if !strings.Contains(html, want) {
			t.Fatalf("expected %q in funding HTML", want)
		}
	}
}

func TestRenderHTML_TelepathyShowsRecentMessages(t *testing.T) {
	html := renderHTML(&DashboardData{
		AgentID: "main",
		Uptime:  "1m",
		Telepathy: &TelepathySnapshot{
			TotalMessages:  74,
			ActiveChannels: 3,
			Persistent:     true,
			RecentMessages: []TelepathyEntry{
				{
					From:      "child-alpha",
					To:        "*",
					Type:      "strategy_update",
					Content:   "Shifting to preservation until a stronger GMAC rotation appears.",
					Timestamp: time.Now().Add(-2 * time.Minute).UnixMilli(),
					Priority:  1,
				},
				{
					From:      "child-beta",
					To:        "main",
					Type:      "warning",
					Content:   "Arbitrum route is thin; wait for better liquidity.",
					Timestamp: time.Now().Add(-1 * time.Minute).UnixMilli(),
					Priority:  2,
				},
			},
		},
	})

	for _, want := range []string{
		"Recent Messages",
		"showing 2 recent messages of 74 total",
		"strategy_update from child-alpha",
		"warning from child-beta",
		"Shifting to preservation until a stronger GMAC rotation appears.",
		"Arbitrum route is thin; wait for better liquidity.",
		"to family",
		"to main",
	} {
		if !strings.Contains(html, want) {
			t.Fatalf("expected %q in rendered html", want)
		}
	}
}

func TestRenderHTML_TradingStatsAreHonestWithoutRealizedPnL(t *testing.T) {
	html := renderHTML(&DashboardData{
		AgentID: "main",
		Uptime:  "1m",
		Trading: &TradingSnapshot{
			TotalTrades:    17,
			RealizedTrades: 0,
			HasRealizedPnL: false,
			ProfitablePct:  0,
			TotalPnL:       0,
		},
	})

	for _, want := range []string{
		"Trade Executions",
		"17",
		"Realized Trades",
		"Realized Win Rate",
		"n/a",
		"pending realization",
	} {
		if !strings.Contains(html, want) {
			t.Fatalf("expected %q in trading HTML", want)
		}
	}
	if strings.Contains(html, "Total Trades") {
		t.Fatal("expected old misleading trade label to be absent")
	}
}

func TestRenderHTML_TradingShowsDecisionsAndMissedOpportunities(t *testing.T) {
	html := renderHTML(&DashboardData{
		AgentID: "main",
		Uptime:  "1m",
		Trading: &TradingSnapshot{
			TotalTrades:    3,
			RealizedTrades: 0,
			HasRealizedPnL: false,
			RecentCycles: []TradeCycleEntry{
				{
					Timestamp:      123,
					Status:         "executed",
					Mode:           "pursue_signal",
					Venue:          "route_aware",
					Chain:          "Ethereum",
					TokenSymbol:    "ALPHA",
					TokenAddress:   "0xalpha",
					Amount:         "0.01",
					ExecutedAction: "buy",
					Summary:        "Take a small liquid signal entry in ALPHA on Ethereum.",
					Outcome:        "Auto-trade executed ALPHA on Ethereum using 0.01 native.",
					Reasons:        []string{"liquidity and volume filters passed"},
				},
			},
			LatestMissedOpportunities: []MissedOpportunityEntry{
				{
					Timestamp:    123,
					TokenSymbol:  "BETA",
					TokenAddress: "0xbeta",
					Chain:        "Arbitrum",
					Score:        88.4,
					Change24H:    7.2,
					LiquidityUSD: 180000,
					Volume24H:    820000,
					Reason:       "viable, but ranked below the selected signal ALPHA",
				},
			},
		},
	})

	for _, want := range []string{
		"Recent Decisions",
		"Missed Opportunities",
		"ALPHA",
		"Ethereum",
		"route_aware",
		"Outcome:",
		"BETA",
		"Arbitrum",
		"ranked below the selected signal ALPHA",
	} {
		if !strings.Contains(html, want) {
			t.Fatalf("expected %q in trading details HTML", want)
		}
	}
}
