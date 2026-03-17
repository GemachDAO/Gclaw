package x402

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestParsePaymentRequirements(t *testing.T) {
	raw := `{
		"x402Version": 1,
		"accepts": [{
			"scheme": "exact",
			"network": "base",
			"maxAmountRequired": "1000",
			"resource": "https://api.example.com/data",
			"description": "Premium API access",
			"mimeType": "application/json",
			"payTo": "0x1234567890abcdef1234567890abcdef12345678",
			"extra": {
				"name": "USDC",
				"version": "2",
				"chainId": 8453,
				"tokenAddress": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
			}
		}]
	}`

	var resp PaymentRequirementsResponse
	err := json.Unmarshal([]byte(raw), &resp)
	require.NoError(t, err)
	assert.Equal(t, 1, resp.X402Version)
	assert.Len(t, resp.Accepts, 1)
	assert.Equal(t, "exact", resp.Accepts[0].Scheme)
	assert.Equal(t, "base", resp.Accepts[0].Network)
	assert.Equal(t, "1000", resp.Accepts[0].MaxAmountRequired)
	assert.Equal(t, "0x1234567890abcdef1234567890abcdef12345678", resp.Accepts[0].PayTo)
}

func TestPaymentHeaderMarshal(t *testing.T) {
	header := PaymentHeader{
		X402Version: 1,
		Scheme:      "exact",
		Network:     "base",
		Payload: PaymentPayload{
			Signature: "0xdeadbeef",
			Authorization: TransferAuthorization{
				From:        "0xfrom",
				To:          "0xto",
				Value:       "1000",
				ValidAfter:  "0",
				ValidBefore: "999999999999",
				Nonce:       "0x1234",
			},
		},
	}

	b, err := json.Marshal(header)
	require.NoError(t, err)

	var decoded PaymentHeader
	err = json.Unmarshal(b, &decoded)
	require.NoError(t, err)
	assert.Equal(t, header.X402Version, decoded.X402Version)
	assert.Equal(t, header.Payload.Signature, decoded.Payload.Signature)
	assert.Equal(t, header.Payload.Authorization.From, decoded.Payload.Authorization.From)
}

func TestAgentRegistrationMarshal(t *testing.T) {
	reg := AgentRegistration{
		Type:        RegistrationType,
		Name:        "TestAgent",
		Description: "A test agent",
		Image:       "https://example.com/image.png",
		Services: []ServiceDef{
			{Name: "web", Endpoint: "https://agent.example.com", Version: "1.0"},
		},
		X402Support: true,
		Active:      true,
		Registrations: []OnChainReg{
			{AgentID: 42, AgentRegistry: "eip155:8453:0x8004A818..."},
		},
	}

	b, err := json.Marshal(reg)
	require.NoError(t, err)

	var decoded AgentRegistration
	err = json.Unmarshal(b, &decoded)
	require.NoError(t, err)
	assert.Equal(t, RegistrationType, decoded.Type)
	assert.True(t, decoded.X402Support)
	assert.True(t, decoded.Active)
	assert.Len(t, decoded.Services, 1)
}

func TestWithinBudget(t *testing.T) {
	tests := []struct {
		requested string
		budget    string
		want      bool
	}{
		{"1000", "2000", true},
		{"2000", "2000", true},
		{"2001", "2000", false},
		{"0", "1000", true},
		{"999999", "1000000", true},
		{"1000001", "1000000", false},
		{"100", "100", true},
		{"", "100", true},
		{"100", "", false},
	}

	for _, tt := range tests {
		t.Run(tt.requested+"_vs_"+tt.budget, func(t *testing.T) {
			got := withinBudget(tt.requested, tt.budget)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestSelectRequirement(t *testing.T) {
	c := &Client{cfg: ClientConfig{Network: "base"}}

	accepts := []PaymentRequirement{
		{Scheme: "exact", Network: "ethereum", MaxAmountRequired: "500"},
		{Scheme: "exact", Network: "base", MaxAmountRequired: "1000"},
		{Scheme: "stream", Network: "base", MaxAmountRequired: "2000"},
	}

	selected := c.selectRequirement(accepts)
	require.NotNil(t, selected)
	assert.Equal(t, "base", selected.Network)
	assert.Equal(t, "1000", selected.MaxAmountRequired)
}

func TestSelectRequirementFallback(t *testing.T) {
	c := &Client{cfg: ClientConfig{Network: "polygon"}}

	accepts := []PaymentRequirement{
		{Scheme: "exact", Network: "ethereum", MaxAmountRequired: "500"},
	}

	selected := c.selectRequirement(accepts)
	require.NotNil(t, selected)
	assert.Equal(t, "ethereum", selected.Network)
}

func TestFetchNon402(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"data": "hello"})
	}))
	defer server.Close()

	client, err := NewClient(ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
		Network:       "base",
	})
	require.NoError(t, err)

	result, err := client.Fetch(context.Background(), "GET", server.URL, nil, nil)
	require.NoError(t, err)
	assert.Equal(t, http.StatusOK, result.StatusCode)
	assert.Contains(t, string(result.Body), "hello")
	assert.Empty(t, result.PaidAmount)
}

func TestFetch402BudgetExceeded(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusPaymentRequired)
		json.NewEncoder(w).Encode(PaymentRequirementsResponse{
			X402Version: 1,
			Accepts: []PaymentRequirement{
				{
					Scheme:            "exact",
					Network:           "base",
					MaxAmountRequired: "5000000", // 5 USDC
					PayTo:             "0xrecipient",
				},
			},
		})
	}))
	defer server.Close()

	client, err := NewClient(ClientConfig{
		WalletAddress:    "0xtest",
		PrivateKey:       "0xdeadbeef",
		Network:          "base",
		MaxPaymentAmount: "1000000", // 1 USDC max
	})
	require.NoError(t, err)

	_, err = client.Fetch(context.Background(), "GET", server.URL, nil, nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "exceeds max budget")
}

func TestFetch402EmptyAccepts(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusPaymentRequired)
		json.NewEncoder(w).Encode(PaymentRequirementsResponse{
			X402Version: 1,
			Accepts:     []PaymentRequirement{},
		})
	}))
	defer server.Close()

	client, err := NewClient(ClientConfig{
		WalletAddress: "0xtest",
		PrivateKey:    "0xdeadbeef",
		Network:       "base",
	})
	require.NoError(t, err)

	_, err = client.Fetch(context.Background(), "GET", server.URL, nil, nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "no accepted payment options")
}
