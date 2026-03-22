package tempo

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
	"strings"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/logger"
	"github.com/GemachDAO/Gclaw/pkg/utils"
)

// ClientConfig configures the Tempo MPP client (buyer-side).
type ClientConfig struct {
	// PrivateKey is the EVM private key for signing Tempo transactions (hex with or without 0x prefix).
	PrivateKey string
	// WalletAddress is the EVM address of the paying wallet (hex with 0x prefix).
	WalletAddress string
	// RPCURL is the Tempo RPC endpoint (optional, defaults to https://rpc.tempo.xyz).
	RPCURL string
	// MaxPaymentAmount is the maximum per-request payment in the token's smallest unit.
	// Zero means no cap.
	MaxPaymentAmount string
	// Proxy is the optional HTTP proxy URL.
	Proxy string
}

// Client is an MPP-aware HTTP client for the Tempo blockchain that transparently
// handles 402 responses by creating signed payment credentials and retrying.
type Client struct {
	cfg        ClientConfig
	httpClient *http.Client
}

// NewClient creates a new Tempo MPP client.
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

// FetchResult contains the HTTP response from a Tempo MPP fetch.
type FetchResult struct {
	StatusCode  int
	Body        []byte
	ContentType string
	PaidAmount  string // non-empty if a payment was made
	Currency    string // token address used for payment
}

// Fetch makes an HTTP request. If the server responds with 402, the client
// automatically creates a signed payment credential and retries the request
// with the Authorization header per the MPP specification.
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

	// Parse the WWW-Authenticate challenge from the 402 response.
	wwwAuth := resp.Header.Get(WWWAuthenticateHeaderName)
	if wwwAuth == "" {
		return nil, fmt.Errorf("tempo: 402 response missing %s header", WWWAuthenticateHeaderName)
	}

	// Extract amount from the challenge for budget checking.
	amount, currency := extractAmountAndCurrency(wwwAuth)

	// Budget check.
	if c.cfg.MaxPaymentAmount != "" && c.cfg.MaxPaymentAmount != "0" {
		if amount == "" {
			return nil, fmt.Errorf(
				"tempo: unable to extract payment amount from challenge while MaxPaymentAmount is set",
			)
		}
		if !withinBudget(amount, c.cfg.MaxPaymentAmount) {
			return nil, fmt.Errorf(
				"tempo: payment amount %s exceeds max budget %s",
				amount, c.cfg.MaxPaymentAmount,
			)
		}
	}

	logger.InfoCF("tempo", "Signing MPP payment for Tempo resource", map[string]any{
		"url":      rawURL,
		"amount":   amount,
		"currency": currency,
	})

	// Sign the payment via Node.js helper.
	credential, err := c.signPayment(ctx, wwwAuth)
	if err != nil {
		return nil, fmt.Errorf("tempo: failed to sign payment: %w", err)
	}

	// Retry request with Authorization header.
	resp2, respBody2, err := c.doRequest(ctx, method, rawURL, headers, body, credential)
	if err != nil {
		return nil, fmt.Errorf("tempo: paid retry failed: %w", err)
	}

	return &FetchResult{
		StatusCode:  resp2.StatusCode,
		Body:        respBody2,
		ContentType: resp2.Header.Get("Content-Type"),
		PaidAmount:  amount,
		Currency:    currency,
	}, nil
}

