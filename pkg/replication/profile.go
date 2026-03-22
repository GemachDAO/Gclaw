package replication

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

// ReplicateOptions carries user-supplied replication hints.
type ReplicateOptions struct {
	Name         string
	StrategyHint string
}

// ChildStrategyProfile is the persisted trading DNA assigned to a child.
type ChildStrategyProfile struct {
	Label           string   `json:"label,omitempty"`
	Fingerprint     string   `json:"fingerprint,omitempty"`
	Style           string   `json:"style"`
	Role            string   `json:"role"`
	RiskProfile     string   `json:"risk_profile"`
	PreferredChains []int64  `json:"preferred_chains,omitempty"`
	PreferredVenues []string `json:"preferred_venues,omitempty"`
	SpendMultiplier float64  `json:"spend_multiplier,omitempty"`
	SignalBias      string   `json:"signal_bias,omitempty"`
	RotationBias    string   `json:"rotation_bias,omitempty"`
	StrategyHint    string   `json:"strategy_hint,omitempty"`
	Mutation        string   `json:"mutation,omitempty"`
	Summary         string   `json:"summary,omitempty"`
}

// BuildChildStrategyProfile derives a deterministic but distinct profile for a child.
func BuildChildStrategyProfile(
	parentCfg *config.Config,
	childID string,
	parentID string,
	opts ReplicateOptions,
) ChildStrategyProfile {
	seedInput := strings.Join([]string{
		strings.TrimSpace(parentID),
		strings.TrimSpace(childID),
		strings.TrimSpace(opts.Name),
		strings.TrimSpace(opts.StrategyHint),
		fmt.Sprintf("%d", defaultChildChain(parentCfg)),
	}, "|")
	hash := sha256.Sum256([]byte(seedInput))

	style := chooseChildStyle(strings.ToLower(strings.TrimSpace(opts.StrategyHint)), hash[0])
	risk := chooseRiskProfile(strings.ToLower(strings.TrimSpace(opts.StrategyHint)), hash[1])
	role := childRoleForStyle(style)
	chains := childPreferredChains(parentCfg, style, opts.StrategyHint, hash[2])
	venues := childPreferredVenues(style, opts.StrategyHint)
	spendMultiplier := childSpendMultiplier(risk)
	signalBias := childSignalBias(style)
	rotationBias := childRotationBias(style, risk)
	mutation := mutateSystemPrompt("")
	fingerprint := strings.ToUpper(hex.EncodeToString(hash[:4]))
	if len(fingerprint) > 8 {
		fingerprint = fingerprint[:8]
	}

	label := strings.TrimSpace(opts.Name)
	if label == "" {
		label = strings.ReplaceAll(style, "_", " ")
	}

	summary := fmt.Sprintf(
		"%s child runs a %s profile with %s risk, favors %s, and biases toward %s before rotating profit toward GMAC.",
		label,
		strings.ReplaceAll(style, "_", " "),
		risk,
		renderChainSummary(chains),
		signalBias,
	)

	return ChildStrategyProfile{
		Label:           label,
		Fingerprint:     fingerprint,
		Style:           style,
		Role:            role,
		RiskProfile:     risk,
		PreferredChains: chains,
		PreferredVenues: venues,
		SpendMultiplier: spendMultiplier,
		SignalBias:      signalBias,
		RotationBias:    rotationBias,
		StrategyHint:    strings.TrimSpace(opts.StrategyHint),
		Mutation:        mutation,
		Summary:         summary,
	}
}

