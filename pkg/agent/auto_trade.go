package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/logger"
	"github.com/GemachDAO/Gclaw/pkg/metabolism"
	"github.com/GemachDAO/Gclaw/pkg/replication"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
	"github.com/GemachDAO/Gclaw/pkg/swarm"
	"github.com/GemachDAO/Gclaw/pkg/venture"
)

const autoTradeReserveBufferGMAC = 25.0

type autoTradeBudgetRegime struct {
	State                  string
	SpendMultiplier        float64
	PreferDirectGMAC       bool
	DisableSignalDiscovery bool
	SignalToolNames        []string
	MaxSignalChains        int
	Reason                 string
}

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

func autoTradeReserveBalance(cfg *config.Config) float64 {
	if cfg == nil {
		return autoTradeReserveBufferGMAC
	}
	threshold := cfg.Metabolism.SurvivalThreshold
	if threshold < 0 {
		threshold = 0
	}
	return threshold + autoTradeReserveBufferGMAC
}

func autoTradePauseReason(agent *AgentInstance, cfg *config.Config) (string, bool) {
	if agent == nil || agent.Tools == nil {
		return "", false
	}
	met := agent.Tools.GetMetabolism()
	if met == nil {
		return "", false
	}

	status := met.GetStatus()
	reserve := autoTradeReserveBalance(cfg)
	if status.SurvivalMode || status.Balance <= reserve {
		return fmt.Sprintf(
			"Auto-trade paused: GMAC balance %.1f is at or below the survival reserve %.1f.",
			status.Balance,
			reserve,
		), true
	}

	return "", false
}

func buildAutoTradeBudgetRegime(
	cfg *config.Config,
	met *metabolism.Metabolism,
	memory *autoTradeLearningMemory,
) *autoTradeBudgetRegime {
	regime := &autoTradeBudgetRegime{
		State:           "growth",
		SpendMultiplier: 1.0,
		SignalToolNames: []string{"gdex_scan", "gdex_trending"},
		MaxSignalChains: 3,
	}
	if met == nil {
		return regime
	}

	status := met.GetStatus()
	reserve := autoTradeReserveBalance(cfg)

	switch {
	case status.SurvivalMode || status.Balance <= reserve:
		regime.State = "paused"
		regime.SpendMultiplier = 0.0
		regime.PreferDirectGMAC = true
		regime.DisableSignalDiscovery = true
		regime.MaxSignalChains = 0
		regime.Reason = "survival reserve reached; preserve enough seeded GMAC runway to stay alive"
	case status.Balance <= reserve+35 || (memory != nil && memory.LossStreak >= 3):
		regime.State = "survival_rebuild"
		regime.SpendMultiplier = 0.35
		regime.PreferDirectGMAC = true
		regime.DisableSignalDiscovery = true
		regime.MaxSignalChains = 0
		regime.Reason = "runway is thin or the loss streak is elevated, so stop paying for new signal hunts and rebuild GMAC directly"
	case status.Balance <= reserve+100 || (memory != nil && memory.LossStreak >= 2):
		regime.State = "capital_preservation"
		regime.SpendMultiplier = 0.60
		regime.PreferDirectGMAC = true
		regime.SignalToolNames = []string{"gdex_trending"}
		regime.MaxSignalChains = 1
		regime.Reason = "capital preservation mode reduces discovery burn and biases toward direct GMAC accumulation"
	case status.Balance <= reserve+200:
		regime.State = "measured_growth"
		regime.SpendMultiplier = 0.85
		regime.SignalToolNames = []string{"gdex_trending"}
		regime.MaxSignalChains = 2
		regime.Reason = "runway is healthy but not abundant, so exploration stays selective"
	}

	return regime
}

