package runtimeinfo

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/utils"
)

// TradingStatus summarizes wallet and trading-tool readiness for GDEX.
type TradingStatus struct {
	Enabled          bool                    `json:"enabled"`
	APIKeyConfigured bool                    `json:"api_key_configured"`
	WalletAddress    string                  `json:"wallet_address,omitempty"`
	HasPrivateKey    bool                    `json:"has_private_key"`
	AutoTradeEnabled bool                    `json:"auto_trade_enabled"`
	AutoTradeRuntime *AutoTradeRuntimeStatus `json:"auto_trade_runtime,omitempty"`
	AutoTradePlan    *AutoTradeStrategy      `json:"auto_trade_plan,omitempty"`
	DefaultChainID   int64                   `json:"default_chain_id"`
	HelpersDir       string                  `json:"helpers_dir,omitempty"`
	HelpersInstalled bool                    `json:"helpers_installed"`
	ToolCount        int                     `json:"tool_count"`
	Tools            []string                `json:"tools,omitempty"`
	ManagedWallets   *ManagedWalletStatus    `json:"managed_wallets,omitempty"`
}

// RegistrationStatus summarizes ERC-8004 registration state.
type RegistrationStatus struct {
	Enabled      bool   `json:"enabled"`
	X402Enabled  bool   `json:"x402_enabled"`
	WalletReady  bool   `json:"wallet_ready"`
	State        string `json:"state"`
	URL          string `json:"url,omitempty"`
	DashboardURL string `json:"dashboard_url,omitempty"`
}

// GatewayProbe reports whether the live gateway endpoints are reachable.
type GatewayProbe struct {
	BaseURL          string `json:"base_url"`
	Reachable        bool   `json:"reachable"`
	HealthOK         bool   `json:"health_ok"`
	ReadyOK          bool   `json:"ready_ok"`
	DashboardOK      bool   `json:"dashboard_ok"`
	RegistrationLive bool   `json:"registration_live"`
}

var gdexToolOrder = []string{
	"gdex_buy",
	"gdex_sell",
	"gdex_limit_buy",
	"gdex_limit_sell",
	"gdex_trending",
	"gdex_search",
	"gdex_price",
	"gdex_holdings",
	"gdex_scan",
	"gdex_copy_trade",
	"gdex_bridge_estimate",
	"gdex_bridge_request",
	"gdex_bridge_orders",
	"gdex_hl_balance",
	"gdex_hl_positions",
	"gdex_hl_deposit",
	"gdex_hl_withdraw",
	"gdex_hl_create_order",
	"gdex_hl_cancel_order",
	"x402_fetch",
	"tempo_pay",
}

// BaseURL returns the gateway base URL using a localhost-safe host.
func BaseURL(cfg *config.Config) string {
	return "http://" + net.JoinHostPort(httpHost(cfg.Gateway.Host), strconv.Itoa(cfg.Gateway.Port))
}

// DashboardURL returns the dashboard URL for the configured gateway.
func DashboardURL(cfg *config.Config) string {
	return BaseURL(cfg) + "/dashboard"
}

// RegistrationURL returns the ERC-8004 registration URL for the configured gateway.
func RegistrationURL(cfg *config.Config) string {
	return BaseURL(cfg) + "/.well-known/agent-registration.json"
}

// ResolveWalletCredentials returns the effective wallet address and private key,
// preferring config values and falling back to environment variables.
func ResolveWalletCredentials(cfg *config.Config) (addr, key string) {
	addr = strings.TrimSpace(cfg.Tools.GDEX.WalletAddress)
	key = strings.TrimSpace(cfg.Tools.GDEX.PrivateKey)
	if addr == "" {
		addr = strings.TrimSpace(os.Getenv("WALLET_ADDRESS"))
	}
	if key == "" {
		key = strings.TrimSpace(os.Getenv("PRIVATE_KEY"))
	}
	return addr, key
}

// SplitGDEXAPIKeys breaks a raw GDEX API key string into individual candidates.
// The community/shared key format may be comma-separated.
func SplitGDEXAPIKeys(raw string) []string {
	parts := strings.FieldsFunc(raw, func(r rune) bool {
		switch r {
		case ',', ';', '\n', '\r', '\t', ' ':
			return true
		default:
			return false
		}
	})

	seen := make(map[string]struct{}, len(parts))
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if _, ok := seen[part]; ok {
			continue
		}
		seen[part] = struct{}{}
		out = append(out, part)
	}
	return out
}

// ResolveGDEXAPIKey returns one concrete GDEX API key to use at runtime,
// preferring environment overrides and normalizing comma-separated shared keys.
func ResolveGDEXAPIKey(cfg *config.Config) string {
	raw := strings.TrimSpace(os.Getenv("GDEX_API_KEY"))
	if raw == "" && cfg != nil {
		raw = strings.TrimSpace(cfg.Tools.GDEX.APIKey)
	}
	keys := SplitGDEXAPIKeys(raw)
	if len(keys) == 0 {
		return ""
	}
	return keys[0]
}

