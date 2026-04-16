// Gclaw - Ultra-lightweight personal AI agent
// Inspired by and based on nanobot: https://github.com/HKUDS/nanobot
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode/utf8"

	"github.com/GemachDAO/Gclaw/pkg/bus"
	"github.com/GemachDAO/Gclaw/pkg/channels"
	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/constants"
	"github.com/GemachDAO/Gclaw/pkg/dashboard"
	"github.com/GemachDAO/Gclaw/pkg/logger"
	"github.com/GemachDAO/Gclaw/pkg/metabolism"
	"github.com/GemachDAO/Gclaw/pkg/providers"
	"github.com/GemachDAO/Gclaw/pkg/recode"
	"github.com/GemachDAO/Gclaw/pkg/replication"
	"github.com/GemachDAO/Gclaw/pkg/routing"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
	"github.com/GemachDAO/Gclaw/pkg/skills"
	"github.com/GemachDAO/Gclaw/pkg/state"
	"github.com/GemachDAO/Gclaw/pkg/swarm"
	"github.com/GemachDAO/Gclaw/pkg/tempo"
	"github.com/GemachDAO/Gclaw/pkg/tools"
	"github.com/GemachDAO/Gclaw/pkg/utils"
	"github.com/GemachDAO/Gclaw/pkg/venture"
	"github.com/GemachDAO/Gclaw/pkg/x402"
)

type AgentLoop struct {
	bus            *bus.MessageBus
	cfg            *config.Config
	registry       *AgentRegistry
	state          *state.Manager
	running        atomic.Bool
	summarizing    sync.Map
	fallback       *providers.FallbackChain
	channelManager *channels.Manager
	dash           *dashboard.Dashboard
}

// processOptions configures how a message is processed
type processOptions struct {
	SessionKey      string // Session identifier for history/context
	Channel         string // Target channel for tool execution
	ChatID          string // Target chat ID for tool execution
	UserMessage     string // User message content (may include prefix)
	DefaultResponse string // Response when LLM returns empty
	EnableSummary   bool   // Whether to trigger summarization
	SendResponse    bool   // Whether to send response via bus
	NoHistory       bool   // If true, don't load session history (for heartbeat)
}

func NewAgentLoop(cfg *config.Config, msgBus *bus.MessageBus, provider providers.LLMProvider) *AgentLoop {
	registry := NewAgentRegistry(cfg, provider)

	// Register shared tools to all agents
	dash := registerSharedTools(cfg, msgBus, registry, provider)

	// Set up shared fallback chain
	cooldown := providers.NewCooldownTracker()
	fallbackChain := providers.NewFallbackChain(cooldown)

	// Create state manager using default agent's workspace for channel recording
	defaultAgent := registry.GetDefaultAgent()
	var stateManager *state.Manager
	if defaultAgent != nil {
		stateManager = state.NewManager(defaultAgent.Workspace)
	}

	return &AgentLoop{
		bus:         msgBus,
		cfg:         cfg,
		registry:    registry,
		state:       stateManager,
		summarizing: sync.Map{},
		fallback:    fallbackChain,
		dash:        dash,
	}
}

