# Tempo MPP Payment Skill

## Overview

This skill enables the Gclaw agent to autonomously pay for HTTP resources
using the **Machine Payments Protocol (MPP)** on the **Tempo blockchain**.
When a service responds with HTTP 402 (Payment Required), the agent
automatically parses the `WWW-Authenticate` challenge, signs a payment
credential, and retries the request with an `Authorization` header — all
without manual intervention.

## Protocol Flow

```
Agent → Service: GET /resource
Service → Agent: 402 + WWW-Authenticate: Payment id="...", realm="...", ...
Agent: [parse challenge, sign Tempo transaction]
Agent → Service: GET /resource + Authorization: Payment <base64-credential>
Service: [verify credential, settle payment]
Service → Agent: 200 + content
```

## Machine Payments Protocol (MPP)

MPP is an open standard for machine-to-machine payments. It uses the
`Payment` HTTP authentication scheme defined in the
[Payment HTTP Auth Spec](https://datatracker.ietf.org/doc/draft-ryan-httpauth-payment/).

### Challenge (WWW-Authenticate)

The server sends a `WWW-Authenticate` header with these parameters:

| Parameter     | Description                                     |
|---------------|-------------------------------------------------|
| `id`          | Unique challenge identifier (HMAC-bound)        |
| `realm`       | Server realm (e.g., hostname)                   |
| `method`      | Payment method (`tempo`, `stripe`, `lightning`)  |
| `intent`      | Intent type (`charge` or `session`)              |
| `request`     | Base64url-encoded JSON with payment details      |
| `expires`     | Optional expiration timestamp (ISO 8601)         |
| `description` | Optional human-readable description              |

### Credential (Authorization)

The agent sends an `Authorization: Payment <base64url>` header containing:

```json
{
  "challenge": { "...challenge fields..." },
  "payload": {
    "signature": "0x...",
    "type": "transaction"
  },
  "source": "did:pkh:eip155:240240:0x..."
}
```

## Supported Intents

| Intent    | Description                                      |
|-----------|--------------------------------------------------|
| `charge`  | One-time TIP-20 token transfer                   |
| `session` | Pay-as-you-go streaming via payment channels     |

## Tempo Chain Details

| Property  | Value                                              |
|-----------|----------------------------------------------------|
| Chain ID  | 240240                                             |
| RPC URL   | https://rpc.tempo.xyz                              |
| USDC      | `0x20c0000000000000000000000000000000000001`       |
| Explorer  | https://explorer.tempo.xyz                         |

## Configuration

```json
{
  "tools": {
    "tempo": {
      "enabled": true,
      "rpc_url": "https://rpc.tempo.xyz",
      "max_payment_amount": "1000000"
    }
  }
}
```

### Environment Variables

| Variable                      | Description                          |
|-------------------------------|--------------------------------------|
| `GCLAW_TEMPO_ENABLED`         | Enable Tempo MPP payments            |
| `GCLAW_TEMPO_RPC_URL`         | Tempo RPC endpoint                   |
| `GCLAW_TEMPO_MAX_PAYMENT_AMOUNT` | Max per-request payment (smallest unit) |

### Wallet Credentials

The Tempo tool reuses the GDEX wallet credentials:

| Variable         | Description                           |
|------------------|---------------------------------------|
| `WALLET_ADDRESS` | EVM wallet address (0x-prefixed)      |
| `PRIVATE_KEY`    | EVM private key for signing           |

## Tool: tempo_pay

### Parameters

| Parameter | Type   | Required | Description                          |
|-----------|--------|----------|--------------------------------------|
| `url`     | string | ✅       | URL to fetch (http/https)            |
| `method`  | string | ❌       | HTTP method (default: GET)           |
| `headers` | object | ❌       | Additional HTTP headers              |
| `body`    | string | ❌       | Request body (for POST/PUT)          |

### Behavior

1. Makes an HTTP request to the given URL
2. If the response is 402 with a `WWW-Authenticate: Payment` header:
   - Parses the MPP challenge
   - Validates the payment amount against the configured budget
   - Signs a Tempo transaction via the Node.js helper
   - Retries the request with the `Authorization: Payment` header
3. Returns the response body and metadata

### Cost

- **3.0 GMAC** per execution (metabolism gating)

## MPP Services Directory

Discover MPP-compatible services at https://mpp.dev/services

The directory includes 100+ integrations spanning:
- Model providers (LLMs, image generation)
- Developer infrastructure (APIs, compute)
- Data services (analytics, market data)
- Agent-to-agent services

## Sessions (Streaming Payments)

MPP supports **sessions** for continuous, pay-as-you-go payments:

1. Agent opens a session (sets aside funds upfront)
2. As resources are consumed, payments stream continuously
3. Thousands of micro-transactions aggregate into one settlement

Think of it as **OAuth for money**: authorize once, then pay programmatically.

## References

- [MPP Specification](https://github.com/tempoxyz/mpp-specs)
- [mppx TypeScript SDK](https://github.com/wevm/mppx)
- [Tempo Documentation](https://docs.tempo.xyz)
- [MPP Services Directory](https://mpp.dev/services)
- [Tempo Blog: Mainnet Launch](https://tempo.xyz/blog/mainnet)
