package swarm

import (
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/replication"
)

// SwarmConfig holds configuration for the swarm coordinator.
type SwarmConfig struct {
	Enabled            bool    `json:"enabled"`
	MaxSwarmSize       int     `json:"max_swarm_size"`      // max agents in swarm (default 5)
	ConsensusThreshold float64 `json:"consensus_threshold"` // fraction of agents that must agree (default 0.6)
	SignalAggregation  string  `json:"signal_aggregation"`  // "majority", "weighted", "unanimous" (default "majority")
	StrategyRotation   bool    `json:"strategy_rotation"`   // rotate strategies among agents (default true)
	RebalanceInterval  int     `json:"rebalance_interval"`  // minutes between strategy rebalance (default 60)
	SharedWalletMode   bool    `json:"shared_wallet_mode"`  // all agents trade from same wallet (default false)
}

// SwarmMember represents a member agent in the swarm.
type SwarmMember struct {
	AgentID     string  `json:"agent_id"`
	Role        string  `json:"role"`         // "leader", "scout", "executor", "analyst"
	Strategy    string  `json:"strategy"`     // assigned trading strategy
	Performance float64 `json:"performance"`  // running P&L score
	SignalCount int     `json:"signal_count"` // number of signals contributed
	LastActive  int64   `json:"last_active"`
	Status      string  `json:"status"` // "active", "idle", "stopped"
}

// SwarmSignal is a trade signal submitted by a swarm member.
type SwarmSignal struct {
	AgentID      string  `json:"agent_id"`
	Action       string  `json:"action"`        // "buy", "sell", "hold"
	TokenAddress string  `json:"token_address"`
	ChainID      int     `json:"chain_id"`
	Confidence   float64 `json:"confidence"` // 0.0-1.0
	Reasoning    string  `json:"reasoning"`
	Timestamp    int64   `json:"timestamp"`
}

// ConsensusResult is the result of a consensus vote on a token action.
type ConsensusResult struct {
	Action       string         `json:"action"`        // consensus action
	TokenAddress string         `json:"token_address"`
	ChainID      int            `json:"chain_id"`
	Confidence   float64        `json:"confidence"`   // aggregated confidence
	Votes        map[string]int `json:"votes"`        // action -> vote count
	Participants int            `json:"participants"`
	Approved     bool           `json:"approved"`  // met consensus threshold
	Reasoning    string         `json:"reasoning"` // summary of agent reasoning
}

// SwarmCoordinator manages a swarm of child agents for distributed trading.
type SwarmCoordinator struct {
	config       SwarmConfig
	leaderID     string
	members      []*SwarmMember
	signals      map[string][]SwarmSignal // token_address -> signals
	telepathyBus *replication.TelepathyBus
	mu           sync.RWMutex
}

// NewSwarmCoordinator creates a new SwarmCoordinator.
func NewSwarmCoordinator(leaderID string, config SwarmConfig, bus *replication.TelepathyBus) *SwarmCoordinator {
	if config.MaxSwarmSize <= 0 {
		config.MaxSwarmSize = 5
	}
	if config.ConsensusThreshold <= 0 {
		config.ConsensusThreshold = 0.6
	}
	if config.SignalAggregation == "" {
		config.SignalAggregation = "majority"
	}
	if config.RebalanceInterval <= 0 {
		config.RebalanceInterval = 60
	}
	return &SwarmCoordinator{
		config:       config,
		leaderID:     leaderID,
		members:      []*SwarmMember{},
		signals:      make(map[string][]SwarmSignal),
		telepathyBus: bus,
	}
}

// AddMember adds an agent to the swarm, enforcing the maximum size.
func (sc *SwarmCoordinator) AddMember(agentID, role, strategy string) error {
	sc.mu.Lock()
	defer sc.mu.Unlock()

	if len(sc.members) >= sc.config.MaxSwarmSize {
		return fmt.Errorf("swarm is full: max size is %d", sc.config.MaxSwarmSize)
	}
	for _, m := range sc.members {
		if m.AgentID == agentID {
			return fmt.Errorf("agent %s is already in the swarm", agentID)
		}
	}
	sc.members = append(sc.members, &SwarmMember{
		AgentID:    agentID,
		Role:       role,
		Strategy:   strategy,
		LastActive: time.Now().UnixMilli(),
		Status:     "active",
	})
	return nil
}

// RemoveMember removes an agent from the swarm.
func (sc *SwarmCoordinator) RemoveMember(agentID string) error {
	sc.mu.Lock()
	defer sc.mu.Unlock()

	for i, m := range sc.members {
		if m.AgentID == agentID {
			sc.members = append(sc.members[:i], sc.members[i+1:]...)
			return nil
		}
	}
	return fmt.Errorf("agent %s not found in swarm", agentID)
}

// GetMembers returns a snapshot of all swarm members.
func (sc *SwarmCoordinator) GetMembers() []*SwarmMember {
	sc.mu.RLock()
	defer sc.mu.RUnlock()

	out := make([]*SwarmMember, len(sc.members))
	copy(out, sc.members)
	return out
}

// GetMember returns the member with the given agentID, or false if not found.
func (sc *SwarmCoordinator) GetMember(agentID string) (*SwarmMember, bool) {
	sc.mu.RLock()
	defer sc.mu.RUnlock()

	for _, m := range sc.members {
		if m.AgentID == agentID {
			return m, true
		}
	}
	return nil, false
}