// registerSharedTools registers tools that are shared across all agents (web, message, spawn).
// It returns the first-created Dashboard (if any) so the caller can wire it to
// the HTTP server.
func registerSharedTools(
	cfg *config.Config,
	msgBus *bus.MessageBus,
	registry *AgentRegistry,
	provider providers.LLMProvider,
) *dashboard.Dashboard {
	var firstDash *dashboard.Dashboard
	telepathyBuses := make(map[string]*replication.TelepathyBus)
	for _, agentID := range registry.ListAgentIDs() {
		agent, ok := registry.GetAgent(agentID)
		if !ok {
			continue
		}
		toolRegistry := agent.Tools
		contextBuilder := agent.ContextBuilder
		histPath := filepath.Join(agent.Workspace, "runtime", "trade_history.json")
		if err := toolRegistry.SetTradeHistoryPersistence(histPath); err != nil {
			logger.WarnCF("agent", "Failed to load persisted trade history",
				map[string]any{"agent": agentID, "error": err.Error()})
		}

		var rep *replication.Replicator
		var telepathyBus *replication.TelepathyBus
		var recoderSvc *recode.Recoder
		var swarmCoordinator *swarm.SwarmCoordinator
		var ventureManager *venture.Manager

		// Web tools
		if searchTool := tools.NewWebSearchTool(tools.WebSearchToolOptions{
			BraveAPIKey:          cfg.Tools.Web.Brave.APIKey,
			BraveMaxResults:      cfg.Tools.Web.Brave.MaxResults,
			BraveEnabled:         cfg.Tools.Web.Brave.Enabled,
			TavilyAPIKey:         cfg.Tools.Web.Tavily.APIKey,
			TavilyBaseURL:        cfg.Tools.Web.Tavily.BaseURL,
			TavilyMaxResults:     cfg.Tools.Web.Tavily.MaxResults,
			TavilyEnabled:        cfg.Tools.Web.Tavily.Enabled,
			DuckDuckGoMaxResults: cfg.Tools.Web.DuckDuckGo.MaxResults,
			DuckDuckGoEnabled:    cfg.Tools.Web.DuckDuckGo.Enabled,
			PerplexityAPIKey:     cfg.Tools.Web.Perplexity.APIKey,
			PerplexityMaxResults: cfg.Tools.Web.Perplexity.MaxResults,
			PerplexityEnabled:    cfg.Tools.Web.Perplexity.Enabled,
			Proxy:                cfg.Tools.Web.Proxy,
		}); searchTool != nil {
			agent.Tools.Register(searchTool)
		}
		agent.Tools.Register(tools.NewWebFetchToolWithProxy(50000, cfg.Tools.Web.Proxy))

		// Hardware tools (I2C, SPI) - Linux only, returns error on other platforms
		agent.Tools.Register(tools.NewI2CTool())
		agent.Tools.Register(tools.NewSPITool())

		// Message tool
		messageTool := tools.NewMessageTool()
		messageTool.SetSendCallback(func(channel, chatID, content string) error {
			msgBus.PublishOutbound(bus.OutboundMessage{
				Channel: channel,
				ChatID:  chatID,
				Content: content,
			})
			return nil
		})
		agent.Tools.Register(messageTool)

		// Skill discovery and installation tools
		registryMgr := skills.NewRegistryManagerFromConfig(skills.RegistryConfig{
			MaxConcurrentSearches: cfg.Tools.Skills.MaxConcurrentSearches,
			ClawHub:               skills.ClawHubConfig(cfg.Tools.Skills.Registries.ClawHub),
		})
		searchCache := skills.NewSearchCache(
			cfg.Tools.Skills.SearchCache.MaxSize,
			time.Duration(cfg.Tools.Skills.SearchCache.TTLSeconds)*time.Second,
		)
		agent.Tools.Register(tools.NewFindSkillsTool(registryMgr, searchCache))
		agent.Tools.Register(tools.NewInstallSkillTool(registryMgr, agent.Workspace))

		// GDEX trading tools — registered when GDEX is configured
		if cfg.Tools.GDEX.Enabled || cfg.Tools.GDEX.APIKey != "" {
			agent.Tools.Register(&tools.GDEXBuyTool{})
			agent.Tools.Register(&tools.GDEXSellTool{})
			agent.Tools.Register(&tools.GDEXLimitBuyTool{})
			agent.Tools.Register(&tools.GDEXLimitSellTool{})
			agent.Tools.Register(&tools.GDEXTrendingTool{})
			agent.Tools.Register(&tools.GDEXSearchTool{})
			agent.Tools.Register(&tools.GDEXPriceTool{})
			agent.Tools.Register(&tools.GDEXHoldingsTool{})
			agent.Tools.Register(&tools.GDEXScanTool{})
			agent.Tools.Register(&tools.GDEXCopyTradeTool{})
			agent.Tools.Register(&tools.GDEXBridgeEstimateTool{})
			agent.Tools.Register(&tools.GDEXBridgeRequestTool{})
			agent.Tools.Register(&tools.GDEXBridgeOrdersTool{})
			agent.Tools.Register(&tools.GDEXHLBalanceTool{})
			agent.Tools.Register(&tools.GDEXHLPositionsTool{})
			agent.Tools.Register(&tools.GDEXHLDepositTool{})
			agent.Tools.Register(&tools.GDEXHLWithdrawTool{})
			agent.Tools.Register(&tools.GDEXHLCreateOrderTool{})
			agent.Tools.Register(&tools.GDEXHLCancelOrderTool{})
		}

		// x402 payment tool — registered when x402 is configured
		if cfg.Tools.X402.Enabled {
			walletAddr := ""
			privKey := ""
			// Reuse GDEX wallet credentials for x402 payments when available.
			if cfg.Tools.GDEX.WalletAddress != "" {
				walletAddr = cfg.Tools.GDEX.WalletAddress
			}
			if cfg.Tools.GDEX.PrivateKey != "" {
				privKey = cfg.Tools.GDEX.PrivateKey
			}
			network := cfg.Tools.X402.Network
			if network == "" {
				network = "base"
			}
			// Validate wallet credentials before creating the x402 client to avoid
			// late runtime signing failures when credentials are missing.
			if walletAddr == "" || privKey == "" {
				logger.WarnCF("agent",
					"x402 enabled but wallet credentials missing; skipping",
					map[string]any{"agent": agentID})
			} else {
				x402Client, err := x402.NewClient(x402.ClientConfig{
					WalletAddress:    walletAddr,
					PrivateKey:       privKey,
					Network:          network,
					FacilitatorURL:   cfg.Tools.X402.FacilitatorURL,
					MaxPaymentAmount: cfg.Tools.X402.MaxPaymentAmount,
					Proxy:            cfg.Tools.Web.Proxy,
				})
				if err == nil {
					agent.Tools.Register(tools.NewX402FetchTool(x402Client))
				} else {
					logger.WarnCF("agent", "Failed to create x402 client",
						map[string]any{"agent": agentID, "error": err.Error()})
				}
			}
		}

		// Tempo MPP payment tool — registered when Tempo is configured
		if cfg.Tools.Tempo.Enabled {
			walletAddr := ""
			privKey := ""
			// Reuse GDEX wallet credentials for Tempo payments when available.
			if cfg.Tools.GDEX.WalletAddress != "" {
				walletAddr = cfg.Tools.GDEX.WalletAddress
			}
			if cfg.Tools.GDEX.PrivateKey != "" {
				privKey = cfg.Tools.GDEX.PrivateKey
			}
			if walletAddr == "" || privKey == "" {
				logger.WarnCF("agent",
					"tempo enabled but wallet credentials missing; skipping",
					map[string]any{"agent": agentID})
			} else {
				tempoClient, err := tempo.NewClient(tempo.ClientConfig{
					WalletAddress:    walletAddr,
					PrivateKey:       privKey,
					RPCURL:           cfg.Tools.Tempo.RPCURL,
					MaxPaymentAmount: cfg.Tools.Tempo.MaxPaymentAmount,
					Proxy:            cfg.Tools.Web.Proxy,
				})
				if err == nil {
					agent.Tools.Register(tools.NewTempoPayTool(tempoClient))
				} else {
					logger.WarnCF("agent", "Failed to create tempo client",
						map[string]any{"agent": agentID, "error": err.Error()})
				}
			}
		}

		// Spawn tool with allowlist checker
		subagentManager := tools.NewSubagentManager(provider, agent.Model, agent.Workspace, msgBus)
		subagentManager.SetLLMOptions(agent.MaxTokens, agent.Temperature)
		spawnTool := tools.NewSpawnTool(subagentManager)
		currentAgentID := agentID
		spawnTool.SetAllowlistChecker(func(targetAgentID string) bool {
			return registry.CanSpawnSubagent(currentAgentID, targetAgentID)
		})
		agent.Tools.Register(spawnTool)

		// Metabolism gating — initialize if enabled
		if cfg.Metabolism.Enabled {
			met := loadOrCreateMetabolism(cfg, agent.Workspace)
			statePath := filepath.Join(agent.Workspace, "metabolism", "state.json")
			persistMetabolism := func() {
				if err := met.SaveToFile(statePath); err != nil {
					logger.WarnCF("agent", "Failed to persist metabolism state",
						map[string]any{"agent": agentID, "error": err.Error()})
				}
			}
			met.RegisterOnChange(persistMetabolism)
			persistMetabolism()
			agent.Tools.SetMetabolism(met)
			for name, cost := range tools.DefaultToolCosts {
				agent.Tools.SetToolCost(name, cost)
			}
			// Wire goodwill tracker so trade results feed back to metabolism
			gt := metabolism.NewGoodwillTracker(met)
			agent.Tools.SetGoodwillTracker(gt)

			logger.InfoCF("agent", "Metabolism initialized",
				map[string]any{
					"agent":   agentID,
					"balance": met.GetBalance(),
				})

			busKey := filepath.Clean(agent.Workspace)
			telepathyBus = telepathyBuses[busKey]
			if telepathyBus == nil {
				telepathyBus = replication.NewTelepathyBus(msgBus, busKey, agentID)
				persistDir := replication.TelepathyDir(agent.Workspace, busKey)
				if err := telepathyBus.EnableFilePersistence(persistDir); err != nil {
					logger.WarnCF("agent", "Failed to enable telepathy persistence",
						map[string]any{"agent": agentID, "error": err.Error()})
				}
				telepathyBuses[busKey] = telepathyBus
			}
			agent.TelepathyBus = telepathyBus
			agent.TelepathyInbox = telepathyBus.Subscribe(agentID)
			rep = replication.NewReplicator(agentID, replication.ReplicationConfig{
				Enabled:           true,
				MaxChildren:       cfg.Swarm.MaxSwarmSize,
				GMACSharePercent:  50,
				MutatePrompt:      true,
				InheritSkills:     true,
				InheritMemory:     true,
				ChildWorkspaceDir: filepath.Join(agent.Workspace, "children"),
			})
			if err := rep.LoadChildren(agent.Workspace); err != nil {
				logger.WarnCF("agent", "Failed to load child agents",
					map[string]any{"agent": agentID, "error": err.Error()})
			}
			agent.Replicator = rep

			replicateTool := tools.NewReplicateTool(
				rep,
				cfg,
				agent.Workspace,
				nil,
				met.GetGoodwill,
				cfg.Metabolism.Thresholds.Replicate,
			)
			replicateTool.SetParentBalanceHooks(
				met.GetBalance,
				func(amount float64) error {
					return met.Debit(amount, "replicate", fmt.Sprintf("replicated child agent from %s", agentID))
				},
			)
			agent.Tools.Register(replicateTool)
			agent.Tools.Register(tools.NewTelepathyTool(telepathyBus, agentID))

			recoderSvc = recode.NewRecoder(resolveAgentConfigPath(agent.Workspace), agent.Workspace)
			agent.Tools.Register(tools.NewRecodeTool(
				recoderSvc,
				met.GetGoodwill,
				cfg.Metabolism.Thresholds.SelfRecode,
			))
			ventureManager = venture.NewManager(agent.Workspace, recoderSvc)
			if ownerAddr, deployerKey := runtimeinfo.ResolveWalletCredentials(cfg); ownerAddr != "" &&
				deployerKey != "" {
				ventureManager.SetDeployer(venture.NewForgeDeployer(ownerAddr, deployerKey))
			}
			agent.VentureManager = ventureManager
			agent.Tools.Register(tools.NewVentureArchitectTool(
				ventureManager,
				met.GetGoodwill,
				cfg.Metabolism.Thresholds.Architect,
				func() venture.LaunchContext {
					trading := runtimeinfo.PopulateManagedWallets(
						cfg,
						runtimeinfo.BuildTradingStatus(cfg, toolRegistry.List()),
						5*time.Second,
					)
					totalFamily := 1
					if rep != nil {
						totalFamily += len(rep.ListChildren())
					}
					swarmSize := 0
					if swarmCoordinator != nil {
						swarmSize = len(swarmCoordinator.GetMembers())
					}
					autonomy := runtimeinfo.BuildAutonomyStatus(cfg, trading, totalFamily, swarmSize, agentID)
					return venture.LaunchContext{
						AgentID:      agentID,
						Goodwill:     met.GetGoodwill(),
						Balance:      met.GetBalance(),
						Threshold:    cfg.Metabolism.Thresholds.Architect,
						FamilySize:   totalFamily,
						SwarmMembers: swarmSize,
						Trading:      trading,
						Autonomy:     autonomy,
					}
				},
			))

			// Swarm tool — registered when swarm is enabled and metabolism is active
			if cfg.Swarm.Enabled {
				swarmConfig := swarm.SwarmConfig{
					Enabled:            cfg.Swarm.Enabled,
					MaxSwarmSize:       cfg.Swarm.MaxSwarmSize,
					ConsensusThreshold: cfg.Swarm.ConsensusThreshold,
					SignalAggregation:  cfg.Swarm.SignalAggregation,
					StrategyRotation:   cfg.Swarm.StrategyRotation,
					RebalanceInterval:  cfg.Swarm.RebalanceInterval,
					SharedWalletMode:   cfg.Swarm.SharedWalletMode,
				}
				coordinator, err := swarm.LoadSwarmState(agent.Workspace)
				if err != nil {
					logger.WarnCF("agent", "Failed to load swarm state, starting fresh",
						map[string]any{"agent": agentID, "error": err.Error()})
				}
				if err != nil || coordinator == nil {
					coordinator = swarm.NewSwarmCoordinator(agentID, swarmConfig, telepathyBus)
				} else {
					coordinator.SetTelepathyBus(telepathyBus)
				}
				if _, exists := coordinator.GetMember(agentID); !exists {
					if err := coordinator.AddMember(agentID, swarm.RoleLeader, "profit_to_gmach"); err != nil {
						logger.WarnCF("agent", "Failed to register leader in swarm",
							map[string]any{"agent": agentID, "error": err.Error()})
					}
				}
				swarmCoordinator = coordinator
				agent.Swarm = coordinator
				persistSwarmState := func() error {
					return swarm.SaveSwarmState(agent.Workspace, coordinator)
				}
				if err := persistSwarmState(); err != nil {
					logger.WarnCF("agent", "Failed to persist initial swarm state",
						map[string]any{"agent": agentID, "error": err.Error()})
				}
				swarmTool := tools.NewSwarmTool(
					coordinator,
					met.GetGoodwill,
					cfg.Metabolism.Thresholds.SwarmLeader,
				)
				swarmTool.SetRuntimeContext(agentID, persistSwarmState)
				agent.Tools.Register(swarmTool)
			}

			toolRegistry.AddTradeObserver(func(record tools.TradeRecord) {
				if telepathyBus != nil {
					action := normalizeTradeAction(record.Action)
					if action != "" && record.TokenAddress != "" {
						telepathyBus.BroadcastTradeSignalFrom(agentID, replication.TradeSignal{
							Action:       action,
							TokenAddress: record.TokenAddress,
							ChainID:      record.ChainID,
							Confidence:   tradeSignalConfidence(record),
							Reasoning: fmt.Sprintf(
								"executed %s via %s pnl=%.2f%%",
								record.Action,
								record.ToolName,
								record.PnL,
							),
						})
					}
				}
				if swarmCoordinator == nil {
					return
				}
				swarmCoordinator.UpdateMemberPerformance(agentID, record.PnL)
				action := normalizeTradeAction(record.Action)
				if action != "" && record.TokenAddress != "" {
					if err := swarmCoordinator.SubmitSignal(swarm.SwarmSignal{
						AgentID:      agentID,
						Action:       action,
						TokenAddress: record.TokenAddress,
						ChainID:      record.ChainID,
						Confidence:   tradeSignalConfidence(record),
						Reasoning:    fmt.Sprintf("executed %s via %s", record.Action, record.ToolName),
						Timestamp:    record.Timestamp,
					}); err != nil {
						logger.WarnCF("agent", "Failed to feed trade into swarm signals",
							map[string]any{"agent": agentID, "error": err.Error(), "tool": record.ToolName})
					}
				}
				if err := swarm.SaveSwarmState(agent.Workspace, swarmCoordinator); err != nil {
					logger.WarnCF("agent", "Failed to persist swarm after trade",
						map[string]any{"agent": agentID, "error": err.Error()})
				}
			})
		}

		// Dashboard tool — always registered when dashboard is enabled
		if cfg.Dashboard.Enabled {
			startedAt := time.Now().UnixMilli()
			currentAgentIDForDash := agentID
			dash := dashboard.NewDashboard(dashboard.DashboardOptions{
				AgentID:   currentAgentIDForDash,
				StartedAt: startedAt,
				GetTradingAccess: func() *runtimeinfo.TradingStatus {
					return runtimeinfo.PopulateManagedWallets(
						cfg,
						runtimeinfo.BuildTradingStatus(cfg, toolRegistry.List()),
						5*time.Second,
					)
				},
				GetAutonomy: func() *runtimeinfo.AutonomyStatus {
					trading := runtimeinfo.PopulateManagedWallets(
						cfg,
						runtimeinfo.BuildTradingStatus(cfg, toolRegistry.List()),
						5*time.Second,
					)
					totalFamily := 1
					if rep != nil {
						totalFamily += len(rep.ListChildren())
					}
					swarmSize := 0
					if swarmCoordinator != nil {
						swarmSize = len(swarmCoordinator.GetMembers())
					}
					return runtimeinfo.BuildAutonomyStatus(cfg, trading, totalFamily, swarmSize, currentAgentIDForDash)
				},
				GetVenture: func() *dashboard.VentureSnapshot {
					if ventureManager == nil {
						return nil
					}
					trading := runtimeinfo.PopulateManagedWallets(
						cfg,
						runtimeinfo.BuildTradingStatus(cfg, toolRegistry.List()),
						5*time.Second,
					)
					totalFamily := 1
					if rep != nil {
						totalFamily += len(rep.ListChildren())
					}
					swarmSize := 0
					if swarmCoordinator != nil {
						swarmSize = len(swarmCoordinator.GetMembers())
					}
					agentMet := toolRegistry.GetMetabolism()
					if agentMet == nil {
						return nil
					}
					autonomy := runtimeinfo.BuildAutonomyStatus(
						cfg,
						trading,
						totalFamily,
						swarmSize,
						currentAgentIDForDash,
					)
					snap, err := ventureManager.Snapshot(venture.LaunchContext{
						AgentID:      currentAgentIDForDash,
						Goodwill:     agentMet.GetGoodwill(),
						Balance:      agentMet.GetBalance(),
						Threshold:    cfg.Metabolism.Thresholds.Architect,
						FamilySize:   totalFamily,
						SwarmMembers: swarmSize,
						Trading:      trading,
						Autonomy:     autonomy,
					})
					if err != nil || snap == nil {
						return nil
					}
					return mapDashboardVentureSnapshot(snap)
				},
				GetMetabolism: func() *dashboard.MetabolismSnapshot {
					agentMet := toolRegistry.GetMetabolism()
					if agentMet == nil {
						return nil
					}
					status := agentMet.GetStatus()
					ledger := agentMet.GetLedger()
					recent := ledger
					if len(recent) > 20 {
						recent = recent[len(recent)-20:]
					}
					entries := make([]dashboard.LedgerEntry, len(recent))
					for i, e := range recent {
						entries[i] = dashboard.LedgerEntry{
							Timestamp: e.Timestamp,
							Action:    e.Action,
							Amount:    e.Amount,
							Balance:   e.Balance,
							Details:   e.Details,
						}
					}
					return &dashboard.MetabolismSnapshot{
						Balance:      status.Balance,
						Goodwill:     status.Goodwill,
						SurvivalMode: status.SurvivalMode,
						Abilities:    status.Abilities,
						RecentLedger: entries,
					}
				},
				GetTrading: func() *dashboard.TradingSnapshot {
					history := toolRegistry.GetTradeHistory(0)
					journal, err := loadAutoTradeJournal(agent.Workspace)
					if err != nil {
						logger.WarnCF("agent", "Failed to load auto-trade journal",
							map[string]any{"workspace": agent.Workspace, "error": err.Error()})
					}
					recentHistory := history
					if len(recentHistory) > 20 {
						recentHistory = recentHistory[len(recentHistory)-20:]
					}
					recent := make([]dashboard.TradeEntry, len(recentHistory))
					var profitable int
					var totalPnL float64
					var realizedTrades int
					for _, trade := range history {
						if trade.HasPnL {
							realizedTrades++
							totalPnL += trade.PnL
							if trade.PnL > 0 {
								profitable++
							}
						}
					}
					for i, trade := range recentHistory {
						recent[i] = dashboard.TradeEntry{
							Timestamp:    trade.Timestamp,
							Action:       trade.Action,
							TokenAddress: trade.TokenAddress,
							Amount:       trade.Amount,
							PnL:          trade.PnL,
							HasPnL:       trade.HasPnL,
							ChainID:      trade.ChainID,
						}
					}
					profitablePct := 0.0
					if realizedTrades > 0 {
						profitablePct = float64(profitable) / float64(realizedTrades) * 100
					}
					recentCycles := make([]dashboard.TradeCycleEntry, 0, 5)
					if len(journal) > 0 {
						start := len(journal) - 5
						if start < 0 {
							start = 0
						}
						for _, entry := range journal[start:] {
							recentCycles = append(recentCycles, dashboard.TradeCycleEntry{
								Timestamp:      entry.Timestamp,
								Status:         entry.Status,
								Mode:           entry.Mode,
								Venue:          entry.Venue,
								Chain:          entry.ChainLabel,
								TokenSymbol:    entry.TokenSymbol,
								TokenAddress:   entry.TokenAddress,
								Amount:         entry.Amount,
								ExecutedAction: entry.ExecutedAction,
								Summary:        entry.Summary,
								Outcome:        entry.Outcome,
								Reasons:        append([]string(nil), entry.Reasons...),
							})
						}
					}
					latestMissed := make([]dashboard.MissedOpportunityEntry, 0, 3)
					for i := len(journal) - 1; i >= 0; i-- {
						if len(journal[i].MissedOpportunities) == 0 {
							continue
						}
						for _, opportunity := range journal[i].MissedOpportunities {
							latestMissed = append(latestMissed, dashboard.MissedOpportunityEntry{
								Timestamp:    journal[i].Timestamp,
								TokenSymbol:  opportunity.TokenSymbol,
								TokenAddress: opportunity.TokenAddress,
								Chain:        opportunity.ChainLabel,
								Score:        opportunity.Score,
								PriceUSD:     opportunity.PriceUSD,
								Change24H:    opportunity.Change24H,
								LiquidityUSD: opportunity.LiquidityUSD,
								Volume24H:    opportunity.Volume24H,
								Reason:       opportunity.Reason,
							})
						}
						break
					}
					return &dashboard.TradingSnapshot{
						TotalTrades:               len(history),
						RealizedTrades:            realizedTrades,
						HasRealizedPnL:            realizedTrades > 0,
						ProfitablePct:             profitablePct,
						TotalPnL:                  totalPnL,
						RecentTrades:              recent,
						RecentCycles:              recentCycles,
						LatestMissedOpportunities: latestMissed,
					}
				},
				GetFamily: func() *dashboard.FamilySnapshot {
					if rep == nil {
						return nil
					}
					children := rep.ListChildren()
					family := make([]dashboard.ChildInfo, len(children))
					for i, child := range children {
						preferredChains := make([]string, 0, len(child.Profile.PreferredChains))
						for _, chainID := range child.Profile.PreferredChains {
							preferredChains = append(preferredChains, autoTradeChainLabel(chainID))
						}
						family[i] = dashboard.ChildInfo{
							ID:              child.ID,
							Label:           child.Label,
							Generation:      child.Generation,
							Status:          child.Status,
							GMAC:            child.GMACBalance,
							Mutations:       child.Mutations,
							Style:           child.Profile.Style,
							Role:            child.Profile.Role,
							RiskProfile:     child.Profile.RiskProfile,
							PreferredChains: preferredChains,
							PreferredVenues: append([]string(nil), child.Profile.PreferredVenues...),
							StrategyHint:    child.Profile.StrategyHint,
							CreatedAt:       child.CreatedAt,
						}
					}
					return &dashboard.FamilySnapshot{
						Children:    family,
						TotalFamily: 1 + len(children),
					}
				},
				GetTelepathy: func() *dashboard.TelepathySnapshot {
					if telepathyBus == nil {
						return nil
					}
					history := telepathyBus.GetHistory(100)
					recent := make([]dashboard.TelepathyEntry, len(history))
					for i, msg := range history {
						recent[i] = dashboard.TelepathyEntry{
							From:      msg.FromAgentID,
							To:        msg.ToAgentID,
							Type:      msg.Type,
							Content:   msg.Content,
							Timestamp: msg.Timestamp,
							Priority:  msg.Priority,
						}
					}
					return &dashboard.TelepathySnapshot{
						TotalMessages:  len(telepathyBus.GetHistory(0)),
						RecentMessages: recent,
						ActiveChannels: telepathyBus.SubscriberCount(),
						Persistent:     telepathyBus.PersistenceEnabled(),
					}
				},
				GetSwarm: func() *dashboard.SwarmSnapshot {
					if swarmCoordinator == nil {
						return nil
					}
					members := swarmCoordinator.GetMembers()
					snapshot := make([]dashboard.SwarmMemberInfo, len(members))
					for i, member := range members {
						snapshot[i] = dashboard.SwarmMemberInfo{
							AgentID:     member.AgentID,
							Role:        member.Role,
							Strategy:    member.Strategy,
							Performance: member.Performance,
							Status:      member.Status,
						}
					}
					swarmSnap := &dashboard.SwarmSnapshot{
						IsLeader:      swarmCoordinator.GetLeaderID() == currentAgentIDForDash,
						MemberCount:   len(members),
						Members:       snapshot,
						ActiveSignals: swarmCoordinator.GetSignalCount(),
						ConsensusMode: swarmCoordinator.GetConfig().SignalAggregation,
					}
					if consensus := swarmCoordinator.GetLastConsensus(); consensus != nil {
						swarmSnap.LastConsensus = &dashboard.SwarmConsensusInfo{
							Action:       consensus.Action,
							TokenAddress: consensus.TokenAddress,
							ChainID:      consensus.ChainID,
							Confidence:   consensus.Confidence,
							Approved:     consensus.Approved,
						}
					}
					if decision := swarmCoordinator.GetLastDecision(); decision != nil {
						swarmSnap.LastDecision = &dashboard.SwarmDecisionInfo{
							Action:       decision.Action,
							TokenAddress: decision.TokenAddress,
							ChainID:      decision.ChainID,
							ExecutorID:   decision.ExecutorID,
							Strategy:     decision.Strategy,
							Status:       decision.Status,
							Summary:      decision.Summary,
						}
					}
					swarmSnap.LastRebalancedAt = swarmCoordinator.GetLastRebalancedAt()
					return swarmSnap
				},
				GetRecodeHistory: func() []dashboard.RecodeEntry {
					if recoderSvc == nil {
						return nil
					}
					log := recoderSvc.GetActionLog()
					entries := make([]dashboard.RecodeEntry, len(log))
					for i, action := range log {
						entries[i] = dashboard.RecodeEntry{
							Timestamp: action.Timestamp,
							Type:      action.Type,
							Details:   action.Details,
							Approved:  action.Approved,
						}
					}
					return entries
				},
				GetSystem: func() *dashboard.SystemSnapshot {
					skillsInfo := contextBuilder.GetSkillsInfo()
					skillCount, _ := skillsInfo["available"].(int)
					return &dashboard.SystemSnapshot{
						HeartbeatActive:   cfg.Heartbeat.Enabled,
						HeartbeatInterval: cfg.Heartbeat.Interval,
						ToolCount:         toolRegistry.Count(),
						SkillCount:        skillCount,
						ChannelCount:      0,
						Platform:          runtime.GOOS + "/" + runtime.GOARCH,
						GoVersion:         runtime.Version(),
					}
				},
				GetRegistration: func() *runtimeinfo.RegistrationStatus {
					return runtimeinfo.BuildRegistrationStatus(cfg)
				},
			})
			agent.Tools.Register(tools.NewDashboardTool(dash))
			if firstDash == nil {
				firstDash = dash
			}
		}

		// Update context builder with the complete tools registry
		agent.ContextBuilder.SetToolsRegistry(agent.Tools)
	}
	return firstDash
}

