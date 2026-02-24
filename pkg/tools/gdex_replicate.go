package tools

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/replication"
)

// ReplicateTool allows the agent to create a child agent via self-replication.
// Replication is goodwill-gated: the agent must reach the configured threshold.
type ReplicateTool struct {
	replicator    *replication.Replicator
	parentConfig  *config.Config
	workspace     string
	parentGMAC    *float64
	goodwillCheck func() int
	threshold     int
}

// NewReplicateTool creates a ReplicateTool wired to the given Replicator.
// goodwillCheck returns the current goodwill score; threshold is the minimum required.
func NewReplicateTool(
	r *replication.Replicator,
	parentConfig *config.Config,
	workspace string,
	parentGMAC *float64,
	goodwillCheck func() int,
	threshold int,
) *ReplicateTool {
	return &ReplicateTool{
		replicator:    r,
		parentConfig:  parentConfig,
		workspace:     workspace,
		parentGMAC:    parentGMAC,
		goodwillCheck: goodwillCheck,
		threshold:     threshold,
	}
}

func (t *ReplicateTool) Name() string { return "replicate" }

func (t *ReplicateTool) Description() string {
	return "Create a child agent that inherits your config, skills, and memory. Requires sufficient goodwill. The child gets a portion of your GMAC balance and a mutated trading strategy."
}

func (t *ReplicateTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"name": map[string]any{
				"type":        "string",
				"description": "Optional label for the child agent",
			},
			"strategy_hint": map[string]any{
				"type":        "string",
				"description": "Optional hint to influence the child's trading strategy mutation",
			},
		},
	}
}

func (t *ReplicateTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	if t.replicator == nil {
		return ErrorResult("replicator not configured")
	}

	// Check goodwill threshold
	if t.goodwillCheck != nil {
		gw := t.goodwillCheck()
		if !t.replicator.CanReplicate(gw, t.threshold) {
			return ErrorResult(fmt.Sprintf(
				"insufficient goodwill for replication: have %d, need %d",
				gw, t.threshold,
			))
		}
	}

	gmac := float64(0)
	if t.parentGMAC != nil {
		gmac = *t.parentGMAC
	}

	child, err := t.replicator.Replicate(t.parentConfig, t.workspace, &gmac)
	if err != nil {
		return ErrorResult(fmt.Sprintf("replication failed: %v", err))
	}

	if t.parentGMAC != nil {
		*t.parentGMAC = gmac
	}

	out, _ := json.MarshalIndent(child, "", "  ")
	return SilentResult(fmt.Sprintf("Child agent created:\n%s", string(out)))
}
