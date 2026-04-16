package agent

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/replication"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

type autoTradeExecutionPlan struct {
	Mode            string
	Summary         string
	Reasons         []string
	EntryChainID    int64
	EntryChainLabel string
	EntryToken      string
	EntrySymbol     string
	SpendAmount     string
	ExitChainID     int64
	ExitChainLabel  string
	ExitToken       string
	ExitSymbol      string
	ExitAmount      string
	SinkChainID     int64
	SinkChainLabel  string
	SinkToken       string
	SinkSymbol      string
}

type autoTradeHolding struct {
	TokenAddress string
	Symbol       string
	ChainID      int64
	Balance      string
	USDValue     float64
	PriceUSD     float64
	Change24H    float64
}

type autoTradeSignalCandidate struct {
	TokenAddress string
	Symbol       string
	ChainID      int64
	PriceUSD     float64
	Change24H    float64
	LiquidityUSD float64
	Volume24H    float64
	MarketCapUSD float64
	Score        float64
}

func buildAutoTradeExecutionPlan(
	cfg *config.Config,
	strategy *runtimeinfo.AutoTradeStrategy,
	autonomy *runtimeinfo.AutonomyStatus,
	holdings []autoTradeHolding,
	signals []autoTradeSignalCandidate,
	profile *replication.ChildStrategyProfile,
	memory *autoTradeLearningMemory,
	directive *autoTradeSwarmDirective,
	budget *autoTradeBudgetRegime,
) *autoTradeExecutionPlan {
	if strategy == nil {
		return &autoTradeExecutionPlan{
			Mode:    "research_only",
			Summary: "Auto-trade planner is not configured.",
		}
	}

	if autonomy != nil &&
		(routeHealthState(autonomy, "helpers") == "blocked" || routeHealthState(autonomy, "credentials") == "blocked") {
		return &autoTradeExecutionPlan{
			Mode:    "research_only",
			Summary: "Trading runtime is not ready, so the agent stays in research mode instead of forcing a trade.",
			Reasons: []string{"helpers or credentials are blocked"},
		}
	}

	if plan := buildPlanFromSwarmDirective(directive, strategy, profile); plan != nil {
		return plan
	}

	spendAmount := strings.TrimSpace(strategy.SpendAmount)
	if spendAmount == "" {
		spendAmount = "0.01"
	}
	spendAmount = applySpendMultiplier(spendAmount, profile)
	spendAmount = applyBudgetSpendMultiplier(spendAmount, budget)

	if rotation, sinkAddress, ok := pickRotationCandidate(cfg, holdings, profile, memory); ok {
		return &autoTradeExecutionPlan{
			Mode: "rotate_profits_to_gmac",
			Summary: fmt.Sprintf(
				"Trim a strong non-GMAC position and route the realized proceeds back into GMAC on %s.",
				autoTradeChainLabel(rotation.ChainID),
			),
			Reasons: append(
				append(
					[]string{
						"existing holding shows enough strength to bank gains",
						"GMAC sink is available on the same chain",
					},
					budgetReason(budget)...),
				profileReason(profile)...),
			ExitChainID:    rotation.ChainID,
			ExitChainLabel: autoTradeChainLabel(rotation.ChainID),
			ExitToken:      rotation.TokenAddress,
			ExitSymbol:     rotation.Symbol,
			ExitAmount:     rotationSellAmount(rotation),
			SinkChainID:    rotation.ChainID,
			SinkChainLabel: autoTradeChainLabel(rotation.ChainID),
			SinkToken:      sinkAddress,
			SinkSymbol:     "GMAC",
			SpendAmount:    spendAmount,
		}
	}

	if budget != nil && budget.PreferDirectGMAC && strings.TrimSpace(strategy.AssetAddress) != "" {
		return &autoTradeExecutionPlan{
			Mode: "accumulate_gmac",
			Summary: fmt.Sprintf(
				"GMAC runway pressure is high, so accumulate GMAC directly on %s instead of paying for a wider hunt.",
				strategy.ChainLabel,
			),
			Reasons: append(
				[]string{"survival game theory favors preserving optionality and rebuilding the GMAC reserve"},
				budgetReason(budget)...),
			EntryChainID:    strategy.ChainID,
			EntryChainLabel: strategy.ChainLabel,
			EntryToken:      strategy.AssetAddress,
			EntrySymbol:     strategy.AssetSymbol,
			SpendAmount:     spendAmount,
		}
	}

	if profile != nil && profile.Style == "gmac_accumulator" {
		return &autoTradeExecutionPlan{
			Mode: "accumulate_gmac",
			Summary: fmt.Sprintf(
				"%s profile is biasing this cycle toward direct GMAC accumulation on %s.",
				profile.Label,
				strategy.ChainLabel,
			),
			Reasons: append(
				append(
					[]string{"child DNA prefers compounding GMAC inventory over speculative entries"},
					budgetReason(budget)...),
				profileReason(profile)...),
			EntryChainID:    strategy.ChainID,
			EntryChainLabel: strategy.ChainLabel,
			EntryToken:      strategy.AssetAddress,
			EntrySymbol:     strategy.AssetSymbol,
			SpendAmount:     spendAmount,
		}
	}

	if signal, ok := pickSignalCandidate(cfg, signals, profile, memory); ok {
		return &autoTradeExecutionPlan{
			Mode: "pursue_signal",
			Summary: fmt.Sprintf(
				"Take a small liquid signal entry in %s on %s and monitor it for later GMAC rotation.",
				signal.Symbol,
				autoTradeChainLabel(signal.ChainID),
			),
			Reasons: append(
				append(
					[]string{"no winner was ready to rotate", "liquidity and volume filters passed"},
					budgetReason(budget)...),
				profileReason(profile)...),
			EntryChainID:    signal.ChainID,
			EntryChainLabel: autoTradeChainLabel(signal.ChainID),
			EntryToken:      signal.TokenAddress,
			EntrySymbol:     signal.Symbol,
			SpendAmount:     spendAmount,
		}
	}

	if strings.TrimSpace(strategy.AssetAddress) != "" {
		return &autoTradeExecutionPlan{
			Mode: "accumulate_gmac",
			Summary: fmt.Sprintf(
				"No strong profit setup was found, so accumulate GMAC directly on %s.",
				strategy.ChainLabel,
			),
			Reasons: append(
				[]string{"profit-hunt filters rejected current signals", "GMAC sink remains funded and available"},
				budgetReason(budget)...),
			EntryChainID:    strategy.ChainID,
			EntryChainLabel: strategy.ChainLabel,
			EntryToken:      strategy.AssetAddress,
			EntrySymbol:     strategy.AssetSymbol,
			SpendAmount:     spendAmount,
		}
	}

	return &autoTradeExecutionPlan{
		Mode:    "research_only",
		Summary: "No acceptable setup passed the liquidity and risk filters, so the agent stays in research mode.",
	}
}