func (al *AgentLoop) runAutoTradeCycle(ctx context.Context, agent *AgentInstance) (string, error) {
	if agent == nil {
		return "", fmt.Errorf("agent not available")
	}

	strategy := runtimeinfo.BuildAutoTradeStrategy(al.cfg)
	if strategy == nil {
		return "", fmt.Errorf("auto-trade strategy is not configured")
	}
	if msg, ok := autoTradePauseReason(agent, al.cfg); ok {
		al.persistAutoTradeJournal(agent, autoTradeJournalEntry{
			Timestamp: time.Now().UnixMilli(),
			Status:    "paused",
			Mode:      "paused",
			Venue:     "system",
			Summary:   msg,
			Outcome:   msg,
		})
		return msg, nil
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
	ventureMessage := al.ensureAutonomousVenture(agent, trading, autonomy, totalFamily, swarmSize)
	childProfile, _ := replication.LoadChildStrategyProfile(agent.Workspace)
	memory := buildAutoTradeLearningMemory(agent.Tools.GetTradeHistory(0))
	budget := buildAutoTradeBudgetRegime(al.cfg, agent.Tools.GetMetabolism(), memory)
	directive := buildSwarmDirective(agent)
	holdings := al.fetchAutoTradeHoldings(ctx, agent, strategy, childProfile)
	signals := al.fetchAutoTradeSignals(ctx, agent, strategy, childProfile, budget)
	plan := buildAutoTradeExecutionPlan(al.cfg, strategy, autonomy, holdings, signals, childProfile, memory, directive, budget)
	if plan == nil {
		al.persistAutoTradeJournal(agent, autoTradeJournalEntry{
			Timestamp: time.Now().UnixMilli(),
			Status:    "failed",
			Mode:      "unknown",
			Venue:     "unknown",
			Summary:   "auto-trade planner returned no executable plan",
			Outcome:   "auto-trade planner returned no executable plan",
		})
		return "", fmt.Errorf("auto-trade planner returned no executable plan")
	}
	journalEntry := newAutoTradeJournalEntry(al.cfg, plan, strategy, signals, childProfile, memory)
	recordResult := func(status, outcome string, err error) {
		if journalEntry == nil {
			return
		}
		entry := *journalEntry
		entry.Status = status
		entry.Outcome = strings.TrimSpace(outcome)
		if err != nil && entry.Outcome == "" {
			entry.Outcome = err.Error()
		}
		al.persistAutoTradeJournal(agent, entry)
	}

	switch plan.Mode {
	case "rotate_profits_to_gmac":
		result, err := al.runAutoTradeProfitRotation(ctx, agent, plan)
		recordResult(autoTradeJournalStatus(err), result, err)
		return prependAutoTradeMessage(ventureMessage, result), err
	case "pursue_signal", "accumulate_gmac", "swarm_consensus_buy":
		result, err := al.runAutoTradeSpotPlan(ctx, agent, plan)
		recordResult(autoTradeJournalStatus(err), result, err)
		return prependAutoTradeMessage(ventureMessage, result), err
	case "swarm_consensus_sell":
		result, err := al.runAutoTradeSellPlan(ctx, agent, plan)
		recordResult(autoTradeJournalStatus(err), result, err)
		return prependAutoTradeMessage(ventureMessage, result), err
	case "research_only":
		recordResult("skipped", plan.Summary, nil)
		return prependAutoTradeMessage(ventureMessage, plan.Summary), nil
	default:
		recordResult("failed", "", fmt.Errorf("unsupported auto-trade mode %q", plan.Mode))
		return "", fmt.Errorf("unsupported auto-trade mode %q", plan.Mode)
	}
}

func (al *AgentLoop) persistAutoTradeJournal(agent *AgentInstance, entry autoTradeJournalEntry) {
	if agent == nil || strings.TrimSpace(agent.Workspace) == "" {
		return
	}
	if err := recordAutoTradeJournalEntry(agent.Workspace, entry); err != nil {
		logger.WarnCF("agent", "Failed to persist auto-trade journal",
			map[string]any{
				"workspace": agent.Workspace,
				"error":     err.Error(),
			})
	}
}

func autoTradeJournalStatus(err error) string {
	if err != nil {
		return "failed"
	}
	return "executed"
}

func prependAutoTradeMessage(prefix, body string) string {
	prefix = strings.TrimSpace(prefix)
	body = strings.TrimSpace(body)
	switch {
	case prefix == "":
		return body
	case body == "":
		return prefix
	default:
		return prefix + " " + body
	}
}

func (al *AgentLoop) ensureAutonomousVenture(
	agent *AgentInstance,
	trading *runtimeinfo.TradingStatus,
	autonomy *runtimeinfo.AutonomyStatus,
	totalFamily int,
	swarmSize int,
) string {
	if agent == nil || agent.VentureManager == nil || agent.Tools == nil {
		return ""
	}
	met := agent.Tools.GetMetabolism()
	if met == nil || !met.CanArchitect() {
		return ""
	}
	ventureCtx := venture.LaunchContext{
		AgentID:      agent.ID,
		Goodwill:     met.GetGoodwill(),
		Balance:      met.GetBalance(),
		Threshold:    al.cfg.Metabolism.Thresholds.Architect,
		FamilySize:   totalFamily,
		SwarmMembers: swarmSize,
		Trading:      trading,
		Autonomy:     autonomy,
	}
	launched, created, err := agent.VentureManager.EnsureAutonomousLaunch(ventureCtx)
	if err != nil || !created || launched == nil {
		return ""
	}
	if launched.DeployedAddress != "" {
		return fmt.Sprintf(
			"Venture architect unlocked: deployed %s (%s) on %s at %s.",
			launched.Title,
			launched.Archetype,
			launched.Chain,
			launched.DeployedAddress,
		)
	}
	return fmt.Sprintf(
		"Venture architect unlocked: launched %s (%s) on %s.",
		launched.Title,
		launched.Archetype,
		launched.Chain,
	)
}

func metabolismThresholdsFromConfig(cfg *config.Config) metabolism.Thresholds {
	if cfg == nil {
		return metabolism.Thresholds{Hibernate: autoTradeReserveBufferGMAC}
	}
	return metabolism.Thresholds{
		Hibernate:   cfg.Metabolism.SurvivalThreshold,
		Replicate:   cfg.Metabolism.Thresholds.Replicate,
		SelfRecode:  cfg.Metabolism.Thresholds.SelfRecode,
		SwarmLeader: cfg.Metabolism.Thresholds.SwarmLeader,
		Architect:   cfg.Metabolism.Thresholds.Architect,
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
	budget *autoTradeBudgetRegime,
) []autoTradeSignalCandidate {
	if agent == nil || strategy == nil {
		return nil
	}
	if budget != nil && budget.DisableSignalDiscovery {
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
	if budget != nil && budget.MaxSignalChains > 0 && len(chainIDs) > budget.MaxSignalChains {
		chainIDs = chainIDs[:budget.MaxSignalChains]
	}

	out := make([]autoTradeSignalCandidate, 0, 24)
	toolNames := []string{"gdex_scan", "gdex_trending"}
	if budget != nil && len(budget.SignalToolNames) > 0 {
		toolNames = budget.SignalToolNames
	}
	for _, chainID := range chainIDs {
		for _, toolName := range toolNames {
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