// SaveChildStrategyProfile persists the profile into the child workspace.
func SaveChildStrategyProfile(workspace string, profile ChildStrategyProfile) error {
	dir := filepath.Join(workspace, "replication")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(profile, "", "  ")
	if err != nil {
		return err
	}

	path := filepath.Join(dir, "profile.json")
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// LoadChildStrategyProfile restores a child profile from the workspace.
func LoadChildStrategyProfile(workspace string) (*ChildStrategyProfile, error) {
	path := filepath.Join(workspace, "replication", "profile.json")
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	var profile ChildStrategyProfile
	if err := json.Unmarshal(data, &profile); err != nil {
		return nil, err
	}
	return &profile, nil
}

// RenderChildStrategyMarkdown produces the living prompt file for a child.
func RenderChildStrategyMarkdown(profile ChildStrategyProfile) string {
	chains := renderChainSummary(profile.PreferredChains)
	venues := "gdex_spot"
	if len(profile.PreferredVenues) > 0 {
		venues = strings.Join(profile.PreferredVenues, ", ")
	}

	var sb strings.Builder
	sb.WriteString("## Trading Strategy\n\n")
	sb.WriteString(profile.Summary)
	sb.WriteString("\n\n")
	if strings.TrimSpace(profile.StrategyHint) != "" {
		sb.WriteString("### Operator Hint\n\n")
		sb.WriteString(profile.StrategyHint)
		sb.WriteString("\n\n")
	}
	sb.WriteString("### DNA\n\n")
	fmt.Fprintf(&sb, "- Style: %s\n", profile.Style)
	fmt.Fprintf(&sb, "- Role: %s\n", profile.Role)
	fmt.Fprintf(&sb, "- Risk: %s\n", profile.RiskProfile)
	fmt.Fprintf(&sb, "- Spend Multiplier: %.2fx\n", profile.SpendMultiplier)
	fmt.Fprintf(&sb, "- Preferred Chains: %s\n", chains)
	fmt.Fprintf(&sb, "- Preferred Venues: %s\n", venues)
	fmt.Fprintf(&sb, "- Signal Bias: %s\n", profile.SignalBias)
	fmt.Fprintf(&sb, "- Rotation Bias: %s\n", profile.RotationBias)
	sb.WriteString("\n### Mutation\n\n")
	sb.WriteString(profile.Mutation)
	sb.WriteString("\n")
	return sb.String()
}

func defaultChildChain(parentCfg *config.Config) int64 {
	if parentCfg == nil {
		return runtimeinfo.EthereumChainID
	}
	if parentCfg.Tools.GDEX.DefaultChainID != 0 {
		return parentCfg.Tools.GDEX.DefaultChainID
	}
	return runtimeinfo.EthereumChainID
}

func chooseChildStyle(hint string, hashByte byte) string {
	switch {
	case strings.Contains(hint, "solana"):
		return "solana_scout"
	case strings.Contains(hint, "bridge"), strings.Contains(hint, "arb"):
		return "bridge_rotator"
	case strings.Contains(hint, "mean"), strings.Contains(hint, "dip"), strings.Contains(hint, "contrarian"):
		return "mean_reversion"
	case strings.Contains(hint, "gmach"), strings.Contains(hint, "gmac"), strings.Contains(hint, "gemach"):
		return "gmac_accumulator"
	case strings.Contains(hint, "hyperliquid"), strings.Contains(hint, "perp"), strings.Contains(hint, "leverage"):
		return "momentum_hunter"
	default:
		styles := []string{
			"momentum_hunter",
			"mean_reversion",
			"solana_scout",
			"bridge_rotator",
			"gmac_accumulator",
		}
		return styles[int(hashByte)%len(styles)]
	}
}

func chooseRiskProfile(hint string, hashByte byte) string {
	switch {
	case strings.Contains(hint, "safe"), strings.Contains(hint, "low risk"), strings.Contains(hint, "defensive"):
		return "cautious"
	case strings.Contains(hint, "aggressive"), strings.Contains(hint, "leverage"), strings.Contains(hint, "conviction"):
		return "aggressive"
	default:
		profiles := []string{"cautious", "balanced", "aggressive"}
		return profiles[int(hashByte)%len(profiles)]
	}
}

func childRoleForStyle(style string) string {
	switch style {
	case "momentum_hunter", "bridge_rotator":
		return "executor"
	case "solana_scout", "mean_reversion":
		return "scout"
	default:
		return "analyst"
	}
}

func childPreferredChains(parentCfg *config.Config, style string, hint string, hashByte byte) []int64 {
	defaultChain := defaultChildChain(parentCfg)
	switch style {
	case "solana_scout":
		return []int64{runtimeinfo.SolanaChainID, runtimeinfo.ArbitrumChainID, defaultChain}
	case "bridge_rotator":
		return []int64{runtimeinfo.ArbitrumChainID, runtimeinfo.EthereumChainID, runtimeinfo.SolanaChainID}
	case "gmac_accumulator":
		return uniqueChainIDs(defaultChain, runtimeinfo.ArbitrumChainID, runtimeinfo.EthereumChainID)
	case "mean_reversion":
		return uniqueChainIDs(runtimeinfo.EthereumChainID, runtimeinfo.ArbitrumChainID, defaultChain)
	default:
		chains := [][]int64{
			{runtimeinfo.ArbitrumChainID, runtimeinfo.EthereumChainID, runtimeinfo.SolanaChainID},
			{runtimeinfo.EthereumChainID, runtimeinfo.ArbitrumChainID, runtimeinfo.SolanaChainID},
		}
		if strings.Contains(strings.ToLower(hint), "solana") {
			return []int64{runtimeinfo.SolanaChainID, runtimeinfo.ArbitrumChainID, runtimeinfo.EthereumChainID}
		}
		return chains[int(hashByte)%len(chains)]
	}
}

func childPreferredVenues(style string, hint string) []string {
	venues := []string{"gdex_spot"}
	if strings.Contains(strings.ToLower(hint), "bridge") || style == "bridge_rotator" || style == "gmac_accumulator" {
		venues = append(venues, "gdex_bridge")
	}
	if strings.Contains(strings.ToLower(hint), "hyperliquid") || strings.Contains(strings.ToLower(hint), "perp") || style == "momentum_hunter" || style == "mean_reversion" {
		venues = append(venues, "hyperliquid_perps")
	}
	return venues
}

func childSpendMultiplier(risk string) float64 {
	switch risk {
	case "cautious":
		return 0.6
	case "aggressive":
		return 1.4
	default:
		return 1.0
	}
}

func childSignalBias(style string) string {
	switch style {
	case "mean_reversion":
		return "buy controlled pullbacks and fade overheated signals"
	case "solana_scout":
		return "hunt early liquid Solana signals before routing profits home"
	case "bridge_rotator":
		return "follow the easiest bridgeable edge and route exits back to Arbitrum"
	case "gmac_accumulator":
		return "prefer direct GMAC accumulation unless an edge is materially stronger"
	default:
		return "press liquid momentum while capping chase risk"
	}
}

func childRotationBias(style string, risk string) string {
	switch {
	case style == "gmac_accumulator":
		return "bank gains early into GMAC"
	case risk == "aggressive":
		return "let winners run until they break structure"
	default:
		return "trim strength and recycle profit into GMAC"
	}
}

func renderChainSummary(chainIDs []int64) string {
	labels := make([]string, 0, len(chainIDs))
	for _, chainID := range chainIDs {
		switch chainID {
		case runtimeinfo.EthereumChainID:
			labels = append(labels, "Ethereum")
		case runtimeinfo.ArbitrumChainID:
			labels = append(labels, "Arbitrum")
		case runtimeinfo.SolanaChainID:
			labels = append(labels, "Solana")
		default:
			labels = append(labels, fmt.Sprintf("Chain %d", chainID))
		}
	}
	if len(labels) == 0 {
		return "none"
	}
	return strings.Join(labels, ", ")
}

func uniqueChainIDs(values ...int64) []int64 {
	out := make([]int64, 0, len(values))
	seen := map[int64]struct{}{}
	for _, value := range values {
		if value == 0 {
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
