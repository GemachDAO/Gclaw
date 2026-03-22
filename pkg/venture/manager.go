package venture

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

const (
	DefaultBurnAllocationPct = 10.0
	defaultReviewCron        = "0 */6 * * *"
)

// RecoderHooks captures the self-modification hooks the venture manager uses
// to keep ventures alive once the architect tier is unlocked.
type RecoderHooks interface {
	ModifySystemPrompt(addition string) error
	AddCronJob(schedule, task string) error
}

// LaunchContext captures the runtime state used to decide whether the agent is
// ready to launch a higher-order venture.
type LaunchContext struct {
	AgentID      string
	Goodwill     int
	Balance      float64
	Threshold    int
	FamilySize   int
	SwarmMembers int
	Trading      *runtimeinfo.TradingStatus
	Autonomy     *runtimeinfo.AutonomyStatus
}

// State persists venture history and the currently active venture.
type State struct {
	Threshold     int       `json:"threshold"`
	ActiveID      string    `json:"active_id,omitempty"`
	LastEvaluated int64     `json:"last_evaluated,omitempty"`
	Ventures      []Venture `json:"ventures,omitempty"`
}

// Venture is one launched venture blueprint.
type Venture struct {
	ID                    string   `json:"id"`
	Title                 string   `json:"title"`
	Archetype             string   `json:"archetype"`
	Status                string   `json:"status"`
	Chain                 string   `json:"chain"`
	Venue                 string   `json:"venue"`
	DeploymentMode        string   `json:"deployment_mode"`
	ContractSystem        string   `json:"contract_system"`
	ProfitModel           string   `json:"profit_model"`
	BurnPolicy            string   `json:"burn_policy"`
	LaunchReason          string   `json:"launch_reason"`
	NextAction            string   `json:"next_action"`
	ReviewCron            string   `json:"review_cron,omitempty"`
	ManifestPath          string   `json:"manifest_path,omitempty"`
	PlaybookPath          string   `json:"playbook_path,omitempty"`
	ContractPath          string   `json:"contract_path,omitempty"`
	FoundryProjectPath    string   `json:"foundry_project_path,omitempty"`
	PromptDirective       string   `json:"prompt_directive,omitempty"`
	RequiredTools         []string `json:"required_tools,omitempty"`
	TriggerGoodwill       int      `json:"trigger_goodwill"`
	TriggerBalanceGMAC    float64  `json:"trigger_balance_gmac"`
	FamilyAtLaunch        int      `json:"family_at_launch"`
	SwarmAtLaunch         int      `json:"swarm_at_launch"`
	BurnAllocationPct     float64  `json:"burn_allocation_pct"`
	RealizedProfitUSD     float64  `json:"realized_profit_usd"`
	BurnAllocationUSD     float64  `json:"burn_allocation_usd"`
	ContractScaffoldReady bool     `json:"contract_scaffold_ready"`
	FoundryAvailable      bool     `json:"foundry_available"`
	RPCConfigured         bool     `json:"rpc_configured"`
	WalletReady           bool     `json:"wallet_ready"`
	RPCEnvVar             string   `json:"rpc_env_var,omitempty"`
	ForgeBinaryPath       string   `json:"forge_binary_path,omitempty"`
	OwnerAddress          string   `json:"owner_address,omitempty"`
	DeploymentState       string   `json:"deployment_state,omitempty"`
	DeployedAddress       string   `json:"deployed_address,omitempty"`
	DeploymentTxHash      string   `json:"deployment_tx_hash,omitempty"`
	DeployError           string   `json:"deploy_error,omitempty"`
	LastDeployAttempt     int64    `json:"last_deploy_attempt,omitempty"`
	CreatedAt             int64    `json:"created_at"`
	UpdatedAt             int64    `json:"updated_at"`
}

