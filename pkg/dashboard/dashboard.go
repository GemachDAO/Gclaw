// Gclaw - Ultra-lightweight personal AI agent
// Inspired by and based on nanobot: https://github.com/HKUDS/nanobot
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package dashboard

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

// DashboardData is the complete snapshot of the agent's life-state.
type DashboardData struct {
	AgentID       string                          `json:"agent_id"`
	Generation    int                             `json:"generation"`
	Uptime        string                          `json:"uptime"`
	StartedAt     int64                           `json:"started_at"`
	Metabolism    *MetabolismSnapshot             `json:"metabolism,omitempty"`
	Trading       *TradingSnapshot                `json:"trading,omitempty"`
	TradingAccess *runtimeinfo.TradingStatus      `json:"trading_access,omitempty"`
	Autonomy      *runtimeinfo.AutonomyStatus     `json:"autonomy,omitempty"`
	Family        *FamilySnapshot                 `json:"family,omitempty"`
	Telepathy     *TelepathySnapshot              `json:"telepathy,omitempty"`
	Swarm         *SwarmSnapshot                  `json:"swarm,omitempty"`
	RecodeHistory []RecodeEntry                   `json:"recode_history,omitempty"`
	Registration  *runtimeinfo.RegistrationStatus `json:"registration,omitempty"`
	System        *SystemSnapshot                 `json:"system,omitempty"`
}

// MetabolismSnapshot captures the current metabolism state.
type MetabolismSnapshot struct {
	Balance      float64       `json:"balance"`
	Goodwill     int           `json:"goodwill"`
	SurvivalMode bool          `json:"survival_mode"`
	Abilities    []string      `json:"abilities"`
	RecentLedger []LedgerEntry `json:"recent_ledger"`
}

// LedgerEntry is a single metabolism ledger record.
type LedgerEntry struct {
	Timestamp int64   `json:"timestamp"`
	Action    string  `json:"action"`
	Amount    float64 `json:"amount"`
	Balance   float64 `json:"balance"`
	Details   string  `json:"details"`
}

// TradingSnapshot captures recent trading activity.
type TradingSnapshot struct {
	TotalTrades     int          `json:"total_trades"`
	RealizedTrades  int          `json:"realized_trades"`
	HasRealizedPnL  bool         `json:"has_realized_pnl"`
	ProfitablePct   float64      `json:"profitable_pct"`
	TotalPnL        float64      `json:"total_pnl"`
	ActivePositions int          `json:"active_positions"`
	RecentTrades    []TradeEntry `json:"recent_trades"`
}

// TradeEntry records a single trade event.
type TradeEntry struct {
	Timestamp    int64   `json:"timestamp"`
	Action       string  `json:"action"`
	TokenAddress string  `json:"token_address"`
	Amount       string  `json:"amount"`
	PnL          float64 `json:"pnl,omitempty"`
	HasPnL       bool    `json:"has_pnl,omitempty"`
	ChainID      int     `json:"chain_id"`
}

// FamilySnapshot captures the agent family tree.
type FamilySnapshot struct {
	ParentID    string      `json:"parent_id,omitempty"`
	Children    []ChildInfo `json:"children"`
	TotalFamily int         `json:"total_family"`
}

// ChildInfo describes a single child agent.
type ChildInfo struct {
	ID              string   `json:"id"`
	Label           string   `json:"label,omitempty"`
	Generation      int      `json:"generation"`
	Status          string   `json:"status"`
	GMAC            float64  `json:"gmac"`
	Goodwill        int      `json:"goodwill"`
	Mutations       []string `json:"mutations"`
	Style           string   `json:"style,omitempty"`
	Role            string   `json:"role,omitempty"`
	RiskProfile     string   `json:"risk_profile,omitempty"`
	PreferredChains []string `json:"preferred_chains,omitempty"`
	PreferredVenues []string `json:"preferred_venues,omitempty"`
	StrategyHint    string   `json:"strategy_hint,omitempty"`
	CreatedAt       int64    `json:"created_at"`
}

// TelepathySnapshot captures inter-agent message activity.
type TelepathySnapshot struct {
	TotalMessages  int              `json:"total_messages"`
	RecentMessages []TelepathyEntry `json:"recent_messages"`
	ActiveChannels int              `json:"active_channels"`
	Persistent     bool             `json:"persistent"`
}

// TelepathyEntry is a single inter-agent message.
type TelepathyEntry struct {
	From      string `json:"from"`
	To        string `json:"to"`
	Type      string `json:"type"`
	Content   string `json:"content"`
	Timestamp int64  `json:"timestamp"`
	Priority  int    `json:"priority"`
}

// SwarmSnapshot captures the current swarm state.
type SwarmSnapshot struct {
	IsLeader         bool                `json:"is_leader"`
	MemberCount      int                 `json:"member_count"`
	Members          []SwarmMemberInfo   `json:"members"`
	ActiveSignals    int                 `json:"active_signals"`
	ConsensusMode    string              `json:"consensus_mode"`
	LastConsensus    *SwarmConsensusInfo `json:"last_consensus,omitempty"`
	LastDecision     *SwarmDecisionInfo  `json:"last_decision,omitempty"`
	LastRebalancedAt int64               `json:"last_rebalanced_at,omitempty"`
}

