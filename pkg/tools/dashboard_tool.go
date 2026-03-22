package tools

import (
	"context"

	"github.com/GemachDAO/Gclaw/pkg/dashboard"
)

// DashboardTool allows the agent to view its own living-agent dashboard.
type DashboardTool struct {
	dash *dashboard.Dashboard
}

// NewDashboardTool creates a DashboardTool backed by the given Dashboard.
func NewDashboardTool(dash *dashboard.Dashboard) *DashboardTool {
	return &DashboardTool{dash: dash}
}

func (t *DashboardTool) Name() string { return "dashboard" }

func (t *DashboardTool) Description() string {
	return "View your living agent dashboard. Use section funding for wallet addresses, auto-trade flag, helper readiness, and loaded trading tool names. Use section autonomy for DNA, route selection, and knowledge graph state. Use section registration for ERC-8004 and x402 status."
}

func (t *DashboardTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"section": map[string]any{
				"type":        "string",
				"description": "Section to display: all | metabolism | trading | funding | autonomy | family | telepathy | swarm | registration | system",
				"enum":        []string{"all", "metabolism", "trading", "funding", "autonomy", "family", "telepathy", "swarm", "registration", "system"},
			},
		},
		"required": []string{},
	}
}

func (t *DashboardTool) Execute(_ context.Context, args map[string]any) *ToolResult {
	if t.dash == nil {
		return ErrorResult("dashboard not configured")
	}

	section, _ := args["section"].(string)
	if section == "" {
		section = "all"
	}

	data := t.dash.GetData()

	switch section {
	case "metabolism":
		if data.Metabolism == nil {
			return SilentResult("metabolism: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:    data.AgentID,
			Uptime:     data.Uptime,
			StartedAt:  data.StartedAt,
			Metabolism: data.Metabolism,
		}))
	case "trading":
		if data.Trading == nil {
			return SilentResult("trading: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:   data.AgentID,
			Uptime:    data.Uptime,
			StartedAt: data.StartedAt,
			Trading:   data.Trading,
		}))
	case "family":
		if data.Family == nil {
			return SilentResult("family: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:   data.AgentID,
			Uptime:    data.Uptime,
			StartedAt: data.StartedAt,
			Family:    data.Family,
		}))
	case "funding":
		if data.TradingAccess == nil {
			return SilentResult("funding: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:       data.AgentID,
			Uptime:        data.Uptime,
			StartedAt:     data.StartedAt,
			TradingAccess: data.TradingAccess,
		}))
	case "autonomy":
		if data.Autonomy == nil {
			return SilentResult("autonomy: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:   data.AgentID,
			Uptime:    data.Uptime,
			StartedAt: data.StartedAt,
			Autonomy:  data.Autonomy,
		}))
	case "telepathy":
		if data.Telepathy == nil {
			return SilentResult("telepathy: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:   data.AgentID,
			Uptime:    data.Uptime,
			StartedAt: data.StartedAt,
			Telepathy: data.Telepathy,
		}))
	case "swarm":
		if data.Swarm == nil {
			return SilentResult("swarm: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:   data.AgentID,
			Uptime:    data.Uptime,
			StartedAt: data.StartedAt,
			Swarm:     data.Swarm,
		}))
	case "registration":
		if data.Registration == nil {
			return SilentResult("registration: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:      data.AgentID,
			Uptime:       data.Uptime,
			StartedAt:    data.StartedAt,
			Registration: data.Registration,
		}))
	case "system":
		if data.System == nil {
			return SilentResult("system: not configured")
		}
		return SilentResult(dashboard.FormatCLI(&dashboard.DashboardData{
			AgentID:   data.AgentID,
			Uptime:    data.Uptime,
			StartedAt: data.StartedAt,
			System:    data.System,
		}))
	default: // "all"
		return SilentResult(dashboard.FormatCLI(data))
	}
}
