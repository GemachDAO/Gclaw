// Gclaw - Ultra-lightweight personal AI agent
// Inspired by and based on nanobot: https://github.com/HKUDS/nanobot
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package dashboard

import (
	"fmt"
	"strings"
	"time"
)

const dashboardWidth = 56

// FormatCLI renders DashboardData as a formatted CLI string.
func FormatCLI(data *DashboardData) string {
	if data == nil {
		return ""
	}

	var sb strings.Builder
	border := strings.Repeat("═", dashboardWidth)

	line := func(content string) {
		padded := fmt.Sprintf("%-*s", dashboardWidth, content)
		sb.WriteString("║ " + padded + " ║\n")
	}
	divider := func() {
		sb.WriteString("╠" + border + "╣\n")
	}

	sb.WriteString("╔" + border + "╗\n")
	line(centerText("🦞 GCLAW LIVING AGENT", dashboardWidth))
	divider()

	// Identity row
	gen := data.Generation
	line(fmt.Sprintf("Agent: %-16s│  Gen: %-2d │  Uptime: %s",
		truncate(data.AgentID, 16), gen, data.Uptime))
	divider()

	// Metabolism
	line("💰 METABOLISM")
	if data.Metabolism != nil {
		m := data.Metabolism
		mode := "ACTIVE"
		if m.SurvivalMode {
			mode = "SURVIVAL"
		}
		line(fmt.Sprintf("  Balance: %-10.2f GMAC    Goodwill: %d",
			m.Balance, m.Goodwill))
		abilities := strings.Join(m.Abilities, ", ")
		if abilities == "" {
			abilities = "none"
		}
		line(fmt.Sprintf("  Mode: %-16s Abilities: %s", mode, truncate(abilities, 24)))
	} else {
		line("  (not configured)")
	}
	divider()

	// Trading
	line("📊 TRADING")
	if data.Trading != nil {
		t := data.Trading
		if t.HasRealizedPnL {
			pnlSign := "+"
			if t.TotalPnL < 0 {
				pnlSign = ""
			}
			line(fmt.Sprintf("  Execs: %-4d  Realized: %-4d  Win Rate: %.1f%%   P&L: %s%.2f GMAC",
				t.TotalTrades, t.RealizedTrades, t.ProfitablePct, pnlSign, t.TotalPnL))
		} else {
			line(fmt.Sprintf("  Execs: %-4d  Realized: %-4d  Win Rate: n/a   P&L: pending",
				t.TotalTrades, t.RealizedTrades))
		}
		if len(t.RecentCycles) > 0 {
			last := t.RecentCycles[len(t.RecentCycles)-1]
			target := truncate(firstNonEmptyCLI(last.TokenSymbol, last.Mode), 14)
			line(fmt.Sprintf("  Last Cycle: %-8s %-14s %s",
				truncate(last.Status, 8),
				target,
				truncate(firstNonEmptyCLI(last.Chain, last.Venue), 16)))
		}
		if len(t.LatestMissedOpportunities) > 0 {
			missed := t.LatestMissedOpportunities[0]
			line(fmt.Sprintf("  Missed: %s",
				truncate(firstNonEmptyCLI(missed.TokenSymbol, missed.TokenAddress), 38)))
		}
	} else {
		line("  (not configured)")
	}
	divider()

	// Trading access
	line("🏦 FUNDING")
	if data.TradingAccess != nil {
		ta := data.TradingAccess
		addr := ta.WalletAddress
		if addr == "" {
			addr = "not configured"
		} else {
			addr = truncate(addr, 26)
		}
		apiKey := "missing"
		if ta.APIKeyConfigured {
			apiKey = "ready"
		}
		privKey := "missing"
		if ta.HasPrivateKey {
			privKey = "ready"
		}
		autoTrade := "off"
		if ta.AutoTradeEnabled {
			autoTrade = "on"
		}
		autoTradeRuntime := "disabled"
		autoTradeLast := ""
		autoTradePlan := ""
		if ta.AutoTradeRuntime != nil {
			autoTradeRuntime = ta.AutoTradeRuntime.State
			if ta.AutoTradeRuntime.Schedule != "" {
				autoTradeRuntime += " (" + ta.AutoTradeRuntime.Schedule + ")"
			}
			if ta.AutoTradeRuntime.LastError != "" {
				autoTradeLast = truncate(ta.AutoTradeRuntime.LastError, 38)
			} else if ta.AutoTradeRuntime.LastStatus != "" {
				autoTradeLast = ta.AutoTradeRuntime.LastStatus
			}
		}
		if ta.AutoTradePlan != nil {
			autoTradePlan = ta.AutoTradePlan.AssetSymbol + " via " + ta.AutoTradePlan.ChainLabel
		}
		line(fmt.Sprintf("  Control: %s", addr))
		line(fmt.Sprintf("  API Key: %-7s Private Key: %-7s Auto: %s", apiKey, privKey, autoTrade))
		line(fmt.Sprintf("  Auto Runtime: %s", truncate(autoTradeRuntime, 38)))
		if autoTradePlan != "" {
			line(fmt.Sprintf("  Auto Plan: %s", truncate(autoTradePlan, 38)))
		}
		if autoTradeLast != "" {
			line(fmt.Sprintf("  Auto Last: %s", autoTradeLast))
		}
		line(fmt.Sprintf("  Tools: %-2d Helpers: %t", ta.ToolCount, ta.HelpersInstalled))
		if mw := ta.ManagedWallets; mw != nil {
			solana := "pending"
			if mw.SolanaAddress != "" {
				solana = truncate(mw.SolanaAddress, 26)
			}
			evm := "pending"
			if mw.EVMAddress != "" {
				evm = truncate(mw.EVMAddress, 26)
			}
			line(fmt.Sprintf("  Managed: %-8s Solana: %s", mw.State, solana))
			line(fmt.Sprintf("  Managed EVM: %s", evm))
		}
	} else {
		line("  (not configured)")
	}
	divider()

	// Autonomy
	line("🧬 AUTONOMY")
	if data.Autonomy != nil {
		a := data.Autonomy
		if a.Identity.Signature != "" {
			line(fmt.Sprintf("  Signature: %s", truncate(a.Identity.Signature, 38)))
		}
		if a.Identity.Fingerprint != "" {
			line(fmt.Sprintf("  Fingerprint: %s", truncate(a.Identity.Fingerprint, 35)))
		}
		line(fmt.Sprintf("  Objective: %s", truncate(a.DNA.Objective, 38)))
		if a.DNA.ProfitSink != "" {
			line(fmt.Sprintf("  Profit Sink: %s", truncate(a.DNA.ProfitSink, 35)))
		}
		line(fmt.Sprintf("  Router: %-11s Selected: %s",
			a.Router.State,
			truncate(a.Router.SelectedRoute, 20)))
		if a.Router.FallbackRoute != "" {
			line(fmt.Sprintf("  Fallback: %s", truncate(a.Router.FallbackRoute, 38)))
		}
		line(fmt.Sprintf("  Graph: %-3d nodes  %-3d edges",
			a.KnowledgeGraph.NodeCount,
			a.KnowledgeGraph.EdgeCount))
		if len(a.DNA.PreferredChains) > 0 {
			line(fmt.Sprintf("  Chains: %s", truncate(strings.Join(a.DNA.PreferredChains, ", "), 40)))
		}
		if len(a.DNA.PreferredVenues) > 0 {
			line(fmt.Sprintf("  Venues: %s", truncate(strings.Join(a.DNA.PreferredVenues, ", "), 40)))
		}
		line(fmt.Sprintf("  Thresholds: rep=%d recode=%d",
			a.DNA.ReplicationThreshold,
			a.DNA.RecodeThreshold))
		if len(a.KnowledgeGraph.KeyNodes) > 0 {
			line(fmt.Sprintf("  Key Nodes: %s", truncate(strings.Join(a.KnowledgeGraph.KeyNodes, ", "), 38)))
		}
		if len(a.Router.Health) > 0 {
			health := make([]string, 0, len(a.Router.Health))
			for _, signal := range a.Router.Health {
				health = append(health, signal.Name+"="+signal.State)
			}
			line(fmt.Sprintf("  Health: %s", truncate(strings.Join(health, ", "), 41)))
		}
	} else {
		line("  (not configured)")
	}
	divider()

	// Venture architect
	line("🏗️  VENTURE")
	if data.Venture != nil {
		v := data.Venture
		tier := "locked"
		if v.Unlocked {
			tier = "unlocked"
		}
		line(fmt.Sprintf("  Tier: %-10s Goodwill: %d/%d", tier, v.CurrentGoodwill, v.Threshold))
		line(fmt.Sprintf("  Ventures: %-3d Launch Ready: %t", v.TotalVentures, v.LaunchReady))
		line(fmt.Sprintf("  Profit: $%-8.2f Burn Pool: $%.2f", v.TotalProfitUSD, v.TotalBurnAllocationUSD))
		if v.Active != nil {
			line(fmt.Sprintf("  Active: %s", truncate(v.Active.Title, 38)))
			line(fmt.Sprintf("  Mode: %-12s Chain: %s", truncate(v.Active.Status, 12), truncate(v.Active.Chain, 18)))
			line(fmt.Sprintf("  Contract: %s", truncate(v.Active.ContractSystem, 35)))
			line(fmt.Sprintf("  Deploy: %-13s Addr: %s", truncate(v.Active.DeploymentState, 13), truncate(firstNonEmptyCLI(v.Active.DeployedAddress, "not deployed"), 23)))
			line(fmt.Sprintf("  Ready: forge=%t rpc=%t wallet=%t", v.Active.FoundryAvailable, v.Active.RPCConfigured, v.Active.WalletReady))
			line(fmt.Sprintf("  RPC Source: %s", truncate(formatRPCSourceCLI(v.Active.RPCEnvVar), 28)))
		}
	} else {
		line("  (not configured)")
	}
	divider()

	// Family tree
	line("👨‍👧‍👦 FAMILY TREE")
	if data.Family != nil && len(data.Family.Children) > 0 {
		line(fmt.Sprintf("  Children: %d", len(data.Family.Children)))
		for i, child := range data.Family.Children {
			prefix := "  ├─"
			if i == len(data.Family.Children)-1 {
				prefix = "  └─"
			}
			line(fmt.Sprintf("%s %s [%s] %s",
				prefix,
				truncate(child.ID, 18),
				child.Status,
				truncate(strings.Join(child.Mutations, ","), 12)))
		}
	} else {
		line("  No children")
	}
	divider()

	// Telepathy
	line("📡 TELEPATHY")
	if data.Telepathy != nil {
		tp := data.Telepathy
		line(fmt.Sprintf("  Messages: %-4d  Active Channels: %d",
			tp.TotalMessages, tp.ActiveChannels))
		if len(tp.RecentMessages) > 0 {
			line("  Recent:")
			start := len(tp.RecentMessages) - 3
			if start < 0 {
				start = 0
			}
			for i := len(tp.RecentMessages) - 1; i >= start; i-- {
				msg := tp.RecentMessages[i]
				target := "family"
				if msg.To != "" && msg.To != "*" {
					target = msg.To
				}
				line(fmt.Sprintf("   %s %s -> %s",
					truncate(msg.Type, 16),
					truncate(msg.From, 12),
					truncate(target, 12)))
				line(fmt.Sprintf("    %s",
					truncate(strings.TrimSpace(msg.Content), 44)))
			}
		}
	} else {
		line("  (not configured)")
	}
	divider()

	// Registration
	line("🪪 REGISTRATION")
	if data.Registration != nil {
		reg := data.Registration
		line(fmt.Sprintf("  ERC-8004: %-8s Wallet Ready: %t", reg.State, reg.WalletReady))
		line(fmt.Sprintf("  x402: %-5t URL: %s", reg.X402Enabled, truncate(reg.URL, 28)))
	} else {
		line("  (not configured)")
	}
	divider()

	// Swarm
	line("🐝 SWARM")
	if data.Swarm != nil {
		sw := data.Swarm
		role := "member"
		if sw.IsLeader {
			role = "Leader"
		}
		line(fmt.Sprintf("  Role: %-8s  Members: %-3d  Consensus: %s",
			role, sw.MemberCount, truncate(sw.ConsensusMode, 10)))
	} else {
		line("  (not configured)")
	}
	divider()

	// System
	line("⚙️  SYSTEM")
	if data.System != nil {
		sys := data.System
		hb := "❌"
		if sys.HeartbeatActive {
			hb = "✅"
		}
		line(fmt.Sprintf("  Heartbeat: %s (%dmin)   Tools: %-4d Skills: %d",
			hb, sys.HeartbeatInterval, sys.ToolCount, sys.SkillCount))
	} else {
		line("  (not configured)")
	}

	sb.WriteString("╚" + border + "╝\n")
	return sb.String()
}