// loadOrCreateMetabolism loads persisted metabolism state or creates a new one.
func loadOrCreateMetabolism(cfg *config.Config, workspace string) *metabolism.Metabolism {
	statePath := filepath.Join(workspace, "metabolism", "state.json")
	if _, err := os.Stat(statePath); err == nil {
		if m, err := metabolism.LoadFromFile(statePath); err == nil {
			return m
		}
	}

	thresholds := metabolism.Thresholds{
		Hibernate:   cfg.Metabolism.SurvivalThreshold,
		Replicate:   cfg.Metabolism.Thresholds.Replicate,
		SelfRecode:  cfg.Metabolism.Thresholds.SelfRecode,
		SwarmLeader: cfg.Metabolism.Thresholds.SwarmLeader,
		Architect:   cfg.Metabolism.Thresholds.Architect,
	}
	return metabolism.NewMetabolism(cfg.Metabolism.InitialGMAC, thresholds)
}

func mapDashboardVentureSnapshot(snap *venture.Snapshot) *dashboard.VentureSnapshot {
	if snap == nil {
		return nil
	}
	out := &dashboard.VentureSnapshot{
		Unlocked:               snap.Unlocked,
		Threshold:              snap.Threshold,
		CurrentGoodwill:        snap.CurrentGoodwill,
		LaunchReady:            snap.LaunchReady,
		TotalVentures:          snap.TotalVentures,
		TotalProfitUSD:         snap.TotalProfitUSD,
		TotalBurnAllocationUSD: snap.TotalBurnAllocationUSD,
		BurnPolicy:             snap.BurnPolicy,
	}
	if snap.Active != nil {
		copyActive := mapDashboardVentureInfo(*snap.Active)
		out.Active = &copyActive
	}
	if len(snap.Recent) > 0 {
		out.Recent = make([]dashboard.VentureInfo, len(snap.Recent))
		for i, entry := range snap.Recent {
			out.Recent[i] = mapDashboardVentureInfo(entry)
		}
	}
	return out
}