func pickRotationCandidate(
	cfg *config.Config,
	holdings []autoTradeHolding,
	profile *replication.ChildStrategyProfile,
	memory *autoTradeLearningMemory,
) (autoTradeHolding, string, bool) {
	bestScore := math.Inf(-1)
	var best autoTradeHolding
	var bestSink string

	for _, holding := range holdings {
		if strings.TrimSpace(holding.TokenAddress) == "" || strings.TrimSpace(holding.Symbol) == "" {
			continue
		}
		if holding.USDValue < 15 || holding.PriceUSD <= 0 {
			continue
		}

		sink := gmacTokenAddressForChain(cfg, holding.ChainID)
		if sink == "" {
			continue
		}
		if strings.EqualFold(strings.TrimSpace(holding.TokenAddress), strings.TrimSpace(sink)) {
			continue
		}
		if holding.Change24H < 7 {
			continue
		}

		score := holding.Change24H*1.6 + math.Min(holding.USDValue, 300)/20
		score += chainPreferenceScore(profile, holding.ChainID)
		score += memory.chainScore(holding.ChainID) * 2
		score += memory.tokenScore(holding.TokenAddress)
		if profile != nil && profile.Style == "gmac_accumulator" {
			score += 6
		}
		if profile != nil && profile.Style == "mean_reversion" {
			score -= 3
		}
		if score <= bestScore {
			continue
		}
		bestScore = score
		best = holding
		bestSink = sink
	}

	if bestScore == math.Inf(-1) {
		return autoTradeHolding{}, "", false
	}
	return best, bestSink, true
}

