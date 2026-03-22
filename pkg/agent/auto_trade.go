package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/replication"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
	"github.com/GemachDAO/Gclaw/pkg/swarm"
)

// RunAutoTradeCycle executes one deterministic autonomous trading cycle
// against the default agent.
func (al *AgentLoop) RunAutoTradeCycle(ctx context.Context) (string, error) {
	agent := al.registry.GetDefaultAgent()
	if agent == nil {
		return "", fmt.Errorf("no default agent available")
	}
	return al.runAutoTradeCycle(ctx, agent)
}

func (al *AgentLoop) tryDirectRuntimeShortcut(
	ctx context.Context,
	agent *AgentInstance,
	opts processOptions,
) (string, bool, error) {
	message := strings.TrimSpace(opts.UserMessage)
	if message == "" {
		return "", false, nil
	}

	if message == runtimeinfo.AutoTradeCycleCommand {
		content, err := al.runAutoTradeCycle(ctx, agent)
		return content, true, err
	}

	section, ok := classifyDashboardShortcut(message)
	if !ok {
		return "", false, nil
	}

	result := agent.Tools.ExecuteWithContext(
		ctx,
		"dashboard",
		map[string]any{"section": section},
		opts.Channel,
		opts.ChatID,
		nil,
	)
	if result.IsError {
		return result.ForLLM, true, nil
	}
	return strings.TrimSpace(result.ForLLM), true, nil
}

func classifyDashboardShortcut(message string) (string, bool) {
	lower := strings.ToLower(message)
	funding := containsAny(lower,
		"wallet",
		"managed solana",
		"managed evm",
		"funding",
		"deposit",
		"auto trade",
		"auto-trade",
		"trading tools",
		"tool names",
		"loaded gdex",
		"gdex tools",
		"helper readiness",
	)
	registration := containsAny(lower,
		"erc-8004",
		"erc8004",
		"x402",
		"registration",
	)

	switch {
	case funding && registration:
		return "all", true
	case funding:
		return "funding", true
	case registration:
		return "registration", true
	default:
		return "", false
	}
}

func containsAny(s string, parts ...string) bool {
	for _, part := range parts {
		if strings.Contains(s, part) {
			return true
		}
	}
	return false
}

func (al *AgentLoop) runAutoTradeCycle(ctx context.Context, agent *AgentInstance) (string, error) {
	if agent == nil {
		return "", fmt.Errorf("agent not available")
	}

	strategy := runtimeinfo.BuildAutoTradeStrategy(al.cfg)
	if strategy == nil {
		return "", fmt.Errorf("auto-trade strategy is not configured")
	}

	trading := runtimeinfo.PopulateManagedWallets(
		al.cfg,
		runtimeinfo.BuildTradingStatus(al.cfg, agent.Tools.List()),
		5*time.Second,
	)
	totalFamily := 1
	if agent.Replicator != nil {
		totalFamily += len(agent.Replicator.ListChildren())
	}
	swarmSize := 0
	if agent.Swarm != nil {
		swarmSize = len(agent.Swarm.GetMembers())
	}
	autonomy := runtimeinfo.BuildAutonomyStatus(al.cfg, trading, totalFamily, swarmSize, agent.ID)
	childProfile, _ := replication.LoadChildStrategyProfile(agent.Workspace)
	memory := buildAutoTradeLearningMemory(agent.Tools.GetTradeHistory(0))
	directive := buildSwarmDirective(agent)
	holdings := al.fetchAutoTradeHoldings(ctx, agent, strategy, childProfile)
	signals := al.fetchAutoTradeSignals(ctx, agent, strategy, childProfile)
	plan := buildAutoTradeExecutionPlan(al.cfg, strategy, autonomy, holdings, signals, childProfile, memory, directive)
	if plan == nil {
		return "", fmt.Errorf("auto-trade planner returned no executable plan")
	}

	switch plan.Mode {
	case "rotate_profits_to_gmac":
		return al.runAutoTradeProfitRotation(ctx, agent, plan)
	case "pursue_signal", "accumulate_gmac", "swarm_consensus_buy":
		return al.runAutoTradeSpotPlan(ctx, agent, plan)
	case "swarm_consensus_sell":
		return al.runAutoTradeSellPlan(ctx, agent, plan)
	case "research_only":
		return plan.Summary, nil
	default:
		return "", fmt.Errorf("unsupported auto-trade mode %q", plan.Mode)
	}
}

