package swarm

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// swarmState is the serialisable form of the coordinator's state.
type swarmState struct {
	LeaderID         string                   `json:"leader_id"`
	Config           SwarmConfig              `json:"config"`
	Members          []*SwarmMember           `json:"members"`
	Signals          map[string][]SwarmSignal `json:"signals,omitempty"`
	LastConsensus    *ConsensusResult         `json:"last_consensus,omitempty"`
	LastDecision     *ExecutionDecision       `json:"last_decision,omitempty"`
	LastRebalancedAt int64                    `json:"last_rebalanced_at,omitempty"`
}

// SaveSwarmState persists the coordinator state to {workspace}/swarm/state.json.
func SaveSwarmState(workspace string, coordinator *SwarmCoordinator) error {
	coordinator.mu.RLock()
	state := swarmState{
		LeaderID:         coordinator.leaderID,
		Config:           coordinator.config,
		Members:          make([]*SwarmMember, len(coordinator.members)),
		Signals:          make(map[string][]SwarmSignal, len(coordinator.signals)),
		LastConsensus:    copyConsensusResult(coordinator.lastConsensus),
		LastDecision:     copyExecutionDecision(coordinator.lastDecision),
		LastRebalancedAt: coordinator.lastRebalancedAt,
	}
	copy(state.Members, coordinator.members)
	for token, signals := range coordinator.signals {
		copied := make([]SwarmSignal, len(signals))
		copy(copied, signals)
		state.Signals[token] = copied
	}
	coordinator.mu.RUnlock()

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}

	dir := filepath.Join(workspace, "swarm")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	path := filepath.Join(dir, "state.json")
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// LoadSwarmState restores the coordinator state from {workspace}/swarm/state.json.
// Returns nil, nil if the file does not exist.
func LoadSwarmState(workspace string) (*SwarmCoordinator, error) {
	path := filepath.Join(workspace, "swarm", "state.json")
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	var state swarmState
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, err
	}

	coordinator := NewSwarmCoordinator(state.LeaderID, state.Config, nil)
	coordinator.mu.Lock()
	coordinator.members = state.Members
	if state.Signals != nil {
		coordinator.signals = state.Signals
	}
	coordinator.lastConsensus = copyConsensusResult(state.LastConsensus)
	coordinator.lastDecision = copyExecutionDecision(state.LastDecision)
	coordinator.lastRebalancedAt = state.LastRebalancedAt
	coordinator.mu.Unlock()
	return coordinator, nil
}