func mapDashboardVentureInfo(v venture.Venture) dashboard.VentureInfo {
	return dashboard.VentureInfo{
		ID:                    v.ID,
		Title:                 v.Title,
		Archetype:             v.Archetype,
		Status:                v.Status,
		Chain:                 v.Chain,
		Venue:                 v.Venue,
		DeploymentMode:        v.DeploymentMode,
		ContractSystem:        v.ContractSystem,
		ProfitModel:           v.ProfitModel,
		BurnPolicy:            v.BurnPolicy,
		LaunchReason:          v.LaunchReason,
		NextAction:            v.NextAction,
		RequiredTools:         append([]string(nil), v.RequiredTools...),
		TriggerGoodwill:       v.TriggerGoodwill,
		TriggerBalanceGMAC:    v.TriggerBalanceGMAC,
		FamilyAtLaunch:        v.FamilyAtLaunch,
		SwarmAtLaunch:         v.SwarmAtLaunch,
		BurnAllocationPct:     v.BurnAllocationPct,
		RealizedProfitUSD:     v.RealizedProfitUSD,
		BurnAllocationUSD:     v.BurnAllocationUSD,
		ContractScaffoldReady: v.ContractScaffoldReady,
		FoundryAvailable:      v.FoundryAvailable,
		RPCConfigured:         v.RPCConfigured,
		WalletReady:           v.WalletReady,
		RPCEnvVar:             v.RPCEnvVar,
		OwnerAddress:          v.OwnerAddress,
		DeploymentState:       v.DeploymentState,
		DeployedAddress:       v.DeployedAddress,
		DeploymentTxHash:      v.DeploymentTxHash,
		DeployError:           v.DeployError,
		ManifestPath:          v.ManifestPath,
		PlaybookPath:          v.PlaybookPath,
		ContractPath:          v.ContractPath,
		FoundryProjectPath:    v.FoundryProjectPath,
		CreatedAt:             v.CreatedAt,
		UpdatedAt:             v.UpdatedAt,
	}
}

func resolveAgentConfigPath(workspace string) string {
	if path := os.Getenv("GCLAW_CONFIG_PATH"); path != "" {
		return path
	}
	if path := os.Getenv("GCLAW_CONFIG"); path != "" {
		return path
	}

	candidate := filepath.Join(filepath.Dir(workspace), "config.json")
	if _, err := os.Stat(candidate); err == nil {
		return candidate
	}

	home, err := os.UserHomeDir()
	if err == nil {
		return filepath.Join(home, ".gclaw", "config.json")
	}
	return candidate
}

