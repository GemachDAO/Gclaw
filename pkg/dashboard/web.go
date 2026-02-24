// Gclaw - Ultra-lightweight personal AI agent
// Inspired by and based on nanobot: https://github.com/HKUDS/nanobot
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package dashboard

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// RegisterHandlers registers dashboard HTTP routes on the given mux.
func RegisterHandlers(mux *http.ServeMux, d *Dashboard) {
	mux.HandleFunc("/dashboard", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		data := d.GetData()
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, renderHTML(data))
	})

	mux.HandleFunc("/dashboard/api", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		b, err := d.GetJSON()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write(b) //nolint:errcheck
	})

	mux.HandleFunc("/dashboard/api/metabolism", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetMetabolism != nil {
				return d.opts.GetMetabolism()
			}
			return nil
		})
	})

	mux.HandleFunc("/dashboard/api/family", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetFamily != nil {
				return d.opts.GetFamily()
			}
			return nil
		})
	})

	mux.HandleFunc("/dashboard/api/telepathy", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetTelepathy != nil {
				return d.opts.GetTelepathy()
			}
			return nil
		})
	})

	mux.HandleFunc("/dashboard/api/swarm", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetSwarm != nil {
				return d.opts.GetSwarm()
			}
			return nil
		})
	})
}

func serveSection(w http.ResponseWriter, r *http.Request, fn func() any) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	v := fn()
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write(b) //nolint:errcheck
}

