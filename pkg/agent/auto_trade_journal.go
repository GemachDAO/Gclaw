package agent

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/replication"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

const autoTradeJournalLimit = 100

type autoTradeJournalEntry struct {
	Timestamp           int64                        `json:"timestamp"`
	Status              string                       `json:"status"`
	Mode                string                       `json:"mode"`
	Venue               string                       `json:"venue"`
	ChainID             int64                        `json:"chain_id,omitempty"`
	ChainLabel          string                       `json:"chain_label,omitempty"`
	TokenAddress        string                       `json:"token_address,omitempty"`
	TokenSymbol         string                       `json:"token_symbol,omitempty"`
	Amount              string                       `json:"amount,omitempty"`
	ExecutedAction      string                       `json:"executed_action,omitempty"`
	Summary             string                       `json:"summary,omitempty"`
	Outcome             string                       `json:"outcome,omitempty"`
	Reasons             []string                     `json:"reasons,omitempty"`
	MissedOpportunities []autoTradeOpportunityRecord `json:"missed_opportunities,omitempty"`
}

type autoTradeOpportunityRecord struct {
	TokenAddress string  `json:"token_address,omitempty"`
	TokenSymbol  string  `json:"token_symbol,omitempty"`
	ChainID      int64   `json:"chain_id,omitempty"`
	ChainLabel   string  `json:"chain_label,omitempty"`
	Score        float64 `json:"score,omitempty"`
	PriceUSD     float64 `json:"price_usd,omitempty"`
	Change24H    float64 `json:"change_24h,omitempty"`
	LiquidityUSD float64 `json:"liquidity_usd,omitempty"`
	Volume24H    float64 `json:"volume_24h,omitempty"`
	Reason       string  `json:"reason,omitempty"`
}

func newAutoTradeJournalEntry(
	cfg *config.Config,
	plan *autoTradeExecutionPlan,
	strategy *runtimeinfo.AutoTradeStrategy,
	signals []autoTradeSignalCandidate,
	profile *replication.ChildStrategyProfile,
	memory *autoTradeLearningMemory,
) *autoTradeJournalEntry {
	entry := &autoTradeJournalEntry{
		Timestamp: time.Now().UnixMilli(),
		Status:    "planned",
	}
	if plan == nil {
		entry.Mode = "unknown"
		entry.Venue = "unknown"
		entry.Summary = "auto-trade planner returned no executable plan"
		return entry
	}

	entry.Mode = strings.TrimSpace(plan.Mode)
	entry.Venue = autoTradeVenueLabel(plan, strategy)
	entry.ExecutedAction = autoTradeActionLabel(plan)
	entry.Summary = strings.TrimSpace(plan.Summary)
	entry.Reasons = append([]string(nil), plan.Reasons...)

	switch {
	case strings.TrimSpace(plan.EntryToken) != "":
		entry.ChainID = plan.EntryChainID
		entry.ChainLabel = strings.TrimSpace(plan.EntryChainLabel)
		entry.TokenAddress = strings.TrimSpace(plan.EntryToken)
		entry.TokenSymbol = strings.TrimSpace(plan.EntrySymbol)
		entry.Amount = strings.TrimSpace(plan.SpendAmount)
	case strings.TrimSpace(plan.ExitToken) != "":
		entry.ChainID = plan.ExitChainID
		entry.ChainLabel = strings.TrimSpace(plan.ExitChainLabel)
		entry.TokenAddress = strings.TrimSpace(plan.ExitToken)
		entry.TokenSymbol = strings.TrimSpace(plan.ExitSymbol)
		entry.Amount = strings.TrimSpace(plan.ExitAmount)
	}

	entry.MissedOpportunities = buildMissedSignalOpportunities(cfg, signals, plan, profile, memory, 3)
	return entry
}

func recordAutoTradeJournalEntry(workspace string, entry autoTradeJournalEntry) error {
	path := autoTradeJournalPath(workspace)
	records, err := loadAutoTradeJournalEntries(path)
	if err != nil {
		return err
	}
	records = append(records, entry)
	if len(records) > autoTradeJournalLimit {
		records = records[len(records)-autoTradeJournalLimit:]
	}
	return persistAutoTradeJournalEntries(path, records)
}

