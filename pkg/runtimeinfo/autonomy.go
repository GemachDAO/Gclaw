package runtimeinfo

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/config"
)

// AutonomyStatus captures the agent's execution DNA, knowledge graph shape,
// and deterministic self-healing route selection.
type AutonomyStatus struct {
	Identity       AgentIdentityStatus     `json:"identity"`
	DNA            AgentDNA                `json:"dna"`
	KnowledgeGraph KnowledgeGraphStatus    `json:"knowledge_graph"`
	Router         SelfHealingRouterStatus `json:"router"`
}

// AgentIdentityStatus is a deterministic visual fingerprint for one agent.
type AgentIdentityStatus struct {
	Fingerprint string   `json:"fingerprint"`
	Signature   string   `json:"signature"`
	Palette     []string `json:"palette,omitempty"`
	Traits      []string `json:"traits,omitempty"`
}

// AgentDNA is the compact policy profile that governs autonomous behavior.
type AgentDNA struct {
	Objective            string   `json:"objective"`
	ProfitSink           string   `json:"profit_sink"`
	PreferredChains      []string `json:"preferred_chains,omitempty"`
	PreferredVenues      []string `json:"preferred_venues,omitempty"`
	SpotSpend            string   `json:"spot_spend,omitempty"`
	PerpExecutionModel   string   `json:"perp_execution_model,omitempty"`
	ReplicationThreshold int      `json:"replication_threshold"`
	RecodeThreshold      int      `json:"recode_threshold"`
	SwarmTarget          int      `json:"swarm_target"`
	StrategyRotation     bool     `json:"strategy_rotation"`
}

// KnowledgeGraphStatus summarizes the current entity/relationship graph the
// agent uses to reason about capital flows.
type KnowledgeGraphStatus struct {
	NodeCount int      `json:"node_count"`
	EdgeCount int      `json:"edge_count"`
	Domains   []string `json:"domains,omitempty"`
	KeyNodes  []string `json:"key_nodes,omitempty"`
}

// SelfHealingRouterStatus summarizes the weighted route graph and current
// selected route.
type SelfHealingRouterStatus struct {
	Objective     string              `json:"objective"`
	State         string              `json:"state"`
	SelectedRoute string              `json:"selected_route,omitempty"`
	FallbackRoute string              `json:"fallback_route,omitempty"`
	Routes        []RouteCandidate    `json:"routes,omitempty"`
	Health        []RouteHealthSignal `json:"health,omitempty"`
}

// RouteCandidate is one deterministic capital-allocation path through the graph.
type RouteCandidate struct {
	Name     string   `json:"name"`
	Summary  string   `json:"summary,omitempty"`
	State    string   `json:"state"`
	Cost     float64  `json:"cost,omitempty"`
	Selected bool     `json:"selected,omitempty"`
	Steps    []string `json:"steps,omitempty"`
	Blockers []string `json:"blockers,omitempty"`
}

// RouteHealthSignal is a health monitor input for the self-healing router.
type RouteHealthSignal struct {
	Name   string `json:"name"`
	State  string `json:"state"`
	Detail string `json:"detail,omitempty"`
}

type autonomyGraphEdge struct {
	ID          string
	From        string
	To          string
	Tool        string
	BaseCost    float64
	Available   bool
	Provisional bool
	Blocker     string
}

// BuildAutonomyStatus derives the agent DNA, lightweight knowledge graph, and
// selected/fallback execution routes from config plus current trading status.
func BuildAutonomyStatus(
	cfg *config.Config,
	trading *TradingStatus,
	totalFamily int,
	swarmMembers int,
	agentID string,
) *AutonomyStatus {
	if cfg == nil {
		return nil
	}
	if trading == nil {
		trading = BuildTradingStatus(cfg, nil)
	}

	dna := buildAgentDNA(cfg, trading)
	health := buildRouteHealth(trading)
	edges := buildAutonomyGraphEdges(cfg, trading)
	routes := buildRouteCandidates(edges)
	selected, fallback := selectRoutes(routes)
	routerState := classifyRouterState(selected, fallback)
	if selected != nil {
		for i := range routes {
			if routes[i].Name == selected.Name {
				routes[i].Selected = true
				break
			}
		}
	}

	return &AutonomyStatus{
		Identity:       buildAgentIdentity(agentID, dna, trading),
		DNA:            dna,
		KnowledgeGraph: buildKnowledgeGraph(dna, trading, routes, totalFamily, swarmMembers),
		Router: SelfHealingRouterStatus{
			Objective:     dna.Objective,
			State:         routerState,
			SelectedRoute: routeName(selected),
			FallbackRoute: routeName(fallback),
			Routes:        routes,
			Health:        health,
		},
	}
}

