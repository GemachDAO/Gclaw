// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package config

import (
	"encoding/json"
	"fmt"

	"github.com/GemachDAO/Gclaw/pkg/logger"
)

// knownTopLevelKeys is the set of valid top-level JSON keys in Config.
var knownTopLevelKeys = map[string]struct{}{
	"agents":     {},
	"bindings":   {},
	"session":    {},
	"channels":   {},
	"providers":  {},
	"model_list": {},
	"gateway":    {},
	"tools":      {},
	"heartbeat":  {},
	"devices":    {},
	"metabolism": {},
	"swarm":      {},
	"dashboard":  {},
}

// knownChainIDs is the set of valid GDEX chain IDs.
var knownChainIDs = map[int64]struct{}{
	1:         {}, // Ethereum mainnet
	8453:      {}, // Base
	42161:     {}, // Arbitrum
	622112261: {}, // custom chain
}

// validSignalAggregations is the set of valid signal aggregation modes.
var validSignalAggregations = map[string]struct{}{
	"majority":  {},
	"weighted":  {},
	"unanimous": {},
}

// WarnUnknownKeys unmarshals raw JSON into a map and logs a warning for any
// top-level key that is not in knownTopLevelKeys. It does not return an error
// because unknown keys should be tolerated for forward-compatibility.
func WarnUnknownKeys(data []byte) {
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		// If we can't parse the JSON at all, the main unmarshal will catch it.
		return
	}
	for key := range raw {
		if _, known := knownTopLevelKeys[key]; !known {
			logger.WarnCF("config", "unknown configuration key", map[string]any{"key": key})
		}
	}
}

// Validate checks that the configuration values are semantically valid.
// It returns the first error encountered.
func (c *Config) Validate() error {
	if err := c.validateMetabolism(); err != nil {
		return err
	}
	if err := c.validateSwarm(); err != nil {
		return err
	}
	if err := c.validateGDEX(); err != nil {
		return err
	}
	if err := c.validateDashboard(); err != nil {
		return err
	}
	return nil
}

func (c *Config) validateMetabolism() error {
	m := c.Metabolism
	if !m.Enabled {
		return nil
	}
	if m.SurvivalThreshold <= 0 {
		return fmt.Errorf("metabolism.survival_threshold must be > 0 when metabolism is enabled")
	}
	if m.HeartbeatCost <= 0 {
		return fmt.Errorf("metabolism.heartbeat_cost must be > 0 when metabolism is enabled")
	}
	t := m.Thresholds
	if t.Replicate != 0 || t.SelfRecode != 0 || t.SwarmLeader != 0 || t.Architect != 0 {
		// Only validate ordering when any threshold is explicitly set.
		if !(t.Replicate < t.SelfRecode) {
			return fmt.Errorf(
				"metabolism.thresholds: replicate (%d) must be less than self_recode (%d)",
				t.Replicate, t.SelfRecode,
			)
		}
		if !(t.SelfRecode < t.SwarmLeader) {
			return fmt.Errorf(
				"metabolism.thresholds: self_recode (%d) must be less than swarm_leader (%d)",
				t.SelfRecode, t.SwarmLeader,
			)
		}
		if !(t.SwarmLeader < t.Architect) {
			return fmt.Errorf(
				"metabolism.thresholds: swarm_leader (%d) must be less than architect (%d)",
				t.SwarmLeader, t.Architect,
			)
		}
	}
	return nil
}

func (c *Config) validateSwarm() error {
	s := c.Swarm
	if !s.Enabled {
		return nil
	}
	if s.ConsensusThreshold < 0 || s.ConsensusThreshold > 1.0 {
		return fmt.Errorf(
			"swarm.consensus_threshold must be between 0.0 and 1.0, got %.4f",
			s.ConsensusThreshold,
		)
	}
	if s.MaxSwarmSize <= 0 {
		return fmt.Errorf("swarm.max_swarm_size must be > 0")
	}
	if s.SignalAggregation != "" {
		if _, ok := validSignalAggregations[s.SignalAggregation]; !ok {
			return fmt.Errorf(
				"swarm.signal_aggregation must be one of \"majority\", \"weighted\", \"unanimous\"; got %q",
				s.SignalAggregation,
			)
		}
	}
	return nil
}

func (c *Config) validateGDEX() error {
	g := c.Tools.GDEX
	if !g.Enabled {
		return nil
	}
	if g.DefaultChainID != 0 {
		if _, ok := knownChainIDs[g.DefaultChainID]; !ok {
			return fmt.Errorf(
				"tools.gdex.default_chain_id %d is not a known chain ID (valid: 1, 8453, 42161, 622112261)",
				g.DefaultChainID,
			)
		}
	}
	return nil
}

func (c *Config) validateDashboard() error {
	d := c.Dashboard
	if !d.Enabled {
		return nil
	}
	if d.RefreshInterval <= 0 {
		return fmt.Errorf("dashboard.refresh_interval must be > 0 when dashboard is enabled")
	}
	return nil
}