func (al *AgentLoop) runAutoTradeSellPlan(
	ctx context.Context,
	agent *AgentInstance,
	plan *autoTradeExecutionPlan,
) (string, error) {
	if plan == nil {
		return "", fmt.Errorf("auto-trade sell plan is required")
	}

	sell := agent.Tools.Execute(ctx, "gdex_sell", map[string]any{
		"chain_id":      plan.ExitChainID,
		"token_address": plan.ExitToken,
		"amount":        plan.ExitAmount,
	})
	if sell.IsError {
		if agent.Swarm != nil {
			agent.Swarm.MarkDecisionStatus("failed", strings.TrimSpace(sell.ForLLM))
			_ = swarm.SaveSwarmState(agent.Workspace, agent.Swarm)
		}
		return "", fmt.Errorf(
			"gdex_sell failed for %s on %s (%s) with amount %s: %s",
			plan.ExitSymbol,
			plan.ExitChainLabel,
			plan.ExitToken,
			plan.ExitAmount,
			strings.TrimSpace(sell.ForLLM),
		)
	}
	if agent.Swarm != nil {
		agent.Swarm.MarkDecisionStatus("executed", "swarm-directed sell completed")
		_ = swarm.SaveSwarmState(agent.Workspace, agent.Swarm)
	}
	return fmt.Sprintf(
		"Auto-trade executed a swarm-directed sell of %s on %s using %s.",
		plan.ExitSymbol,
		plan.ExitChainLabel,
		plan.ExitAmount,
	), nil
}

func (al *AgentLoop) runAutoTradeSpotPlan(
	ctx context.Context,
	agent *AgentInstance,
	plan *autoTradeExecutionPlan,
) (string, error) {
	if plan == nil {
		return "", fmt.Errorf("auto-trade plan is required")
	}

	amount := strings.TrimSpace(plan.SpendAmount)
	if amount == "" {
		amount = autoTradeSpendAmount(al.cfg.Tools.GDEX.MaxTradeSizeSOL)
	}

	buy := agent.Tools.Execute(ctx, "gdex_buy", map[string]any{
		"chain_id":      plan.EntryChainID,
		"token_address": plan.EntryToken,
		"amount":        amount,
	})
	if buy.IsError {
		if agent.Swarm != nil && plan.Mode == "swarm_consensus_buy" {
			agent.Swarm.MarkDecisionStatus("failed", strings.TrimSpace(buy.ForLLM))
			_ = swarm.SaveSwarmState(agent.Workspace, agent.Swarm)
		}
		return "", fmt.Errorf(
			"gdex_buy failed for %s on %s (%s) with %s native: %s",
			plan.EntrySymbol,
			plan.EntryChainLabel,
			plan.EntryToken,
			amount,
			strings.TrimSpace(buy.ForLLM),
		)
	}
	if agent.Swarm != nil && plan.Mode == "swarm_consensus_buy" {
		agent.Swarm.MarkDecisionStatus("executed", "swarm-directed entry completed")
		_ = swarm.SaveSwarmState(agent.Workspace, agent.Swarm)
	}

	return fmt.Sprintf(
		"Auto-trade executed %s on %s using %s native. %s",
		plan.EntrySymbol,
		plan.EntryChainLabel,
		amount,
		plan.Summary,
	), nil
}