func buildAgentIdentity(agentID string, dna AgentDNA, trading *TradingStatus) AgentIdentityStatus {
	seedParts := []string{
		strings.ToLower(strings.TrimSpace(agentID)),
		strings.ToLower(strings.TrimSpace(dna.Objective)),
		strings.Join(dna.PreferredChains, ","),
		strings.Join(dna.PreferredVenues, ","),
	}

	if trading != nil {
		seedParts = append(seedParts, strings.ToLower(strings.TrimSpace(trading.WalletAddress)))
		if trading.ManagedWallets != nil {
			seedParts = append(seedParts,
				strings.ToLower(strings.TrimSpace(trading.ManagedWallets.EVMAddress)),
				strings.ToLower(strings.TrimSpace(trading.ManagedWallets.SolanaAddress)),
			)
		}
	}

	hash := sha256.Sum256([]byte(strings.Join(seedParts, "|")))
	raw := strings.ToUpper(hex.EncodeToString(hash[:8]))
	fingerprint := raw[:4] + "-" + raw[4:8] + "-" + raw[8:12] + "-" + raw[12:16]
	signature := fmt.Sprintf("HELIX-%02X%02X-%02X%02X", hash[8], hash[9], hash[10], hash[11])

	spineCount := 18 + int(hash[12]%8)
	twistStyle := []string{"calm coil", "wide helix", "tight braid", "phase-shifted ladder"}[int(hash[13])%4]
	temperament := []string{"patient", "adaptive", "aggressive", "disciplined"}[int(hash[14])%4]
	broodStyle := "fixed brood"
	if dna.StrategyRotation {
		broodStyle = "mutating brood"
	}

	return AgentIdentityStatus{
		Fingerprint: fingerprint,
		Signature:   signature,
		Palette:     paletteFromHash(hash),
		Traits: []string{
			fmt.Sprintf("%s stance", temperament),
			fmt.Sprintf("%d-rung spine", spineCount),
			twistStyle,
			broodStyle,
		},
	}
}

func paletteFromHash(hash [32]byte) []string {
	return []string{
		hslToHex(float64(hash[0])*360/255, 0.70, 0.56),
		hslToHex(float64(hash[1])*360/255, 0.78, 0.62),
		hslToHex(float64(hash[2])*360/255, 0.66, 0.48),
	}
}

func hslToHex(h, s, l float64) string {
	h = math.Mod(h, 360)
	if h < 0 {
		h += 360
	}
	s = clampFloat(s, 0, 1)
	l = clampFloat(l, 0, 1)

	c := (1 - math.Abs(2*l-1)) * s
	x := c * (1 - math.Abs(math.Mod(h/60, 2)-1))
	m := l - c/2

	var r, g, b float64
	switch {
	case h < 60:
		r, g, b = c, x, 0
	case h < 120:
		r, g, b = x, c, 0
	case h < 180:
		r, g, b = 0, c, x
	case h < 240:
		r, g, b = 0, x, c
	case h < 300:
		r, g, b = x, 0, c
	default:
		r, g, b = c, 0, x
	}

	return fmt.Sprintf("#%02x%02x%02x",
		int(math.Round((r+m)*255)),
		int(math.Round((g+m)*255)),
		int(math.Round((b+m)*255)),
	)
}

func clampFloat(v, minValue, maxValue float64) float64 {
	if v < minValue {
		return minValue
	}
	if v > maxValue {
		return maxValue
	}
	return v
}

