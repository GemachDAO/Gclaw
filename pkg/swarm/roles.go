package swarm

const (
	RoleLeader   = "leader"   // Coordinates swarm, runs consensus, makes final decisions
	RoleScout    = "scout"    // Scans for new tokens, monitors trending, finds opportunities
	RoleExecutor = "executor" // Executes trades based on consensus signals
	RoleAnalyst  = "analyst"  // Analyzes price action, calculates risk, provides insights
)

// RoleDescriptions maps roles to system prompt additions.
var RoleDescriptions = map[string]string{
	RoleLeader:   "You are the swarm leader. Coordinate your team, run consensus votes on trade signals, and make final trading decisions. Monitor all members' performance.",
	RoleScout:    "You are a scout agent. Your job is to scan for new trading opportunities using gdex_trending, gdex_scan, and gdex_search. Report promising tokens to the swarm via telepathy.",
	RoleExecutor: "You are an executor agent. When the swarm reaches consensus on a trade, you execute it using gdex_buy or gdex_sell. Report execution results back to the swarm.",
	RoleAnalyst:  "You are an analyst agent. Analyze token prices, check holdings, evaluate risk/reward ratios, and provide analytical insights to the swarm via telepathy.",
}

// GetRolePromptAddition returns the role description for a system prompt.
func GetRolePromptAddition(role string) string {
	if desc, ok := RoleDescriptions[role]; ok {
		return desc
	}
	return ""
}
