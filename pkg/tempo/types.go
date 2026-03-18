// Package tempo implements the client-side (buyer) flow for the Machine
// Payments Protocol (MPP) on the Tempo blockchain.
//
// The MPP protocol enables pay-per-request HTTP resources:
//
//  1. Client sends a normal HTTP request.
//  2. Server responds with HTTP 402 and a WWW-Authenticate challenge.
//  3. Client creates a signed payment credential (charge or session).
//  4. Client re-sends the request with the Authorization header.
//  5. Server verifies the payment and serves the resource.
//
// References:
//   - https://mpp.dev/
//   - https://docs.tempo.xyz/guide/using-tempo-with-ai
//   - https://github.com/tempoxyz/mpp-specs
package tempo

// --- MPP challenge/credential types ---

// Challenge is the parsed payment challenge from a 402 response's
// WWW-Authenticate header (Payment scheme).
type Challenge struct {
	ID          string            `json:"id"`
	Realm       string            `json:"realm"`
	Method      string            `json:"method"`  // e.g. "tempo"
	Intent      string            `json:"intent"`  // e.g. "charge", "session"
	Request     map[string]any    `json:"request"` // method-specific payment request data
	Description string            `json:"description,omitempty"`
	Expires     string            `json:"expires,omitempty"`
	Digest      string            `json:"digest,omitempty"`
	Opaque      map[string]string `json:"opaque,omitempty"`
}

// ChargeRequest contains the parsed request fields for a Tempo charge challenge.
type ChargeRequest struct {
	Amount    string `json:"amount"`    // amount in smallest unit
	Currency  string `json:"currency"`  // TIP-20 token address
	Recipient string `json:"recipient"` // recipient address
}

// Credential is the payment proof sent in the Authorization header.
type Credential struct {
	Challenge Challenge `json:"challenge"`
	Payload   any       `json:"payload"`
	Source    string    `json:"source,omitempty"` // DID of the payer (e.g. "did:pkh:eip155:1:0x...")
}

// --- Well-known constants ---

const (
	// TempoChainID is the chain ID for the Tempo mainnet.
	TempoChainID = 240240

	// DefaultRPCURL is the default Tempo RPC endpoint.
	DefaultRPCURL = "https://rpc.tempo.xyz"

	// TempoUSDC is the USDC token address on Tempo mainnet.
	TempoUSDC = "0x20c0000000000000000000000000000000000001"

	// AuthorizationHeaderName is the standard HTTP header for MPP credentials.
	AuthorizationHeaderName = "Authorization"

	// WWWAuthenticateHeaderName is the standard HTTP header for MPP challenges.
	WWWAuthenticateHeaderName = "WWW-Authenticate"

	// PaymentScheme is the authentication scheme used by MPP.
	PaymentScheme = "Payment"

	// MPPDirectoryURL is the MPP services directory for discovering payable services.
	MPPDirectoryURL = "https://mpp.dev/services"
)
