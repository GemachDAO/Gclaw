package runtimeinfo

import (
	"strconv"

	"github.com/GemachDAO/Gclaw/pkg/config"
)

const (
	EthereumChainID = int64(1)
	ArbitrumChainID = int64(42161)
	SolanaChainID   = int64(622112261)
)

// AutoTradeStrategy describes the deterministic strategy the runtime will use
// for the current auto-trade cycle.
type AutoTradeStrategy struct {
	Mode            string   `json:"mode"`
	Venue           string   `json:"venue"`
	ChainID         int64    `json:"chain_id"`
	ChainLabel      string   `json:"chain_label"`
	AssetSymbol     string   `json:"asset_symbol"`
	AssetAddress    string   `json:"asset_address,omitempty"`
	SpendAmount     string   `json:"spend_amount,omitempty"`
	Goal            string   `json:"goal,omitempty"`
	SignalSource    string   `json:"signal_source,omitempty"`
	ProfitPolicy    string   `json:"profit_policy,omitempty"`
	RiskProfile     string   `json:"risk_profile,omitempty"`
	PreferredRoutes []string `json:"preferred_routes,omitempty"`
	Notes           []string `json:"notes,omitempty"`
}

// BuildAutoTradeStrategy returns the current deterministic trading plan.
// The agent prioritizes GMAC accumulation on configured chains and falls back
// to liquid Solana discovery only when no GMAC route is configured.
func BuildAutoTradeStrategy(cfg *config.Config) *AutoTradeStrategy {
	if cfg == nil {
		return nil
	}

	spendAmount := FormatAutoTradeSpendAmount(cfg.Tools.GDEX.MaxTradeSizeSOL)
	notes := []string{
		"Primary objective is profit that compounds into GMAC inventory, goodwill, replication, and self-recoding.",
		"Use holdings plus token discovery to decide whether to rotate partial winners into GMAC or open a fresh small signal trade.",
		"HyperLiquid leverage is controlled through position sizing; the update_leverage endpoint is not implemented by the backend.",
	}

	for _, chainID := range preferredGMACChains(cfg.Tools.GDEX.DefaultChainID) {
		if tokenAddress := gmacTokenAddressForChain(cfg, chainID); tokenAddress != "" {
			return &AutoTradeStrategy{
				Mode:            "profit_rotation",
				Venue:           "route_aware",
				ChainID:         chainID,
				ChainLabel:      autoTradeChainLabel(chainID),
				AssetSymbol:     "GMAC",
				AssetAddress:    tokenAddress,
				SpendAmount:     spendAmount,
				Goal:            "Seek liquid opportunities, realize partial gains, and rotate the proceeds back into Gemach inventory.",
				SignalSource:    "gdex_holdings + gdex_scan + gdex_trending",
				ProfitPolicy:    "Sell a controlled slice of strong non-GMAC positions, then rebuy GMAC on the same chain when possible.",
				RiskProfile:     "Small-size entries, no forced trades, partial exits only, respect configured max native spend.",
				PreferredRoutes: []string{"spot_gmac_direct", "hyperliquid_profit_loop"},
				Notes:           notes,
			}
		}
	}

	fallbackNotes := append([]string{}, notes...)
	fallbackNotes = append(fallbackNotes,
		"No GMAC token route is configured for the preferred EVM/Solana chains, so the runtime falls back to liquid Solana discovery.",
	)
	return &AutoTradeStrategy{
		Mode:            "liquidity_fallback",
		Venue:           "gdex_spot",
		ChainID:         SolanaChainID,
		ChainLabel:      autoTradeChainLabel(SolanaChainID),
		AssetSymbol:     "trending token",
		SpendAmount:     spendAmount,
		Goal:            "Seek liquid spot opportunities until a funded GMAC accumulation route is available.",
		SignalSource:    "gdex_scan + gdex_trending",
		ProfitPolicy:    "Bank gains conservatively and wait for a GMAC sink route to become available.",
		RiskProfile:     "Small-size entries, prefer liquid markets, skip unsafe setups.",
		PreferredRoutes: []string{"spot_gmac_direct"},
		Notes:           fallbackNotes,
	}
}

func preferredGMACChains(defaultChainID int64) []int64 {
	switch defaultChainID {
	case ArbitrumChainID:
		return []int64{ArbitrumChainID, EthereumChainID, SolanaChainID}
	case SolanaChainID:
		return []int64{SolanaChainID, ArbitrumChainID, EthereumChainID}
	case EthereumChainID:
		return []int64{EthereumChainID, ArbitrumChainID, SolanaChainID}
	default:
		if defaultChainID > 0 {
			return []int64{defaultChainID, ArbitrumChainID, EthereumChainID, SolanaChainID}
		}
		return []int64{EthereumChainID, ArbitrumChainID, SolanaChainID}
	}
}

func gmacTokenAddressForChain(cfg *config.Config, chainID int64) string {
	if cfg == nil {
		return ""
	}
	switch chainID {
	case EthereumChainID:
		return cfg.Tools.GDEX.GmacToken.Ethereum
	case ArbitrumChainID:
		return cfg.Tools.GDEX.GmacToken.Arbitrum
	case SolanaChainID:
		return cfg.Tools.GDEX.GmacToken.Solana
	default:
		return ""
	}
}

func autoTradeChainLabel(chainID int64) string {
	switch chainID {
	case EthereumChainID:
		return "Ethereum"
	case ArbitrumChainID:
		return "Arbitrum"
	case SolanaChainID:
		return "Solana"
	default:
		return "Chain " + strconv.FormatInt(chainID, 10)
	}
}

func FormatAutoTradeSpendAmount(amount float64) string {
	if amount <= 0 {
		amount = 0.01
	}
	return strconv.FormatFloat(amount, 'f', -1, 64)
}