func (c *Client) doRequest(
	ctx context.Context,
	method, rawURL string,
	headers map[string]string,
	body []byte,
	authHeader string,
) (*http.Response, []byte, error) {
	var bodyReader io.Reader
	if body != nil {
		bodyReader = bytes.NewReader(body)
	}

	req, err := http.NewRequestWithContext(ctx, method, rawURL, bodyReader)
	if err != nil {
		return nil, nil, fmt.Errorf("tempo: failed to create request: %w", err)
	}

	req.Header.Set("User-Agent", "Gclaw/1.0 tempo-mpp-client")
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	if authHeader != "" {
		req.Header.Set(AuthorizationHeaderName, authHeader)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("tempo: request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("tempo: failed to read response: %w", err)
	}

	return resp, respBody, nil
}

// signPayment calls the Node.js helper to create an MPP payment credential
// for the given WWW-Authenticate challenge.
func (c *Client) signPayment(ctx context.Context, wwwAuthenticate string) (string, error) {
	if err := ensureTempoDeps(); err != nil {
		return "", err
	}

	rpcURL := c.cfg.RPCURL
	if rpcURL == "" {
		rpcURL = DefaultRPCURL
	}

	input := map[string]any{
		"action": "pay",
		"params": map[string]any{
			"private_key":      c.cfg.PrivateKey,
			"wallet_address":   c.cfg.WalletAddress,
			"www_authenticate": wwwAuthenticate,
			"rpc_url":          rpcURL,
		},
	}

	inputJSON, err := json.Marshal(input)
	if err != nil {
		return "", fmt.Errorf("failed to marshal sign input: %w", err)
	}

	scriptPath := filepath.Join(tempoHelperDir(), "pay.js")
	cmd := exec.CommandContext(ctx, "node", scriptPath)
	cmd.Stdin = bytes.NewReader(inputJSON)
	cmd.Env = os.Environ()

	out, err := cmd.CombinedOutput()
	if err != nil {
		// Try to parse a structured error from the helper's output.
		var check map[string]any
		if jsonErr := json.Unmarshal(out, &check); jsonErr == nil {
			if errMsg, ok := check["error"].(string); ok && errMsg != "" {
				return "", fmt.Errorf("tempo pay helper error: %s", errMsg)
			}
		}
		return "", fmt.Errorf("tempo pay helper failed: %w — %s", err, strings.TrimSpace(string(out)))
	}

	// Validate the output is valid JSON.
	var result map[string]any
	if err := json.Unmarshal(out, &result); err != nil {
		return "", fmt.Errorf("tempo pay helper returned invalid JSON: %w", err)
	}

	if errMsg, ok := result["error"].(string); ok && errMsg != "" {
		return "", fmt.Errorf("tempo pay helper error: %s", errMsg)
	}

	authHeader, ok := result["authorization"].(string)
	if !ok || authHeader == "" {
		return "", fmt.Errorf("tempo pay helper did not return authorization header")
	}

	return authHeader, nil
}

// extractAmountAndCurrency parses the amount and currency from a
// WWW-Authenticate header's request parameter.
func extractAmountAndCurrency(wwwAuth string) (amount, currency string) {
	// The request parameter is base64url-encoded JSON.
	reqStart := strings.Index(wwwAuth, `request="`)
	if reqStart == -1 {
		return "", ""
	}
	reqStart += len(`request="`)
	reqEnd := strings.Index(wwwAuth[reqStart:], `"`)
	if reqEnd == -1 {
		return "", ""
	}
	encoded := wwwAuth[reqStart : reqStart+reqEnd]

	// Decode base64url (no padding).
	decoded, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		// Try standard base64.
		decoded, err = base64.StdEncoding.DecodeString(encoded)
		if err != nil {
			return "", ""
		}
	}

	var req map[string]any
	if err := json.Unmarshal(decoded, &req); err != nil {
		return "", ""
	}

	if a, ok := req["amount"].(string); ok {
		amount = a
	}
	if c, ok := req["currency"].(string); ok {
		currency = c
	}
	return amount, currency
}

// withinBudget returns true if the requested amount does not exceed the max budget.
// Both values are string representations of big integers in token smallest units.
func withinBudget(requested, maxBudget string) bool {
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
	tempoDepsOnce sync.Once
	errTempoDeps  error
)

func tempoHelperDir() string {
	return utils.ResolveWorkspaceSkillDir("TEMPO_HELPERS_DIR", "tempo-payment/helpers")
}

func ensureTempoDeps() error {
	tempoDepsOnce.Do(func() {
		dir := tempoHelperDir()
		nodeModules := filepath.Join(dir, "node_modules")
		if _, err := os.Stat(nodeModules); err == nil {
			return // already installed
		}

		logger.InfoCF("tempo", "tempo helpers: installing dependencies...",
			map[string]any{"dir": dir})

		cmd := exec.Command("npm", "install", "--no-audit", "--no-fund")
		cmd.Dir = dir
		cmd.Env = os.Environ()
		if out, err := cmd.CombinedOutput(); err != nil {
			errTempoDeps = fmt.Errorf("failed to install tempo helper dependencies: %w — %s", err, string(out))
			logger.ErrorCF("tempo", "npm install failed for tempo helpers",
				map[string]any{"error": errTempoDeps.Error()})
		} else {
			logger.InfoCF("tempo", "tempo helpers: dependencies installed", nil)
		}
	})
	return errTempoDeps
}