// centerText centers a string within a fixed width (best-effort, ignoring multi-byte rune widths).
func centerText(s string, width int) string {
	if len(s) >= width {
		return s
	}
	pad := (width - len(s)) / 2
	return strings.Repeat(" ", pad) + s
}

// truncate shortens s to at most n runes, appending "…" if truncated.
func truncate(s string, n int) string {
	runes := []rune(s)
	if len(runes) <= n {
		return s
	}
	if n <= 1 {
		return string(runes[:n])
	}
	return string(runes[:n-1]) + "…"
}

// formatAgo returns a short human-readable "time ago" string for a Unix ms timestamp.
func formatAgo(ms int64) string {
	if ms == 0 {
		return "unknown"
	}
	diff := time.Now().UnixMilli() - ms
	if diff < 0 {
		diff = 0
	}
	secs := diff / 1000
	if secs < 60 {
		return fmt.Sprintf("%ds ago", secs)
	}
	mins := secs / 60
	if mins < 60 {
		return fmt.Sprintf("%dm ago", mins)
	}
	return fmt.Sprintf("%dh ago", mins/60)
}

func firstNonEmptyCLI(values ...string) string {
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" {
			return value
		}
	}
	return ""
}

func formatRPCSourceCLI(source string) string {
	source = strings.TrimSpace(source)
	switch source {
	case "":
		return "not configured"
	case "builtin_public_rpc":
		return "built-in public RPC"
	default:
		return source
	}
}
