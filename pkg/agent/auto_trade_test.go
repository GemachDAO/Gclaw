package agent

import (
	"errors"
	"strings"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/metabolism"
	"github.com/GemachDAO/Gclaw/pkg/replication"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
	"github.com/GemachDAO/Gclaw/pkg/tools"
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

func TestAutoTradeReserveBalance(t *testing.T) {
	cfg := config.DefaultConfig()
	if got := autoTradeReserveBalance(cfg); got != 75 {
		t.Fatalf("autoTradeReserveBalance(default) = %.1f, want 75.0", got)
	}
}

func TestAutoTradePauseReason_WhenBalanceNearSurvivalReserve(t *testing.T) {
	cfg := config.DefaultConfig()
	agent := &AgentInstance{Tools: tools.NewToolRegistry()}
	agent.Tools.SetMetabolism(metabolism.NewMetabolism(40, metabolismThresholdsFromConfig(cfg)))

	msg, ok := autoTradePauseReason(agent, cfg)
	if !ok {
		t.Fatal("expected auto-trade to pause near survival reserve")
	}
	if !strings.Contains(msg, "survival reserve 75.0") {
		t.Fatalf("unexpected pause message: %s", msg)
	}
}

func TestAutoTradePauseReason_WhenBalanceHealthy(t *testing.T) {
	cfg := config.DefaultConfig()
	agent := &AgentInstance{Tools: tools.NewToolRegistry()}
	agent.Tools.SetMetabolism(metabolism.NewMetabolism(200, metabolismThresholdsFromConfig(cfg)))

	if msg, ok := autoTradePauseReason(agent, cfg); ok {
		t.Fatalf("expected auto-trade to continue, got pause %q", msg)
	}
}

func TestDefaultThresholds_SetVentureArchitectHigh(t *testing.T) {
	cfg := config.DefaultConfig()
	if cfg.Metabolism.Thresholds.Architect != 5000 {
		t.Fatalf("architect threshold = %d, want 5000", cfg.Metabolism.Thresholds.Architect)
	}
}

func TestBuildAutoTradeBudgetRegime_LowBalanceBiasesRecovery(t *testing.T) {
	cfg := config.DefaultConfig()
	met := metabolism.NewMetabolism(140, metabolismThresholdsFromConfig(cfg))
	regime := buildAutoTradeBudgetRegime(cfg, met, nil)
	if regime == nil {
		t.Fatal("expected budget regime")
	}
	if regime.State != "capital_preservation" {
		t.Fatalf("regime state = %q, want capital_preservation", regime.State)
	}
	if !regime.PreferDirectGMAC {
		t.Fatal("expected low-balance regime to prefer direct GMAC")
	}
	if regime.SpendMultiplier >= 1 {
		t.Fatalf("expected reduced spend multiplier, got %.2f", regime.SpendMultiplier)
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
	}, nil, nil, buildAutoTradeLearningMemory(nil), nil, nil)

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
	}, nil, buildAutoTradeLearningMemory(nil), nil, nil)

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

