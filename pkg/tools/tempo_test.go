package tools

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/tempo"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestTempoPayToolName(t *testing.T) {
	client, err := tempo.NewClient(tempo.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
	})
	require.NoError(t, err)

	tool := NewTempoPayTool(client)
	assert.Equal(t, "tempo_pay", tool.Name())
}

func TestTempoPayToolDescription(t *testing.T) {
	client, err := tempo.NewClient(tempo.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
	})
	require.NoError(t, err)

	tool := NewTempoPayTool(client)
	desc := tool.Description()
	assert.Contains(t, desc, "Tempo")
	assert.Contains(t, desc, "MPP")
	assert.Contains(t, desc, "402")
}

func TestTempoPayToolParameters(t *testing.T) {
	client, err := tempo.NewClient(tempo.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
	})
	require.NoError(t, err)

	tool := NewTempoPayTool(client)
	params := tool.Parameters()

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

func TestTempoPayToolMissingURL(t *testing.T) {
	client, err := tempo.NewClient(tempo.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
	})
	require.NoError(t, err)

	tool := NewTempoPayTool(client)
	result := tool.Execute(t.Context(), map[string]any{})
	assert.Contains(t, result.ForLLM, "url is required")
}

func TestTempoPayToolInvalidScheme(t *testing.T) {
	client, err := tempo.NewClient(tempo.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
	})
	require.NoError(t, err)

	tool := NewTempoPayTool(client)
	result := tool.Execute(t.Context(), map[string]any{
		"url": "ftp://example.com",
	})
	assert.Contains(t, result.ForLLM, "only http/https URLs are allowed")
}

func TestTempoPayToolNon402Response(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok": true}`))
	}))
	defer ts.Close()

	client, err := tempo.NewClient(tempo.ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
	})
	require.NoError(t, err)

	tool := NewTempoPayTool(client)
	result := tool.Execute(t.Context(), map[string]any{
		"url": ts.URL,
	})

	assert.Contains(t, result.ForLLM, "status: 200")
	assert.NotContains(t, result.ForLLM, "paid")
}

func TestTempoPayTool402BudgetExceeded(t *testing.T) {
	// Build a base64url-encoded request for the challenge.
	reqData := map[string]any{
		"amount":    "5000000",
		"currency":  "0x20c0000000000000000000000000000000000001",
		"recipient": "0x742d35Cc6634c0532925a3b844bC9e7595F8fE00",
	}
	reqJSON, _ := json.Marshal(reqData)
	reqEncoded := base64.RawURLEncoding.EncodeToString(reqJSON)

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("WWW-Authenticate",
			fmt.Sprintf(`Payment id="test123", realm="api.test.com", method="tempo", intent="charge", request="%s"`, reqEncoded))
		w.WriteHeader(http.StatusPaymentRequired)
		_, _ = w.Write([]byte(`Payment Required`))
	}))
	defer ts.Close()

	// Max budget of 1000000 (1 USDC) should be exceeded by 5000000.
	client, err := tempo.NewClient(tempo.ClientConfig{
		WalletAddress:    "0xtest",
		PrivateKey:       "0xdeadbeef",
		MaxPaymentAmount: "1000000",
	})
	require.NoError(t, err)

	tool := NewTempoPayTool(client)
	result := tool.Execute(t.Context(), map[string]any{
		"url": ts.URL,
	})

	assert.Contains(t, result.ForLLM, "exceeds max budget")
}