func buildAgentDNA(cfg *config.Config, trading *TradingStatus) AgentDNA {
	chains := make([]string, 0, 4)
	for _, chainID := range preferredGMACChains(cfg.Tools.GDEX.DefaultChainID) {
		label := autoTradeChainLabel(chainID)
		if !containsString(chains, label) {
			chains = append(chains, label)
		}
	}

	venues := make([]string, 0, 3)
	if hasTradingTool(trading, "gdex_hl_create_order") || hasTradingTool(trading, "gdex_hl_deposit") {
		venues = append(venues, "hyperliquid_perps")
	}
	if hasTradingTool(trading, "gdex_bridge_estimate") || hasTradingTool(trading, "gdex_bridge_request") {
		venues = append(venues, "gdex_bridge")
	}
	if hasTradingTool(trading, "gdex_buy") {
		venues = append(venues, "gdex_spot")
	}

	return AgentDNA{
		Objective:            "profit_to_gmach",
		ProfitSink:           "GMAC inventory, replication capital, and self-recode budget",
		PreferredChains:      chains,
		PreferredVenues:      venues,
		SpotSpend:            FormatAutoTradeSpendAmount(cfg.Tools.GDEX.MaxTradeSizeSOL),
		PerpExecutionModel:   "position-sized HyperLiquid execution; explicit leverage update is not backend-controlled",
		ReplicationThreshold: cfg.Metabolism.Thresholds.Replicate,
		RecodeThreshold:      cfg.Metabolism.Thresholds.SelfRecode,
		SwarmTarget:          cfg.Swarm.MaxSwarmSize,
		StrategyRotation:     cfg.Swarm.StrategyRotation,
	}
}

func buildRouteHealth(trading *TradingStatus) []RouteHealthSignal {
	signals := []RouteHealthSignal{
		{
			Name:   "helpers",
			State:  boolState(trading != nil && trading.HelpersInstalled),
			Detail: "GDEX helper runtime availability",
		},
		{
			Name: "credentials",
			State: boolState(
				trading != nil && trading.APIKeyConfigured && trading.WalletAddress != "" && trading.HasPrivateKey,
			),
			Detail: "control wallet + API key readiness",
		},
		{
			Name:   "gmac_route",
			State:  boolState(hasGMACRoute(trading)),
			Detail: "direct GMAC accumulation path",
		},
		{
			Name: "bridge_flow",
			State: boolState(
				hasTradingTool(trading, "gdex_bridge_estimate") && hasTradingTool(trading, "gdex_bridge_request"),
			),
			Detail: "native cross-chain bridge legs",
		},
		{
			Name:   "hl_funding",
			State:  boolState(hasTradingTool(trading, "gdex_hl_deposit")),
			Detail: "HyperLiquid USDC funding leg, including optional Arbitrum ETH -> USDC auto-funding",
		},
		{
			Name:   "hl_execution",
			State:  provisionalState(hasTradingTool(trading, "gdex_hl_create_order")),
			Detail: "HyperLiquid order leg is wired. Unfunded HL accounts still need a settled USDC deposit before orders can execute; gdex_hl_deposit can auto-fund from Arbitrum ETH first.",
		},
	}

	if trading != nil && trading.ManagedWallets != nil {
		state := trading.ManagedWallets.State
		if state == "" {
			state = "provisional"
		}
		signals = append(signals, RouteHealthSignal{
			Name:   "managed_wallets",
			State:  state,
			Detail: "backend-managed wallet resolution",
		})
	} else {
		signals = append(signals, RouteHealthSignal{
			Name:   "managed_wallets",
			State:  "provisional",
			Detail: "managed wallet lookup not populated yet",
		})
	}

	return signals
}