func TestPickSignalCandidate_IgnoresStablecoinLikeSignals(t *testing.T) {
	cfg := config.DefaultConfig()
	signal, ok := pickSignalCandidate(cfg, []autoTradeSignalCandidate{
		{
			TokenAddress: "0xusdc",
			Symbol:       "USDC",
			ChainID:      runtimeinfo.EthereumChainID,
			PriceUSD:     1.0,
			Change24H:    0.1,
			LiquidityUSD: 1000000,
			Volume24H:    5000000,
		},
		{
			TokenAddress: "0xalpha",
			Symbol:       "ALPHA",
			ChainID:      runtimeinfo.EthereumChainID,
			PriceUSD:     1.25,
			Change24H:    9,
			LiquidityUSD: 125000,
			Volume24H:    750000,
			MarketCapUSD: 50000000,
		},
	}, nil, buildAutoTradeLearningMemory(nil))
	if !ok {
		t.Fatal("expected viable non-stable signal")
	}
	if signal.Symbol != "ALPHA" {
		t.Fatalf("expected ALPHA signal, got %+v", signal)
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

	momentumPlan := buildAutoTradeExecutionPlan(cfg, strategy, autonomy, nil, signals, momentum, buildAutoTradeLearningMemory(nil), nil, nil)
	reversionPlan := buildAutoTradeExecutionPlan(cfg, strategy, autonomy, nil, signals, meanReversion, buildAutoTradeLearningMemory(nil), nil, nil)

	if momentumPlan == nil || reversionPlan == nil {
		t.Fatal("expected both plans")
	}
	if momentumPlan.EntrySymbol == reversionPlan.EntrySymbol {
		t.Fatalf("expected different entry symbols for divergent child DNA, got %q", momentumPlan.EntrySymbol)
	}
}

func TestBuildAutoTradeExecutionPlan_BudgetRegimePrefersGMACOverSignalHunt(t *testing.T) {
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
	}, nil, buildAutoTradeLearningMemory(nil), nil, &autoTradeBudgetRegime{
		State:            "capital_preservation",
		SpendMultiplier:  0.6,
		PreferDirectGMAC: true,
		Reason:           "capital preservation mode reduces discovery burn and biases toward direct GMAC accumulation",
	})

	if plan == nil {
		t.Fatal("expected execution plan")
	}
	if plan.Mode != "accumulate_gmac" {
		t.Fatalf("plan mode = %q, want accumulate_gmac", plan.Mode)
	}
	if plan.EntrySymbol != strategy.AssetSymbol {
		t.Fatalf("entry symbol = %q, want %q", plan.EntrySymbol, strategy.AssetSymbol)
	}
}

func TestEmitAutoTradeTelepathyNarrative_BroadcastsStrategyInsightAndWarning(t *testing.T) {
	tb := replication.NewTelepathyBus(nil, "family", "main")
	ch := tb.Subscribe("observer")
	agent := &AgentInstance{ID: "main", TelepathyBus: tb}
	entry := &autoTradeJournalEntry{
		Status:      "failed",
		Mode:        "pursue_signal",
		Venue:       "route_aware",
		ChainLabel:  "Ethereum",
		TokenSymbol: "The Glitch",
		Summary:     "Take a small liquid signal entry in The Glitch on Ethereum and monitor it for later GMAC rotation.",
		Reasons:     []string{"no winner was ready to rotate", "liquidity and volume filters passed"},
		MissedOpportunities: []autoTradeOpportunityRecord{
			{TokenSymbol: "GOLDEN", ChainLabel: "Ethereum", Score: 84},
			{TokenSymbol: "WBTC", ChainLabel: "Ethereum", Score: 82},
		},
	}

	emitAutoTradeTelepathyNarrative(agent, &autoTradeBudgetRegime{
		State:  "survival_rebuild",
		Reason: "runway is thin or the loss streak is elevated, so stop paying for new signal hunts and rebuild GMAC directly",
	}, entry, "gdex_buy failed", errors.New("gdex_buy failed"))

	var messages []replication.TelepathyMessage
	for i := 0; i < 3; i++ {
		select {
		case msg := <-ch:
			messages = append(messages, msg)
		default:
			t.Fatalf("expected 3 telepathy messages, got %d", len(messages))
		}
	}

	types := make(map[string]string, len(messages))
	for _, msg := range messages {
		types[msg.Type] = msg.Content
	}
	if !strings.Contains(types["strategy_update"], "The Glitch") {
		t.Fatalf("expected strategy update to mention selected token, got %q", types["strategy_update"])
	}
	if !strings.Contains(types["market_insight"], "GOLDEN") || !strings.Contains(types["market_insight"], "WBTC") {
		t.Fatalf("expected market insight to mention missed opportunities, got %q", types["market_insight"])
	}
	if !strings.Contains(types["warning"], "Execution warning") {
		t.Fatalf("expected warning message, got %q", types["warning"])
	}
}
