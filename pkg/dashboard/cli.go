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
		pnlSign := "+"
		if t.TotalPnL < 0 {
			pnlSign = ""
		}
		line(fmt.Sprintf("  Trades: %-4d  Win Rate: %.1f%%   P&L: %s%.2f GMAC",
			t.TotalTrades, t.ProfitablePct, pnlSign, t.TotalPnL))
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
			last := tp.RecentMessages[len(tp.RecentMessages)-1]
			ago := formatAgo(last.Timestamp)
			line(fmt.Sprintf("  Latest: %s from %s (%s)",
				truncate(last.Type, 16),
				truncate(last.From, 12),
				ago))
		}
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
