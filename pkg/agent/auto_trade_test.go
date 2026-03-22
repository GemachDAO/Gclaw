package agent

import (
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/replication"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

func TestAutoTradeSpendAmount(t *testing.T) {
	if got := autoTradeSpendAmount(0.01); got != "0.01" {
		t.Fatalf("autoTradeSpendAmount(0.01) = %q, want 0.01", got)
	}
	if got := autoTradeSpendAmount(0); got != "0.01" {
		t.Fatalf("autoTradeSpendAmount(0) = %q, want 0.01", got)
	}
	if got := autoTradeSpendAmount(1.25); got != "1.25" {
		t.Fatalf("autoTradeSpendAmount(1.25) = %q, want 1.25", got)
	}
}

func TestBuildAutoTradeExecutionPlan_RotatesWinnerIntoGMAC(t *testing.T) {
	cfg := config.DefaultConfig()
	strategy := runtimeinfo.BuildAutoTradeStrategy(cfg)
	autonomy := &runtimeinfo.AutonomyStatus{
		Router: runtimeinfo.SelfHealingRouterStatus{
			Health: []runtimeinfo.RouteHealthSignal{
				{Name: "helpers", State: "ready"},
				{Name: "credentials", State: "ready"},
			},
		},
	}

	plan := buildAutoTradeExecutionPlan(cfg, strategy, autonomy, []autoTradeHolding{
		{
			TokenAddress: "0x00000000000000000000000000000000000000ab",
			Symbol:       "ETHWIN",
			ChainID:      runtimeinfo.EthereumChainID,
			USDValue:     125,
			PriceUSD:     150,
			Change24H:    18,
		},
	}, nil, nil, buildAutoTradeLearningMemory(nil), nil)

	if plan == nil {
		t.Fatal("expected execution plan")
	}
	if plan.Mode != "rotate_profits_to_gmac" {
		t.Fatalf("plan mode = %q, want rotate_profits_to_gmac", plan.Mode)
	}
	if plan.SinkSymbol != "GMAC" || plan.SinkToken == "" {
		t.Fatalf("expected GMAC sink, got %+v", plan)
	}
}

func TestBuildAutoTradeExecutionPlan_PicksLiquidSignalWhenNoWinnerExists(t *testing.T) {
	cfg := config.DefaultConfig()
	strategy := runtimeinfo.BuildAutoTradeStrategy(cfg)
	autonomy := &runtimeinfo.AutonomyStatus{
		Router: runtimeinfo.SelfHealingRouterStatus{
			Health: []runtimeinfo.RouteHealthSignal{
				{Name: "helpers", State: "ready"},
				{Name: "credentials", State: "ready"},
			},
		},
	}

	plan := buildAutoTradeExecutionPlan(cfg, strategy, autonomy, nil, []autoTradeSignalCandidate{
		{
			TokenAddress: "0xabc",
			Symbol:       "ALPHA",
			ChainID:      runtimeinfo.EthereumChainID,
			PriceUSD:     1.25,
			Change24H:    9,
			LiquidityUSD: 125000,
			Volume24H:    750000,
			MarketCapUSD: 50000000,
		},
	}, nil, buildAutoTradeLearningMemory(nil), nil)

	if plan == nil {
		t.Fatal("expected execution plan")
	}
	if plan.Mode != "pursue_signal" {
		t.Fatalf("plan mode = %q, want pursue_signal", plan.Mode)
	}
	if plan.EntrySymbol != "ALPHA" {
		t.Fatalf("expected ALPHA signal, got %+v", plan)
	}
}

func TestParseAutoTradeHoldings(t *testing.T) {
	raw := `{"balances":[{"tokenAddress":"0xabc","symbol":"ALPHA","usdValue":42,"priceUsd":2.1,"change24h":12,"chainId":1}]}`
	holdings := parseAutoTradeHoldings(raw)
	if len(holdings) != 1 {
		t.Fatalf("expected one holding, got %d", len(holdings))
	}
	if holdings[0].Symbol != "ALPHA" || holdings[0].ChainID != 1 {
		t.Fatalf("unexpected holding: %+v", holdings[0])
	}
}

func TestBuildAutoTradeExecutionPlan_ChildProfilesChooseDifferentSignals(t *testing.T) {
	cfg := config.DefaultConfig()
	strategy := runtimeinfo.BuildAutoTradeStrategy(cfg)
	autonomy := &runtimeinfo.AutonomyStatus{
		Router: runtimeinfo.SelfHealingRouterStatus{
			Health: []runtimeinfo.RouteHealthSignal{
				{Name: "helpers", State: "ready"},
				{Name: "credentials", State: "ready"},
			},
		},
	}

	signals := []autoTradeSignalCandidate{
		{
			TokenAddress: "0xmomentum",
			Symbol:       "MOON",
			ChainID:      runtimeinfo.ArbitrumChainID,
			PriceUSD:     1.5,
			Change24H:    14,
			LiquidityUSD: 250000,
			Volume24H:    900000,
			MarketCapUSD: 80000000,
		},
		{
			TokenAddress: "0xdip",
			Symbol:       "DIP",
			ChainID:      runtimeinfo.EthereumChainID,
			PriceUSD:     0.8,
			Change24H:    -3,
			LiquidityUSD: 300000,
			Volume24H:    950000,
			MarketCapUSD: 50000000,
		},
	}

	momentum := &replication.ChildStrategyProfile{
		Style:           "momentum_hunter",
		RiskProfile:     "aggressive",
		PreferredChains: []int64{runtimeinfo.ArbitrumChainID},
		SpendMultiplier: 1.2,
	}
	meanReversion := &replication.ChildStrategyProfile{
		Style:           "mean_reversion",
		RiskProfile:     "balanced",
		PreferredChains: []int64{runtimeinfo.EthereumChainID},
		SpendMultiplier: 0.8,
	}

	momentumPlan := buildAutoTradeExecutionPlan(cfg, strategy, autonomy, nil, signals, momentum, buildAutoTradeLearningMemory(nil), nil)
	reversionPlan := buildAutoTradeExecutionPlan(cfg, strategy, autonomy, nil, signals, meanReversion, buildAutoTradeLearningMemory(nil), nil)

	if momentumPlan == nil || reversionPlan == nil {
		t.Fatal("expected both plans")
	}
	if momentumPlan.EntrySymbol == reversionPlan.EntrySymbol {
		t.Fatalf("expected different entry symbols for divergent child DNA, got %q", momentumPlan.EntrySymbol)
	}
}
