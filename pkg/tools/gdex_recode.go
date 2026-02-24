package tools

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/GemachDAO/Gclaw/pkg/recode"
)

// RecodeTool allows the agent to modify its own configuration when it has
// earned sufficient goodwill (default threshold: 100).
type RecodeTool struct {
	recoder       *recode.Recoder
	goodwillCheck func() int
	threshold     int
}

// NewRecodeTool creates a RecodeTool wired to the given Recoder.
func NewRecodeTool(r *recode.Recoder, goodwillCheck func() int, threshold int) *RecodeTool {
	return &RecodeTool{
		recoder:       r,
		goodwillCheck: goodwillCheck,
		threshold:     threshold,
	}
}

func (t *RecodeTool) Name() string { return "self_recode" }

func (t *RecodeTool) Description() string {
	return "Modify your own configuration. You can update your system prompt, add cron jobs, install skills, or adjust trading parameters. Requires goodwill ≥ 100."
}

func (t *RecodeTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"action": map[string]any{
				"type":        "string",
				"description": "The modification action: modify_prompt | add_cron | install_skill | adjust_trading",
				"enum":        []string{"modify_prompt", "add_cron", "install_skill", "adjust_trading"},
			},
			"value": map[string]any{
				"type":        "string",
				"description": "The modification content. For add_cron use 'SCHEDULE|TASK'. For install_skill use 'SLUG|REGISTRY'. For adjust_trading use JSON.",
			},
		},
		"required": []string{"action", "value"},
	}
}

func (t *RecodeTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	if t.recoder == nil {
		return ErrorResult("recoder not configured")
	}

	// Check goodwill threshold
	if t.goodwillCheck != nil {
		gw := t.goodwillCheck()
		if gw < t.threshold {
			return ErrorResult(fmt.Sprintf(
				"insufficient goodwill for self-recode: have %d, need %d",
				gw, t.threshold,
			))
		}
	}

	action, _ := args["action"].(string)
	value, _ := args["value"].(string)
	if action == "" || value == "" {
		return ErrorResult("action and value are required")
	}

	var err error
	switch action {
	case "modify_prompt":
		err = t.recoder.ModifySystemPrompt(value)
	case "add_cron":
		schedule, task := splitPipe(value)
		if schedule == "" || task == "" {
			return ErrorResult("for add_cron, value must be 'SCHEDULE|TASK'")
		}
		err = t.recoder.AddCronJob(schedule, task)
	case "install_skill":
		slug, registry := splitPipe(value)
		if slug == "" {
			return ErrorResult("for install_skill, value must be 'SLUG|REGISTRY'")
		}
		err = t.recoder.InstallSkill(slug, registry)
	case "adjust_trading":
		var params map[string]any
		if jsonErr := json.Unmarshal([]byte(value), &params); jsonErr != nil {
			return ErrorResult(fmt.Sprintf("adjust_trading value must be JSON: %v", jsonErr))
		}
		err = t.recoder.AdjustTradingParams(params)
	default:
		return ErrorResult(fmt.Sprintf("unknown action %q", action))
	}

	if err != nil {
		return ErrorResult(fmt.Sprintf("self_recode failed: %v", err))
	}

	return SilentResult(fmt.Sprintf("self_recode action '%s' applied successfully", action))
}

// splitPipe splits "A|B" into ("A", "B"). Returns ("A", "") if no pipe.
func splitPipe(s string) (string, string) {
	for i, c := range s {
		if c == '|' {
			return s[:i], s[i+1:]
		}
	}
	return s, ""
}