func buildAutonomyGraphEdges(cfg *config.Config, trading *TradingStatus) []autonomyGraphEdge {
	helpersReady := trading != nil && trading.HelpersInstalled
	credsReady := trading != nil && trading.APIKeyConfigured && trading.WalletAddress != "" && trading.HasPrivateKey
	gmacReady := hasGMACRoute(trading)
	managedReady := trading != nil && trading.ManagedWallets != nil && trading.ManagedWallets.State == "ready"

	return []autonomyGraphEdge{
		{
			ID:        "spot_buy",
			From:      "capital",
			To:        "spot_market",
			Tool:      "gdex_buy",
			BaseCost:  4.0,
			Available: helpersReady && credsReady && gmacReady && hasTradingTool(trading, "gdex_buy"),
			Blocker: firstMissingAutonomyBlocker(
				helpersReady,
				credsReady,
				gmacReady,
				hasTradingTool(trading, "gdex_buy"),
			),
		},
		{
			ID:        "settle_gmac",
			From:      "spot_market",
			To:        "gmac_inventory",
			BaseCost:  0.4,
			Available: gmacReady,
			Blocker:   ternaryString(gmacReady, "", "GMAC accumulation target not configured"),
		},
		{
			ID:        "bridge_estimate",
			From:      "capital",
			To:        "bridge_quote",
			Tool:      "gdex_bridge_estimate",
			BaseCost:  0.8,
			Available: helpersReady && credsReady && hasTradingTool(trading, "gdex_bridge_estimate"),
			Blocker: firstMissingAutonomyBlocker(
				helpersReady,
				credsReady,
				hasTradingTool(trading, "gdex_bridge_estimate"),
			),
		},
		{
			ID:        "bridge_request",
			From:      "bridge_quote",
			To:        "bridge_transfer",
			Tool:      "gdex_bridge_request",
			BaseCost:  1.2,
			Available: helpersReady && credsReady && hasTradingTool(trading, "gdex_bridge_request"),
			Blocker: firstMissingAutonomyBlocker(
				helpersReady,
				credsReady,
				hasTradingTool(trading, "gdex_bridge_request"),
			),
		},
		{
			ID:          "hl_deposit",
			From:        "bridge_transfer",
			To:          "hl_balance",
			Tool:        "gdex_hl_deposit",
			BaseCost:    1.1,
			Available:   helpersReady && credsReady && hasTradingTool(trading, "gdex_hl_deposit"),
			Provisional: !managedReady,
			Blocker: firstMissingAutonomyBlocker(
				helpersReady,
				credsReady,
				hasTradingTool(trading, "gdex_hl_deposit"),
			),
		},
		{
			ID:          "hl_trade",
			From:        "hl_balance",
			To:          "hl_profit",
			Tool:        "gdex_hl_create_order",
			BaseCost:    1.0,
			Available:   helpersReady && credsReady && hasTradingTool(trading, "gdex_hl_create_order"),
			Provisional: true,
			Blocker: firstMissingAutonomyBlocker(
				helpersReady,
				credsReady,
				hasTradingTool(trading, "gdex_hl_create_order"),
			),
		},
		{
			ID:        "profit_to_spot",
			From:      "hl_profit",
			To:        "spot_market",
			Tool:      "gdex_buy",
			BaseCost:  0.9,
			Available: helpersReady && credsReady && gmacReady && hasTradingTool(trading, "gdex_buy"),
			Blocker: firstMissingAutonomyBlocker(
				helpersReady,
				credsReady,
				gmacReady,
				hasTradingTool(trading, "gdex_buy"),
			),
		},
	}
}

func buildRouteCandidates(edges []autonomyGraphEdge) []RouteCandidate {
	edgeByID := make(map[string]autonomyGraphEdge, len(edges))
	graph := make(map[string][]autonomyGraphEdge)
	for _, edge := range edges {
		edgeByID[edge.ID] = edge
		if edge.Available {
			graph[edge.From] = append(graph[edge.From], edge)
		}
	}

	candidates := []RouteCandidate{
		evaluateRouteCandidate(
			"spot_gmac_direct",
			"Use direct GDEX spot buys to compound into GMAC inventory.",
			[]string{"capital", "gdex_buy", "GMAC inventory"},
			[]string{"spot_buy", "settle_gmac"},
			edgeByID,
		),
		evaluateRouteCandidate(
			"hyperliquid_profit_loop",
			"Bridge capital, auto-fund HyperLiquid from Arbitrum ETH or USDC, trade perps, then recycle profits into GMAC.",
			[]string{
				"capital",
				"gdex_bridge_estimate",
				"gdex_bridge_request",
				"gdex_hl_deposit",
				"gdex_hl_create_order",
				"gdex_buy",
				"GMAC inventory",
			},
			[]string{"bridge_estimate", "bridge_request", "hl_deposit", "hl_trade", "profit_to_spot", "settle_gmac"},
			edgeByID,
		),
	}

	if _, _, ok := shortestPath(graph, "capital", "gmac_inventory"); ok {
		sort.SliceStable(candidates, func(i, j int) bool {
			if candidates[i].State == "blocked" && candidates[j].State != "blocked" {
				return false
			}
			if candidates[i].State != "blocked" && candidates[j].State == "blocked" {
				return true
			}
			return candidates[i].Cost < candidates[j].Cost
		})
	}

	return candidates
}