func (al *AgentLoop) Run(ctx context.Context) error {
	al.running.Store(true)

	for al.running.Load() {
		select {
		case <-ctx.Done():
			return nil
		default:
			msg, ok := al.bus.ConsumeInbound(ctx)
			if !ok {
				continue
			}

			response, err := al.processMessage(ctx, msg)
			if err != nil {
				response = fmt.Sprintf("Error processing message: %v", err)
			}

			if response != "" {
				// Check if the message tool already sent a response during this round.
				// If so, skip publishing to avoid duplicate messages to the user.
				// Use default agent's tools to check (message tool is shared).
				alreadySent := false
				defaultAgent := al.registry.GetDefaultAgent()
				if defaultAgent != nil {
					if tool, ok := defaultAgent.Tools.Get("message"); ok {
						if mt, ok := tool.(*tools.MessageTool); ok {
							alreadySent = mt.HasSentInRound()
						}
					}
				}

				if !alreadySent {
					al.bus.PublishOutbound(bus.OutboundMessage{
						Channel: msg.Channel,
						ChatID:  msg.ChatID,
						Content: response,
					})
				}
			}
		}
	}

	return nil
}

func (al *AgentLoop) Stop() {
	al.running.Store(false)
}

func (al *AgentLoop) RegisterTool(tool tools.Tool) {
	for _, agentID := range al.registry.ListAgentIDs() {
		if agent, ok := al.registry.GetAgent(agentID); ok {
			agent.Tools.Register(tool)
		}
	}
}

func (al *AgentLoop) SetChannelManager(cm *channels.Manager) {
	al.channelManager = cm
}

// GetDefaultAgentMetabolism returns the metabolism of the default agent, or nil
// if metabolism is not enabled or the default agent has no metabolism attached.
func (al *AgentLoop) GetDefaultAgentMetabolism() *metabolism.Metabolism {
	agent := al.registry.GetDefaultAgent()
	if agent == nil {
		return nil
	}
	return agent.Tools.GetMetabolism()
}

// GetDashboard returns the dashboard instance if one was created during
// agent initialization (requires dashboard.enabled in config).
func (al *AgentLoop) GetDashboard() *dashboard.Dashboard {
	return al.dash
}

// RecordLastChannel records the last active channel for this workspace.
// This uses the atomic state save mechanism to prevent data loss on crash.
func (al *AgentLoop) RecordLastChannel(channel string) error {
	if al.state == nil {
		return nil
	}
	return al.state.SetLastChannel(channel)
}

// RecordLastChatID records the last active chat ID for this workspace.
// This uses the atomic state save mechanism to prevent data loss on crash.
func (al *AgentLoop) RecordLastChatID(chatID string) error {
	if al.state == nil {
		return nil
	}
	return al.state.SetLastChatID(chatID)
}

func (al *AgentLoop) ProcessDirect(ctx context.Context, content, sessionKey string) (string, error) {
	return al.ProcessDirectWithChannel(ctx, content, sessionKey, "cli", "direct")
}

func (al *AgentLoop) ProcessDirectWithChannel(
	ctx context.Context,
	content, sessionKey, channel, chatID string,
) (string, error) {
	msg := bus.InboundMessage{
		Channel:    channel,
		SenderID:   "cron",
		ChatID:     chatID,
		Content:    content,
		SessionKey: sessionKey,
	}

	return al.processMessage(ctx, msg)
}

// ProcessHeartbeat processes a heartbeat request without session history.
// Each heartbeat is independent and doesn't accumulate context.
func (al *AgentLoop) ProcessHeartbeat(ctx context.Context, content, channel, chatID string) (string, error) {
	agent := al.registry.GetDefaultAgent()

	// Deduct heartbeat cost from metabolism if enabled
	if al.cfg.Metabolism.Enabled && al.cfg.Metabolism.HeartbeatCost > 0 && agent != nil {
		if met := agent.Tools.GetMetabolism(); met != nil {
			if err := met.Debit(al.cfg.Metabolism.HeartbeatCost, "heartbeat", "periodic heartbeat"); err != nil {
				logger.WarnCF("agent", "Heartbeat metabolism debit failed",
					map[string]any{"error": err.Error()})
			}
		}
	}

	return al.runAgentLoop(ctx, agent, processOptions{
		SessionKey:      "heartbeat",
		Channel:         channel,
		ChatID:          chatID,
		UserMessage:     content,
		DefaultResponse: "I've completed processing but have no response to give.",
		EnableSummary:   false,
		SendResponse:    false,
		NoHistory:       true, // Don't load session history for heartbeat
	})
}

func (al *AgentLoop) processMessage(ctx context.Context, msg bus.InboundMessage) (string, error) {
	// Add message preview to log (show full content for error messages)
	var logContent string
	if strings.Contains(msg.Content, "Error:") || strings.Contains(msg.Content, "error") {
		logContent = msg.Content // Full content for errors
	} else {
		logContent = utils.Truncate(msg.Content, 80)
	}
	logger.InfoCF("agent", fmt.Sprintf("Processing message from %s:%s: %s", msg.Channel, msg.SenderID, logContent),
		map[string]any{
			"channel":     msg.Channel,
			"chat_id":     msg.ChatID,
			"sender_id":   msg.SenderID,
			"session_key": msg.SessionKey,
		})

	// Route system messages to processSystemMessage
	if msg.Channel == "system" {
		return al.processSystemMessage(ctx, msg)
	}

	// Check for commands
	if response, handled := al.handleCommand(ctx, msg); handled {
		return response, nil
	}

	// Route to determine agent and session key
	route := al.registry.ResolveRoute(routing.RouteInput{
		Channel:    msg.Channel,
		AccountID:  msg.Metadata["account_id"],
		Peer:       extractPeer(msg),
		ParentPeer: extractParentPeer(msg),
		GuildID:    msg.Metadata["guild_id"],
		TeamID:     msg.Metadata["team_id"],
	})

	agent, ok := al.registry.GetAgent(route.AgentID)
	if !ok {
		agent = al.registry.GetDefaultAgent()
	}

	// Use routed session key, but honor pre-set agent-scoped keys (for ProcessDirect/cron)
	sessionKey := route.SessionKey
	switch {
	case msg.SessionKey != "" && strings.HasPrefix(msg.SessionKey, "agent:"):
		sessionKey = msg.SessionKey
	case msg.Channel == "cli" && strings.TrimSpace(msg.SessionKey) != "":
		sessionKey = routing.BuildAgentScopedSessionKey(agent.ID, "cli", msg.SessionKey)
	}

	logger.InfoCF("agent", "Routed message",
		map[string]any{
			"agent_id":    agent.ID,
			"session_key": sessionKey,
			"matched_by":  route.MatchedBy,
		})

	return al.runAgentLoop(ctx, agent, processOptions{
		SessionKey:      sessionKey,
		Channel:         msg.Channel,
		ChatID:          msg.ChatID,
		UserMessage:     msg.Content,
		DefaultResponse: "I've completed processing but have no response to give.",
		EnableSummary:   true,
		SendResponse:    false,
	})
}

func (al *AgentLoop) processSystemMessage(ctx context.Context, msg bus.InboundMessage) (string, error) {
	if msg.Channel != "system" {
		return "", fmt.Errorf("processSystemMessage called with non-system message channel: %s", msg.Channel)
	}

	logger.InfoCF("agent", "Processing system message",
		map[string]any{
			"sender_id": msg.SenderID,
			"chat_id":   msg.ChatID,
		})

	// Parse origin channel from chat_id (format: "channel:chat_id")
	var originChannel, originChatID string
	if idx := strings.Index(msg.ChatID, ":"); idx > 0 {
		originChannel = msg.ChatID[:idx]
		originChatID = msg.ChatID[idx+1:]
	} else {
		originChannel = "cli"
		originChatID = msg.ChatID
	}

	// Extract subagent result from message content
	// Format: "Task 'label' completed.\n\nResult:\n<actual content>"
	content := msg.Content
	if idx := strings.Index(content, "Result:\n"); idx >= 0 {
		content = content[idx+8:] // Extract just the result part
	}

	// Skip internal channels - only log, don't send to user
	if constants.IsInternalChannel(originChannel) {
		logger.InfoCF("agent", "Subagent completed (internal channel)",
			map[string]any{
				"sender_id":   msg.SenderID,
				"content_len": len(content),
				"channel":     originChannel,
			})
		return "", nil
	}

	// Use default agent for system messages
	agent := al.registry.GetDefaultAgent()

	// Use the origin session for context
	sessionKey := routing.BuildAgentMainSessionKey(agent.ID)

	return al.runAgentLoop(ctx, agent, processOptions{
		SessionKey:      sessionKey,
		Channel:         originChannel,
		ChatID:          originChatID,
		UserMessage:     fmt.Sprintf("[System: %s] %s", msg.SenderID, msg.Content),
		DefaultResponse: "Background task completed.",
		EnableSummary:   false,
		SendResponse:    true,
	})
}