func rotationSellAmount(holding autoTradeHolding) string {
	switch {
	case holding.Change24H >= 20 || holding.USDValue >= 150:
		return "50%"
	case holding.Change24H >= 12 || holding.USDValue >= 60:
		return "35%"
	default:
		return "25%"
	}
}

func pickSignalCandidate(
	cfg *config.Config,
	signals []autoTradeSignalCandidate,
	profile *replication.ChildStrategyProfile,
	memory *autoTradeLearningMemory,
) (autoTradeSignalCandidate, bool) {
	ranked := rankSignalCandidates(cfg, signals, profile, memory)
	if len(ranked) == 0 {
		return autoTradeSignalCandidate{}, false
	}
	return ranked[0], true
}

func rankSignalCandidates(
	cfg *config.Config,
	signals []autoTradeSignalCandidate,
	profile *replication.ChildStrategyProfile,
	memory *autoTradeLearningMemory,
) []autoTradeSignalCandidate {
	if len(signals) == 0 {
		return nil
	}
	excluded := map[string]struct{}{}
	if cfg != nil {
		for _, address := range []string{
			cfg.Tools.GDEX.GmacToken.Ethereum,
			cfg.Tools.GDEX.GmacToken.Arbitrum,
			cfg.Tools.GDEX.GmacToken.Solana,
		} {
			address = strings.TrimSpace(strings.ToLower(address))
			if address != "" {
				excluded[address] = struct{}{}
			}
		}
	}

	filtered := make([]autoTradeSignalCandidate, 0, len(signals))
	for _, signal := range signals {
		address := strings.TrimSpace(strings.ToLower(signal.TokenAddress))
		if address == "" {
			continue
		}
		if isStablecoinLikeSignal(signal) {
			continue
		}
		if _, skip := excluded[address]; skip {
			continue
		}
		if signal.PriceUSD <= 0 || signal.LiquidityUSD < 25000 || signal.Volume24H < 100000 {
			continue
		}
		if signal.Change24H < -12 || signal.Change24H > 40 {
			continue
		}
		signal.Score = scoreSignalCandidate(signal, profile, memory)
		filtered = append(filtered, signal)
	}

	if len(filtered) == 0 {
		return nil
	}

	sort.SliceStable(filtered, func(i, j int) bool {
		return filtered[i].Score > filtered[j].Score
	})
	return filtered
}

func isStablecoinLikeSignal(signal autoTradeSignalCandidate) bool {
	switch strings.ToUpper(strings.TrimSpace(signal.Symbol)) {
	case "USDC", "USDT", "DAI", "USDE", "FDUSD", "TUSD", "USDS", "USDB", "BUSD", "PYUSD":
		return true
	}
	return signal.PriceUSD >= 0.98 && signal.PriceUSD <= 1.02 && math.Abs(signal.Change24H) <= 3
}

func scoreSignalCandidate(
	signal autoTradeSignalCandidate,
	profile *replication.ChildStrategyProfile,
	memory *autoTradeLearningMemory,
) float64 {
	liquidityComponent := math.Min(signal.LiquidityUSD/250000, 1) * 35
	volumeComponent := math.Min(signal.Volume24H/1000000, 1) * 35
	momentum := clampFloat(signal.Change24H, -5, 20)
	momentumComponent := ((momentum + 5) / 25) * 20
	marketCapComponent := 0.0
	if signal.MarketCapUSD > 0 {
		marketCapComponent = math.Min(signal.MarketCapUSD/250000000, 1) * 10
	}
	score := liquidityComponent + volumeComponent + momentumComponent + marketCapComponent
	score += chainPreferenceScore(profile, signal.ChainID)
	score += memory.chainScore(signal.ChainID) * 3
	score += memory.tokenScore(signal.TokenAddress)
	if memory != nil && memory.LossStreak >= 2 {
		score -= 6
	}
	switch styleFromProfile(profile) {
	case "momentum_hunter":
		score += math.Max(signal.Change24H, 0) * 0.8
	case "mean_reversion":
		score += meanReversionScore(signal.Change24H)
	case "solana_scout":
		if signal.ChainID == runtimeinfo.SolanaChainID {
			score += 18
		}
	case "bridge_rotator":
		if signal.ChainID == runtimeinfo.ArbitrumChainID || signal.ChainID == runtimeinfo.EthereumChainID {
			score += 10
		}
	case "gmac_accumulator":
		score -= 10
	}
	if profile != nil && profile.RiskProfile == "cautious" && signal.LiquidityUSD < 100000 {
		score -= 12
	}
	return score
}

