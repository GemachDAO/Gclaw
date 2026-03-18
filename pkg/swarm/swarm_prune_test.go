// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package swarm

import (
	"testing"
	"time"
)

func TestPruneSignals_RemovesStaleSignals(t *testing.T) {
	sc := NewSwarmCoordinator("leader", SwarmConfig{
		MaxSwarmSize:       5,
		ConsensusThreshold: 0.6,
		SignalAggregation:  "majority",
	}, nil)

	old := time.Now().Add(-2 * time.Hour).UnixMilli()
	fresh := time.Now().Add(-30 * time.Second).UnixMilli()

	sc.signals["TOKEN_A"] = []SwarmSignal{
		{AgentID: "a1", TokenAddress: "TOKEN_A", Action: "buy", Timestamp: old},
		{AgentID: "a2", TokenAddress: "TOKEN_A", Action: "buy", Timestamp: fresh},
	}
	sc.signals["TOKEN_B"] = []SwarmSignal{
		{AgentID: "a1", TokenAddress: "TOKEN_B", Action: "sell", Timestamp: old},
	}

	sc.PruneSignals(time.Hour)

	// TOKEN_A should have 1 remaining signal
	remaining := sc.signals["TOKEN_A"]
	if len(remaining) != 1 {
		t.Errorf("TOKEN_A: want 1 signal, got %d", len(remaining))
	}
	if remaining[0].AgentID != "a2" {
		t.Errorf("TOKEN_A: expected fresh signal from a2, got %s", remaining[0].AgentID)
	}

	// TOKEN_B should be deleted (all signals stale)
	if _, ok := sc.signals["TOKEN_B"]; ok {
		t.Error("TOKEN_B should have been deleted")
	}
}

func TestPruneSignals_ZeroMaxAgeNoOp(t *testing.T) {
	sc := NewSwarmCoordinator("leader", SwarmConfig{
		MaxSwarmSize:       5,
		ConsensusThreshold: 0.6,
	}, nil)
	sc.signals["TOKEN_A"] = []SwarmSignal{
		{AgentID: "a1", TokenAddress: "TOKEN_A", Action: "buy", Timestamp: time.Now().UnixMilli()},
	}

	sc.PruneSignals(0)
	if len(sc.signals["TOKEN_A"]) != 1 {
		t.Error("expected signals unchanged with zero maxAge")
	}
}

func TestPruneSignals_EmptyMapIsNoOp(t *testing.T) {
	sc := NewSwarmCoordinator("leader", SwarmConfig{MaxSwarmSize: 3}, nil)
	// Should not panic
	sc.PruneSignals(time.Minute)
}
