package x402

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/logger"
	"github.com/GemachDAO/Gclaw/pkg/utils"
)

// ClientConfig configures the x402 HTTP client (buyer-side).
type ClientConfig struct {
	// WalletAddress is the EVM address of the paying wallet (hex with 0x prefix).
	WalletAddress string
	// PrivateKey is the EVM private key used for signing (hex with or without 0x prefix).
	PrivateKey string
	// Network is the preferred chain (e.g. "base", "ethereum", "base-sepolia").
	Network string
	// FacilitatorURL is the settlement facilitator endpoint (optional).
	FacilitatorURL string
	// MaxPaymentAmount is the maximum per-request payment in token smallest unit (e.g. "1000000" = 1 USDC).
	// Zero means no cap.
	MaxPaymentAmount string
	// Proxy is the optional HTTP proxy URL.
	Proxy string
}

// Client is an x402-aware HTTP client that transparently handles 402 responses
// by signing payments and retrying the request.
type Client struct {
	cfg        ClientConfig
	httpClient *http.Client
}

// NewClient creates a new x402 client.
func NewClient(cfg ClientConfig) (*Client, error) {
	transport := &http.Transport{
		MaxIdleConns:        10,
		IdleConnTimeout:     30 * time.Second,
		DisableCompression:  false,
		TLSHandshakeTimeout: 15 * time.Second,
	}

	if cfg.Proxy != "" {
		proxy, err := url.Parse(cfg.Proxy)
		if err != nil {
			return nil, fmt.Errorf("invalid proxy URL: %w", err)
		}
		transport.Proxy = http.ProxyURL(proxy)
	} else {
		transport.Proxy = http.ProxyFromEnvironment
	}

	return &Client{
		cfg: cfg,
		httpClient: &http.Client{
			Timeout:   60 * time.Second,
			Transport: transport,
		},
	}, nil
}

// FetchResult contains the HTTP response from an x402 fetch.
type FetchResult struct {
	StatusCode  int
	Body        []byte
	ContentType string
	PaidAmount  string // non-empty if a payment was made
	Network     string // chain used for payment
}

// Fetch makes an HTTP request. If the server responds with 402, the client
// automatically signs a payment and retries the request with the X-PAYMENT header.
func (c *Client) Fetch(
	ctx context.Context,
	method, rawURL string,
	headers map[string]string,
	body []byte,
) (*FetchResult, error) {
	// Initial request.
	resp, respBody, err := c.doRequest(ctx, method, rawURL, headers, body, "")
	if err != nil {
		return nil, err
	}

	// If not 402, return immediately.
	if resp.StatusCode != http.StatusPaymentRequired {
		return &FetchResult{
			StatusCode:  resp.StatusCode,
			Body:        respBody,
			ContentType: resp.Header.Get("Content-Type"),
		}, nil
	}

	// Parse payment requirements from 402 body.
	var reqResp PaymentRequirementsResponse
	parseErr := json.Unmarshal(respBody, &reqResp)
	if parseErr != nil {
		return nil, fmt.Errorf("x402: failed to parse 402 payment requirements: %w", parseErr)
	}

	if len(reqResp.Accepts) == 0 {
		return nil, fmt.Errorf("x402: 402 response has no accepted payment options")
	}

	// Select the best payment option (prefer the configured network).
	requirement := c.selectRequirement(reqResp.Accepts)
	if requirement == nil {
		return nil, fmt.Errorf("x402: no compatible payment option found for network %q", c.cfg.Network)
	}

	// Validate required fields on the selected payment requirement.
	if strings.TrimSpace(requirement.Scheme) == "" {
		return nil, fmt.Errorf("x402: selected payment option is missing scheme")
	}
	if strings.TrimSpace(requirement.Network) == "" {
		return nil, fmt.Errorf("x402: selected payment option is missing network")
	}
	if strings.TrimSpace(requirement.PayTo) == "" {
		return nil, fmt.Errorf("x402: selected payment option is missing payTo")
	}
	maxAmtStr := strings.TrimSpace(requirement.MaxAmountRequired)
	if maxAmtStr == "" {
		return nil, fmt.Errorf("x402: selected payment option is missing maxAmountRequired")
	}
	maxAmt, err := strconv.ParseInt(maxAmtStr, 10, 64)
	if err != nil || maxAmt < 0 {
		return nil, fmt.Errorf(
			"x402: selected payment option has invalid maxAmountRequired %q",
			requirement.MaxAmountRequired,
		)
	}

	// Budget check.
	if c.cfg.MaxPaymentAmount != "" && c.cfg.MaxPaymentAmount != "0" {
		if !withinBudget(requirement.MaxAmountRequired, c.cfg.MaxPaymentAmount) {
			return nil, fmt.Errorf(
				"x402: payment amount %s exceeds max budget %s",
				requirement.MaxAmountRequired, c.cfg.MaxPaymentAmount,
			)
		}
	}

	logger.InfoCF("x402", "Signing payment for x402 resource", map[string]any{
		"url":     rawURL,
		"amount":  requirement.MaxAmountRequired,
		"network": requirement.Network,
		"payTo":   requirement.PayTo,
	})

	// Sign the payment via Node.js helper.
	paymentHeader, err := c.signPayment(ctx, requirement)
	if err != nil {
		return nil, fmt.Errorf("x402: failed to sign payment: %w", err)
	}

	// Retry request with X-PAYMENT header.
	encoded := base64.StdEncoding.EncodeToString(paymentHeader)
	resp2, respBody2, err := c.doRequest(ctx, method, rawURL, headers, body, encoded)
	if err != nil {
		return nil, fmt.Errorf("x402: paid retry failed: %w", err)
	}

	return &FetchResult{
		StatusCode:  resp2.StatusCode,
		Body:        respBody2,
		ContentType: resp2.Header.Get("Content-Type"),
		PaidAmount:  requirement.MaxAmountRequired,
		Network:     requirement.Network,
	}, nil
}