func evaluateRouteCandidate(
	name string,
	summary string,
	steps []string,
	edgeIDs []string,
	edgeByID map[string]autonomyGraphEdge,
) RouteCandidate {
	route := RouteCandidate{
		Name:    name,
		Summary: summary,
		Steps:   steps,
		State:   "ready",
	}
	totalCost := 0.0
	var blockers []string
	var degraded bool
	for _, edgeID := range edgeIDs {
		edge, ok := edgeByID[edgeID]
		if !ok {
			blockers = append(blockers, "missing graph edge "+edgeID)
			continue
		}
		if !edge.Available {
			if edge.Blocker != "" {
				blockers = append(blockers, edge.Blocker)
			} else {
				blockers = append(blockers, edge.Tool+" unavailable")
			}
			continue
		}
		totalCost += weightedRouteCost(edge)
		if edge.Provisional {
			degraded = true
		}
	}
	route.Blockers = uniqueStrings(blockers)
	if len(route.Blockers) > 0 {
		route.State = "blocked"
		return route
	}
	route.Cost = totalCost
	if degraded {
		route.State = "degraded"
	}
	return route
}

func selectRoutes(routes []RouteCandidate) (*RouteCandidate, *RouteCandidate) {
	var selected *RouteCandidate
	var fallback *RouteCandidate
	for i := range routes {
		route := &routes[i]
		if route.State == "blocked" {
			continue
		}
		if selected == nil {
			selected = route
			continue
		}
		fallback = route
		break
	}
	return selected, fallback
}

func classifyRouterState(selected, fallback *RouteCandidate) string {
	switch {
	case selected == nil:
		return "blocked"
	case selected.State == "degraded":
		return "degraded"
	case fallback != nil:
		return "self-healing"
	default:
		return "single-path"
	}
}

func buildKnowledgeGraph(
	dna AgentDNA,
	trading *TradingStatus,
	routes []RouteCandidate,
	totalFamily int,
	swarmMembers int,
) KnowledgeGraphStatus {
	nodeSet := map[string]struct{}{}
	edgeSet := map[string]struct{}{}
	keyNodes := make([]string, 0, 8)
	domains := []string{"wallets", "chains", "venues", "routes", "lineage"}

	addNode := func(name string, key bool) {
		if strings.TrimSpace(name) == "" {
			return
		}
		if _, ok := nodeSet[name]; ok {
			return
		}
		nodeSet[name] = struct{}{}
		if key && len(keyNodes) < 8 {
			keyNodes = append(keyNodes, name)
		}
	}
	addEdge := func(from, to string) {
		if from == "" || to == "" {
			return
		}
		edgeSet[from+"->"+to] = struct{}{}
	}

	addNode("objective:profit_to_gmach", true)
	addNode("asset:GMAC", true)
	addEdge("objective:profit_to_gmach", "asset:GMAC")

	if trading != nil {
		if trading.WalletAddress != "" {
			addNode("wallet:control:"+ShortAddress(trading.WalletAddress), true)
			addEdge("wallet:control:"+ShortAddress(trading.WalletAddress), "objective:profit_to_gmach")
		}
		if mw := trading.ManagedWallets; mw != nil {
			if mw.EVMAddress != "" {
				addNode("wallet:managed_evm:"+ShortAddress(mw.EVMAddress), true)
				addEdge(
					"wallet:control:"+ShortAddress(trading.WalletAddress),
					"wallet:managed_evm:"+ShortAddress(mw.EVMAddress),
				)
			}
			if mw.SolanaAddress != "" {
				addNode("wallet:managed_solana:"+ShortAddress(mw.SolanaAddress), true)
				addEdge(
					"wallet:control:"+ShortAddress(trading.WalletAddress),
					"wallet:managed_solana:"+ShortAddress(mw.SolanaAddress),
				)
			}
		}
	}

	for _, chain := range dna.PreferredChains {
		addNode("chain:"+chain, false)
		addEdge("objective:profit_to_gmach", "chain:"+chain)
	}
	for _, venue := range dna.PreferredVenues {
		addNode("venue:"+venue, true)
		addEdge("objective:profit_to_gmach", "venue:"+venue)
	}
	for _, route := range routes {
		addNode("route:"+route.Name, false)
		addEdge("objective:profit_to_gmach", "route:"+route.Name)
		for i := 0; i < len(route.Steps)-1; i++ {
			addEdge(route.Steps[i], route.Steps[i+1])
			addNode(route.Steps[i], false)
			addNode(route.Steps[i+1], false)
		}
	}
	if totalFamily > 0 {
		familyNode := "family:size"
		addNode(familyNode, true)
		addEdge("objective:profit_to_gmach", familyNode)
	}
	if swarmMembers > 0 {
		swarmNode := "swarm:members"
		addNode(swarmNode, true)
		addEdge("objective:profit_to_gmach", swarmNode)
	}

	sort.Strings(domains)
	return KnowledgeGraphStatus{
		NodeCount: len(nodeSet),
		EdgeCount: len(edgeSet),
		Domains:   domains,
		KeyNodes:  keyNodes,
	}
}