func buildPlanFromSwarmDirective(
	directive *autoTradeSwarmDirective,
	strategy *runtimeinfo.AutoTradeStrategy,
	profile *replication.ChildStrategyProfile,
) *autoTradeExecutionPlan {
	if directive == nil || strategy == nil {
		return nil
	}
	spendAmount := strings.TrimSpace(directive.SpendAmount)
	if spendAmount == "" {
		spendAmount = applySpendMultiplier(strings.TrimSpace(strategy.SpendAmount), profile)
	}
	switch strings.ToLower(strings.TrimSpace(directive.Action)) {
	case "sell":
		return &autoTradeExecutionPlan{
			Mode: "swarm_consensus_sell",
			Summary: firstNonEmptyString(
				strings.TrimSpace(directive.Summary),
				"Execute the swarm-approved trim and report the result back to the swarm.",
			),
			Reasons:        append([]string{"swarm consensus approved a sell"}, profileReason(profile)...),
			ExitChainID:    directive.ChainID,
			ExitChainLabel: autoTradeChainLabel(directive.ChainID),
			ExitToken:      directive.TokenAddress,
			ExitSymbol:     normalizeTokenSymbol(directive.TokenAddress),
			ExitAmount:     firstNonEmptyString(strings.TrimSpace(directive.SellAmount), "25%"),
		}
	default:
		return &autoTradeExecutionPlan{
			Mode: "swarm_consensus_buy",
			Summary: firstNonEmptyString(
				strings.TrimSpace(directive.Summary),
				"Execute the swarm-approved entry and report the result back to the swarm.",
			),
			Reasons:         append([]string{"swarm consensus approved a buy"}, profileReason(profile)...),
			EntryChainID:    directive.ChainID,
			EntryChainLabel: autoTradeChainLabel(directive.ChainID),
			EntryToken:      directive.TokenAddress,
			EntrySymbol:     normalizeTokenSymbol(directive.TokenAddress),
			SpendAmount:     firstNonEmptyString(spendAmount, "0.01"),
		}
	}
}

func chainPreferenceScore(profile *replication.ChildStrategyProfile, chainID int64) float64 {
	if profile == nil || len(profile.PreferredChains) == 0 {
		return 0
	}
	for idx, preferred := range profile.PreferredChains {
		if preferred != chainID {
			continue
		}
		switch idx {
		case 0:
			return 18
		case 1:
			return 12
		default:
			return 6
		}
	}
	return -4
}

func meanReversionScore(change24h float64) float64 {
	switch {
	case change24h >= -8 && change24h <= 2:
		return 16 - math.Abs(change24h+2)
	case change24h > 15:
		return -10
	default:
		return 0
	}
}

func profileReason(profile *replication.ChildStrategyProfile) []string {
	if profile == nil {
		return nil
	}
	reasons := []string{fmt.Sprintf("child DNA style=%s risk=%s", profile.Style, profile.RiskProfile)}
	if strings.TrimSpace(profile.StrategyHint) != "" {
		reasons = append(reasons, "operator hint influenced this child profile")
	}
	return reasons
}

func styleFromProfile(profile *replication.ChildStrategyProfile) string {
	if profile == nil {
		return ""
	}
	return strings.TrimSpace(profile.Style)
}

