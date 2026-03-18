// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package config

import (
	"bytes"
	"log"
	"strings"
	"testing"
)

func TestValidate_ValidConfig(t *testing.T) {
	cfg := &Config{
		Metabolism: MetabolismConfig{
			Enabled:           true,
			SurvivalThreshold: 1.0,
			HeartbeatCost:     0.1,
			Thresholds: struct {
				Replicate   int `json:"replicate"`
				SelfRecode  int `json:"self_recode"`
				SwarmLeader int `json:"swarm_leader"`
				Architect   int `json:"architect"`
			}{
				Replicate:   10,
				SelfRecode:  50,
				SwarmLeader: 100,
				Architect:   200,
			},
		},
		Swarm: SwarmConfig{
			Enabled:            true,
			MaxSwarmSize:       5,
			ConsensusThreshold: 0.6,
			SignalAggregation:  "majority",
		},
		Tools: ToolsConfig{
			GDEX: GDEXConfig{
				Enabled:        true,
				DefaultChainID: 8453,
			},
		},
		Dashboard: DashboardConfig{
			Enabled:         true,
			RefreshInterval: 10,
		},
	}
	if err := cfg.Validate(); err != nil {
		t.Errorf("expected no error, got: %v", err)
	}
}

func TestValidate_InvalidSurvivalThreshold(t *testing.T) {
	cfg := &Config{
		Metabolism: MetabolismConfig{
			Enabled:           true,
			SurvivalThreshold: 0, // invalid
			HeartbeatCost:     0.1,
		},
	}
	err := cfg.Validate()
	if err == nil {
		t.Fatal("expected error for zero survival_threshold")
	}
	if !strings.Contains(err.Error(), "survival_threshold") {
		t.Errorf("expected error message about survival_threshold, got: %v", err)
	}
}

func TestValidate_InvalidHeartbeatCost(t *testing.T) {
	cfg := &Config{
		Metabolism: MetabolismConfig{
			Enabled:           true,
			SurvivalThreshold: 1.0,
			HeartbeatCost:     0, // invalid
		},
	}
	err := cfg.Validate()
	if err == nil {
		t.Fatal("expected error for zero heartbeat_cost")
	}
	if !strings.Contains(err.Error(), "heartbeat_cost") {
		t.Errorf("expected error about heartbeat_cost, got: %v", err)
	}
}

func TestValidate_InvalidThresholdOrdering(t *testing.T) {
	tests := []struct {
		name              string
		replicate         int
		selfRecode        int
		swarmLeader       int
		architect         int
		wantErrContaining string
	}{
		{
			name:              "replicate >= self_recode",
			replicate:         100,
			selfRecode:        50,
			swarmLeader:       200,
			architect:         500,
			wantErrContaining: "replicate",
		},
		{
			name:              "self_recode >= swarm_leader",
			replicate:         50,
			selfRecode:        200,
			swarmLeader:       100,
			architect:         500,
			wantErrContaining: "self_recode",
		},
		{
			name:              "swarm_leader >= architect",
			replicate:         50,
			selfRecode:        100,
			swarmLeader:       500,
			architect:         200,
			wantErrContaining: "swarm_leader",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &Config{
				Metabolism: MetabolismConfig{
					Enabled:           true,
					SurvivalThreshold: 1.0,
					HeartbeatCost:     0.1,
					Thresholds: struct {
						Replicate   int `json:"replicate"`
						SelfRecode  int `json:"self_recode"`
						SwarmLeader int `json:"swarm_leader"`
						Architect   int `json:"architect"`
					}{
						Replicate:   tt.replicate,
						SelfRecode:  tt.selfRecode,
						SwarmLeader: tt.swarmLeader,
						Architect:   tt.architect,
					},
				},
			}
			err := cfg.Validate()
			if err == nil {
				t.Fatalf("expected error for %s", tt.name)
			}
			if !strings.Contains(err.Error(), tt.wantErrContaining) {
				t.Errorf("expected error containing %q, got: %v", tt.wantErrContaining, err)
			}
		})
	}
}