func weightedRouteCost(edge autonomyGraphEdge) float64 {
	if !edge.Available {
		return math.Inf(1)
	}
	if edge.Provisional {
		return edge.BaseCost + 5
	}
	return edge.BaseCost
}

func shortestPath(
	graph map[string][]autonomyGraphEdge,
	start string,
	goal string,
) (float64, []string, bool) {
	dist := map[string]float64{start: 0}
	prev := map[string]string{}
	unvisited := map[string]struct{}{start: {}}

	for len(unvisited) > 0 {
		current := ""
		best := math.Inf(1)
		for node := range unvisited {
			if d := dist[node]; d < best {
				best = d
				current = node
			}
		}
		delete(unvisited, current)
		if current == goal {
			break
		}

		for _, edge := range graph[current] {
			weight := weightedRouteCost(edge)
			if math.IsInf(weight, 1) {
				continue
			}
			next := dist[current] + weight
			if old, ok := dist[edge.To]; !ok || next < old {
				dist[edge.To] = next
				prev[edge.To] = current
				unvisited[edge.To] = struct{}{}
			}
		}
	}

	best, ok := dist[goal]
	if !ok {
		return 0, nil, false
	}

	path := []string{goal}
	for node := goal; node != start; {
		parent, ok := prev[node]
		if !ok {
			return 0, nil, false
		}
		path = append([]string{parent}, path...)
		node = parent
	}
	return best, path, true
}

func hasGMACRoute(trading *TradingStatus) bool {
	return trading != nil &&
		trading.AutoTradePlan != nil &&
		strings.EqualFold(strings.TrimSpace(trading.AutoTradePlan.AssetSymbol), "GMAC") &&
		strings.TrimSpace(trading.AutoTradePlan.AssetAddress) != ""
}

func hasTradingTool(trading *TradingStatus, name string) bool {
	if trading == nil {
		return false
	}
	for _, tool := range trading.Tools {
		if tool == name {
			return true
		}
	}
	return false
}

func firstMissingAutonomyBlocker(values ...bool) string {
	for _, value := range values {
		if value {
			continue
		}
		switch {
		case len(values) > 0 && !values[0]:
			return "GDEX helper runtime is not ready"
		case len(values) > 1 && !values[1]:
			return "control wallet or API key is not configured"
		case len(values) > 2 && !values[2]:
			return "required route capability is not available"
		default:
			return "route requirement missing"
		}
	}
	return ""
}

func routeName(route *RouteCandidate) string {
	if route == nil {
		return ""
	}
	return route.Name
}

func boolState(v bool) string {
	if v {
		return "ready"
	}
	return "blocked"
}

func provisionalState(v bool) string {
	if v {
		return "provisional"
	}
	return "blocked"
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func uniqueStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	seen := make(map[string]struct{}, len(values))
	out := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	return out
}

func ternaryString(condition bool, ifTrue, ifFalse string) string {
	if condition {
		return ifTrue
	}
	return ifFalse
}
