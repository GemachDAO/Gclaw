package tools

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/GemachDAO/Gclaw/pkg/swarm"
)

// SwarmTool allows the agent to manage its swarm for distributed trading.
// It is goodwill-gated at ≥ 200 (swarm leader threshold).
type SwarmTool struct {
	coordinator   *swarm.SwarmCoordinator
	goodwillCheck func() int
	threshold     int
	agentID       string
	persist       func() error
}

// NewSwarmTool creates a SwarmTool wired to the given SwarmCoordinator.
// goodwillCheck returns the current goodwill score; threshold is the minimum required.
func NewSwarmTool(
	coordinator *swarm.SwarmCoordinator,
	goodwillCheck func() int,
	threshold int,
) *SwarmTool {
	return &SwarmTool{
		coordinator:   coordinator,
		goodwillCheck: goodwillCheck,
		threshold:     threshold,
	}
}

// SetRuntimeContext configures the owning agent ID and optional persistence hook.
func (t *SwarmTool) SetRuntimeContext(agentID string, persist func() error) {
	t.agentID = agentID
	t.persist = persist
}

func (t *SwarmTool) Name() string { return "swarm" }

func (t *SwarmTool) Description() string {
	return "Manage your agent swarm for distributed trading. Add/remove members, assign roles, submit trade signals, run consensus votes, and coordinate strategies. Requires goodwill ≥ 200 (swarm leader)."
}

func (t *SwarmTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"action": map[string]any{
				"type":        "string",
				"description": "Action to perform",
				"enum": []string{
					"add_member",
					"remove_member",
					"list_members",
					"submit_signal",
					"run_consensus",
					"broadcast_strategy",
					"get_status",
				},
			},
			"agent_id": map[string]any{
				"type":        "string",
				"description": "Target agent ID for add/remove actions",
			},
			"role": map[string]any{
				"type":        "string",
				"description": "Role for the member: leader | scout | executor | analyst",
				"enum":        []string{"leader", "scout", "executor", "analyst"},
			},
			"strategy": map[string]any{
				"type":        "string",
				"description": "Strategy name to assign, or broadcast content for broadcast_strategy",
			},
			"token_address": map[string]any{
				"type":        "string",
				"description": "Token address for signal submission or consensus",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID for signal submission or consensus",
			},
			"action_signal": map[string]any{
				"type":        "string",
				"description": "Trade action for signal submission: buy | sell | hold",
				"enum":        []string{"buy", "sell", "hold"},
			},
			"confidence": map[string]any{
				"type":        "number",
				"description": "Confidence score 0.0-1.0 for signal submission",
			},
			"reasoning": map[string]any{
				"type":        "string",
				"description": "Reasoning for the signal",
			},
		},
		"required": []string{"action"},
	}
}

func (t *SwarmTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	if t.coordinator == nil {
		return ErrorResult("swarm coordinator not configured")
	}

	// Check goodwill threshold
	if t.goodwillCheck != nil {
		gw := t.goodwillCheck()
		if gw < t.threshold {
			return ErrorResult(fmt.Sprintf(
				"insufficient goodwill for swarm leadership: have %d, need %d",
				gw, t.threshold,
			))
		}
	}

	action, _ := args["action"].(string)
	if action == "" {
		return ErrorResult("action is required")
	}

	switch action {
	case "add_member":
		return t.addMember(args)
	case "remove_member":
		return t.removeMember(args)
	case "list_members":
		return t.listMembers()
	case "submit_signal":
		return t.submitSignal(args)
	case "run_consensus":
		return t.runConsensus(args)
	case "broadcast_strategy":
		return t.broadcastStrategy(args)
	case "get_status":
		return t.getStatus()
	default:
		return ErrorResult(fmt.Sprintf("unknown action: %s", action))
	}
}

func (t *SwarmTool) addMember(args map[string]any) *ToolResult {
	agentID, _ := args["agent_id"].(string)
	role, _ := args["role"].(string)
	strategy, _ := args["strategy"].(string)

	if agentID == "" {
		return ErrorResult("agent_id is required for add_member")
	}
	if role == "" {
		role = swarm.RoleScout
	}

	if err := t.coordinator.AddMember(agentID, role, strategy); err != nil {
		return ErrorResult(fmt.Sprintf("failed to add member: %v", err))
	}
	if err := t.persistState(); err != nil {
		return ErrorResult(fmt.Sprintf("member added but failed to persist swarm state: %v", err))
	}
	return SilentResult(fmt.Sprintf("agent %s added to swarm with role %s", agentID, role))
}

