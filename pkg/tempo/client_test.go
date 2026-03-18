package tempo

import (
	"encoding/base64"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewClient(t *testing.T) {
	client, err := NewClient(ClientConfig{
		WalletAddress: "0x742d35Cc6634c0532925a3b844bC9e7595F8fE00",
		PrivateKey:    "0xdeadbeef",
	})
	require.NoError(t, err)
	assert.NotNil(t, client)
}

func TestNewClientWithProxy(t *testing.T) {
	client, err := NewClient(ClientConfig{
		WalletAddress: "0x742d35Cc6634c0532925a3b844bC9e7595F8fE00",
		PrivateKey:    "0xdeadbeef",
		Proxy:         "http://localhost:8080",
	})
	require.NoError(t, err)
	assert.NotNil(t, client)
}

func TestNewClientInvalidProxy(t *testing.T) {
	_, err := NewClient(ClientConfig{
		WalletAddress: "0x742d35Cc6634c0532925a3b844bC9e7595F8fE00",
		PrivateKey:    "0xdeadbeef",
		Proxy:         "://invalid",
	})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "invalid proxy URL")
}

func TestWithinBudget(t *testing.T) {
	tests := []struct {
		name      string
		requested string
		budget    string
		want      bool
	}{
		{"equal amounts", "1000000", "1000000", true},
		{"under budget", "500000", "1000000", true},
		{"over budget", "2000000", "1000000", false},
		{"zero requested", "0", "1000000", true},
		{"equal with leading zeros", "001000000", "1000000", true},
		{"large amounts", "100000000000", "100000000001", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := withinBudget(tt.requested, tt.budget)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestExtractAmountAndCurrency(t *testing.T) {
	reqData := map[string]any{
		"amount":    "1000000",
		"currency":  "0x20c0000000000000000000000000000000000001",
		"recipient": "0x742d35Cc6634c0532925a3b844bC9e7595F8fE00",
	}
	reqJSON, _ := json.Marshal(reqData)
	reqEncoded := base64.RawURLEncoding.EncodeToString(reqJSON)

	header := `Payment id="abc123", realm="api.test.com", method="tempo", intent="charge", request="` + reqEncoded + `"`

	amount, currency := extractAmountAndCurrency(header)
	assert.Equal(t, "1000000", amount)
	assert.Equal(t, "0x20c0000000000000000000000000000000000001", currency)
}

func TestExtractAmountAndCurrencyMissingRequest(t *testing.T) {
	header := `Payment id="abc123", realm="api.test.com", method="tempo", intent="charge"`
	amount, currency := extractAmountAndCurrency(header)
	assert.Empty(t, amount)
	assert.Empty(t, currency)
}

func TestConstants(t *testing.T) {
	assert.Equal(t, 240240, TempoChainID)
	assert.Equal(t, "https://rpc.tempo.xyz", DefaultRPCURL)
	assert.Equal(t, "0x20c0000000000000000000000000000000000001", TempoUSDC)
	assert.Equal(t, "Authorization", AuthorizationHeaderName)
	assert.Equal(t, "WWW-Authenticate", WWWAuthenticateHeaderName)
	assert.Equal(t, "Payment", PaymentScheme)
}
