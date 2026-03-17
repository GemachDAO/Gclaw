package tools

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/x402"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestX402FetchToolName(t *testing.T) {
	client, err := x402.NewClient(x402.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
		Network:       "base",
	})
	require.NoError(t, err)

	tool := NewX402FetchTool(client)
	assert.Equal(t, "x402_fetch", tool.Name())
}

func TestX402FetchToolDescription(t *testing.T) {
	client, err := x402.NewClient(x402.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
		Network:       "base",
	})
	require.NoError(t, err)

	tool := NewX402FetchTool(client)
	desc := tool.Description()
	assert.Contains(t, desc, "x402")
	assert.Contains(t, desc, "402")
	assert.Contains(t, desc, "ERC-8004")
}

func TestX402FetchToolParameters(t *testing.T) {
	client, err := x402.NewClient(x402.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
		Network:       "base",
	})
	require.NoError(t, err)

	tool := NewX402FetchTool(client)
	params := tool.Parameters()
	assert.Equal(t, "object", params["type"])

	props, ok := params["properties"].(map[string]any)
	require.True(t, ok)
	assert.Contains(t, props, "url")
	assert.Contains(t, props, "method")
	assert.Contains(t, props, "headers")
	assert.Contains(t, props, "body")

	required, ok := params["required"].([]string)
	require.True(t, ok)
	assert.Contains(t, required, "url")
}

func TestX402FetchToolMissingURL(t *testing.T) {
	client, err := x402.NewClient(x402.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
		Network:       "base",
	})
	require.NoError(t, err)

	tool := NewX402FetchTool(client)
	result := tool.Execute(context.Background(), map[string]any{})
	assert.True(t, result.IsError)
	assert.Contains(t, result.ForLLM, "url is required")
}

func TestX402FetchToolInvalidScheme(t *testing.T) {
	client, err := x402.NewClient(x402.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
		Network:       "base",
	})
	require.NoError(t, err)

	tool := NewX402FetchTool(client)
	result := tool.Execute(context.Background(), map[string]any{
		"url": "ftp://example.com/file",
	})
	assert.True(t, result.IsError)
	assert.Contains(t, result.ForLLM, "only http/https URLs are allowed")
}

func TestX402FetchToolNon402Response(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"data": "free content"})
	}))
	defer server.Close()

	client, err := x402.NewClient(x402.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
		Network:       "base",
	})
	require.NoError(t, err)

	tool := NewX402FetchTool(client)
	result := tool.Execute(context.Background(), map[string]any{
		"url": server.URL,
	})
	assert.False(t, result.IsError)
	assert.Contains(t, result.ForUser, "free content")
	assert.Contains(t, result.ForLLM, "status: 200")
	assert.NotContains(t, result.ForLLM, "paid")
}

func TestX402FetchTool402BudgetExceeded(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusPaymentRequired)
		json.NewEncoder(w).Encode(x402.PaymentRequirementsResponse{
			X402Version: 1,
			Accepts: []x402.PaymentRequirement{
				{
					Scheme:            "exact",
					Network:           "base",
					MaxAmountRequired: "10000000", // 10 USDC
					PayTo:             "0xrecipient",
				},
			},
		})
	}))
	defer server.Close()

	client, err := x402.NewClient(x402.ClientConfig{
		WalletAddress:    "0xtest",
		PrivateKey:       "0xdeadbeef",
		Network:          "base",
		MaxPaymentAmount: "1000000", // 1 USDC max
	})
	require.NoError(t, err)

	tool := NewX402FetchTool(client)
	result := tool.Execute(context.Background(), map[string]any{
		"url": server.URL,
	})
	assert.True(t, result.IsError)
	assert.Contains(t, result.ForLLM, "exceeds max budget")
}
