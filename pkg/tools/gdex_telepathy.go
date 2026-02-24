package tools

import (
	"context"
	"fmt"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/replication"
)

// TelepathyTool allows the agent to send messages to its parent or child agents
// via the telepathy bus.
type TelepathyTool struct {
	bus     *replication.TelepathyBus
	agentID string
}

// NewTelepathyTool creates a TelepathyTool wired to the given TelepathyBus.
func NewTelepathyTool(bus *replication.TelepathyBus, agentID string) *TelepathyTool {
	return &TelepathyTool{bus: bus, agentID: agentID}
}

func (t *TelepathyTool) Name() string { return "telepathy" }

func (t *TelepathyTool) Description() string {
	return "Send a message to your parent or child agents via the telepathy bus. Share trade signals, market insights, or coordinate strategies with your agent family."
}

func (t *TelepathyTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"to": map[string]any{
				"type":        "string",
				"description": "Target agent ID, or \"*\" for broadcast to all family members (default \"*\")",
			},
			"type": map[string]any{
				"type":        "string",
				"description": "Message type: trade_signal | market_insight | strategy_update | warning",
				"enum":        []string{"trade_signal", "market_insight", "strategy_update", "warning"},
			},
			"content": map[string]any{
				"type":        "string",
				"description": "The message content",
			},
			"priority": map[string]any{
				"type":        "number",
				"description": "Message priority: 0=low, 1=normal, 2=urgent (default 1)",
			},
		},
		"required": []string{"type", "content"},
	}
}

func (t *TelepathyTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	if t.bus == nil {
		return ErrorResult("telepathy bus not configured")
	}

	msgType, _ := args["type"].(string)
	content, _ := args["content"].(string)
	if msgType == "" || content == "" {
		return ErrorResult("type and content are required")
	}

	to, _ := args["to"].(string)
	if to == "" {
		to = "*"
	}

	priority := 1
	if p, ok := args["priority"].(float64); ok {
		priority = int(p)
	}

	msg := replication.TelepathyMessage{
		FromAgentID: t.agentID,
		ToAgentID:   to,
		Type:        msgType,
		Content:     content,
		Timestamp:   time.Now().UnixMilli(),
		Priority:    priority,
	}

	if to == "*" {
		t.bus.Broadcast(msg)
		return SilentResult(fmt.Sprintf("broadcast %s message to all family members", msgType))
	}
	t.bus.SendTo(to, msg)
	return SilentResult(fmt.Sprintf("sent %s message to agent %s", msgType, to))
}