// SubmitSignal records a trade signal from a swarm member.
func (sc *SwarmCoordinator) SubmitSignal(signal SwarmSignal) error {
	if signal.AgentID == "" {
		return fmt.Errorf("signal must have an agent_id")
	}
	if signal.TokenAddress == "" {
		return fmt.Errorf("signal must have a token_address")
	}
	if signal.Timestamp == 0 {
		signal.Timestamp = time.Now().UnixMilli()
	}

	sc.mu.Lock()
	defer sc.mu.Unlock()

	sc.signals[signal.TokenAddress] = append(sc.signals[signal.TokenAddress], signal)

	// Update member's signal count and last active
	for _, m := range sc.members {
		if m.AgentID == signal.AgentID {
			m.SignalCount++
			m.LastActive = signal.Timestamp
			break
		}
	}
	return nil
}

// GetSignals returns all signals for a given token address.
func (sc *SwarmCoordinator) GetSignals(tokenAddress string) []SwarmSignal {
	sc.mu.RLock()
	defer sc.mu.RUnlock()

	sigs := sc.signals[tokenAddress]
	out := make([]SwarmSignal, len(sigs))
	copy(out, sigs)
	return out
}

// RunConsensus aggregates signals for a token and determines the consensus action.
func (sc *SwarmCoordinator) RunConsensus(tokenAddress string, chainID int) (*ConsensusResult, error) {
	sc.mu.RLock()
	sigs := sc.signals[tokenAddress]
	aggregation := sc.config.SignalAggregation
	threshold := sc.config.ConsensusThreshold
	sc.mu.RUnlock()

	if len(sigs) == 0 {
		return nil, fmt.Errorf("no signals available for token %s", tokenAddress)
	}

	result := &ConsensusResult{
		TokenAddress: tokenAddress,
		ChainID:      chainID,
		Votes:        make(map[string]int),
		Participants: len(sigs),
	}

	var reasonings []string
	actionConfidence := map[string]float64{}
	actionCount := map[string]int{}

	for _, sig := range sigs {
		actionCount[sig.Action]++
		actionConfidence[sig.Action] += sig.Confidence
		if sig.Reasoning != "" {
			reasonings = append(reasonings, sig.AgentID+": "+sig.Reasoning)
		}
		result.Votes[sig.Action]++
	}

	switch aggregation {
	case "unanimous":
		// All agents must agree
		if len(actionCount) == 1 {
			for action := range actionCount {
				result.Action = action
				result.Confidence = actionConfidence[action] / float64(actionCount[action])
				result.Approved = true
			}
		} else {
			// No consensus — pick majority action but mark not approved
			best := majorityAction(actionCount)
			result.Action = best
			result.Confidence = actionConfidence[best] / float64(actionCount[best])
			result.Approved = false
		}

	case "weighted":
		// Weight votes by agent confidence; action with highest weighted score wins
		best := ""
		bestScore := -1.0
		for action, totalConf := range actionConfidence {
			score := totalConf // sum of confidence scores is the weight
			if score > bestScore {
				bestScore = score
				best = action
			}
		}
		result.Action = best
		result.Confidence = bestScore / float64(actionCount[best])
		fraction := float64(actionCount[best]) / float64(len(sigs))
		result.Approved = fraction >= threshold

	default: // "majority"
		best := majorityAction(actionCount)
		result.Action = best
		votes := actionCount[best]
		fraction := float64(votes) / float64(len(sigs))
		result.Confidence = actionConfidence[best] / float64(votes)
		result.Approved = fraction >= threshold
	}

	if len(reasonings) > 0 {
		result.Reasoning = strings.Join(reasonings, "; ")
	}

	return result, nil
}

// ClearSignals removes all signals for a token address.
func (sc *SwarmCoordinator) ClearSignals(tokenAddress string) {
	sc.mu.Lock()
	defer sc.mu.Unlock()
	delete(sc.signals, tokenAddress)
}

// BroadcastStrategy sends a strategy update to all members via the telepathy bus.
func (sc *SwarmCoordinator) BroadcastStrategy(strategy string) {
	if sc.telepathyBus == nil {
		return
	}
	sc.telepathyBus.Broadcast(replication.TelepathyMessage{
		FromAgentID: sc.leaderID,
		ToAgentID:   "*",
		Type:        "strategy_update",
		Content:     strategy,
		Timestamp:   time.Now().UnixMilli(),
		Priority:    1,
	})
}

// UpdateMemberPerformance updates the running P&L for an agent.
func (sc *SwarmCoordinator) UpdateMemberPerformance(agentID string, pnl float64) {
	sc.mu.Lock()
	defer sc.mu.Unlock()

	for _, m := range sc.members {
		if m.AgentID == agentID {
			m.Performance += pnl
			m.LastActive = time.Now().UnixMilli()
			return
		}
	}
}

// GetConfig returns the swarm configuration.
func (sc *SwarmCoordinator) GetConfig() SwarmConfig {
	return sc.config
}

// GetLeaderID returns the leader's agent ID.
func (sc *SwarmCoordinator) GetLeaderID() string {
	return sc.leaderID
}

// majorityAction returns the action with the highest vote count.
func majorityAction(counts map[string]int) string {
	best := ""
	bestCount := -1
	for action, count := range counts {
		if count > bestCount {
			bestCount = count
			best = action
		}
	}
	return best
}