// renderHTML produces a dark-themed, auto-refreshing HTML dashboard page.
func renderHTML(data *DashboardData) string {
	var sb strings.Builder

	metabHTML := "<p><em>not configured</em></p>"
	if data.Metabolism != nil {
		m := data.Metabolism
		mode := "ACTIVE"
		if m.SurvivalMode {
			mode = `<span style="color:#f87171">SURVIVAL</span>`
		}
		abilities := strings.Join(m.Abilities, ", ")
		if abilities == "" {
			abilities = "none"
		}
		metabHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Balance</span><span class="value">%.2f GMAC</span>
</div>
<div class="stat-row">
  <span class="label">Goodwill</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Mode</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Abilities</span><span class="value">%s</span>
</div>`, m.Balance, m.Goodwill, mode, abilities)
	}

	tradingHTML := "<p><em>not configured</em></p>"
	if data.Trading != nil {
		t := data.Trading
		pnlClass := "positive"
		if t.TotalPnL < 0 {
			pnlClass = "negative"
		}
		tradingHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Total Trades</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Win Rate</span><span class="value">%.1f%%</span>
</div>
<div class="stat-row">
  <span class="label">P&amp;L</span><span class="value %s">%+.2f GMAC</span>
</div>`, t.TotalTrades, t.ProfitablePct, pnlClass, t.TotalPnL)
	}

	familyHTML := "<p>No children</p>"
	if data.Family != nil && len(data.Family.Children) > 0 {
		var flines strings.Builder
		for _, c := range data.Family.Children {
			mutations := strings.Join(c.Mutations, ", ")
			if mutations == "" {
				mutations = "—"
			}
			fmt.Fprintf(&flines,
				`<li><code>%s</code> [<em>%s</em>] gen:%d mutations: %s</li>`,
				htmlEscape(c.ID), htmlEscape(c.Status), c.Generation, htmlEscape(mutations))
		}
		familyHTML = fmt.Sprintf(`<p>Children: %d</p><ul>%s</ul>`,
			len(data.Family.Children), flines.String())
	}

	telepathyHTML := "<p><em>not configured</em></p>"
	if data.Telepathy != nil {
		tp := data.Telepathy
		latestLine := ""
		if len(tp.RecentMessages) > 0 {
			last := tp.RecentMessages[len(tp.RecentMessages)-1]
			latestLine = fmt.Sprintf(`<div class="stat-row"><span class="label">Latest</span><span class="value">%s from %s (%s)</span></div>`,
				htmlEscape(last.Type), htmlEscape(last.From), formatAgo(last.Timestamp))
		}
		telepathyHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Messages</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Active Channels</span><span class="value">%d</span>
</div>%s`, tp.TotalMessages, tp.ActiveChannels, latestLine)
	}

	swarmHTML := "<p><em>not configured</em></p>"
	if data.Swarm != nil {
		sw := data.Swarm
		role := "member"
		if sw.IsLeader {
			role = "Leader"
		}
		swarmHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Role</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Members</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Consensus</span><span class="value">%s</span>
</div>`, role, sw.MemberCount, htmlEscape(sw.ConsensusMode))
	}

	systemHTML := "<p><em>not configured</em></p>"
	if data.System != nil {
		sys := data.System
		hbIcon := "❌"
		if sys.HeartbeatActive {
			hbIcon = "✅"
		}
		systemHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Heartbeat</span><span class="value">%s (%dmin)</span>
</div>
<div class="stat-row">
  <span class="label">Tools</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Platform</span><span class="value">%s</span>
</div>`, hbIcon, sys.HeartbeatInterval, sys.ToolCount, htmlEscape(sys.Platform))
	}

	refreshTs := time.Now().Format("15:04:05")

	sb.WriteString(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🦞 Gclaw Living Agent</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif; padding: 1rem; }
  h1 { text-align: center; font-size: 1.5rem; padding: 1rem 0; color: #f8fafc; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1rem; }
  .card h2 { font-size: 1rem; margin-bottom: .75rem; color: #94a3b8; }
  .stat-row { display: flex; justify-content: space-between; padding: .25rem 0; border-bottom: 1px solid #1e293b; }
  .label { color: #64748b; font-size: .85rem; }
  .value { color: #e2e8f0; font-size: .85rem; font-weight: 600; }
  .positive { color: #4ade80; }
  .negative { color: #f87171; }
  ul { margin-left: 1rem; font-size: .85rem; }
  li { padding: .2rem 0; }
  code { color: #7dd3fc; font-size: .8rem; }
  .meta { text-align: center; color: #475569; font-size: .75rem; margin-top: 1rem; }
  em { color: #475569; font-style: italic; }
</style>
</head>
<body>
<h1>🦞 Gclaw Living Agent</h1>
<div class="card" style="margin-bottom:1rem;text-align:center">
  <span style="font-size:1.1rem">`)

	sb.WriteString(htmlEscape(data.AgentID))
	sb.WriteString(`</span>
  &nbsp;│&nbsp; Gen: `)
	sb.WriteString(fmt.Sprintf("%d", data.Generation))
	sb.WriteString(` &nbsp;│&nbsp; Uptime: `)
	sb.WriteString(htmlEscape(data.Uptime))
	sb.WriteString(`
</div>
<div class="grid">
  <div class="card"><h2>💰 Metabolism</h2>`)
	sb.WriteString(metabHTML)
	sb.WriteString(`</div>
  <div class="card"><h2>📊 Trading</h2>`)
	sb.WriteString(tradingHTML)
	sb.WriteString(`</div>
  <div class="card"><h2>👨‍👧‍👦 Family Tree</h2>`)
	sb.WriteString(familyHTML)
	sb.WriteString(`</div>
  <div class="card"><h2>📡 Telepathy</h2>`)
	sb.WriteString(telepathyHTML)
	sb.WriteString(`</div>
  <div class="card"><h2>🐝 Swarm</h2>`)
	sb.WriteString(swarmHTML)
	sb.WriteString(`</div>
  <div class="card"><h2>⚙️ System</h2>`)
	sb.WriteString(systemHTML)
	sb.WriteString(`</div>
</div>
<p class="meta">Last updated: `)
	sb.WriteString(refreshTs)
	sb.WriteString(` &nbsp;·&nbsp; Auto-refreshes every 10s</p>
<script>
  setTimeout(function(){ location.reload(); }, 10000);
</script>
</body>
</html>`)

	return sb.String()
}

// htmlEscape escapes special HTML characters to prevent XSS.
func htmlEscape(s string) string {
	s = strings.ReplaceAll(s, "&", "&amp;")
	s = strings.ReplaceAll(s, "<", "&lt;")
	s = strings.ReplaceAll(s, ">", "&gt;")
	s = strings.ReplaceAll(s, `"`, "&#34;")
	s = strings.ReplaceAll(s, "'", "&#39;")
	return s
}
