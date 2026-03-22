package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/venture"
)

// VentureArchitectTool launches and tracks higher-order venture systems once
// the architect tier is unlocked.
type VentureArchitectTool struct {
	manager       *venture.Manager
	goodwillCheck func() int
	threshold     int
	contextSource func() venture.LaunchContext
}

// NewVentureArchitectTool creates a venture tool.
func NewVentureArchitectTool(
	manager *venture.Manager,
	goodwillCheck func() int,
	threshold int,
	contextSource func() venture.LaunchContext,
) *VentureArchitectTool {
	return &VentureArchitectTool{
		manager:       manager,
		goodwillCheck: goodwillCheck,
		threshold:     threshold,
		contextSource: contextSource,
	}
}

func (t *VentureArchitectTool) Name() string { return "venture_architect" }

func (t *VentureArchitectTool) Description() string {
	return "Launch and track higher-order profit ventures once goodwill reaches the venture-architect tier. Creates persistent venture manifests, contract scaffolds, profit-routing policy, and recurring review cadence."
}

func (t *VentureArchitectTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"action": map[string]any{
				"type":        "string",
				"description": "The venture action: status | launch | deploy | record_profit",
				"enum":        []string{"status", "launch", "deploy", "record_profit"},
			},
			"venture_id": map[string]any{
				"type":        "string",
				"description": "Optional venture ID for record_profit. Defaults to the active venture.",
			},
			"profit_usd": map[string]any{
				"type":        "number",
				"description": "Realized venture profit in USD, used to compute the GMAC buy-and-burn allocation.",
			},
		},
	}
}

func (t *VentureArchitectTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	if t.manager == nil {
		return ErrorResult("venture manager not configured")
	}

	action := strings.TrimSpace(stringArg(args, "action"))
	if action == "" {
		action = "status"
	}
	launchCtx := t.launchContext()

	switch action {
	case "status":
		snap, err := t.manager.Snapshot(launchCtx)
		if err != nil {
			return ErrorResult(fmt.Sprintf("venture status failed: %v", err))
		}
		raw, _ := json.MarshalIndent(snap, "", "  ")
		return SilentResult(string(raw))
	case "launch":
		if t.goodwillCheck != nil {
			gw := t.goodwillCheck()
			if gw < t.threshold {
				return ErrorResult(fmt.Sprintf(
					"insufficient goodwill for venture architect tier: have %d, need %d",
					gw, t.threshold,
				))
			}
		}
		v, created, err := t.manager.EnsureAutonomousLaunch(launchCtx)
		if err != nil {
			return ErrorResult(fmt.Sprintf("venture launch failed: %v", err))
		}
		if v == nil {
			return SilentResult("venture architect tier not unlocked yet")
		}
		raw, _ := json.MarshalIndent(v, "", "  ")
		if created {
			return SilentResult("Launched venture:\n" + string(raw))
		}
		return SilentResult("Active venture already exists:\n" + string(raw))
	case "deploy":
		ventureID := strings.TrimSpace(stringArg(args, "venture_id"))
		if ventureID == "" {
			snap, err := t.manager.Snapshot(launchCtx)
			if err != nil {
				return ErrorResult(fmt.Sprintf("venture status failed: %v", err))
			}
			if snap == nil || snap.Active == nil {
				return ErrorResult("no active venture to deploy")
			}
			ventureID = snap.Active.ID
		}
		v, err := t.manager.Deploy(ventureID)
		if err != nil {
			return ErrorResult(fmt.Sprintf("venture deploy failed: %v", err))
		}
		raw, _ := json.MarshalIndent(v, "", "  ")
		return SilentResult("Deployed venture contract:\n" + string(raw))
	case "record_profit":
		amount, ok := floatArg(args, "profit_usd")
		if !ok || amount <= 0 {
			return ErrorResult("profit_usd must be a positive number")
		}
		ventureID := strings.TrimSpace(stringArg(args, "venture_id"))
		if ventureID == "" {
			snap, err := t.manager.Snapshot(launchCtx)
			if err != nil {
				return ErrorResult(fmt.Sprintf("venture status failed: %v", err))
			}
			if snap == nil || snap.Active == nil {
				return ErrorResult("no active venture to record profit against")
			}
			ventureID = snap.Active.ID
		}
		v, err := t.manager.RecordProfit(ventureID, amount)
		if err != nil {
			return ErrorResult(fmt.Sprintf("record_profit failed: %v", err))
		}
		raw, _ := json.MarshalIndent(v, "", "  ")
		return SilentResult("Recorded venture profit:\n" + string(raw))
	default:
		return ErrorResult(fmt.Sprintf("unknown venture action %q", action))
	}
}

func (t *VentureArchitectTool) launchContext() venture.LaunchContext {
	if t.contextSource == nil {
		return venture.LaunchContext{Threshold: t.threshold}
	}
	ctx := t.contextSource()
	if ctx.Threshold == 0 {
		ctx.Threshold = t.threshold
	}
	return ctx
}

func floatArg(args map[string]any, key string) (float64, bool) {
	value, ok := args[key]
	if !ok {
		return 0, false
	}
	switch n := value.(type) {
	case float64:
		return n, true
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	case json.Number:
		f, err := n.Float64()
		return f, err == nil
	default:
		return 0, false
	}
}