func applySpendMultiplier(amount string, profile *replication.ChildStrategyProfile) string {
	if profile == nil || profile.SpendMultiplier == 0 {
		return strings.TrimSpace(amount)
	}
	value, err := strconv.ParseFloat(strings.TrimSpace(amount), 64)
	if err != nil || value <= 0 {
		return strings.TrimSpace(amount)
	}
	value *= profile.SpendMultiplier
	if value < 0.0025 {
		value = 0.0025
	}
	return runtimeinfo.FormatAutoTradeSpendAmount(value)
}

func applyBudgetSpendMultiplier(amount string, budget *autoTradeBudgetRegime) string {
	if budget == nil || budget.SpendMultiplier == 0 || budget.SpendMultiplier == 1 {
		return strings.TrimSpace(amount)
	}
	value, err := strconv.ParseFloat(strings.TrimSpace(amount), 64)
	if err != nil || value <= 0 {
		return strings.TrimSpace(amount)
	}
	value *= budget.SpendMultiplier
	if value < 0.0025 {
		value = 0.0025
	}
	return runtimeinfo.FormatAutoTradeSpendAmount(value)
}

func budgetReason(budget *autoTradeBudgetRegime) []string {
	if budget == nil {
		return nil
	}
	reason := strings.TrimSpace(budget.Reason)
	if reason == "" {
		return nil
	}
	return []string{reason}
}

func parseAutoTradeHoldings(raw string) []autoTradeHolding {
	var decoded any
	if err := json.Unmarshal([]byte(raw), &decoded); err != nil {
		return nil
	}

	entries := flattenMaps(decoded)
	holdings := make([]autoTradeHolding, 0, len(entries))
	for _, entry := range entries {
		address := mapString(entry, "tokenAddress", "token_address", "address")
		if address == "" {
			continue
		}
		holdings = append(holdings, autoTradeHolding{
			TokenAddress: address,
			Symbol:       normalizeTokenSymbol(mapString(entry, "symbol", "name")),
			ChainID:      mapInt64(entry, "chainId", "chain_id", "chain"),
			Balance:      mapString(entry, "balance", "rawBalance", "raw_balance"),
			USDValue:     mapFloat(entry, "usdValue", "usd_value", "valueUsd", "value_usd"),
			PriceUSD:     mapFloat(entry, "priceUsd", "price_usd"),
			Change24H:    mapFloat(entry, "change24h", "change_24h"),
		})
	}
	return holdings
}

func parseAutoTradeSignals(raw string, defaultChainID int64) []autoTradeSignalCandidate {
	var decoded any
	if err := json.Unmarshal([]byte(raw), &decoded); err != nil {
		return nil
	}

	entries := flattenMaps(decoded)
	signals := make([]autoTradeSignalCandidate, 0, len(entries))
	for _, entry := range entries {
		address := mapString(
			entry,
			"tokenAddress",
			"token_address",
			"address",
			"mint",
			"contractAddress",
			"contract_address",
		)
		if address == "" {
			continue
		}

		change24H := mapFloat(entry, "change24h", "change_24h")
		if priceChanges, ok := entry["priceChanges"].(map[string]any); ok {
			change24H = firstFloat(change24H, mapFloat(priceChanges, "h24"))
		}
		volume24H := mapFloat(entry, "volume24h", "volume_24h")
		if volumes, ok := entry["volumes"].(map[string]any); ok {
			volume24H = firstFloat(volume24H, mapFloat(volumes, "h24"))
		}

		chainID := mapInt64(entry, "chainId", "chain_id", "chain")
		if chainID == 0 {
			chainID = defaultChainID
		}

		signals = append(signals, autoTradeSignalCandidate{
			TokenAddress: address,
			Symbol:       normalizeTokenSymbol(mapString(entry, "symbol", "name")),
			ChainID:      chainID,
			PriceUSD:     mapFloat(entry, "priceUsd", "price_usd"),
			Change24H:    change24H,
			LiquidityUSD: mapFloat(entry, "liquidityUsd", "liquidity_usd"),
			Volume24H:    volume24H,
			MarketCapUSD: mapFloat(entry, "marketCap", "market_cap"),
		})
	}
	return signals
}