func loadAutoTradeJournal(workspace string) ([]autoTradeJournalEntry, error) {
	return loadAutoTradeJournalEntries(autoTradeJournalPath(workspace))
}

func autoTradeJournalPath(workspace string) string {
	workspace = strings.TrimSpace(workspace)
	if workspace == "" {
		return ""
	}
	return filepath.Join(workspace, "runtime", "auto_trade_journal.json")
}

func loadAutoTradeJournalEntries(path string) ([]autoTradeJournalEntry, error) {
	path = strings.TrimSpace(path)
	if path == "" {
		return nil, nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var records []autoTradeJournalEntry
	if err := json.Unmarshal(data, &records); err != nil {
		return nil, err
	}
	return records, nil
}

func persistAutoTradeJournalEntries(path string, records []autoTradeJournalEntry) error {
	path = strings.TrimSpace(path)
	if path == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(records, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func buildMissedSignalOpportunities(
	cfg *config.Config,
	signals []autoTradeSignalCandidate,
	plan *autoTradeExecutionPlan,
	profile *replication.ChildStrategyProfile,
	memory *autoTradeLearningMemory,
	limit int,
) []autoTradeOpportunityRecord {
	ranked := rankSignalCandidates(cfg, signals, profile, memory)
	if len(ranked) == 0 || limit <= 0 {
		return nil
	}

	selected := ""
	if plan != nil {
		selected = strings.ToLower(strings.TrimSpace(plan.EntryToken))
	}

	out := make([]autoTradeOpportunityRecord, 0, limit)
	seen := make(map[string]struct{}, limit)
	for _, signal := range ranked {
		address := strings.ToLower(strings.TrimSpace(signal.TokenAddress))
		if address == selected {
			continue
		}
		if _, ok := seen[address]; ok {
			continue
		}
		seen[address] = struct{}{}
		out = append(out, autoTradeOpportunityRecord{
			TokenAddress: signal.TokenAddress,
			TokenSymbol:  signal.Symbol,
			ChainID:      signal.ChainID,
			ChainLabel:   autoTradeChainLabel(signal.ChainID),
			Score:        signal.Score,
			PriceUSD:     signal.PriceUSD,
			Change24H:    signal.Change24H,
			LiquidityUSD: signal.LiquidityUSD,
			Volume24H:    signal.Volume24H,
			Reason:       missedOpportunityReason(plan),
		})
		if len(out) >= limit {
			break
		}
	}
	return out
}

func missedOpportunityReason(plan *autoTradeExecutionPlan) string {
	if plan == nil {
		return "watched, but no execution route was committed this cycle"
	}
	switch strings.TrimSpace(plan.Mode) {
	case "pursue_signal":
		if strings.TrimSpace(plan.EntrySymbol) != "" {
			return "viable, but ranked below the selected signal " + plan.EntrySymbol
		}
		return "viable, but another signal ranked higher this cycle"
	case "rotate_profits_to_gmac":
		return "viable, but the cycle prioritized realizing gains into GMAC"
	case "accumulate_gmac":
		return "viable, but the cycle favored direct GMAC accumulation"
	case "swarm_consensus_buy", "swarm_consensus_sell":
		return "viable, but a swarm directive overrode it"
	case "research_only":
		return "watched, but the cycle stayed in research mode"
	default:
		return "watched, but not selected this cycle"
	}
}

func autoTradeVenueLabel(plan *autoTradeExecutionPlan, strategy *runtimeinfo.AutoTradeStrategy) string {
	if plan == nil {
		return "unknown"
	}
	switch strings.TrimSpace(plan.Mode) {
	case "research_only":
		return "research"
	case "swarm_consensus_buy", "swarm_consensus_sell":
		return "swarm_consensus"
	default:
		if strategy != nil && strings.TrimSpace(strategy.Venue) != "" {
			return strings.TrimSpace(strategy.Venue)
		}
		return "gdex_spot"
	}
}

func autoTradeActionLabel(plan *autoTradeExecutionPlan) string {
	if plan == nil {
		return "observe"
	}
	switch strings.TrimSpace(plan.Mode) {
	case "rotate_profits_to_gmac":
		return "rotate"
	case "swarm_consensus_sell":
		return "sell"
	case "research_only":
		return "observe"
	default:
		return "buy"
	}
}