func (al *AgentLoop) runAutoTradeProfitRotation(
	ctx context.Context,
	agent *AgentInstance,
	plan *autoTradeExecutionPlan,
) (string, error) {
	if plan == nil {
		return "", fmt.Errorf("auto-trade rotation plan is required")
	}

	sell := agent.Tools.Execute(ctx, "gdex_sell", map[string]any{
		"chain_id":      plan.ExitChainID,
		"token_address": plan.ExitToken,
		"amount":        plan.ExitAmount,
	})
	if sell.IsError {
		return "", fmt.Errorf(
			"gdex_sell failed for %s on %s (%s) with amount %s: %s",
			plan.ExitSymbol,
			plan.ExitChainLabel,
			plan.ExitToken,
			plan.ExitAmount,
			strings.TrimSpace(sell.ForLLM),
		)
	}

	buyAmount := strings.TrimSpace(plan.SpendAmount)
	if amountOut, ok := extractTradeAmountOut(sell.ForLLM); ok && amountOut > 0 {
		buyAmount = clampNativeSpend(amountOut, al.cfg.Tools.GDEX.MaxTradeSizeSOL)
	}
	if buyAmount == "" {
		buyAmount = autoTradeSpendAmount(al.cfg.Tools.GDEX.MaxTradeSizeSOL)
	}

	buy := agent.Tools.Execute(ctx, "gdex_buy", map[string]any{
		"chain_id":      plan.SinkChainID,
		"token_address": plan.SinkToken,
		"amount":        buyAmount,
	})
	if buy.IsError {
		return "", fmt.Errorf(
			"gdex_buy failed while rotating into %s on %s (%s) with %s native: %s",
			plan.SinkSymbol,
			plan.SinkChainLabel,
			plan.SinkToken,
			buyAmount,
			strings.TrimSpace(buy.ForLLM),
		)
	}

	return fmt.Sprintf(
		"Auto-trade rotated %s of %s on %s into %s using %s native of realized proceeds.",
		plan.ExitAmount,
		plan.ExitSymbol,
		plan.ExitChainLabel,
		plan.SinkSymbol,
		buyAmount,
	), nil
}

func autoTradeSpendAmount(maxTradeSizeSOL float64) string {
	return runtimeinfo.FormatAutoTradeSpendAmount(maxTradeSizeSOL)
}

func (al *AgentLoop) fetchAutoTradeHoldings(
	ctx context.Context,
	agent *AgentInstance,
	strategy *runtimeinfo.AutoTradeStrategy,
	profile *replication.ChildStrategyProfile,
) []autoTradeHolding {
	if agent == nil || strategy == nil {
		return nil
	}

	chainIDs := make([]int64, 0, 4)
	appendChain := func(chainID int64) {
		if chainID == 0 {
			return
		}
		for _, existing := range chainIDs {
			if existing == chainID {
				return
			}
		}
		chainIDs = append(chainIDs, chainID)
	}

	if profile != nil {
		for _, chainID := range profile.PreferredChains {
			appendChain(chainID)
		}
	}
	appendChain(strategy.ChainID)
	appendChain(al.cfg.Tools.GDEX.DefaultChainID)
	for _, chainID := range []int64{
		runtimeinfo.EthereumChainID,
		runtimeinfo.ArbitrumChainID,
		runtimeinfo.SolanaChainID,
	} {
		if gmacTokenAddressForChain(al.cfg, chainID) != "" {
			appendChain(chainID)
		}
	}

	out := make([]autoTradeHolding, 0, 16)
	for _, chainID := range chainIDs {
		holdings := agent.Tools.Execute(ctx, "gdex_holdings", map[string]any{
			"chain_id": chainID,
		})
		if holdings.IsError {
			continue
		}
		out = append(out, parseAutoTradeHoldings(holdings.ForLLM)...)
	}
	if len(out) == 0 {
		return nil
	}
	return al.enrichAutoTradeHoldings(ctx, agent, out)
}