func flattenMaps(v any) []map[string]any {
	switch node := v.(type) {
	case []any:
		out := make([]map[string]any, 0, len(node))
		for _, item := range node {
			out = append(out, flattenMaps(item)...)
		}
		return out
	case map[string]any:
		if mapString(node, "tokenAddress", "token_address", "address", "mint", "contractAddress", "contract_address") != "" {
			return []map[string]any{node}
		}
		if mapString(node, "symbol", "name") != "" && (mapFloat(node, "usdValue", "priceUsd", "liquidityUsd") > 0 || node["priceChanges"] != nil) {
			return []map[string]any{node}
		}
		out := make([]map[string]any, 0)
		for _, key := range []string{"data", "balances", "tokens", "items", "results", "pairs"} {
			if child, ok := node[key]; ok {
				out = append(out, flattenMaps(child)...)
			}
		}
		return out
	default:
		return nil
	}
}

func normalizeTokenSymbol(symbol string) string {
	symbol = strings.TrimSpace(symbol)
	if symbol == "" {
		return "token"
	}
	return strings.TrimPrefix(symbol, "$")
}

func firstNonEmptyString(values ...string) string {
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" {
			return value
		}
	}
	return ""
}

func mapString(m map[string]any, keys ...string) string {
	for _, key := range keys {
		switch value := m[key].(type) {
		case string:
			value = strings.TrimSpace(value)
			if value != "" {
				return value
			}
		case float64:
			if value != 0 {
				return fmt.Sprintf("%.0f", value)
			}
		}
	}
	return ""
}

func mapFloat(m map[string]any, keys ...string) float64 {
	for _, key := range keys {
		if value, ok := m[key]; ok {
			switch typed := value.(type) {
			case float64:
				return typed
			case int:
				return float64(typed)
			case int64:
				return float64(typed)
			case string:
				var parsed float64
				if _, err := fmt.Sscanf(strings.TrimSpace(typed), "%f", &parsed); err == nil {
					return parsed
				}
			}
		}
	}
	return 0
}

func mapInt64(m map[string]any, keys ...string) int64 {
	for _, key := range keys {
		if value, ok := m[key]; ok {
			switch typed := value.(type) {
			case float64:
				return int64(typed)
			case int:
				return int64(typed)
			case int64:
				return typed
			case string:
				switch strings.ToLower(strings.TrimSpace(typed)) {
				case "solana":
					return runtimeinfo.SolanaChainID
				case "ethereum":
					return runtimeinfo.EthereumChainID
				case "arbitrum":
					return runtimeinfo.ArbitrumChainID
				}
				var parsed int64
				if _, err := fmt.Sscanf(strings.TrimSpace(typed), "%d", &parsed); err == nil {
					return parsed
				}
			}
		}
	}
	return 0
}

func firstFloat(values ...float64) float64 {
	for _, value := range values {
		if value != 0 {
			return value
		}
	}
	return 0
}

func gmacTokenAddressForChain(cfg *config.Config, chainID int64) string {
	if cfg == nil {
		return ""
	}
	switch chainID {
	case runtimeinfo.EthereumChainID:
		return cfg.Tools.GDEX.GmacToken.Ethereum
	case runtimeinfo.ArbitrumChainID:
		return cfg.Tools.GDEX.GmacToken.Arbitrum
	case runtimeinfo.SolanaChainID:
		return cfg.Tools.GDEX.GmacToken.Solana
	default:
		return ""
	}
}

func autoTradeChainLabel(chainID int64) string {
	switch chainID {
	case runtimeinfo.EthereumChainID:
		return "Ethereum"
	case runtimeinfo.ArbitrumChainID:
		return "Arbitrum"
	case runtimeinfo.SolanaChainID:
		return "Solana"
	default:
		return fmt.Sprintf("Chain %d", chainID)
	}
}

func routeHealthState(autonomy *runtimeinfo.AutonomyStatus, name string) string {
	if autonomy == nil {
		return ""
	}
	for _, signal := range autonomy.Router.Health {
		if signal.Name == name {
			return strings.TrimSpace(strings.ToLower(signal.State))
		}
	}
	return ""
}

func clampFloat(v, minValue, maxValue float64) float64 {
	if v < minValue {
		return minValue
	}
	if v > maxValue {
		return maxValue
	}
	return v
}