func (c *Client) doRequest(
	ctx context.Context,
	method, rawURL string,
	headers map[string]string,
	body []byte,
	paymentHeader string,
) (*http.Response, []byte, error) {
	var bodyReader io.Reader
	if body != nil {
		bodyReader = bytes.NewReader(body)
	}

	req, err := http.NewRequestWithContext(ctx, method, rawURL, bodyReader)
	if err != nil {
		return nil, nil, fmt.Errorf("x402: failed to create request: %w", err)
	}

	req.Header.Set("User-Agent", "Gclaw/1.0 x402-client")
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	if paymentHeader != "" {
		req.Header.Set(PaymentHeaderName, paymentHeader)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("x402: request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("x402: failed to read response: %w", err)
	}

	return resp, respBody, nil
}

// selectRequirement picks the best payment requirement based on the configured network.
func (c *Client) selectRequirement(accepts []PaymentRequirement) *PaymentRequirement {
	// Prefer exact match with configured network.
	for i := range accepts {
		if strings.EqualFold(accepts[i].Network, c.cfg.Network) && strings.EqualFold(accepts[i].Scheme, "exact") {
			return &accepts[i]
		}
	}
	// Fall back to the first "exact" scheme option.
	for i := range accepts {
		if strings.EqualFold(accepts[i].Scheme, "exact") {
			return &accepts[i]
		}
	}
	// Last resort: first option.
	if len(accepts) > 0 {
		return &accepts[0]
	}
	return nil
}

// signPayment calls the Node.js helper to create an EIP-3009
// transferWithAuthorization signature for the given payment requirement.
func (c *Client) signPayment(ctx context.Context, req *PaymentRequirement) ([]byte, error) {
	if err := ensureX402Deps(); err != nil {
		return nil, err
	}

	input := map[string]any{
		"action": "sign",
		"params": map[string]any{
			"private_key":    c.cfg.PrivateKey,
			"wallet_address": c.cfg.WalletAddress,
			"pay_to":         req.PayTo,
			"amount":         req.MaxAmountRequired,
			"network":        req.Network,
			"extra":          req.Extra,
		},
	}

	inputJSON, err := json.Marshal(input)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal sign input: %w", err)
	}

	scriptPath := filepath.Join(x402HelperDir(), "sign.js")
	cmd := exec.CommandContext(ctx, "node", scriptPath)
	cmd.Stdin = bytes.NewReader(inputJSON)
	cmd.Env = os.Environ()

	out, err := cmd.CombinedOutput()
	if err != nil {
		// Try to parse a structured error from the helper's output.
		var check map[string]any
		if jsonErr := json.Unmarshal(out, &check); jsonErr == nil {
			if errMsg, ok := check["error"].(string); ok && errMsg != "" {
				return nil, fmt.Errorf("x402 sign helper error: %s", errMsg)
			}
		}
		// Fall back to including the raw combined output for debugging.
		return nil, fmt.Errorf("x402 sign helper failed: %w — %s", err, strings.TrimSpace(string(out)))
	}

	// Validate the output is valid JSON.
	var check map[string]any
	if err := json.Unmarshal(out, &check); err != nil {
		return nil, fmt.Errorf("x402 sign helper returned invalid JSON: %w", err)
	}

	if errMsg, ok := check["error"].(string); ok {
		return nil, fmt.Errorf("x402 sign helper error: %s", errMsg)
	}

	return out, nil
}

// withinBudget returns true if the requested amount does not exceed the max budget.
// Both values are string representations of big integers in token smallest units.
func withinBudget(requested, maxBudget string) bool {
	// Simple numeric string comparison (left-padded for correct ordering).
	r := strings.TrimLeft(requested, "0")
	m := strings.TrimLeft(maxBudget, "0")
	if r == "" {
		r = "0"
	}
	if m == "" {
		m = "0"
	}
	if len(r) != len(m) {
		return len(r) < len(m)
	}
	return r <= m
}

// --- Node.js helper management ---

var (
	x402DepsOnce sync.Once
	errX402Deps  error
)

func x402HelperDir() string {
	return utils.ResolveWorkspaceSkillDir("X402_HELPERS_DIR", "x402-payment/helpers")
}

func ensureX402Deps() error {
	x402DepsOnce.Do(func() {
		dir := x402HelperDir()
		nodeModules := filepath.Join(dir, "node_modules")
		if _, err := os.Stat(nodeModules); err == nil {
			return // already installed
		}

		logger.InfoCF("x402", "x402 helpers: installing dependencies...",
			map[string]any{"dir": dir})

		cmd := exec.Command("npm", "install", "--no-audit", "--no-fund")
		cmd.Dir = dir
		cmd.Env = os.Environ()
		if out, err := cmd.CombinedOutput(); err != nil {
			errX402Deps = fmt.Errorf("failed to install x402 helper dependencies: %w — %s", err, string(out))
			logger.ErrorCF("x402", "npm install failed for x402 helpers",
				map[string]any{"error": errX402Deps.Error()})
		} else {
			logger.InfoCF("x402", "x402 helpers: dependencies installed", nil)
		}
	})
	return errX402Deps
}