func (al *AgentLoop) enrichAutoTradeHoldings(
	ctx context.Context,
	agent *AgentInstance,
	holdings []autoTradeHolding,
) []autoTradeHolding {
	if len(holdings) == 0 {
		return holdings
	}

	sort.SliceStable(holdings, func(i, j int) bool {
		return holdings[i].USDValue > holdings[j].USDValue
	})

	limit := len(holdings)
	if limit > 3 {
		limit = 3
	}
	for i := 0; i < limit; i++ {
		if holdings[i].Change24H != 0 && holdings[i].PriceUSD > 0 {
			continue
		}
		price := agent.Tools.Execute(ctx, "gdex_price", map[string]any{
			"chain_id":      holdings[i].ChainID,
			"token_address": holdings[i].TokenAddress,
		})
		if price.IsError {
			continue
		}
		signals := parseAutoTradeSignals(price.ForLLM, holdings[i].ChainID)
		if len(signals) == 0 {
			continue
		}
		holdings[i].PriceUSD = firstFloat(holdings[i].PriceUSD, signals[0].PriceUSD)
		holdings[i].Change24H = firstFloat(holdings[i].Change24H, signals[0].Change24H)
	}
	return holdings
}

func (al *AgentLoop) fetchAutoTradeSignals(
	ctx context.Context,
	agent *AgentInstance,
	strategy *runtimeinfo.AutoTradeStrategy,
	profile *replication.ChildStrategyProfile,
) []autoTradeSignalCandidate {
	if agent == nil || strategy == nil {
		return nil
	}

	chainIDs := make([]int64, 0, 3)
	appendChain := func(chainID int64) {
		if chainID == 0 {
			return
		}
		for _, existing := range chainIDs {
			if existing == chainID {
				return
			}
		}
		chainIDs = append(chainIDs, chainID)
	}

	if profile != nil {
		for _, chainID := range profile.PreferredChains {
			appendChain(chainID)
		}
	}
	appendChain(strategy.ChainID)
	appendChain(al.cfg.Tools.GDEX.DefaultChainID)
	appendChain(runtimeinfo.SolanaChainID)

	out := make([]autoTradeSignalCandidate, 0, 24)
	for _, chainID := range chainIDs {
		for _, toolName := range []string{"gdex_scan", "gdex_trending"} {
			result := agent.Tools.Execute(ctx, toolName, map[string]any{
				"chain_id": chainID,
				"limit":    12,
			})
			if result.IsError {
				continue
			}
			out = append(out, parseAutoTradeSignals(result.ForLLM, chainID)...)
		}
	}

	return out
}

type autoTradeSwarmDirective struct {
	Action       string
	TokenAddress string
	ChainID      int64
	Confidence   float64
	ExecutorID   string
	Summary      string
	SpendAmount  string
	SellAmount   string
}

func buildSwarmDirective(agent *AgentInstance) *autoTradeSwarmDirective {
	if agent == nil || agent.Swarm == nil {
		return nil
	}
	decision := agent.Swarm.PendingDecisionFor(agent.ID)
	if decision == nil {
		return nil
	}
	return &autoTradeSwarmDirective{
		Action:       decision.Action,
		TokenAddress: decision.TokenAddress,
		ChainID:      int64(decision.ChainID),
		Confidence:   decision.Confidence,
		ExecutorID:   decision.ExecutorID,
		Summary:      decision.Summary,
		SpendAmount:  decision.SpendAmount,
		SellAmount:   decision.SellAmount,
	}
}

func extractTradeAmountOut(raw string) (float64, bool) {
	var decoded map[string]any
	if err := json.Unmarshal([]byte(raw), &decoded); err != nil {
		return 0, false
	}
	return mapFloat(decoded, "amountOut", "amount_out"), true
}

func clampNativeSpend(amount, configuredMax float64) string {
	if amount <= 0 {
		return ""
	}
	maxSpend := configuredMax
	if maxSpend <= 0 {
		maxSpend = 0.01
	}
	if amount > maxSpend {
		amount = maxSpend
	}
	return runtimeinfo.FormatAutoTradeSpendAmount(amount)
}