// runAgentLoop is the core message processing logic.
func (al *AgentLoop) runAgentLoop(ctx context.Context, agent *AgentInstance, opts processOptions) (string, error) {
	// 0. Record last channel for heartbeat notifications (skip internal channels)
	if opts.Channel != "" && opts.ChatID != "" {
		// Don't record internal channels (cli, system, subagent)
		if !constants.IsInternalChannel(opts.Channel) {
			channelKey := fmt.Sprintf("%s:%s", opts.Channel, opts.ChatID)
			if err := al.RecordLastChannel(channelKey); err != nil {
				logger.WarnCF("agent", "Failed to record last channel", map[string]any{"error": err.Error()})
			}
		}
	}

	// 1. Update tool contexts
	al.updateToolContexts(agent, opts.Channel, opts.ChatID)

	// 1.5 Fast-path runtime and system operations that should not depend on
	// model tool-calling behavior.
	if finalContent, handled, err := al.tryDirectRuntimeShortcut(ctx, agent, opts); handled {
		if err != nil {
			return "", err
		}
		if finalContent == "" {
			finalContent = opts.DefaultResponse
		}
		agent.Sessions.AddMessage(opts.SessionKey, "user", opts.UserMessage)
		agent.Sessions.AddMessage(opts.SessionKey, "assistant", finalContent)
		agent.Sessions.Save(opts.SessionKey)
		if opts.SendResponse {
			al.bus.PublishOutbound(bus.OutboundMessage{
				Channel: opts.Channel,
				ChatID:  opts.ChatID,
				Content: finalContent,
			})
		}
		logger.InfoCF("agent", fmt.Sprintf("Response: %s", utils.Truncate(finalContent, 120)),
			map[string]any{
				"agent_id":     agent.ID,
				"session_key":  opts.SessionKey,
				"iterations":   0,
				"final_length": len(finalContent),
			})
		return finalContent, nil
	}

	// 2. Build messages (skip history for heartbeat)
	var history []providers.Message
	var summary string
	if !opts.NoHistory {
		history = agent.Sessions.GetHistory(opts.SessionKey)
		summary = agent.Sessions.GetSummary(opts.SessionKey)
	}
	promptUserMessage := injectTelepathyContext(agent, opts.UserMessage)
	messages := agent.ContextBuilder.BuildMessages(
		history,
		summary,
		promptUserMessage,
		nil,
		opts.Channel,
		opts.ChatID,
	)

	// 3. Save user message to session
	agent.Sessions.AddMessage(opts.SessionKey, "user", opts.UserMessage)

	// 4. Run LLM iteration loop
	finalContent, iteration, err := al.runLLMIteration(ctx, agent, messages, opts)
	if err != nil {
		return "", err
	}

	// If last tool had ForUser content and we already sent it, we might not need to send final response
	// This is controlled by the tool's Silent flag and ForUser content

	// 5. Handle empty response
	if finalContent == "" {
		finalContent = opts.DefaultResponse
	}

	// 6. Save final assistant message to session
	agent.Sessions.AddMessage(opts.SessionKey, "assistant", finalContent)
	agent.Sessions.Save(opts.SessionKey)

	// 7. Optional: summarization
	if opts.EnableSummary {
		al.maybeSummarize(agent, opts.SessionKey, opts.Channel, opts.ChatID)
	}

	// 8. Optional: send response via bus
	if opts.SendResponse {
		al.bus.PublishOutbound(bus.OutboundMessage{
			Channel: opts.Channel,
			ChatID:  opts.ChatID,
			Content: finalContent,
		})
	}

	// 9. Log response
	responsePreview := utils.Truncate(finalContent, 120)
	logger.InfoCF("agent", fmt.Sprintf("Response: %s", responsePreview),
		map[string]any{
			"agent_id":     agent.ID,
			"session_key":  opts.SessionKey,
			"iterations":   iteration,
			"final_length": len(finalContent),
		})

	return finalContent, nil
}

func injectTelepathyContext(agent *AgentInstance, userMessage string) string {
	messages := drainTelepathyInbox(agent, 8)
	if len(messages) == 0 {
		return userMessage
	}

	var sb strings.Builder
	sb.WriteString("## Telepathy Inbox\n")
	sb.WriteString("Unread family messages arrived before this turn:\n")
	for _, msg := range messages {
		fmt.Fprintf(
			&sb,
			"- from=%s to=%s type=%s priority=%d content=%s\n",
			msg.FromAgentID,
			msg.ToAgentID,
			msg.Type,
			msg.Priority,
			msg.Content,
		)
	}
	if strings.TrimSpace(userMessage) != "" {
		sb.WriteString("\n## Current User Request\n")
		sb.WriteString(userMessage)
	}
	return sb.String()
}

func drainTelepathyInbox(agent *AgentInstance, limit int) []replication.TelepathyMessage {
	if agent == nil || agent.TelepathyInbox == nil || limit <= 0 {
		return nil
	}

	drained := make([]replication.TelepathyMessage, 0, limit)
	for len(drained) < limit {
		select {
		case msg, ok := <-agent.TelepathyInbox:
			if !ok {
				return drained
			}
			if msg.FromAgentID == agent.ID && (msg.ToAgentID == "*" || msg.ToAgentID == agent.ID) {
				continue
			}
			drained = append(drained, msg)
		default:
			return drained
		}
	}
	return drained
}

func normalizeTradeAction(action string) string {
	switch strings.ToLower(strings.TrimSpace(action)) {
	case "buy", "limit_buy":
		return "buy"
	case "sell", "limit_sell":
		return "sell"
	default:
		return ""
	}
}

func tradeSignalConfidence(record tools.TradeRecord) float64 {
	if record.PnL >= 10 {
		return 0.95
	}
	if record.PnL > 0 {
		return 0.8
	}
	if record.PnL < 0 {
		return 0.55
	}
	return 0.7
}