// BuildTradingStatus summarizes GDEX readiness from config and, optionally,
// the runtime tool list from an active tool registry.
func BuildTradingStatus(cfg *config.Config, toolNames []string) *TradingStatus {
	addr, key := ResolveWalletCredentials(cfg)
	apiKey := ResolveGDEXAPIKey(cfg)
	helpersDir := utils.ResolveWorkspaceSkillDir("GDEX_HELPERS_DIR", "gdex-trading/helpers")
	helpersInstalled := helperPackagesInstalled(helpersDir)

	tools := FilterTradingTools(toolNames)
	if len(toolNames) == 0 {
		tools = expectedTradingTools(cfg, addr, key)
	}

	return &TradingStatus{
		Enabled:          cfg.Tools.GDEX.Enabled || apiKey != "",
		APIKeyConfigured: apiKey != "",
		WalletAddress:    addr,
		HasPrivateKey:    key != "",
		AutoTradeEnabled: cfg.Tools.GDEX.AutoTrade,
		AutoTradeRuntime: BuildAutoTradeRuntimeStatus(cfg),
		AutoTradePlan:    BuildAutoTradeStrategy(cfg),
		DefaultChainID:   cfg.Tools.GDEX.DefaultChainID,
		HelpersDir:       helpersDir,
		HelpersInstalled: helpersInstalled,
		ToolCount:        len(tools),
		Tools:            tools,
	}
}

// BuildRegistrationStatus summarizes ERC-8004 readiness from the current config.
func BuildRegistrationStatus(cfg *config.Config) *RegistrationStatus {
	addr, key := ResolveWalletCredentials(cfg)
	enabled := cfg.Tools.ERC8004.Enabled || cfg.Tools.X402.Enabled
	walletReady := addr != "" && key != ""
	state := "disabled"
	if enabled {
		if walletReady {
			state = "active"
		} else {
			state = "deferred"
		}
	}

	return &RegistrationStatus{
		Enabled:      enabled,
		X402Enabled:  cfg.Tools.X402.Enabled,
		WalletReady:  walletReady,
		State:        state,
		URL:          RegistrationURL(cfg),
		DashboardURL: DashboardURL(cfg),
	}
}

// ProbeGateway checks the local gateway endpoints and reports their status.
func ProbeGateway(cfg *config.Config, timeout time.Duration) GatewayProbe {
	baseURL := BaseURL(cfg)
	client := &http.Client{Timeout: timeout}

	probe := GatewayProbe{
		BaseURL:          baseURL,
		HealthOK:         urlOK(client, baseURL+"/health"),
		ReadyOK:          urlOK(client, baseURL+"/ready"),
		DashboardOK:      urlOK(client, DashboardURL(cfg)),
		RegistrationLive: urlOK(client, RegistrationURL(cfg)),
	}
	probe.Reachable = probe.HealthOK || probe.ReadyOK || probe.DashboardOK || probe.RegistrationLive
	return probe
}

// FetchTradingStatus reads the live funding snapshot from the running gateway.
func FetchTradingStatus(cfg *config.Config, timeout time.Duration) (*TradingStatus, error) {
	client := &http.Client{Timeout: timeout}
	req, err := http.NewRequest(http.MethodGet, BaseURL(cfg)+"/dashboard/api/funding", nil)
	if err != nil {
		return nil, err
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		_, _ = io.Copy(io.Discard, resp.Body)
		return nil, fmt.Errorf("funding endpoint returned %s", resp.Status)
	}

	var status TradingStatus
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		return nil, err
	}
	return &status, nil
}

// FilterTradingTools keeps only GDEX/x402/Tempo tools in stable display order.
func FilterTradingTools(toolNames []string) []string {
	if len(toolNames) == 0 {
		return nil
	}

	have := make(map[string]struct{}, len(toolNames))
	for _, name := range toolNames {
		have[name] = struct{}{}
	}

	out := make([]string, 0, len(gdexToolOrder))
	for _, name := range gdexToolOrder {
		if _, ok := have[name]; ok {
			out = append(out, name)
		}
	}
	return out
}

// FormatToolList renders a short human-readable tool list.
func FormatToolList(toolNames []string) string {
	if len(toolNames) == 0 {
		return "none"
	}
	return strings.Join(toolNames, ", ")
}

// ShortAddress renders a public wallet address in a compact form.
func ShortAddress(addr string) string {
	if len(addr) <= 12 {
		return addr
	}
	return fmt.Sprintf("%s…%s", addr[:8], addr[len(addr)-4:])
}

func expectedTradingTools(cfg *config.Config, addr, key string) []string {
	if !(cfg.Tools.GDEX.Enabled || ResolveGDEXAPIKey(cfg) != "") {
		return nil
	}

	tools := make([]string, 0, len(gdexToolOrder))
	for _, name := range gdexToolOrder {
		if name == "x402_fetch" || name == "tempo_pay" {
			continue
		}
		tools = append(tools, name)
	}
	if cfg.Tools.X402.Enabled && addr != "" && key != "" {
		tools = append(tools, "x402_fetch")
	}
	if cfg.Tools.Tempo.Enabled && addr != "" && key != "" {
		tools = append(tools, "tempo_pay")
	}
	return tools
}

func httpHost(host string) string {
	switch strings.TrimSpace(host) {
	case "", "0.0.0.0", "::", "[::]":
		return "127.0.0.1"
	default:
		return host
	}
}

func dirExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func helperPackagesInstalled(helperDir string) bool {
	requiredDirs := []string{
		filepath.Join(helperDir, "node_modules"),
		filepath.Join(helperDir, "node_modules", "@gdexsdk", "gdex-skill"),
		filepath.Join(helperDir, "node_modules", "ethers"),
	}
	for _, path := range requiredDirs {
		info, err := os.Stat(path)
		if err != nil || !info.IsDir() {
			return false
		}
	}
	return true
}

func urlOK(client *http.Client, url string) bool {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return false
	}

	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)

	return resp.StatusCode >= 200 && resp.StatusCode < 400
}
