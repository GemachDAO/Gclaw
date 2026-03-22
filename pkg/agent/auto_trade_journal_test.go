package agent

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

func TestRecordAutoTradeJournalEntry_PersistsAndReloads(t *testing.T) {
	workspace := t.TempDir()
	entry := autoTradeJournalEntry{
		Timestamp:      123,
		Status:         "executed",
		Mode:           "pursue_signal",
		Venue:          "route_aware",
		ChainLabel:     "Ethereum",
		TokenSymbol:    "ALPHA",
		TokenAddress:   "0xabc",
		Amount:         "0.01",
		ExecutedAction: "buy",
		Summary:        "Take a small liquid signal entry.",
	}

	if err := recordAutoTradeJournalEntry(workspace, entry); err != nil {
		t.Fatalf("recordAutoTradeJournalEntry failed: %v", err)
	}

	path := filepath.Join(workspace, "runtime", "auto_trade_journal.json")
	records, err := loadAutoTradeJournalEntries(path)
	if err != nil {
		t.Fatalf("loadAutoTradeJournalEntries failed: %v", err)
	}
	if len(records) != 1 {
		t.Fatalf("expected 1 journal entry, got %d", len(records))
	}
	if records[0].TokenSymbol != "ALPHA" || records[0].Status != "executed" {
		t.Fatalf("unexpected journal entry: %+v", records[0])
	}
}

func TestBuildMissedSignalOpportunities_UsesRankedAlternatives(t *testing.T) {
	cfg := config.DefaultConfig()
	plan := &autoTradeExecutionPlan{
		Mode:         "pursue_signal",
		EntryToken:   "0xalpha",
		EntrySymbol:  "ALPHA",
		EntryChainID: runtimeinfo.EthereumChainID,
	}

	missed := buildMissedSignalOpportunities(cfg, []autoTradeSignalCandidate{
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
		{
			TokenAddress: "0xbeta",
			Symbol:       "BETA",
			ChainID:      runtimeinfo.ArbitrumChainID,
			PriceUSD:     0.9,
			Change24H:    8,
			LiquidityUSD: 180000,
			Volume24H:    810000,
			MarketCapUSD: 65000000,
		},
		{
			TokenAddress: "0xbeta",
			Symbol:       "BETA",
			ChainID:      runtimeinfo.ArbitrumChainID,
			PriceUSD:     0.9,
			Change24H:    8,
			LiquidityUSD: 180000,
			Volume24H:    810000,
			MarketCapUSD: 65000000,
		},
	}, plan, nil, buildAutoTradeLearningMemory(nil), 3)

	if len(missed) != 1 {
		t.Fatalf("expected 1 missed opportunity, got %d", len(missed))
	}
	if missed[0].TokenSymbol != "BETA" {
		t.Fatalf("expected BETA missed opportunity, got %+v", missed[0])
	}
	if !strings.Contains(missed[0].Reason, "ALPHA") {
		t.Fatalf("expected selected signal reason, got %q", missed[0].Reason)
	}
}