// Snapshot is a dashboard-friendly view of venture state.
type Snapshot struct {
	Unlocked               bool      `json:"unlocked"`
	Threshold              int       `json:"threshold"`
	CurrentGoodwill        int       `json:"current_goodwill"`
	LaunchReady            bool      `json:"launch_ready"`
	TotalVentures          int       `json:"total_ventures"`
	TotalProfitUSD         float64   `json:"total_profit_usd"`
	TotalBurnAllocationUSD float64   `json:"total_burn_allocation_usd"`
	BurnPolicy             string    `json:"burn_policy,omitempty"`
	Active                 *Venture  `json:"active,omitempty"`
	Recent                 []Venture `json:"recent,omitempty"`
}

// Manager owns persisted venture launch state for one workspace.
type Manager struct {
	workspace string
	recoder   RecoderHooks
	deployer  *ForgeDeployer
	mu        sync.Mutex
}

// NewManager creates a venture manager for one agent workspace.
func NewManager(workspace string, recoder RecoderHooks) *Manager {
	return &Manager{
		workspace: strings.TrimSpace(workspace),
		recoder:   recoder,
	}
}

// SetDeployer wires an optional live Foundry deployer into the manager.
func (m *Manager) SetDeployer(deployer *ForgeDeployer) {
	if m == nil {
		return
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.deployer = deployer
}

// EnsureAutonomousLaunch launches a venture blueprint once the architect tier
// is unlocked and no active venture exists yet.
func (m *Manager) EnsureAutonomousLaunch(ctx LaunchContext) (*Venture, bool, error) {
	if strings.TrimSpace(m.workspace) == "" {
		return nil, false, fmt.Errorf("venture workspace not configured")
	}
	if ctx.Threshold <= 0 || ctx.Goodwill < ctx.Threshold {
		return nil, false, nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	state, err := m.loadStateLocked()
	if err != nil {
		return nil, false, err
	}
	state.Threshold = ctx.Threshold
	state.LastEvaluated = time.Now().UnixMilli()

	if active := activeVenture(state); active != nil {
		if err := m.saveStateLocked(state); err != nil {
			return nil, false, err
		}
		return active, false, nil
	}

	candidate := chooseCandidate(ctx)
	now := time.Now().UnixMilli()
	id := fmt.Sprintf("venture-%d-%s", now, slugify(candidate.Archetype))
	dir := filepath.Join(m.workspace, "ventures", id)
	manifestPath := filepath.Join(dir, "manifest.json")
	playbookPath := filepath.Join(dir, "PLAYBOOK.md")
	contractPath := filepath.Join(dir, "contracts", candidate.ContractSystem+".sol")
	foundryPath := filepath.Join(dir, "foundry.toml")

	venture := Venture{
		ID:                    id,
		Title:                 candidate.Title,
		Archetype:             candidate.Archetype,
		Status:                "live_strategy",
		Chain:                 candidate.Chain,
		Venue:                 candidate.Venue,
		DeploymentMode:        candidate.DeploymentMode,
		ContractSystem:        candidate.ContractSystem,
		ProfitModel:           candidate.ProfitModel,
		BurnPolicy:            fmt.Sprintf("Route %.0f%% of realized venture profit into GMAC buy-and-burn on Ethereum.", DefaultBurnAllocationPct),
		LaunchReason:          candidate.LaunchReason,
		NextAction:            candidate.NextAction,
		ReviewCron:            defaultReviewCron,
		ManifestPath:          manifestPath,
		PlaybookPath:          playbookPath,
		ContractPath:          contractPath,
		FoundryProjectPath:    dir,
		PromptDirective:       candidate.PromptDirective,
		RequiredTools:         append([]string(nil), candidate.RequiredTools...),
		TriggerGoodwill:       ctx.Goodwill,
		TriggerBalanceGMAC:    ctx.Balance,
		FamilyAtLaunch:        ctx.FamilySize,
		SwarmAtLaunch:         ctx.SwarmMembers,
		BurnAllocationPct:     DefaultBurnAllocationPct,
		ContractScaffoldReady: true,
		DeploymentState:       "scaffold_only",
		CreatedAt:             now,
		UpdatedAt:             now,
	}

	if err := os.MkdirAll(filepath.Dir(contractPath), 0o755); err != nil {
		return nil, false, err
	}
	if err := os.WriteFile(foundryPath, []byte(renderFoundryToml()), 0o644); err != nil {
		return nil, false, err
	}
	if err := writeJSONFile(manifestPath, venture); err != nil {
		return nil, false, err
	}
	if err := os.WriteFile(playbookPath, []byte(renderPlaybook(venture)), 0o644); err != nil {
		return nil, false, err
	}
	if err := os.WriteFile(contractPath, []byte(renderContractScaffold(venture)), 0o644); err != nil {
		return nil, false, err
	}
	if m.deployer != nil {
		m.deployer.ApplyReadiness(&venture)
		if venture.DeploymentState == "deploy_ready" {
			if err := m.deployer.Deploy(&venture); err != nil {
				venture.DeployError = strings.TrimSpace(firstNonEmpty(venture.DeployError, err.Error()))
			}
		}
	}

	if m.recoder != nil {
		if strings.TrimSpace(venture.PromptDirective) != "" {
			_ = m.recoder.ModifySystemPrompt(venture.PromptDirective)
		}
		_ = m.recoder.AddCronJob(defaultReviewCron,
			fmt.Sprintf("Review venture %s metrics, protect treasury, and route 10%% of realized venture profits into GMAC buy-and-burn on Ethereum.", venture.ID))
	}

	state.ActiveID = venture.ID
	state.Ventures = append(state.Ventures, venture)
	if err := m.saveStateLocked(state); err != nil {
		return nil, false, err
	}

	return &venture, true, nil
}

// Deploy deploys an existing venture contract scaffold live on chain.
func (m *Manager) Deploy(id string) (*Venture, error) {
	if strings.TrimSpace(id) == "" {
		return nil, fmt.Errorf("venture id is required")
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if m.deployer == nil {
		return nil, fmt.Errorf("venture deployer not configured")
	}
	state, err := m.loadStateLocked()
	if err != nil {
		return nil, err
	}
	idx := findVentureIndex(state, id)
	if idx < 0 {
		return nil, fmt.Errorf("venture %q not found", id)
	}
	m.deployer.ApplyReadiness(&state.Ventures[idx])
	if err := m.deployer.Deploy(&state.Ventures[idx]); err != nil {
		state.Ventures[idx].UpdatedAt = time.Now().UnixMilli()
		_ = writeJSONFile(state.Ventures[idx].ManifestPath, state.Ventures[idx])
		_ = m.saveStateLocked(state)
		return nil, err
	}
	state.Ventures[idx].UpdatedAt = time.Now().UnixMilli()
	if err := writeJSONFile(state.Ventures[idx].ManifestPath, state.Ventures[idx]); err != nil {
		return nil, err
	}
	if err := m.saveStateLocked(state); err != nil {
		return nil, err
	}
	updated := state.Ventures[idx]
	return &updated, nil
}

// RecordProfit records realized venture profit and the matching GMAC burn allocation.
func (m *Manager) RecordProfit(id string, amountUSD float64) (*Venture, error) {
	if amountUSD <= 0 {
		return nil, fmt.Errorf("profit amount must be positive")
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	state, err := m.loadStateLocked()
	if err != nil {
		return nil, err
	}
	idx := findVentureIndex(state, id)
	if idx < 0 {
		return nil, fmt.Errorf("venture %q not found", id)
	}
	state.Ventures[idx].RealizedProfitUSD += amountUSD
	state.Ventures[idx].BurnAllocationUSD += amountUSD * (state.Ventures[idx].BurnAllocationPct / 100)
	state.Ventures[idx].UpdatedAt = time.Now().UnixMilli()
	if err := writeJSONFile(state.Ventures[idx].ManifestPath, state.Ventures[idx]); err != nil {
		return nil, err
	}
	if err := m.saveStateLocked(state); err != nil {
		return nil, err
	}
	updated := state.Ventures[idx]
	return &updated, nil
}

// Snapshot returns the current venture status for dashboards and tools.
func (m *Manager) Snapshot(ctx LaunchContext) (*Snapshot, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	state, err := m.loadStateLocked()
	if err != nil {
		return nil, err
	}

	snap := &Snapshot{
		Unlocked:        ctx.Threshold > 0 && ctx.Goodwill >= ctx.Threshold,
		Threshold:       ctx.Threshold,
		CurrentGoodwill: ctx.Goodwill,
		LaunchReady:     ctx.Threshold > 0 && ctx.Goodwill >= ctx.Threshold && activeVenture(state) == nil,
		TotalVentures:   len(state.Ventures),
		BurnPolicy:      fmt.Sprintf("Route %.0f%% of realized venture profit into GMAC buy-and-burn on Ethereum.", DefaultBurnAllocationPct),
	}

	if active := activeVenture(state); active != nil {
		if m.deployer != nil {
			m.deployer.ApplyReadiness(active)
		}
		copyActive := *active
		snap.Active = &copyActive
	}

	if len(state.Ventures) > 0 {
		start := 0
		if len(state.Ventures) > 3 {
			start = len(state.Ventures) - 3
		}
		snap.Recent = append([]Venture(nil), state.Ventures[start:]...)
	}

	for _, venture := range state.Ventures {
		snap.TotalProfitUSD += venture.RealizedProfitUSD
		snap.TotalBurnAllocationUSD += venture.BurnAllocationUSD
	}
	sort.SliceStable(snap.Recent, func(i, j int) bool {
		return snap.Recent[i].CreatedAt > snap.Recent[j].CreatedAt
	})
	if m.deployer != nil {
		for i := range snap.Recent {
			m.deployer.ApplyReadiness(&snap.Recent[i])
		}
	}

	return snap, nil
}

type candidate struct {
	Title           string
	Archetype       string
	Chain           string
	Venue           string
	DeploymentMode  string
	ContractSystem  string
	ProfitModel     string
	LaunchReason    string
	NextAction      string
	PromptDirective string
	RequiredTools   []string
}

func chooseCandidate(ctx LaunchContext) candidate {
	trading := ctx.Trading
	autonomy := ctx.Autonomy

	hasHL := hasTool(trading, "gdex_hl_create_order") && hasTool(trading, "gdex_hl_deposit")
	hasBridge := hasTool(trading, "gdex_bridge_request")
	hasSpot := hasTool(trading, "gdex_buy") && hasTool(trading, "gdex_sell")
	hasSignals := hasTool(trading, "gdex_scan") && hasTool(trading, "gdex_trending")

	switch {
	case hasHL && hasBridge && ctx.SwarmMembers >= 2:
		return candidate{
			Title:           "Cross-Chain Basis Desk",
			Archetype:       "cross_chain_basis_desk",
			Chain:           "Arbitrum",
			Venue:           "hyperliquid_perps",
			DeploymentMode:  "live_strategy + contract_scaffold",
			ContractSystem:  "BasisTreasuryRouter",
			ProfitModel:     "Bridge capital to Arbitrum, hedge liquid perp exposure, and recycle realized basis into GMAC treasury growth.",
			LaunchReason:    "HyperLiquid, bridge flow, and swarm coordination are all available, so the runtime can support a multi-leg basis desk.",
			NextAction:      "Keep the contract scaffold ready for on-chain treasury routing while the live strategy manages inventory and settlement.",
			PromptDirective: "Operate an active cross-chain basis desk: protect treasury, bridge only when edge is clear, and route 10% of realized venture profit into GMAC buy-and-burn on Ethereum.",
			RequiredTools:   []string{"gdex_bridge_request", "gdex_hl_deposit", "gdex_hl_create_order"},
		}
	case hasSignals && ctx.FamilySize >= 2:
		return candidate{
			Title:           "Swarm Signal Vault",
			Archetype:       "swarm_signal_vault",
			Chain:           preferredChain(autonomy, "Ethereum"),
			Venue:           "gdex_spot",
			DeploymentMode:  "live_strategy + contract_scaffold",
			ContractSystem:  "SwarmSignalVault",
			ProfitModel:     "Aggregate swarm signals into treasury-managed spot entries, harvest winners, and rotate realized gains into GMAC.",
			LaunchReason:    "The family has diversified signal producers, so a strategy vault can formalize execution and profit routing.",
			NextAction:      "Monitor signal quality, keep trade size bounded, and escalate to on-chain vault deployment once treasury conditions justify it.",
			PromptDirective: "Run the swarm signal vault as a treasury strategy: only promote signals with real liquidity and route 10% of realized venture profit into GMAC buy-and-burn on Ethereum.",
			RequiredTools:   []string{"gdex_scan", "gdex_trending", "gdex_buy", "gdex_sell"},
		}
	case hasBridge && hasSpot:
		return candidate{
			Title:           "GMAC Treasury Router",
			Archetype:       "gmac_treasury_router",
			Chain:           preferredChain(autonomy, "Ethereum"),
			Venue:           "gdex_bridge + gdex_spot",
			DeploymentMode:  "live_strategy + contract_scaffold",
			ContractSystem:  "GMACBurnTreasury",
			ProfitModel:     "Move treasury to the best chain, harvest relative pricing, and convert the burn allocation into GMAC on Ethereum.",
			LaunchReason:    "Bridge and spot execution are live, which is enough to run a treasury router that compounds into GMAC.",
			NextAction:      "Exploit spread and liquidity differences conservatively, then buy and burn GMAC from the venture allocation.",
			PromptDirective: "Operate the GMAC treasury router conservatively: defend runway first, route 10% of realized venture profit into GMAC buy-and-burn on Ethereum, and keep contract scaffolds current.",
			RequiredTools:   []string{"gdex_bridge_request", "gdex_buy", "gdex_sell"},
		}
	default:
		return candidate{
			Title:           "Stable Yield Router",
			Archetype:       "stable_yield_router",
			Chain:           preferredChain(autonomy, "Arbitrum"),
			Venue:           "gdex_spot",
			DeploymentMode:  "live_strategy + contract_scaffold",
			ContractSystem:  "StableYieldRouter",
			ProfitModel:     "Run treasury-aware stable rotations and convert a fixed venture slice into GMAC burn inventory.",
			LaunchReason:    "The runtime has enough autonomy to stage a conservative treasury venture even before more advanced perps or swarm routes dominate.",
			NextAction:      "Prefer durable flows over spectacle: stable treasury gains that keep the agent alive long enough to spawn stronger children.",
			PromptDirective: "Operate a conservative stable-yield venture, minimize hidden risk, and route 10% of realized venture profit into GMAC buy-and-burn on Ethereum.",
			RequiredTools:   []string{"gdex_buy", "gdex_sell"},
		}
	}
}

func preferredChain(autonomy *runtimeinfo.AutonomyStatus, fallback string) string {
	if autonomy == nil || len(autonomy.DNA.PreferredChains) == 0 {
		return fallback
	}
	return autonomy.DNA.PreferredChains[0]
}

func hasTool(trading *runtimeinfo.TradingStatus, name string) bool {
	if trading == nil {
		return false
	}
	for _, tool := range trading.Tools {
		if strings.EqualFold(strings.TrimSpace(tool), strings.TrimSpace(name)) {
			return true
		}
	}
	return false
}

func activeVenture(state *State) *Venture {
	if state == nil {
		return nil
	}
	idx := findVentureIndex(state, state.ActiveID)
	if idx < 0 {
		return nil
	}
	return &state.Ventures[idx]
}

func findVentureIndex(state *State, id string) int {
	if state == nil || strings.TrimSpace(id) == "" {
		return -1
	}
	for i := range state.Ventures {
		if state.Ventures[i].ID == id {
			return i
		}
	}
	return -1
}

func (m *Manager) loadStateLocked() (*State, error) {
	path := filepath.Join(m.workspace, "ventures", "state.json")
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return &State{}, nil
		}
		return nil, err
	}
	var state State
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, err
	}
	return &state, nil
}

func (m *Manager) saveStateLocked(state *State) error {
	if state == nil {
		state = &State{}
	}
	path := filepath.Join(m.workspace, "ventures", "state.json")
	return writeJSONFile(path, state)
}

func writeJSONFile(path string, value any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func renderPlaybook(v Venture) string {
	return fmt.Sprintf(`# %s

- ID: %s
- Archetype: %s
- Chain: %s
- Venue: %s
- Deployment Mode: %s
- Contract System: %s
- Profit Model: %s
- Burn Policy: %s
- Review Cron: %s

## Launch Reason

%s

## Next Action

%s

## Treasury Rule

Protect runway first. Route %.0f%% of realized venture profit into GMAC buy-and-burn on Ethereum. Do not starve the core agent to feed a venture that is not working.
`, v.Title, v.ID, v.Archetype, v.Chain, v.Venue, v.DeploymentMode, v.ContractSystem, v.ProfitModel, v.BurnPolicy, v.ReviewCron, v.LaunchReason, v.NextAction, v.BurnAllocationPct)
}

func renderFoundryToml() string {
	return `[profile.default]
src = "contracts"
out = "out"
libs = []
solc_version = "0.8.24"
optimizer = true
optimizer_runs = 200
`
}

func renderContractScaffold(v Venture) string {
	name := sanitizeIdentifier(v.ContractSystem)
	return fmt.Sprintf(`// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title %s
/// @notice Autogenerated venture scaffold for %s.
/// @dev This scaffold defines treasury ownership, profit accounting, and the
/// burn-allocation policy. Strategy-specific execution modules should be added
/// before a real on-chain deployment.
contract %s {
    address public owner;
    uint256 public totalRealizedProfitUsd;
    uint256 public totalBurnAllocationUsd;

    event VentureProfitRecorded(uint256 profitUsd, uint256 burnAllocationUsd);
    event OwnershipTransferred(address indexed oldOwner, address indexed newOwner);

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    constructor(address owner_) {
        require(owner_ != address(0), "owner=0");
        owner = owner_;
        emit OwnershipTransferred(address(0), owner_);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "owner=0");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function recordProfit(uint256 profitUsd, uint256 burnAllocationUsd) external onlyOwner {
        totalRealizedProfitUsd += profitUsd;
        totalBurnAllocationUsd += burnAllocationUsd;
        emit VentureProfitRecorded(profitUsd, burnAllocationUsd);
    }
}
`, name, v.Title, name)
}

func sanitizeIdentifier(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return "VentureScaffold"
	}
	var out strings.Builder
	makeUpper := true
	for _, r := range value {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') {
			if makeUpper && r >= 'a' && r <= 'z' {
				r = r - 'a' + 'A'
			}
			if makeUpper && r >= 'A' && r <= 'Z' {
				out.WriteRune(r)
			} else {
				out.WriteRune(r)
			}
			makeUpper = false
			continue
		}
		makeUpper = true
	}
	result := out.String()
	if result == "" {
		return "VentureScaffold"
	}
	return result
}

func slugify(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	value = strings.ReplaceAll(value, " ", "-")
	value = strings.ReplaceAll(value, "_", "-")
	var out strings.Builder
	lastDash := false
	for _, r := range value {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			out.WriteRune(r)
			lastDash = false
			continue
		}
		if !lastDash {
			out.WriteByte('-')
			lastDash = true
		}
	}
	return strings.Trim(out.String(), "-")
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" {
			return value
		}
	}
	return ""
}
