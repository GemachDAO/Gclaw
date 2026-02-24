package swarm

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// swarmState is the serialisable form of the coordinator's state.
type swarmState struct {
	LeaderID string         `json:"leader_id"`
	Config   SwarmConfig    `json:"config"`
	Members  []*SwarmMember `json:"members"`
}

// SaveSwarmState persists the coordinator state to {workspace}/swarm/state.json.
func SaveSwarmState(workspace string, coordinator *SwarmCoordinator) error {
	coordinator.mu.RLock()
	state := swarmState{
		LeaderID: coordinator.leaderID,
		Config:   coordinator.config,
		Members:  make([]*SwarmMember, len(coordinator.members)),
	}
	copy(state.Members, coordinator.members)
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
	coordinator.mu.Unlock()
	return coordinator, nil
}