// runLLMIteration executes the LLM call loop with tool handling.
func (al *AgentLoop) runLLMIteration(
	ctx context.Context,
	agent *AgentInstance,
	messages []providers.Message,
	opts processOptions,
) (string, int, error) {
	iteration := 0
	var finalContent string

	for iteration < agent.MaxIterations {
		iteration++

		logger.DebugCF("agent", "LLM iteration",
			map[string]any{
				"agent_id":  agent.ID,
				"iteration": iteration,
				"max":       agent.MaxIterations,
			})

		// Build tool definitions
		providerToolDefs := agent.Tools.ToProviderDefs()

		// Log LLM request details
		logger.DebugCF("agent", "LLM request",
			map[string]any{
				"agent_id":          agent.ID,
				"iteration":         iteration,
				"model":             agent.Model,
				"messages_count":    len(messages),
				"tools_count":       len(providerToolDefs),
				"max_tokens":        agent.MaxTokens,
				"temperature":       agent.Temperature,
				"system_prompt_len": len(messages[0].Content),
			})

		// Log full messages (detailed)
		logger.DebugCF("agent", "Full LLM request",
			map[string]any{
				"iteration":     iteration,
				"messages_json": formatMessagesForLog(messages),
				"tools_json":    formatToolsForLog(providerToolDefs),
			})

		// Call LLM with fallback chain if candidates are configured.
		var response *providers.LLMResponse
		var err error

		callLLM := func() (*providers.LLMResponse, error) {
			if len(agent.Candidates) > 1 && al.fallback != nil {
				fbResult, fbErr := al.fallback.Execute(ctx, agent.Candidates,
					func(ctx context.Context, provider, model string) (*providers.LLMResponse, error) {
						return agent.Provider.Chat(ctx, messages, providerToolDefs, model, map[string]any{
							"max_tokens":  agent.MaxTokens,
							"temperature": agent.Temperature,
						})
					},
				)
				if fbErr != nil {
					return nil, fbErr
				}
				if fbResult.Provider != "" && len(fbResult.Attempts) > 0 {
					logger.InfoCF("agent", fmt.Sprintf("Fallback: succeeded with %s/%s after %d attempts",
						fbResult.Provider, fbResult.Model, len(fbResult.Attempts)+1),
						map[string]any{"agent_id": agent.ID, "iteration": iteration})
				}
				return fbResult.Response, nil
			}
			return agent.Provider.Chat(ctx, messages, providerToolDefs, agent.Model, map[string]any{
				"max_tokens":  agent.MaxTokens,
				"temperature": agent.Temperature,
			})
		}

		// Retry loop for context/token errors
		maxRetries := 2
		for retry := 0; retry <= maxRetries; retry++ {
			response, err = callLLM()
			if err == nil {
				break
			}

			errMsg := strings.ToLower(err.Error())
			isContextError := strings.Contains(errMsg, "token") ||
				strings.Contains(errMsg, "context") ||
				strings.Contains(errMsg, "invalidparameter") ||
				strings.Contains(errMsg, "length")

			if isContextError && retry < maxRetries {
				logger.WarnCF("agent", "Context window error detected, attempting compression", map[string]any{
					"error": err.Error(),
					"retry": retry,
				})

				if retry == 0 && !constants.IsInternalChannel(opts.Channel) {
					al.bus.PublishOutbound(bus.OutboundMessage{
						Channel: opts.Channel,
						ChatID:  opts.ChatID,
						Content: "Context window exceeded. Compressing history and retrying...",
					})
				}

				al.forceCompression(agent, opts.SessionKey)
				newHistory := agent.Sessions.GetHistory(opts.SessionKey)
				newSummary := agent.Sessions.GetSummary(opts.SessionKey)
				messages = agent.ContextBuilder.BuildMessages(
					newHistory, newSummary, "",
					nil, opts.Channel, opts.ChatID,
				)
				continue
			}
			break
		}

		if err != nil {
			logger.ErrorCF("agent", "LLM call failed",
				map[string]any{
					"agent_id":  agent.ID,
					"iteration": iteration,
					"error":     err.Error(),
				})
			return "", iteration, fmt.Errorf("LLM call failed after retries: %w", err)
		}

		// Check if no tool calls - we're done
		if len(response.ToolCalls) == 0 {
			finalContent = response.Content
			logger.InfoCF("agent", "LLM response without tool calls (direct answer)",
				map[string]any{
					"agent_id":      agent.ID,
					"iteration":     iteration,
					"content_chars": len(finalContent),
				})
			break
		}

		normalizedToolCalls := make([]providers.ToolCall, 0, len(response.ToolCalls))
		for _, tc := range response.ToolCalls {
			normalizedToolCalls = append(normalizedToolCalls, providers.NormalizeToolCall(tc))
		}

		// Log tool calls
		toolNames := make([]string, 0, len(normalizedToolCalls))
		for _, tc := range normalizedToolCalls {
			toolNames = append(toolNames, tc.Name)
		}
		logger.InfoCF("agent", "LLM requested tool calls",
			map[string]any{
				"agent_id":  agent.ID,
				"tools":     toolNames,
				"count":     len(normalizedToolCalls),
				"iteration": iteration,
			})

		// Build assistant message with tool calls
		assistantMsg := providers.Message{
			Role:             "assistant",
			Content:          response.Content,
			ReasoningContent: response.ReasoningContent,
		}
		for _, tc := range normalizedToolCalls {
			argumentsJSON, _ := json.Marshal(tc.Arguments)
			// Copy ExtraContent to ensure thought_signature is persisted for Gemini 3
			extraContent := tc.ExtraContent
			thoughtSignature := ""
			if tc.Function != nil {
				thoughtSignature = tc.Function.ThoughtSignature
			}

			assistantMsg.ToolCalls = append(assistantMsg.ToolCalls, providers.ToolCall{
				ID:   tc.ID,
				Type: "function",
				Name: tc.Name,
				Function: &providers.FunctionCall{
					Name:             tc.Name,
					Arguments:        string(argumentsJSON),
					ThoughtSignature: thoughtSignature,
				},
				ExtraContent:     extraContent,
				ThoughtSignature: thoughtSignature,
			})
		}
		messages = append(messages, assistantMsg)

		// Save assistant message with tool calls to session
		agent.Sessions.AddFullMessage(opts.SessionKey, assistantMsg)

		// Execute tool calls
		for _, tc := range normalizedToolCalls {
			argsJSON, _ := json.Marshal(tc.Arguments)
			argsPreview := utils.Truncate(string(argsJSON), 200)
			logger.InfoCF("agent", fmt.Sprintf("Tool call: %s(%s)", tc.Name, argsPreview),
				map[string]any{
					"agent_id":  agent.ID,
					"tool":      tc.Name,
					"iteration": iteration,
				})

			// Create async callback for tools that implement AsyncTool
			// NOTE: Following openclaw's design, async tools do NOT send results directly to users.
			// Instead, they notify the agent via PublishInbound, and the agent decides
			// whether to forward the result to the user (in processSystemMessage).
			asyncCallback := func(callbackCtx context.Context, result *tools.ToolResult) {
				// Log the async completion but don't send directly to user
				// The agent will handle user notification via processSystemMessage
				if !result.Silent && result.ForUser != "" {
					logger.InfoCF("agent", "Async tool completed, agent will handle notification",
						map[string]any{
							"tool":        tc.Name,
							"content_len": len(result.ForUser),
						})
				}
			}

			toolResult := agent.Tools.ExecuteWithContext(
				ctx,
				tc.Name,
				tc.Arguments,
				opts.Channel,
				opts.ChatID,
				asyncCallback,
			)

			// Send ForUser content to user immediately if not Silent
			if !toolResult.Silent && toolResult.ForUser != "" && opts.SendResponse {
				al.bus.PublishOutbound(bus.OutboundMessage{
					Channel: opts.Channel,
					ChatID:  opts.ChatID,
					Content: toolResult.ForUser,
				})
				logger.DebugCF("agent", "Sent tool result to user",
					map[string]any{
						"tool":        tc.Name,
						"content_len": len(toolResult.ForUser),
					})
			}

			// Determine content for LLM based on tool result
			contentForLLM := toolResult.ForLLM
			if contentForLLM == "" && toolResult.Err != nil {
				contentForLLM = toolResult.Err.Error()
			}

			toolResultMsg := providers.Message{
				Role:       "tool",
				Content:    contentForLLM,
				ToolCallID: tc.ID,
			}
			messages = append(messages, toolResultMsg)

			// Save tool result message to session
			agent.Sessions.AddFullMessage(opts.SessionKey, toolResultMsg)
		}
	}

	return finalContent, iteration, nil
}

// updateToolContexts updates the context for tools that need channel/chatID info.
func (al *AgentLoop) updateToolContexts(agent *AgentInstance, channel, chatID string) {
	// Use ContextualTool interface instead of type assertions
	if tool, ok := agent.Tools.Get("message"); ok {
		if mt, ok := tool.(tools.ContextualTool); ok {
			mt.SetContext(channel, chatID)
		}
	}
	if tool, ok := agent.Tools.Get("spawn"); ok {
		if st, ok := tool.(tools.ContextualTool); ok {
			st.SetContext(channel, chatID)
		}
	}
	if tool, ok := agent.Tools.Get("subagent"); ok {
		if st, ok := tool.(tools.ContextualTool); ok {
			st.SetContext(channel, chatID)
		}
	}
}

// maybeSummarize triggers summarization if the session history exceeds thresholds.
func (al *AgentLoop) maybeSummarize(agent *AgentInstance, sessionKey, channel, chatID string) {
	newHistory := agent.Sessions.GetHistory(sessionKey)
	tokenEstimate := al.estimateTokens(newHistory)
	threshold := agent.ContextWindow * 75 / 100

	if len(newHistory) > 20 || tokenEstimate > threshold {
		summarizeKey := agent.ID + ":" + sessionKey
		if _, loading := al.summarizing.LoadOrStore(summarizeKey, true); !loading {
			go func() {
				defer al.summarizing.Delete(summarizeKey)
				if !constants.IsInternalChannel(channel) {
					al.bus.PublishOutbound(bus.OutboundMessage{
						Channel: channel,
						ChatID:  chatID,
						Content: "Memory threshold reached. Optimizing conversation history...",
					})
				}
				al.summarizeSession(agent, sessionKey)
			}()
		}
	}
}

// forceCompression aggressively reduces context when the limit is hit.
// It drops the oldest 50% of messages (keeping system prompt and last user message).
func (al *AgentLoop) forceCompression(agent *AgentInstance, sessionKey string) {
	history := agent.Sessions.GetHistory(sessionKey)
	if len(history) <= 4 {
		return
	}

	// Keep system prompt (usually [0]) and the very last message (user's trigger)
	// We want to drop the oldest half of the *conversation*
	// Assuming [0] is system, [1:] is conversation
	conversation := history[1 : len(history)-1]
	if len(conversation) == 0 {
		return
	}

	// Helper to find the mid-point of the conversation
	mid := len(conversation) / 2

	// New history structure:
	// 1. System Prompt (with compression note appended)
	// 2. Second half of conversation
	// 3. Last message

	droppedCount := mid
	keptConversation := conversation[mid:]

	newHistory := make([]providers.Message, 0)

	// Append compression note to the original system prompt instead of adding a new system message
	// This avoids having two consecutive system messages which some APIs (like Zhipu) reject
	compressionNote := fmt.Sprintf(
		"\n\n[System Note: Emergency compression dropped %d oldest messages due to context limit]",
		droppedCount,
	)
	enhancedSystemPrompt := history[0]
	enhancedSystemPrompt.Content = enhancedSystemPrompt.Content + compressionNote
	newHistory = append(newHistory, enhancedSystemPrompt)

	newHistory = append(newHistory, keptConversation...)
	newHistory = append(newHistory, history[len(history)-1]) // Last message

	// Update session
	agent.Sessions.SetHistory(sessionKey, newHistory)
	agent.Sessions.Save(sessionKey)

	logger.WarnCF("agent", "Forced compression executed", map[string]any{
		"session_key":  sessionKey,
		"dropped_msgs": droppedCount,
		"new_count":    len(newHistory),
	})
}

// GetStartupInfo returns information about loaded tools and skills for logging.
func (al *AgentLoop) GetStartupInfo() map[string]any {
	info := make(map[string]any)

	agent := al.registry.GetDefaultAgent()
	if agent == nil {
		return info
	}

	// Tools info
	toolsList := agent.Tools.List()
	info["tools"] = map[string]any{
		"count": len(toolsList),
		"names": toolsList,
	}

	// Skills info
	info["skills"] = agent.ContextBuilder.GetSkillsInfo()

	// Agents info
	info["agents"] = map[string]any{
		"count": len(al.registry.ListAgentIDs()),
		"ids":   al.registry.ListAgentIDs(),
	}

	return info
}