// SwarmMemberInfo describes a single swarm member.
type SwarmMemberInfo struct {
	AgentID     string  `json:"agent_id"`
	Role        string  `json:"role"`
	Strategy    string  `json:"strategy"`
	Performance float64 `json:"performance"`
	Status      string  `json:"status"`
}

// SwarmConsensusInfo is the last vote outcome observed by the runtime.
type SwarmConsensusInfo struct {
	Action       string  `json:"action"`
	TokenAddress string  `json:"token_address"`
	ChainID      int     `json:"chain_id"`
	Confidence   float64 `json:"confidence"`
	Approved     bool    `json:"approved"`
}

// SwarmDecisionInfo is the last pending/executed decision assigned by the swarm.
type SwarmDecisionInfo struct {
	Action       string `json:"action"`
	TokenAddress string `json:"token_address"`
	ChainID      int    `json:"chain_id"`
	ExecutorID   string `json:"executor_id,omitempty"`
	Strategy     string `json:"strategy,omitempty"`
	Status       string `json:"status,omitempty"`
	Summary      string `json:"summary,omitempty"`
}

// RecodeEntry records a single self-modification action.
type RecodeEntry struct {
	Timestamp int64  `json:"timestamp"`
	Type      string `json:"type"`
	Details   string `json:"details"`
	Approved  bool   `json:"approved"`
}

// SystemSnapshot captures runtime system information.
type SystemSnapshot struct {
	HeartbeatActive   bool   `json:"heartbeat_active"`
	HeartbeatInterval int    `json:"heartbeat_interval_min"`
	ToolCount         int    `json:"tool_count"`
	SkillCount        int    `json:"skill_count"`
	ChannelCount      int    `json:"channel_count"`
	Platform          string `json:"platform"`
	GoVersion         string `json:"go_version"`
}

// DashboardOptions configures optional data sources for the dashboard.
// Each field is a callback so the dashboard package stays free of heavy imports.
type DashboardOptions struct {
	AgentID          string
	StartedAt        int64
	GetMetabolism    func() *MetabolismSnapshot
	GetTradingAccess func() *runtimeinfo.TradingStatus
	GetAutonomy      func() *runtimeinfo.AutonomyStatus
	GetFamily        func() *FamilySnapshot
	GetTelepathy     func() *TelepathySnapshot
	GetSwarm         func() *SwarmSnapshot
	GetRecodeHistory func() []RecodeEntry
	GetRegistration  func() *runtimeinfo.RegistrationStatus
	GetSystem        func() *SystemSnapshot
	GetTrading       func() *TradingSnapshot
}

// Dashboard aggregates the agent's current life-state on demand.
type Dashboard struct {
	opts DashboardOptions
}

// NewDashboard creates a Dashboard with the given options.
func NewDashboard(opts DashboardOptions) *Dashboard {
	return &Dashboard{opts: opts}
}

// GetData aggregates current state from all configured sources.
func (d *Dashboard) GetData() *DashboardData {
	now := time.Now().UnixMilli()
	startedAt := d.opts.StartedAt
	if startedAt == 0 {
		startedAt = now
	}

	data := &DashboardData{
		AgentID:   d.opts.AgentID,
		StartedAt: startedAt,
		Uptime:    formatUptime(now - startedAt),
	}

	if d.opts.GetMetabolism != nil {
		if snap := d.opts.GetMetabolism(); snap != nil {
			data.Metabolism = snap
		}
	}

	if d.opts.GetFamily != nil {
		if snap := d.opts.GetFamily(); snap != nil {
			data.Family = snap
		}
	}

	if d.opts.GetTradingAccess != nil {
		if snap := d.opts.GetTradingAccess(); snap != nil {
			data.TradingAccess = snap
		}
	}

	if d.opts.GetAutonomy != nil {
		if snap := d.opts.GetAutonomy(); snap != nil {
			data.Autonomy = snap
		}
	}

	if d.opts.GetTelepathy != nil {
		if snap := d.opts.GetTelepathy(); snap != nil {
			data.Telepathy = snap
		}
	}

	if d.opts.GetSwarm != nil {
		if snap := d.opts.GetSwarm(); snap != nil {
			data.Swarm = snap
		}
	}

	if d.opts.GetRecodeHistory != nil {
		data.RecodeHistory = d.opts.GetRecodeHistory()
	}

	if d.opts.GetSystem != nil {
		if snap := d.opts.GetSystem(); snap != nil {
			data.System = snap
		}
	}

	if d.opts.GetRegistration != nil {
		if snap := d.opts.GetRegistration(); snap != nil {
			data.Registration = snap
		}
	}

	if d.opts.GetTrading != nil {
		if snap := d.opts.GetTrading(); snap != nil {
			data.Trading = snap
		}
	}

	return data
}

// GetJSON returns the current dashboard data as formatted JSON.
func (d *Dashboard) GetJSON() ([]byte, error) {
	data := d.GetData()
	return json.MarshalIndent(data, "", "  ")
}

// formatUptime converts a millisecond duration into a human-readable string.
func formatUptime(ms int64) string {
	if ms <= 0 {
		return "0s"
	}
	total := ms / 1000
	h := total / 3600
	m := (total % 3600) / 60
	s := total % 60
	if h > 0 {
		return fmt.Sprintf("%dh %dm", h, m)
	}
	if m > 0 {
		return fmt.Sprintf("%dm %ds", m, s)
	}
	return fmt.Sprintf("%ds", s)
}
