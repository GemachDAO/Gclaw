// Gclaw - Ultra-lightweight personal AI agent
// Inspired by and based on nanobot: https://github.com/HKUDS/nanobot
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package dashboard

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"strings"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
	"github.com/skip2/go-qrcode"
)

type dashboardDNANode struct {
	x      float64
	y      float64
	radius float64
	fill   string
	glow   string
	front  bool
	alpha  float64
}

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

	mux.HandleFunc("/dashboard/api/trading", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetTrading != nil {
				return d.opts.GetTrading()
			}
			return nil
		})
	})

	mux.HandleFunc("/dashboard/api/funding", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetTradingAccess != nil {
				return d.opts.GetTradingAccess()
			}
			return nil
		})
	})

	mux.HandleFunc("/dashboard/api/autonomy", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetAutonomy != nil {
				return d.opts.GetAutonomy()
			}
			return nil
		})
	})

	mux.HandleFunc("/dashboard/api/venture", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetVenture != nil {
				return d.opts.GetVenture()
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

	mux.HandleFunc("/dashboard/api/registration", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetRegistration != nil {
				return d.opts.GetRegistration()
			}
			return nil
		})
	})

	mux.HandleFunc("/dashboard/api/system", func(w http.ResponseWriter, r *http.Request) {
		serveSection(w, r, func() any {
			if d.opts.GetSystem != nil {
				return d.opts.GetSystem()
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
		winRateValue := "n/a"
		pnlValue := `<span class="value">pending realization</span>`
		if t.HasRealizedPnL {
			winRateValue = fmt.Sprintf("%.1f%%", t.ProfitablePct)
			pnlValue = fmt.Sprintf(`<span class="value %s">%+.2f GMAC</span>`, pnlClass, t.TotalPnL)
		}
		cyclesHTML := buildTradingCycleHTML(t.RecentCycles)
		missedHTML := buildMissedOpportunityHTML(t.LatestMissedOpportunities)
		tradingHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Trade Executions</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Realized Trades</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Realized Win Rate</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Realized P&amp;L</span>%s
</div>
<div class="tool-list">Recent Decisions</div>
%s
<div class="tool-list">Missed Opportunities</div>
%s`, t.TotalTrades, t.RealizedTrades, winRateValue, pnlValue, cyclesHTML, missedHTML)
	}

	fundingHTML := "<p><em>not configured</em></p>"
	if data.TradingAccess != nil {
		ta := data.TradingAccess
		controlWallet := "not configured"
		if ta.WalletAddress != "" {
			controlWallet = htmlEscape(ta.WalletAddress)
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
		autoTradeSchedule := ""
		autoTradePlan := ""
		autoTradeGoal := ""
		autoTradeNote := ""
		if ta.AutoTradeRuntime != nil {
			autoTradeRuntime = htmlEscape(ta.AutoTradeRuntime.State)
			autoTradeSchedule = htmlEscape(ta.AutoTradeRuntime.Schedule)
			if ta.AutoTradeRuntime.LastError != "" {
				autoTradeNote = fmt.Sprintf(`<div class="tool-list">%s</div>`, htmlEscape(ta.AutoTradeRuntime.LastError))
			} else if ta.AutoTradeRuntime.LastStatus != "" {
				autoTradeNote = fmt.Sprintf(`<div class="tool-list">Last auto-trade status: %s</div>`, htmlEscape(ta.AutoTradeRuntime.LastStatus))
			}
		}
		if ta.AutoTradePlan != nil {
			autoTradePlan = htmlEscape(fmt.Sprintf("%s via %s on %s", ta.AutoTradePlan.AssetSymbol, ta.AutoTradePlan.Venue, ta.AutoTradePlan.ChainLabel))
			autoTradeGoal = htmlEscape(ta.AutoTradePlan.Goal)
		}
		toolList := "none"
		if len(ta.Tools) > 0 {
			toolList = htmlEscape(strings.Join(ta.Tools, ", "))
		}
		managedState := "pending"
		managedEVM := "pending"
		managedSolana := "pending"
		depositPanels := ""
		managedNote := ""
		fundingGuidance := buildFundingInstructionHTML(nil)
		capitalMobility := buildCapitalMobilityHTML(nil)
		if ta.ManagedWallets != nil {
			managedState = htmlEscape(ta.ManagedWallets.State)
			if ta.ManagedWallets.EVMAddress != "" {
				managedEVM = htmlEscape(ta.ManagedWallets.EVMAddress)
				depositPanels += buildDepositPanelHTML("Managed EVM", "Deposit ETH", ta.ManagedWallets.EVMAddress)
			}
			if ta.ManagedWallets.SolanaAddress != "" {
				managedSolana = htmlEscape(ta.ManagedWallets.SolanaAddress)
				depositPanels += buildDepositPanelHTML("Managed Solana", "Deposit SOL", ta.ManagedWallets.SolanaAddress)
			}
			if ta.ManagedWallets.Error != "" {
				managedNote = fmt.Sprintf(`<div class="tool-list">%s</div>`, htmlEscape(ta.ManagedWallets.Error))
			} else if len(ta.ManagedWallets.Warnings) > 0 {
				managedNote = fmt.Sprintf(`<div class="tool-list">%s</div>`, htmlEscape(strings.Join(ta.ManagedWallets.Warnings, "; ")))
			}
		}
		fundingGuidance = buildFundingInstructionHTML(ta.FundingInstructions)
		capitalMobility = buildCapitalMobilityHTML(ta.CapitalMobility)
		if depositPanels != "" {
			depositPanels = `<div class="deposit-grid">` + depositPanels + `</div>`
		}
		fundingHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Control Wallet</span><span class="value wrap">%s</span>
</div>
<div class="stat-row">
  <span class="label">API Key</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Private Key</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Auto-Trade Flag</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Auto-Trade Runtime</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Auto-Trade Schedule</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Auto-Trade Plan</span><span class="value wrap">%s</span>
</div>
<div class="stat-row">
  <span class="label">Auto-Trade Goal</span><span class="value wrap">%s</span>
</div>
<div class="stat-row">
  <span class="label">Trading Tools</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Helpers Ready</span><span class="value">%t</span>
</div>
<div class="stat-row">
  <span class="label">Managed Lookup</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Managed EVM</span><span class="value wrap">%s</span>
</div>
<div class="stat-row">
  <span class="label">Managed Solana</span><span class="value wrap">%s</span>
</div>
<div class="tool-list">%s</div>%s
<div class="tool-list">Funding Guidance</div>
%s
<div class="tool-list">Capital Mobility</div>
%s%s%s`, controlWallet, apiKey, privKey, autoTrade, autoTradeRuntime, autoTradeSchedule, autoTradePlan, autoTradeGoal, ta.ToolCount, ta.HelpersInstalled, managedState, managedEVM, managedSolana, toolList, autoTradeNote, fundingGuidance, capitalMobility, depositPanels, managedNote)
	}

	familyHTML := "<p>No children</p>"
	if data.Family != nil && len(data.Family.Children) > 0 {
		var flines strings.Builder
		for _, c := range data.Family.Children {
			mutations := strings.Join(c.Mutations, ", ")
			if mutations == "" {
				mutations = "—"
			}
			style := strings.TrimSpace(c.Style)
			if style == "" {
				style = "unassigned"
			}
			role := strings.TrimSpace(c.Role)
			if role == "" {
				role = "member"
			}
			chains := strings.Join(c.PreferredChains, ", ")
			if chains == "" {
				chains = "none"
			}
			venues := strings.Join(c.PreferredVenues, ", ")
			if venues == "" {
				venues = "gdex_spot"
			}
			fmt.Fprintf(&flines,
				`<li><code>%s</code> [<em>%s</em>] gen:%d style:%s role:%s risk:%s chains:%s venues:%s mutations:%s</li>`,
				htmlEscape(c.ID),
				htmlEscape(c.Status),
				c.Generation,
				htmlEscape(style),
				htmlEscape(role),
				htmlEscape(c.RiskProfile),
				htmlEscape(chains),
				htmlEscape(venues),
				htmlEscape(mutations),
			)
		}
		familyHTML = fmt.Sprintf(`<p>Children: %d</p><ul>%s</ul>`,
			len(data.Family.Children), flines.String())
	}

	autonomyHTML := "<p><em>not configured</em></p>"
	if data.Autonomy != nil {
		a := data.Autonomy
		chains := "none"
		if len(a.DNA.PreferredChains) > 0 {
			chains = htmlEscape(strings.Join(a.DNA.PreferredChains, ", "))
		}
		venues := "none"
		if len(a.DNA.PreferredVenues) > 0 {
			venues = htmlEscape(strings.Join(a.DNA.PreferredVenues, ", "))
		}
		selected := htmlEscape(a.Router.SelectedRoute)
		if selected == "" {
			selected = "none"
		}
		fallback := htmlEscape(a.Router.FallbackRoute)
		if fallback == "" {
			fallback = "none"
		}
		domains := "none"
		if len(a.KnowledgeGraph.Domains) > 0 {
			domains = htmlEscape(strings.Join(a.KnowledgeGraph.Domains, ", "))
		}
		profitSink := htmlEscape(a.DNA.ProfitSink)
		spotSpend := htmlEscape(a.DNA.SpotSpend)
		if spotSpend == "" {
			spotSpend = "not set"
		}
		perpModel := htmlEscape(a.DNA.PerpExecutionModel)
		if perpModel == "" {
			perpModel = "not set"
		}
		rotation := "disabled"
		if a.DNA.StrategyRotation {
			rotation = "enabled"
		}
		keyNodes := buildAutonomyChipList(a.KnowledgeGraph.KeyNodes, "No key nodes yet")
		health := buildAutonomyHealthHTML(a.Router.Health)
		routes := buildAutonomyRouteHTML(a.Router.Routes)
		identity := buildAgentIdentityHeroHTML(data.AgentID, a.Identity)
		autonomyHTML = fmt.Sprintf(`
%s
<div class="stat-row">
  <span class="label">Objective</span><span class="value wrap">%s</span>
</div>
<div class="stat-row">
  <span class="label">Router</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Selected</span><span class="value wrap">%s</span>
</div>
<div class="stat-row">
  <span class="label">Fallback</span><span class="value wrap">%s</span>
</div>
<div class="stat-row">
  <span class="label">Graph</span><span class="value">%d nodes / %d edges</span>
</div>
<div class="autonomy-block">
  <div class="autonomy-title">DNA</div>
  <div class="stat-row">
    <span class="label">Profit Sink</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Spot Spend</span><span class="value">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Perp Model</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Replication Threshold</span><span class="value">%d GMAC</span>
  </div>
  <div class="stat-row">
    <span class="label">Recode Threshold</span><span class="value">%d GMAC</span>
  </div>
  <div class="stat-row">
    <span class="label">Swarm Target</span><span class="value">%d agents</span>
  </div>
  <div class="stat-row">
    <span class="label">Strategy Rotation</span><span class="value">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">DNA Chains</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">DNA Venues</span><span class="value wrap">%s</span>
  </div>
</div>
<div class="autonomy-block">
  <div class="autonomy-title">Knowledge Graph</div>
  <div class="stat-row">
    <span class="label">Domains</span><span class="value wrap">%s</span>
  </div>
  <div class="autonomy-subtitle">Key Nodes</div>
  %s
</div>
<div class="autonomy-block">
  <div class="autonomy-title">Route Health</div>
  %s
</div>
<div class="autonomy-block">
  <div class="autonomy-title">Route Candidates</div>
  %s
</div>`,
			identity,
			htmlEscape(a.DNA.Objective),
			htmlEscape(a.Router.State),
			selected,
			fallback,
			a.KnowledgeGraph.NodeCount,
			a.KnowledgeGraph.EdgeCount,
			profitSink,
			spotSpend,
			perpModel,
			a.DNA.ReplicationThreshold,
			a.DNA.RecodeThreshold,
			a.DNA.SwarmTarget,
			rotation,
			chains,
			venues,
			domains,
			keyNodes,
			health,
			routes,
		)
	}

	ventureHTML := "<p><em>not configured</em></p>"
	if data.Venture != nil {
		v := data.Venture
		unlocked := "locked"
		if v.Unlocked {
			unlocked = "unlocked"
		}
		launchReady := "no"
		if v.LaunchReady {
			launchReady = "yes"
		}
		activeHTML := `<div class="tool-list">No active venture yet.</div>`
		if v.Active != nil {
			active := v.Active
			required := "none"
			if len(active.RequiredTools) > 0 {
				required = htmlEscape(strings.Join(active.RequiredTools, ", "))
			}
			activeHTML = fmt.Sprintf(`
<div class="autonomy-block">
  <div class="autonomy-title">Active Venture</div>
  <div class="stat-row">
    <span class="label">Title</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Status</span><span class="value">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Archetype</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Chain</span><span class="value">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Venue</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Deploy Mode</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Contract</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Profit Model</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Tracked Profit</span><span class="value">$%.2f</span>
  </div>
  <div class="stat-row">
    <span class="label">Burn Allocation</span><span class="value">$%.2f (%.0f%%)</span>
  </div>
  <div class="stat-row">
    <span class="label">Contract Scaffold</span><span class="value">%t</span>
  </div>
  <div class="stat-row">
    <span class="label">Deployment</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Deploy Ready</span><span class="value">%t / %t / %t</span>
  </div>
  <div class="stat-row">
    <span class="label">Owner</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">RPC Source</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Contract Address</span><span class="value wrap">%s</span>
  </div>
  <div class="stat-row">
    <span class="label">Deploy Tx</span><span class="value wrap">%s</span>
  </div>
  <div class="tool-list">Required tools: %s</div>
  <div class="tool-list">%s</div>
  <div class="tool-list">%s</div>
  <div class="tool-list">%s</div>
</div>`,
				htmlEscape(active.Title),
				htmlEscape(active.Status),
				htmlEscape(active.Archetype),
				htmlEscape(active.Chain),
				htmlEscape(active.Venue),
				htmlEscape(active.DeploymentMode),
				htmlEscape(active.ContractSystem),
				htmlEscape(active.ProfitModel),
				active.RealizedProfitUSD,
				active.BurnAllocationUSD,
				active.BurnAllocationPct,
				active.ContractScaffoldReady,
				htmlEscape(active.DeploymentState),
				active.FoundryAvailable,
				active.RPCConfigured,
				active.WalletReady,
				htmlEscape(firstNonEmptyString(active.OwnerAddress, "not configured")),
				htmlEscape(formatRPCSource(active.RPCEnvVar)),
				htmlEscape(firstNonEmptyString(active.DeployedAddress, "not deployed")),
				htmlEscape(firstNonEmptyString(active.DeploymentTxHash, "not deployed")),
				required,
				htmlEscape(active.LaunchReason),
				htmlEscape(active.NextAction),
				htmlEscape(firstNonEmptyString(active.DeployError, "deployment path healthy")),
			)
		}
		ventureHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Tier</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Goodwill</span><span class="value">%d / %d</span>
</div>
<div class="stat-row">
  <span class="label">Launch Ready</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Ventures</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Tracked Profit</span><span class="value">$%.2f</span>
</div>
<div class="stat-row">
  <span class="label">GMAC Burn Pool</span><span class="value">$%.2f</span>
</div>
<div class="tool-list">%s</div>
%s`,
			unlocked,
			v.CurrentGoodwill,
			v.Threshold,
			launchReady,
			v.TotalVentures,
			v.TotalProfitUSD,
			v.TotalBurnAllocationUSD,
			htmlEscape(v.BurnPolicy),
			activeHTML,
		)
	}

	telepathyHTML := "<p><em>not configured</em></p>"
	if data.Telepathy != nil {
		tp := data.Telepathy
		recentMessagesHTML := buildTelepathyMessagesHTML(tp.RecentMessages, tp.TotalMessages)
		telepathyHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Messages</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Active Channels</span><span class="value">%d</span>
</div>
<div class="stat-row">
  <span class="label">Persistence</span><span class="value">%t</span>
</div>
<div class="tool-list">Recent Messages</div>
%s`, tp.TotalMessages, tp.ActiveChannels, tp.Persistent, recentMessagesHTML)
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
		if sw.LastConsensus != nil {
			swarmHTML += fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Last Vote</span><span class="value wrap">%s %s (%t)</span>
</div>`,
				htmlEscape(sw.LastConsensus.Action),
				htmlEscape(sw.LastConsensus.TokenAddress),
				sw.LastConsensus.Approved,
			)
		}
		if sw.LastDecision != nil {
			swarmHTML += fmt.Sprintf(`
<div class="stat-row">
  <span class="label">Decision</span><span class="value wrap">%s via %s [%s]</span>
</div>
<div class="stat-row">
  <span class="label">Executor</span><span class="value wrap">%s</span>
</div>`,
				htmlEscape(sw.LastDecision.Action),
				htmlEscape(sw.LastDecision.Strategy),
				htmlEscape(sw.LastDecision.Status),
				htmlEscape(sw.LastDecision.ExecutorID),
			)
		}
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

	registrationHTML := "<p><em>not configured</em></p>"
	if data.Registration != nil {
		reg := data.Registration
		registrationHTML = fmt.Sprintf(`
<div class="stat-row">
  <span class="label">ERC-8004</span><span class="value">%s</span>
</div>
<div class="stat-row">
  <span class="label">Wallet Ready</span><span class="value">%t</span>
</div>
<div class="stat-row">
  <span class="label">x402 Payments</span><span class="value">%t</span>
</div>
<div class="stat-row">
  <span class="label">Registration URL</span><span class="value wrap">%s</span>
</div>`, htmlEscape(reg.State), reg.WalletReady, reg.X402Enabled, htmlEscape(reg.URL))
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
  .wrap { max-width: 65%; overflow-wrap: anywhere; text-align: right; }
  .positive { color: #4ade80; }
  .negative { color: #f87171; }
  .tool-list { margin-top: .75rem; color: #94a3b8; font-size: .78rem; line-height: 1.4; overflow-wrap: anywhere; }
  .deposit-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: .85rem; margin-top: 1rem; }
  .deposit-panel { background: linear-gradient(180deg, rgba(30,41,59,.88) 0%, rgba(15,23,42,.98) 100%); border: 1px solid #475569; border-radius: 14px; padding: .85rem; box-shadow: inset 0 1px 0 rgba(255,255,255,.04); }
  .deposit-kicker { color: #7dd3fc; font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; margin-bottom: .35rem; }
  .deposit-title { color: #f8fafc; font-size: .95rem; font-weight: 700; margin-bottom: .65rem; }
  .qr-shell { background: #f8fafc; border-radius: 12px; padding: .55rem; display: flex; justify-content: center; align-items: center; min-height: 156px; }
  .qr-shell img { width: 132px; height: 132px; display: block; image-rendering: pixelated; }
  .deposit-address { margin-top: .65rem; color: #cbd5e1; font-size: .76rem; line-height: 1.45; overflow-wrap: anywhere; }
  .identity-hero { display: grid; gap: 1rem; margin-bottom: 1rem; padding: 1rem; border-radius: 20px; border: 1px solid rgba(125,211,252,.22); background:
      radial-gradient(circle at top left, rgba(56,189,248,.18), transparent 45%),
      radial-gradient(circle at bottom right, rgba(249,115,22,.12), transparent 45%),
      linear-gradient(135deg, rgba(15,23,42,.98) 0%, rgba(30,41,59,.9) 100%); }
  .dna-stage { border-radius: 18px; padding: .55rem; background: rgba(2,6,23,.72); border: 1px solid rgba(148,163,184,.18); box-shadow: inset 0 1px 0 rgba(255,255,255,.04); }
  .dna-stage svg { width: 100%; height: auto; display: block; }
  .identity-meta { display: grid; gap: .55rem; }
  .identity-kicker { color: #7dd3fc; font-size: .68rem; letter-spacing: .16em; text-transform: uppercase; }
  .identity-signature { color: #f8fafc; font-family: 'IBM Plex Mono', 'SFMono-Regular', ui-monospace, monospace; font-size: 1.15rem; font-weight: 700; letter-spacing: .04em; }
  .identity-fingerprint { color: #cbd5e1; font-family: 'IBM Plex Mono', 'SFMono-Regular', ui-monospace, monospace; font-size: .8rem; letter-spacing: .12em; text-transform: uppercase; overflow-wrap: anywhere; }
  .identity-caption { color: #94a3b8; font-size: .78rem; line-height: 1.5; }
  .palette-row { display: flex; gap: .45rem; align-items: center; }
  .swatch { width: 18px; height: 18px; border-radius: 999px; border: 1px solid rgba(255,255,255,.22); box-shadow: 0 0 0 1px rgba(15,23,42,.45); }
  .autonomy-block { margin-top: 1rem; padding-top: .85rem; border-top: 1px solid #334155; }
  .autonomy-title { color: #f8fafc; font-size: .82rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; margin-bottom: .65rem; }
  .autonomy-subtitle { color: #94a3b8; font-size: .74rem; letter-spacing: .08em; text-transform: uppercase; margin-top: .75rem; margin-bottom: .45rem; }
  .chip-list { display: flex; flex-wrap: wrap; gap: .45rem; margin-top: .3rem; }
  .chip { border-radius: 999px; padding: .32rem .6rem; font-size: .72rem; line-height: 1.3; background: rgba(15,23,42,.92); border: 1px solid #334155; color: #cbd5e1; overflow-wrap: anywhere; }
  .health-grid, .route-stack { display: grid; gap: .65rem; margin-top: .35rem; }
  .health-item, .route-card { background: rgba(15,23,42,.72); border: 1px solid #334155; border-radius: 12px; padding: .7rem; }
  .route-top, .health-top { display: flex; justify-content: space-between; gap: .6rem; align-items: center; }
  .route-name, .health-name { color: #f8fafc; font-size: .83rem; font-weight: 700; }
  .route-summary, .health-detail { color: #94a3b8; font-size: .75rem; line-height: 1.45; margin-top: .35rem; }
  .route-steps, .route-blockers { color: #cbd5e1; font-size: .74rem; line-height: 1.5; margin-top: .45rem; overflow-wrap: anywhere; }
  .route-blockers { color: #fca5a5; }
  .telepathy-stream { display: grid; gap: .65rem; margin-top: .35rem; max-height: 420px; overflow-y: auto; padding-right: .2rem; }
  .telepathy-card { background: rgba(15,23,42,.72); border: 1px solid #334155; border-radius: 12px; padding: .7rem; }
  .telepathy-top { display: flex; justify-content: space-between; gap: .6rem; align-items: center; }
  .telepathy-title { color: #f8fafc; font-size: .83rem; font-weight: 700; }
  .telepathy-meta { color: #94a3b8; font-size: .72rem; margin-top: .35rem; overflow-wrap: anywhere; }
  .telepathy-body { color: #cbd5e1; font-size: .75rem; line-height: 1.5; margin-top: .45rem; overflow-wrap: anywhere; white-space: pre-wrap; }
  .badge { display: inline-flex; align-items: center; border-radius: 999px; padding: .18rem .5rem; font-size: .68rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; border: 1px solid #334155; }
  .state-ready { background: rgba(22,163,74,.16); color: #86efac; border-color: rgba(34,197,94,.35); }
  .state-self-healing { background: rgba(14,165,233,.16); color: #7dd3fc; border-color: rgba(56,189,248,.35); }
  .state-degraded, .state-provisional { background: rgba(245,158,11,.14); color: #fcd34d; border-color: rgba(251,191,36,.35); }
  .state-blocked { background: rgba(220,38,38,.16); color: #fca5a5; border-color: rgba(248,113,113,.35); }
  ul { margin-left: 1rem; font-size: .85rem; }
  li { padding: .2rem 0; }
  code { color: #7dd3fc; font-size: .8rem; }
  .meta { text-align: center; color: #475569; font-size: .75rem; margin-top: 1rem; }
  em { color: #475569; font-style: italic; }
  @media (min-width: 720px) { .identity-hero { grid-template-columns: minmax(0, 1.15fr) minmax(0, .85fr); align-items: center; } }
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
  <div class="card"><h2>🏦 Funding</h2>`)
	sb.WriteString(fundingHTML)
	sb.WriteString(`</div>
  <div class="card"><h2>🧬 Autonomy</h2>`)
	sb.WriteString(autonomyHTML)
	sb.WriteString(`</div>
  <div class="card"><h2>🏗️ Venture Architect</h2>`)
	sb.WriteString(ventureHTML)
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
  <div class="card"><h2>🪪 Registration</h2>`)
	sb.WriteString(registrationHTML)
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

func buildDepositPanelHTML(title, action, address string) string {
	if strings.TrimSpace(address) == "" {
		return ""
	}

	qrSrc := buildQRCodeDataURI(address)
	if qrSrc == "" {
		return ""
	}

	return fmt.Sprintf(`
  <div class="deposit-panel">
    <div class="deposit-kicker">%s</div>
    <div class="deposit-title">%s</div>
    <div class="qr-shell"><img src="%s" alt="%s QR code"></div>
    <div class="deposit-address">%s</div>
  </div>`, htmlEscape(action), htmlEscape(title), qrSrc, htmlEscape(title), htmlEscape(address))
}

func buildQRCodeDataURI(payload string) string {
	png, err := qrcode.Encode(payload, qrcode.Medium, 192)
	if err != nil {
		return ""
	}
	return "data:image/png;base64," + base64.StdEncoding.EncodeToString(png)
}

func buildAutonomyChipList(items []string, empty string) string {
	if len(items) == 0 {
		return `<div class="tool-list">` + htmlEscape(empty) + `</div>`
	}

	parts := make([]string, 0, len(items))
	for _, item := range items {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		parts = append(parts, `<span class="chip">`+htmlEscape(item)+`</span>`)
	}
	if len(parts) == 0 {
		return `<div class="tool-list">` + htmlEscape(empty) + `</div>`
	}
	return `<div class="chip-list">` + strings.Join(parts, "") + `</div>`
}

func buildAgentIdentityHeroHTML(agentID string, identity runtimeinfo.AgentIdentityStatus) string {
	if strings.TrimSpace(identity.Fingerprint) == "" {
		return ""
	}

	signature := identity.Signature
	if strings.TrimSpace(signature) == "" {
		signature = "HELIX-UNSET"
	}
	traits := buildAutonomyChipList(identity.Traits, "No identity traits yet")
	palette := buildPaletteRowHTML(identity.Palette)
	return fmt.Sprintf(`
<div class="identity-hero">
  <div class="dna-stage">%s</div>
  <div class="identity-meta">
    <div class="identity-kicker">Agent DNA Signature</div>
    <div class="identity-signature">%s</div>
    <div class="identity-fingerprint">%s</div>
    <div class="identity-caption">Deterministic helix seeded from the agent identity and wallet graph. It stays stable for this agent and visually distinguishes it from other living agents.</div>
    %s
    %s
    <div class="tool-list">Agent: %s</div>
  </div>
</div>`,
		buildDNAAvatarSVG(identity),
		htmlEscape(signature),
		htmlEscape(identity.Fingerprint),
		palette,
		traits,
		htmlEscape(agentID),
	)
}

func buildPaletteRowHTML(colors []string) string {
	if len(colors) == 0 {
		return ""
	}
	parts := make([]string, 0, len(colors))
	for _, color := range colors {
		color = strings.TrimSpace(color)
		if color == "" {
			continue
		}
		parts = append(parts, `<span class="swatch" style="background:`+htmlEscape(color)+`"></span>`)
	}
	if len(parts) == 0 {
		return ""
	}
	return `<div class="palette-row">` + strings.Join(parts, "") + `</div>`
}

func buildDNAAvatarSVG(identity runtimeinfo.AgentIdentityStatus) string {
	palette := append([]string(nil), identity.Palette...)
	for len(palette) < 3 {
		palette = append(palette, []string{"#38bdf8", "#f97316", "#14b8a6"}[len(palette)])
	}

	seed := sha256.Sum256([]byte(identity.Fingerprint + "|" + identity.Signature))
	width := 360.0
	height := 250.0
	cx := width / 2
	topPad := 28.0
	usableHeight := height - (topPad * 2)
	amplitude := 42.0 + float64(seed[0]%44)
	turns := 1.85 + float64(seed[1]%5)*0.22
	phase := float64(seed[2]) / 255 * math.Pi * 2
	rungs := 18 + int(seed[3]%8)

	backNodes := make([]dashboardDNANode, 0, rungs)
	frontNodes := make([]dashboardDNANode, 0, rungs)
	rungsHTML := make([]string, 0, rungs)

	for i := 0; i < rungs; i++ {
		t := float64(i) / float64(maxInt(rungs-1, 1))
		y := topPad + (usableHeight * t)
		angle := phase + t*(2*math.Pi*turns)
		offset := amplitude * math.Sin(angle)
		zLeft := math.Cos(angle)
		zRight := -zLeft
		leftX := cx - offset
		rightX := cx + offset

		rungOpacity := 0.18 + (math.Abs(zLeft) * 0.28)
		rungWidth := 1.2 + (math.Abs(zLeft) * 1.8)
		rungsHTML = append(rungsHTML, fmt.Sprintf(
			`<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-opacity="%.3f" stroke-width="%.2f" stroke-linecap="round"/>`,
			leftX, y, rightX, y, palette[2], rungOpacity, rungWidth,
		))

		leftNode := dashboardDNANode{
			x:      leftX,
			y:      y,
			radius: 4.0 + ((zLeft + 1) / 2 * 4.6),
			fill:   palette[0],
			glow:   palette[1],
			front:  zLeft >= 0,
			alpha:  0.35 + ((zLeft + 1) / 2 * 0.5),
		}
		rightNode := dashboardDNANode{
			x:      rightX,
			y:      y,
			radius: 4.0 + ((zRight + 1) / 2 * 4.6),
			fill:   palette[1],
			glow:   palette[0],
			front:  zRight >= 0,
			alpha:  0.35 + ((zRight + 1) / 2 * 0.5),
		}
		if leftNode.front {
			frontNodes = append(frontNodes, leftNode)
			backNodes = append(backNodes, rightNode)
		} else {
			backNodes = append(backNodes, leftNode)
			frontNodes = append(frontNodes, rightNode)
		}
	}

	var sb strings.Builder
	sb.WriteString(fmt.Sprintf(`<svg viewBox="0 0 %.0f %.0f" role="img" aria-label="Agent DNA fingerprint">`, width, height))
	sb.WriteString(`<defs>
  <linearGradient id="dna-bg" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#020617"/>
    <stop offset="100%" stop-color="#111827"/>
  </linearGradient>
  <radialGradient id="dna-glow" cx="50%" cy="45%" r="70%">
    <stop offset="0%" stop-color="` + htmlEscape(palette[0]) + `" stop-opacity=".24"/>
    <stop offset="65%" stop-color="` + htmlEscape(palette[1]) + `" stop-opacity=".08"/>
    <stop offset="100%" stop-color="#020617" stop-opacity="0"/>
  </radialGradient>
  <filter id="dna-soft-glow" x="-40%" y="-40%" width="180%" height="180%">
    <feGaussianBlur stdDeviation="6" result="blur"/>
    <feMerge>
      <feMergeNode in="blur"/>
      <feMergeNode in="SourceGraphic"/>
    </feMerge>
  </filter>
</defs>`)
	sb.WriteString(fmt.Sprintf(`<rect x="0" y="0" width="%.0f" height="%.0f" rx="22" fill="url(#dna-bg)"/>`, width, height))
	sb.WriteString(fmt.Sprintf(`<rect x="0" y="0" width="%.0f" height="%.0f" rx="22" fill="url(#dna-glow)"/>`, width, height))

	for i := 0; i < 6; i++ {
		x := 28.0 + float64(i)*60.0
		sb.WriteString(fmt.Sprintf(`<path d="M %.2f 20 C %.2f 90 %.2f 160 %.2f 230" fill="none" stroke="%s" stroke-opacity=".08" stroke-width="1"/>`,
			x, x+16, x-12, x+8, palette[2]))
	}

	for _, rung := range rungsHTML {
		sb.WriteString(rung)
	}
	writeDNANodes(&sb, backNodes)
	writeDNANodes(&sb, frontNodes)

	sb.WriteString(fmt.Sprintf(`<text x="22" y="224" fill="#e2e8f0" font-size="14" font-family="'IBM Plex Mono','SFMono-Regular',ui-monospace,monospace">%s</text>`,
		htmlEscape(identity.Signature)))
	sb.WriteString(fmt.Sprintf(`<text x="22" y="240" fill="#7dd3fc" font-size="11" letter-spacing="1.6" font-family="'IBM Plex Mono','SFMono-Regular',ui-monospace,monospace">%s</text>`,
		htmlEscape(identity.Fingerprint)))
	sb.WriteString(`</svg>`)
	return sb.String()
}

func writeDNANodes(sb *strings.Builder, nodes []dashboardDNANode) {
	for _, node := range nodes {
		sb.WriteString(fmt.Sprintf(
			`<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s" fill-opacity="%.3f" filter="url(#dna-soft-glow)"/>`,
			node.x, node.y, node.radius+1.6, node.glow, node.alpha*0.22,
		))
		sb.WriteString(fmt.Sprintf(
			`<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s" fill-opacity="%.3f" stroke="#f8fafc" stroke-opacity=".22" stroke-width=".35"/>`,
			node.x, node.y, node.radius, node.fill, node.alpha,
		))
	}
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func buildAutonomyHealthHTML(signals []runtimeinfo.RouteHealthSignal) string {
	if len(signals) == 0 {
		return `<p><em>no health signals</em></p>`
	}

	items := make([]string, 0, len(signals))
	for _, signal := range signals {
		items = append(items, fmt.Sprintf(`
<div class="health-item">
  <div class="health-top">
    <span class="health-name">%s</span>
    %s
  </div>
  <div class="health-detail">%s</div>
</div>`, htmlEscape(signal.Name), buildStateBadge(signal.State), htmlEscape(signal.Detail)))
	}
	return `<div class="health-grid">` + strings.Join(items, "") + `</div>`
}

func buildAutonomyRouteHTML(routes []runtimeinfo.RouteCandidate) string {
	if len(routes) == 0 {
		return `<p><em>no route candidates</em></p>`
	}

	items := make([]string, 0, len(routes))
	for _, route := range routes {
		topline := route.Name
		if route.Selected {
			topline += " · selected"
		}
		body := ""
		if route.Summary != "" {
			body += `<div class="route-summary">` + htmlEscape(route.Summary) + `</div>`
		}
		if len(route.Steps) > 0 {
			body += `<div class="route-steps">Steps: ` + htmlEscape(strings.Join(route.Steps, " -> ")) + `</div>`
		}
		if len(route.Blockers) > 0 {
			body += `<div class="route-blockers">Blockers: ` + htmlEscape(strings.Join(route.Blockers, "; ")) + `</div>`
		}
		items = append(items, fmt.Sprintf(`
<div class="route-card">
  <div class="route-top">
    <span class="route-name">%s</span>
    %s
  </div>
  %s
</div>`, htmlEscape(topline), buildStateBadge(route.State), body))
	}
	return `<div class="route-stack">` + strings.Join(items, "") + `</div>`
}

func buildTradingCycleHTML(entries []TradeCycleEntry) string {
	if len(entries) == 0 {
		return `<div class="tool-list">no auto-trade journal yet</div>`
	}

	items := make([]string, 0, len(entries))
	for _, entry := range entries {
		title := strings.TrimSpace(entry.TokenSymbol)
		if title == "" {
			title = strings.TrimSpace(entry.Mode)
		}
		if title == "" {
			title = "cycle"
		}
		meta := []string{}
		if strings.TrimSpace(entry.ExecutedAction) != "" {
			meta = append(meta, entry.ExecutedAction)
		}
		if strings.TrimSpace(entry.Chain) != "" {
			meta = append(meta, entry.Chain)
		}
		if strings.TrimSpace(entry.Venue) != "" {
			meta = append(meta, entry.Venue)
		}
		if strings.TrimSpace(entry.Amount) != "" {
			meta = append(meta, "size "+entry.Amount)
		}
		body := ""
		if strings.TrimSpace(entry.Summary) != "" {
			body += `<div class="route-summary">` + htmlEscape(entry.Summary) + `</div>`
		}
		if strings.TrimSpace(entry.Outcome) != "" && strings.TrimSpace(entry.Outcome) != strings.TrimSpace(entry.Summary) {
			body += `<div class="route-steps">Outcome: ` + htmlEscape(entry.Outcome) + `</div>`
		}
		if len(entry.Reasons) > 0 {
			body += `<div class="route-blockers">Why: ` + htmlEscape(strings.Join(entry.Reasons, "; ")) + `</div>`
		}
		items = append(items, fmt.Sprintf(`
<div class="route-card">
  <div class="route-top">
    <span class="route-name">%s</span>
    %s
  </div>
  <div class="route-steps">%s</div>
  %s
</div>`,
			htmlEscape(title),
			buildStateBadge(entry.Status),
			htmlEscape(strings.Join(meta, " · ")),
			body,
		))
	}
	return `<div class="route-stack">` + strings.Join(items, "") + `</div>`
}

func buildMissedOpportunityHTML(entries []MissedOpportunityEntry) string {
	if len(entries) == 0 {
		return `<div class="tool-list">no viable missed opportunities recorded yet</div>`
	}

	items := make([]string, 0, len(entries))
	for _, entry := range entries {
		title := strings.TrimSpace(entry.TokenSymbol)
		if title == "" {
			title = strings.TrimSpace(entry.TokenAddress)
		}
		if title == "" {
			title = "signal"
		}
		meta := []string{}
		if strings.TrimSpace(entry.Chain) != "" {
			meta = append(meta, entry.Chain)
		}
		if entry.Score != 0 {
			meta = append(meta, fmt.Sprintf("score %.1f", entry.Score))
		}
		if entry.Change24H != 0 {
			meta = append(meta, fmt.Sprintf("24h %+.1f%%", entry.Change24H))
		}
		if entry.LiquidityUSD > 0 {
			meta = append(meta, fmt.Sprintf("liq $%.0fk", entry.LiquidityUSD/1000))
		}
		if entry.Volume24H > 0 {
			meta = append(meta, fmt.Sprintf("vol $%.0fk", entry.Volume24H/1000))
		}
		body := ""
		if strings.TrimSpace(entry.Reason) != "" {
			body += `<div class="route-summary">` + htmlEscape(entry.Reason) + `</div>`
		}
		if entry.PriceUSD > 0 || strings.TrimSpace(entry.TokenAddress) != "" {
			detail := []string{}
			if entry.PriceUSD > 0 {
				detail = append(detail, fmt.Sprintf("price $%.6g", entry.PriceUSD))
			}
			if strings.TrimSpace(entry.TokenAddress) != "" {
				detail = append(detail, entry.TokenAddress)
			}
			body += `<div class="route-steps">` + htmlEscape(strings.Join(detail, " · ")) + `</div>`
		}
		items = append(items, fmt.Sprintf(`
<div class="route-card">
  <div class="route-top">
    <span class="route-name">%s</span>
    %s
  </div>
  <div class="route-steps">%s</div>
  %s
</div>`,
			htmlEscape(title),
			buildStateBadge("missed"),
			htmlEscape(strings.Join(meta, " · ")),
			body,
		))
	}
	return `<div class="route-stack">` + strings.Join(items, "") + `</div>`
}

func buildFundingInstructionHTML(entries []runtimeinfo.FundingInstruction) string {
	if len(entries) == 0 {
		return `<div class="tool-list">deposit ETH into the managed EVM wallet for EVM spot, bridging, and HyperLiquid. deposit SOL into the managed Solana wallet for Solana spot routing.</div>`
	}

	items := make([]string, 0, len(entries))
	for _, entry := range entries {
		title := strings.TrimSpace(entry.Label)
		if title == "" {
			title = "Deposit"
		}
		meta := []string{}
		if strings.TrimSpace(entry.Asset) != "" {
			meta = append(meta, entry.Asset)
		}
		if strings.TrimSpace(entry.Network) != "" {
			meta = append(meta, entry.Network)
		}
		body := ""
		if strings.TrimSpace(entry.Purpose) != "" {
			body += `<div class="route-summary">` + htmlEscape(entry.Purpose) + `</div>`
		}
		if strings.TrimSpace(entry.Address) != "" {
			body += `<div class="route-steps">` + htmlEscape(entry.Address) + `</div>`
		}
		items = append(items, fmt.Sprintf(`
<div class="route-card">
  <div class="route-top">
    <span class="route-name">%s</span>
    %s
  </div>
  <div class="route-steps">%s</div>
  %s
</div>`,
			htmlEscape(title),
			buildStateBadge("ready"),
			htmlEscape(strings.Join(meta, " · ")),
			body,
		))
	}
	return `<div class="route-stack">` + strings.Join(items, "") + `</div>`
}

func buildCapitalMobilityHTML(mobility *runtimeinfo.CapitalMobilityStatus) string {
	if mobility == nil {
		return `<div class="tool-list">capital router status is not available yet</div>`
	}

	chips := []string{}
	if mobility.CanSpotTrade {
		chips = append(chips, "spot ready")
	}
	if mobility.CanBridge {
		chips = append(chips, "native bridge ready")
	}
	if mobility.CanHyperLiquidFund {
		chips = append(chips, "HyperLiquid funding ready")
	}
	if mobility.CanHyperLiquidTrade {
		chips = append(chips, "HyperLiquid trade ready")
	}
	if mobility.NativeBridgeOnly {
		chips = append(chips, "native-asset bridge only")
	}
	body := ""
	if strings.TrimSpace(mobility.Summary) != "" {
		body += `<div class="route-summary">` + htmlEscape(mobility.Summary) + `</div>`
	}
	if len(chips) > 0 {
		body += `<div class="route-steps">` + htmlEscape(strings.Join(chips, " · ")) + `</div>`
	}
	if len(mobility.Guidance) > 0 {
		body += `<div class="route-blockers">` + htmlEscape(strings.Join(mobility.Guidance, " ")) + `</div>`
	}
	return fmt.Sprintf(`
<div class="route-card">
  <div class="route-top">
    <span class="route-name">Capital Router</span>
    %s
  </div>
  %s
</div>`, buildStateBadge(mobility.State), body)
}

func buildTelepathyMessagesHTML(entries []TelepathyEntry, total int) string {
	if len(entries) == 0 {
		if total == 0 {
			return `<div class="tool-list">no telepathy chatter yet</div>`
		}
		return `<div class="tool-list">telepathy history exists, but no recent messages are loaded</div>`
	}

	items := make([]string, 0, len(entries))
	for i := len(entries) - 1; i >= 0; i-- {
		entry := entries[i]
		target := "family"
		if strings.TrimSpace(entry.To) != "" && entry.To != "*" {
			target = entry.To
		}
		content := strings.TrimSpace(entry.Content)
		if content == "" {
			content = "(empty message)"
		}
		meta := []string{
			"to " + target,
			formatAgo(entry.Timestamp),
			"priority " + telepathyPriorityLabel(entry.Priority),
		}
		items = append(items, fmt.Sprintf(`
<div class="telepathy-card">
  <div class="telepathy-top">
    <span class="telepathy-title">%s from %s</span>
    %s
  </div>
  <div class="telepathy-meta">%s</div>
  <div class="telepathy-body">%s</div>
</div>`,
			htmlEscape(entry.Type),
			htmlEscape(entry.From),
			buildStateBadge(entry.Type),
			htmlEscape(strings.Join(meta, " · ")),
			htmlEscape(content),
		))
	}

	caption := fmt.Sprintf("showing %d recent message", len(entries))
	if len(entries) != 1 {
		caption += "s"
	}
	if total > len(entries) {
		caption += fmt.Sprintf(" of %d total", total)
	}

	return `<div class="tool-list">` + htmlEscape(caption) + `</div><div class="telepathy-stream">` + strings.Join(items, "") + `</div>`
}

func telepathyPriorityLabel(priority int) string {
	switch priority {
	case 2:
		return "urgent"
	case 1:
		return "normal"
	default:
		return "low"
	}
}

func firstNonEmptyString(values ...string) string {
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" {
			return value
		}
	}
	return ""
}

func formatRPCSource(source string) string {
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

func buildStateBadge(state string) string {
	state = strings.TrimSpace(strings.ToLower(state))
	if state == "" {
		state = "unknown"
	}
	className := "state-provisional"
	switch state {
	case "ready":
		className = "state-ready"
	case "self-healing":
		className = "state-self-healing"
	case "blocked":
		className = "state-blocked"
	case "degraded":
		className = "state-degraded"
	case "provisional":
		className = "state-provisional"
	}
	return `<span class="badge ` + className + `">` + htmlEscape(state) + `</span>`
}