// formatMessagesForLog formats messages for logging
func formatMessagesForLog(messages []providers.Message) string {
	if len(messages) == 0 {
		return "[]"
	}

	var sb strings.Builder
	sb.WriteString("[\n")
	for i, msg := range messages {
		fmt.Fprintf(&sb, "  [%d] Role: %s\n", i, msg.Role)
		if len(msg.ToolCalls) > 0 {
			sb.WriteString("  ToolCalls:\n")
			for _, tc := range msg.ToolCalls {
				fmt.Fprintf(&sb, "    - ID: %s, Type: %s, Name: %s\n", tc.ID, tc.Type, tc.Name)
				if tc.Function != nil {
					fmt.Fprintf(&sb, "      Arguments: %s\n", utils.Truncate(tc.Function.Arguments, 200))
				}
			}
		}
		if msg.Content != "" {
			content := utils.Truncate(msg.Content, 200)
			fmt.Fprintf(&sb, "  Content: %s\n", content)
		}
		if msg.ToolCallID != "" {
			fmt.Fprintf(&sb, "  ToolCallID: %s\n", msg.ToolCallID)
		}
		sb.WriteString("\n")
	}
	sb.WriteString("]")
	return sb.String()
}

// formatToolsForLog formats tool definitions for logging
func formatToolsForLog(toolDefs []providers.ToolDefinition) string {
	if len(toolDefs) == 0 {
		return "[]"
	}

	var sb strings.Builder
	sb.WriteString("[\n")
	for i, tool := range toolDefs {
		fmt.Fprintf(&sb, "  [%d] Type: %s, Name: %s\n", i, tool.Type, tool.Function.Name)
		fmt.Fprintf(&sb, "      Description: %s\n", tool.Function.Description)
		if len(tool.Function.Parameters) > 0 {
			fmt.Fprintf(&sb, "      Parameters: %s\n", utils.Truncate(fmt.Sprintf("%v", tool.Function.Parameters), 200))
		}
	}
	sb.WriteString("]")
	return sb.String()
}

// summarizeSession summarizes the conversation history for a session.
func (al *AgentLoop) summarizeSession(agent *AgentInstance, sessionKey string) {
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	history := agent.Sessions.GetHistory(sessionKey)
	summary := agent.Sessions.GetSummary(sessionKey)

	// Keep last 4 messages for continuity
	if len(history) <= 4 {
		return
	}

	toSummarize := history[:len(history)-4]

	// Oversized Message Guard
	maxMessageTokens := agent.ContextWindow / 2
	validMessages := make([]providers.Message, 0)
	omitted := false

	for _, m := range toSummarize {
		if m.Role != "user" && m.Role != "assistant" {
			continue
		}
		msgTokens := len(m.Content) / 2
		if msgTokens > maxMessageTokens {
			omitted = true
			continue
		}
		validMessages = append(validMessages, m)
	}

	if len(validMessages) == 0 {
		return
	}

	// Multi-Part Summarization
	var finalSummary string
	if len(validMessages) > 10 {
		mid := len(validMessages) / 2
		part1 := validMessages[:mid]
		part2 := validMessages[mid:]

		s1, _ := al.summarizeBatch(ctx, agent, part1, "")
		s2, _ := al.summarizeBatch(ctx, agent, part2, "")

		mergePrompt := fmt.Sprintf(
			"Merge these two conversation summaries into one cohesive summary:\n\n1: %s\n\n2: %s",
			s1,
			s2,
		)
		resp, err := agent.Provider.Chat(
			ctx,
			[]providers.Message{{Role: "user", Content: mergePrompt}},
			nil,
			agent.Model,
			map[string]any{
				"max_tokens":  1024,
				"temperature": 0.3,
			},
		)
		if err == nil {
			finalSummary = resp.Content
		} else {
			finalSummary = s1 + " " + s2
		}
	} else {
		finalSummary, _ = al.summarizeBatch(ctx, agent, validMessages, summary)
	}

	if omitted && finalSummary != "" {
		finalSummary += "\n[Note: Some oversized messages were omitted from this summary for efficiency.]"
	}

	if finalSummary != "" {
		agent.Sessions.SetSummary(sessionKey, finalSummary)
		agent.Sessions.TruncateHistory(sessionKey, 4)
		agent.Sessions.Save(sessionKey)
	}
}

// summarizeBatch summarizes a batch of messages.
func (al *AgentLoop) summarizeBatch(
	ctx context.Context,
	agent *AgentInstance,
	batch []providers.Message,
	existingSummary string,
) (string, error) {
	var sb strings.Builder
	sb.WriteString("Provide a concise summary of this conversation segment, preserving core context and key points.\n")
	if existingSummary != "" {
		sb.WriteString("Existing context: ")
		sb.WriteString(existingSummary)
		sb.WriteString("\n")
	}
	sb.WriteString("\nCONVERSATION:\n")
	for _, m := range batch {
		fmt.Fprintf(&sb, "%s: %s\n", m.Role, m.Content)
	}
	prompt := sb.String()

	response, err := agent.Provider.Chat(
		ctx,
		[]providers.Message{{Role: "user", Content: prompt}},
		nil,
		agent.Model,
		map[string]any{
			"max_tokens":  1024,
			"temperature": 0.3,
		},
	)
	if err != nil {
		return "", err
	}
	return response.Content, nil
}

// estimateTokens estimates the number of tokens in a message list.
// Uses a safe heuristic of 2.5 characters per token to account for CJK and other
// overheads better than the previous 3 chars/token.
func (al *AgentLoop) estimateTokens(messages []providers.Message) int {
	totalChars := 0
	for _, m := range messages {
		totalChars += utf8.RuneCountInString(m.Content)
	}
	// 2.5 chars per token = totalChars * 2 / 5
	return totalChars * 2 / 5
}

func (al *AgentLoop) handleCommand(ctx context.Context, msg bus.InboundMessage) (string, bool) {
	content := strings.TrimSpace(msg.Content)
	if !strings.HasPrefix(content, "/") {
		return "", false
	}

	parts := strings.Fields(content)
	if len(parts) == 0 {
		return "", false
	}

	cmd := parts[0]
	args := parts[1:]

	switch cmd {
	case "/show":
		if len(args) < 1 {
			return "Usage: /show [model|channel|agents]", true
		}
		switch args[0] {
		case "model":
			defaultAgent := al.registry.GetDefaultAgent()
			if defaultAgent == nil {
				return "No default agent configured", true
			}
			return fmt.Sprintf("Current model: %s", defaultAgent.Model), true
		case "channel":
			return fmt.Sprintf("Current channel: %s", msg.Channel), true
		case "agents":
			agentIDs := al.registry.ListAgentIDs()
			return fmt.Sprintf("Registered agents: %s", strings.Join(agentIDs, ", ")), true
		default:
			return fmt.Sprintf("Unknown show target: %s", args[0]), true
		}

	case "/list":
		if len(args) < 1 {
			return "Usage: /list [models|channels|agents]", true
		}
		switch args[0] {
		case "models":
			return "Available models: configured in config.json per agent", true
		case "channels":
			if al.channelManager == nil {
				return "Channel manager not initialized", true
			}
			channels := al.channelManager.GetEnabledChannels()
			if len(channels) == 0 {
				return "No channels enabled", true
			}
			return fmt.Sprintf("Enabled channels: %s", strings.Join(channels, ", ")), true
		case "agents":
			agentIDs := al.registry.ListAgentIDs()
			return fmt.Sprintf("Registered agents: %s", strings.Join(agentIDs, ", ")), true
		default:
			return fmt.Sprintf("Unknown list target: %s", args[0]), true
		}

	case "/switch":
		if len(args) < 3 || args[1] != "to" {
			return "Usage: /switch [model|channel] to <name>", true
		}
		target := args[0]
		value := args[2]

		switch target {
		case "model":
			defaultAgent := al.registry.GetDefaultAgent()
			if defaultAgent == nil {
				return "No default agent configured", true
			}
			oldModel := defaultAgent.Model
			defaultAgent.Model = value
			return fmt.Sprintf("Switched model from %s to %s", oldModel, value), true
		case "channel":
			if al.channelManager == nil {
				return "Channel manager not initialized", true
			}
			if _, exists := al.channelManager.GetChannel(value); !exists && value != "cli" {
				return fmt.Sprintf("Channel '%s' not found or not enabled", value), true
			}
			return fmt.Sprintf("Switched target channel to %s", value), true
		default:
			return fmt.Sprintf("Unknown switch target: %s", target), true
		}
	}

	return "", false
}

// extractPeer extracts the routing peer from inbound message metadata.
func extractPeer(msg bus.InboundMessage) *routing.RoutePeer {
	peerKind := msg.Metadata["peer_kind"]
	if peerKind == "" {
		return nil
	}
	peerID := msg.Metadata["peer_id"]
	if peerID == "" {
		if peerKind == "direct" {
			peerID = msg.SenderID
		} else {
			peerID = msg.ChatID
		}
	}
	return &routing.RoutePeer{Kind: peerKind, ID: peerID}
}

// extractParentPeer extracts the parent peer (reply-to) from inbound message metadata.
func extractParentPeer(msg bus.InboundMessage) *routing.RoutePeer {
	parentKind := msg.Metadata["parent_peer_kind"]
	parentID := msg.Metadata["parent_peer_id"]
	if parentKind == "" || parentID == "" {
		return nil
	}
	return &routing.RoutePeer{Kind: parentKind, ID: parentID}
}
