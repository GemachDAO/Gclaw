// Package x402 implements the client-side (buyer) flow for the x402 HTTP
// payment protocol and ERC-8004 agent identity types.
//
// The x402 protocol enables pay-per-request HTTP resources:
//
//  1. Client sends a normal HTTP request.
//  2. Server responds with HTTP 402 and payment requirements.
//  3. Client signs an EIP-3009 transferWithAuthorization for USDC.
//  4. Client re-sends the request with the X-PAYMENT header.
//  5. Server (or facilitator) verifies the payment and serves the resource.
//
// ERC-8004 defines a standard for on-chain agent identity, enabling
// trustless agent-to-agent interaction and discovery via
// /.well-known/agent-registration.json.
//
// References:
//   - https://eips.ethereum.org/EIPS/eip-8004
//   - https://www.x402.org/
package x402

// --- x402 payment protocol types ---

// PaymentRequirementsResponse is the JSON body returned by a server in an
// HTTP 402 response.
type PaymentRequirementsResponse struct {
	X402Version int                  `json:"x402Version"`
	Accepts     []PaymentRequirement `json:"accepts"`
}

// PaymentRequirement describes a single payment option the server accepts.
type PaymentRequirement struct {
	Scheme            string         `json:"scheme"`            // "exact"
	Network           string         `json:"network"`           // e.g. "base", "base-sepolia", "ethereum"
	MaxAmountRequired string         `json:"maxAmountRequired"` // amount in token smallest unit
	Resource          string         `json:"resource"`          // URL of the paid resource
	Description       string         `json:"description"`       // human-readable description
	MimeType          string         `json:"mimeType"`          // expected response content type
	PayTo             string         `json:"payTo"`             // recipient wallet address
	Extra             map[string]any `json:"extra,omitempty"`   // token contract info
}

// PaymentHeader is the JSON structure sent as the X-PAYMENT header value
// (base64-encoded).
type PaymentHeader struct {
	X402Version int            `json:"x402Version"`
	Scheme      string         `json:"scheme"`
	Network     string         `json:"network"`
	Payload     PaymentPayload `json:"payload"`
}

// PaymentPayload contains the signed EIP-3009 authorization.
type PaymentPayload struct {
	Signature     string                `json:"signature"`
	Authorization TransferAuthorization `json:"authorization"`
}

// TransferAuthorization represents the EIP-3009 transferWithAuthorization
// parameters.
type TransferAuthorization struct {
	From        string `json:"from"`
	To          string `json:"to"`
	Value       string `json:"value"`
	ValidAfter  string `json:"validAfter"`
	ValidBefore string `json:"validBefore"`
	Nonce       string `json:"nonce"`
}

// --- ERC-8004 agent identity types ---

// AgentRegistration is the JSON document served at
// /.well-known/agent-registration.json per the ERC-8004 specification.
type AgentRegistration struct {
	Type           string       `json:"type"`
	Name           string       `json:"name"`
	Description    string       `json:"description,omitempty"`
	Image          string       `json:"image,omitempty"`
	Services       []ServiceDef `json:"services"`
	X402Support    bool         `json:"x402Support"`
	Active         bool         `json:"active"`
	Registrations  []OnChainReg `json:"registrations,omitempty"`
	SupportedTrust []string     `json:"supportedTrust,omitempty"`
}

// RegistrationType is the canonical type URI for ERC-8004 registration v1.
const RegistrationType = "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"

// ServiceDef describes an endpoint the agent exposes.
type ServiceDef struct {
	Name     string   `json:"name"`
	Endpoint string   `json:"endpoint,omitempty"`
	Version  string   `json:"version,omitempty"`
	Skills   []string `json:"skills,omitempty"`
	Domains  []string `json:"domains,omitempty"`
}

// OnChainReg links the registration to its on-chain record.
type OnChainReg struct {
	AgentID       int64  `json:"agentId"`
	AgentRegistry string `json:"agentRegistry"` // CAIP-10 format
}

// --- Well-known constants ---

const (
	// PaymentHeaderName is the HTTP header used to carry x402 payment proofs.
	PaymentHeaderName = "X-Payment"

	// DefaultFacilitatorURL is the Coinbase-hosted x402 facilitator.
	DefaultFacilitatorURL = "https://x402.org/facilitator"

	// USDCBase is the USDC contract address on Base mainnet.
	USDCBase = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
	// USDCEthereum is the USDC contract address on Ethereum mainnet.
	USDCEthereum = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
	// USDCBaseSepolia is the USDC contract address on Base Sepolia testnet.
	USDCBaseSepolia = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

	// ChainIDBase is the chain ID for Base mainnet.
	ChainIDBase = 8453
	// ChainIDEthereum is the chain ID for Ethereum mainnet.
	ChainIDEthereum = 1
	// ChainIDBaseSepolia is the chain ID for Base Sepolia testnet.
	ChainIDBaseSepolia = 84532
)