func (t *SwarmTool) removeMember(args map[string]any) *ToolResult {
	agentID, _ := args["agent_id"].(string)
	if agentID == "" {
		return ErrorResult("agent_id is required for remove_member")
	}
	if err := t.coordinator.RemoveMember(agentID); err != nil {
		return ErrorResult(fmt.Sprintf("failed to remove member: %v", err))
	}
	if err := t.persistState(); err != nil {
		return ErrorResult(fmt.Sprintf("member removed but failed to persist swarm state: %v", err))
	}
	return SilentResult(fmt.Sprintf("agent %s removed from swarm", agentID))
}

func (t *SwarmTool) listMembers() *ToolResult {
	members := t.coordinator.GetMembers()
	out, _ := json.MarshalIndent(members, "", "  ")
	return SilentResult(fmt.Sprintf("swarm members (%d):\n%s", len(members), string(out)))
}

func (t *SwarmTool) submitSignal(args map[string]any) *ToolResult {
	agentID, _ := args["agent_id"].(string)
	if agentID == "" {
		agentID = t.agentID
	}
	tokenAddress, _ := args["token_address"].(string)
	actionSignal, _ := args["action_signal"].(string)
	reasoning, _ := args["reasoning"].(string)

	confidence := 0.5
	if c, ok := args["confidence"].(float64); ok {
		confidence = c
	}
	chainID := 0
	if c, ok := args["chain_id"].(float64); ok {
		chainID = int(c)
	}

	if tokenAddress == "" {
		return ErrorResult("token_address is required for submit_signal")
	}
	if actionSignal == "" {
		return ErrorResult("action_signal is required for submit_signal")
	}

	sig := swarm.SwarmSignal{
		AgentID:      agentID,
		Action:       actionSignal,
		TokenAddress: tokenAddress,
		ChainID:      chainID,
		Confidence:   confidence,
		Reasoning:    reasoning,
	}
	if err := t.coordinator.SubmitSignal(sig); err != nil {
		return ErrorResult(fmt.Sprintf("failed to submit signal: %v", err))
	}
	if err := t.persistState(); err != nil {
		return ErrorResult(fmt.Sprintf("signal submitted but failed to persist swarm state: %v", err))
	}
	return SilentResult(
		fmt.Sprintf("signal submitted: %s %s (confidence=%.2f)", actionSignal, tokenAddress, confidence),
	)
}

func (t *SwarmTool) runConsensus(args map[string]any) *ToolResult {
	tokenAddress, _ := args["token_address"].(string)
	chainID := 0
	if c, ok := args["chain_id"].(float64); ok {
		chainID = int(c)
	}

	if tokenAddress == "" {
		return ErrorResult("token_address is required for run_consensus")
	}

	result, err := t.coordinator.RunConsensus(tokenAddress, chainID)
	if err != nil {
		return ErrorResult(fmt.Sprintf("consensus failed: %v", err))
	}
	if err := t.persistState(); err != nil {
		return ErrorResult(fmt.Sprintf("consensus computed but failed to persist swarm state: %v", err))
	}

	payload := map[string]any{"consensus": result}
	if decision := t.coordinator.GetLastDecision(); decision != nil {
		payload["decision"] = decision
	}
	out, _ := json.MarshalIndent(payload, "", "  ")
	status := "REJECTED"
	if result.Approved {
		status = "APPROVED"
	}
	return SilentResult(fmt.Sprintf("consensus result [%s]:\n%s", status, string(out)))
}

func (t *SwarmTool) broadcastStrategy(args map[string]any) *ToolResult {
	strategy, _ := args["strategy"].(string)
	if strategy == "" {
		return ErrorResult("strategy is required for broadcast_strategy")
	}
	t.coordinator.BroadcastStrategy(strategy)
	_ = t.persistState()
	return SilentResult(fmt.Sprintf("strategy broadcast: %s", strategy))
}

func (t *SwarmTool) getStatus() *ToolResult {
	members := t.coordinator.GetMembers()
	cfg := t.coordinator.GetConfig()

	status := map[string]any{
		"leader_id":           t.coordinator.GetLeaderID(),
		"member_count":        len(members),
		"max_swarm_size":      cfg.MaxSwarmSize,
		"consensus_threshold": cfg.ConsensusThreshold,
		"signal_aggregation":  cfg.SignalAggregation,
		"strategy_rotation":   cfg.StrategyRotation,
		"last_consensus":      t.coordinator.GetLastConsensus(),
		"last_decision":       t.coordinator.GetLastDecision(),
		"last_rebalanced_at":  t.coordinator.GetLastRebalancedAt(),
		"members":             members,
	}
	out, _ := json.MarshalIndent(status, "", "  ")
	return SilentResult(fmt.Sprintf("swarm status:\n%s", string(out)))
}

func (t *SwarmTool) persistState() error {
	if t.persist == nil {
		return nil
	}
	return t.persist()
}
