package swarm

// StrategyPool is the set of distributed trading strategies assignable to swarm members.
var StrategyPool = []string{
	"momentum_scalper",    // Quick in-and-out on momentum moves
	"dip_buyer",           // Buy tokens that dropped >20% in last hour
	"new_token_sniper",    // Target tokens under 30 minutes old
	"copy_trade_tracker",  // Follow top performing wallets
	"liquidity_watcher",   // Monitor liquidity changes for entry/exit signals
	"cross_chain_arb",     // Look for price differences across chains
	"volume_spike_hunter", // Target tokens with sudden volume increases
	"whale_follower",      // Track large wallet movements
}

// AssignStrategies distributes strategies round-robin to members, avoiding duplicates when possible.
// Returns a map of agentID -> strategy.
func AssignStrategies(members []*SwarmMember) map[string]string {
	assignments := make(map[string]string, len(members))
	for i, m := range members {
		assignments[m.AgentID] = StrategyPool[i%len(StrategyPool)]
	}
	return assignments
}

// RotateStrategies rotates strategies based on performance: the worst-performing member
// receives the strategy of the best-performing member.
// Returns the updated assignment map.
func RotateStrategies(members []*SwarmMember, current map[string]string) map[string]string {
	if len(members) < 2 {
		return current
	}

	updated := make(map[string]string, len(current))
	for k, v := range current {
		updated[k] = v
	}

	// Find best and worst performers
	best := members[0]
	worst := members[0]
	for _, m := range members[1:] {
		if m.Performance > best.Performance {
			best = m
		}
		if m.Performance < worst.Performance {
			worst = m
		}
	}

	if best.AgentID == worst.AgentID {
		return updated
	}

	// Give worst performer the best performer's strategy
	bestStrategy := updated[best.AgentID]
	if bestStrategy != "" {
		updated[worst.AgentID] = bestStrategy
	}

	return updated
}