func TestValidate_InvalidConsensusThreshold(t *testing.T) {
	tests := []struct {
		name      string
		threshold float64
	}{
		{"negative", -0.1},
		{"above 1", 1.1},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &Config{
				Swarm: SwarmConfig{
					Enabled:            true,
					MaxSwarmSize:       5,
					ConsensusThreshold: tt.threshold,
					SignalAggregation:  "majority",
				},
			}
			err := cfg.Validate()
			if err == nil {
				t.Fatalf("expected error for consensus_threshold=%.2f", tt.threshold)
			}
			if !strings.Contains(err.Error(), "consensus_threshold") {
				t.Errorf("expected error about consensus_threshold, got: %v", err)
			}
		})
	}
}

func TestValidate_InvalidSignalAggregation(t *testing.T) {
	cfg := &Config{
		Swarm: SwarmConfig{
			Enabled:            true,
			MaxSwarmSize:       5,
			ConsensusThreshold: 0.6,
			SignalAggregation:  "bogus",
		},
	}
	err := cfg.Validate()
	if err == nil {
		t.Fatal("expected error for invalid signal_aggregation")
	}
	if !strings.Contains(err.Error(), "signal_aggregation") {
		t.Errorf("expected error about signal_aggregation, got: %v", err)
	}
}

func TestValidate_InvalidChainID(t *testing.T) {
	cfg := &Config{
		Tools: ToolsConfig{
			GDEX: GDEXConfig{
				Enabled:        true,
				DefaultChainID: 9999,
			},
		},
	}
	err := cfg.Validate()
	if err == nil {
		t.Fatal("expected error for unknown chain ID")
	}
	if !strings.Contains(err.Error(), "chain_id") {
		t.Errorf("expected error about chain_id, got: %v", err)
	}
}

func TestValidate_DisabledMetabolismSkipsValidation(t *testing.T) {
	cfg := &Config{
		Metabolism: MetabolismConfig{
			Enabled:           false,
			SurvivalThreshold: 0, // invalid but disabled
			HeartbeatCost:     0, // invalid but disabled
		},
	}
	if err := cfg.Validate(); err != nil {
		t.Errorf("expected no error when metabolism disabled, got: %v", err)
	}
}

func TestValidate_DisabledGDEXSkipsChainIDValidation(t *testing.T) {
	cfg := &Config{
		Tools: ToolsConfig{
			GDEX: GDEXConfig{
				Enabled:        false,
				DefaultChainID: 9999, // invalid but disabled
			},
		},
	}
	if err := cfg.Validate(); err != nil {
		t.Errorf("expected no error when GDEX disabled, got: %v", err)
	}
}

func TestWarnUnknownKeys(t *testing.T) {
	// Capture log output
	var buf bytes.Buffer
	old := log.Writer()
	log.SetOutput(&buf)
	defer log.SetOutput(old)

	WarnUnknownKeys([]byte(`{"agents":{},"unknown_key_abc":true,"another_bad_key":42}`))

	output := buf.String()
	if !strings.Contains(output, "unknown_key_abc") {
		t.Errorf("expected log to mention 'unknown_key_abc'; got: %s", output)
	}
	if !strings.Contains(output, "another_bad_key") {
		t.Errorf("expected log to mention 'another_bad_key'; got: %s", output)
	}
	// Known keys should NOT be warned about
	if strings.Contains(output, "agents") {
		t.Errorf("should not warn about known key 'agents'; got: %s", output)
	}
}

func TestWarnUnknownKeys_InvalidJSON(t *testing.T) {
	// Should not panic on invalid JSON
	WarnUnknownKeys([]byte(`not json`))
}

func TestValidate_ValidSignalAggregations(t *testing.T) {
	for _, agg := range []string{"majority", "weighted", "unanimous"} {
		cfg := &Config{
			Swarm: SwarmConfig{
				Enabled:            true,
				MaxSwarmSize:       3,
				ConsensusThreshold: 0.5,
				SignalAggregation:  agg,
			},
		}
		if err := cfg.Validate(); err != nil {
			t.Errorf("expected no error for aggregation=%q, got: %v", agg, err)
		}
	}
}

func TestValidate_ValidChainIDs(t *testing.T) {
	for _, id := range []int64{1, 8453, 42161, 622112261} {
		cfg := &Config{
			Tools: ToolsConfig{
				GDEX: GDEXConfig{
					Enabled:        true,
					DefaultChainID: id,
				},
			},
		}
		if err := cfg.Validate(); err != nil {
			t.Errorf("expected no error for chain_id=%d, got: %v", id, err)
		}
	}
}
