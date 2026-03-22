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
	balanceSource func() float64
	debitParent   func(float64) error
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

// SetParentBalanceHooks lets the tool source and debit GMAC from a live parent
// balance store such as metabolism, instead of a detached float pointer.
func (t *ReplicateTool) SetParentBalanceHooks(
	balanceSource func() float64,
	debitParent func(float64) error,
) {
	t.balanceSource = balanceSource
	t.debitParent = debitParent
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
	} else if t.balanceSource != nil {
		gmac = t.balanceSource()
	}
	originalGMAC := gmac
	options := &replication.ReplicateOptions{
		Name:         stringArg(args, "name"),
		StrategyHint: stringArg(args, "strategy_hint"),
	}

	child, err := t.replicator.Replicate(t.parentConfig, t.workspace, &gmac, options)
	if err != nil {
		return ErrorResult(fmt.Sprintf("replication failed: %v", err))
	}

	if t.parentGMAC != nil {
		*t.parentGMAC = gmac
	} else if t.debitParent != nil {
		share := originalGMAC - gmac
		if share > 0 {
			if err := t.debitParent(share); err != nil {
				return ErrorResult(fmt.Sprintf("replication created child but failed to debit parent GMAC: %v", err))
			}
		}
	}

	if err := t.replicator.SaveChildren(t.workspace); err != nil {
		return ErrorResult(fmt.Sprintf("replication succeeded but failed to persist child state: %v", err))
	}

	out, _ := json.MarshalIndent(child, "", "  ")
	return SilentResult(fmt.Sprintf("Child agent created:\n%s", string(out)))
}
