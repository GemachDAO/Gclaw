---
name: x402-payment
description: "Access paid HTTP resources using the x402 payment protocol (ERC-8004) with automatic USDC payments via EIP-3009."
---

# x402 Payment Skill (ERC-8004)

## Overview

Enables the Gclaw agent to access paid HTTP resources using the x402 payment
protocol. When a server returns HTTP 402 (Payment Required), the agent
automatically signs a USDC payment via EIP-3009 `transferWithAuthorization`
and retries the request.

## Protocol Flow

```
Agent                     Server                  Facilitator (optional)
  |--- GET /resource ------->|                           |
  |<-- 402 + requirements ---|                           |
  |                          |                           |
  |  [sign EIP-3009 auth]    |                           |
  |                          |                           |
  |--- GET /resource ------->|                           |
  |    X-PAYMENT: <base64>   |--- verify payment ------->|
  |                          |<-- verification result ---|
  |<-- 200 + content --------|                           |
```

## Supported Networks

| Network       | Chain ID | USDC Contract                              |
|---------------|----------|--------------------------------------------|
| Base          | 8453     | 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 |
| Ethereum      | 1        | 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 |
| Base Sepolia  | 84532    | 0x036CbD53842c5426634e7929541eC2318f3dCF7e |

## Configuration

```json
{
  "tools": {
    "x402": {
      "enabled": true,
      "network": "base",
      "max_payment_amount": "1000000",
      "facilitator_url": ""
    }
  }
}
```

- **network**: Preferred chain for payments (`base`, `ethereum`, `base-sepolia`)
- **max_payment_amount**: Max per-request payment in USDC smallest unit
  (`1000000` = 1 USDC). Set to `"0"` for no limit.
- **facilitator_url**: Optional settlement facilitator (defaults to
  `https://x402.org/facilitator`)

## Wallet Credentials

The x402 tool reuses the GDEX wallet credentials:

```json
{
  "tools": {
    "gdex": {
      "wallet_address": "0x...",
      "private_key": "0x..."
    }
  }
}
```

Or via environment variables:
- `WALLET_ADDRESS`
- `PRIVATE_KEY`

## Tool: x402_fetch

### Parameters

| Parameter | Type   | Required | Description                    |
|-----------|--------|----------|--------------------------------|
| url       | string | Yes      | URL to fetch (http/https)      |
| method    | string | No       | HTTP method (default: GET)     |
| headers   | object | No       | Custom HTTP headers            |
| body      | string | No       | Request body (for POST/PUT)    |

### Example Usage

```
Use x402_fetch to access https://api.example.com/premium-data
```

The tool will:
1. Make the HTTP request
2. If the server returns 402, parse payment requirements
3. Check that payment is within budget
4. Sign the USDC payment
5. Retry with payment header
6. Return the response content

### GMAC Cost

3.0 GMAC per execution (metabolism gating).

## ERC-8004 Agent Identity

The x402 types package includes ERC-8004 agent registration types for
on-chain agent identity. An agent can publish its registration at
`/.well-known/agent-registration.json`:

```json
{
  "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
  "name": "My Gclaw Agent",
  "description": "Autonomous AI agent",
  "services": [
    {"name": "web", "endpoint": "https://agent.example.com", "version": "1.0"}
  ],
  "x402Support": true,
  "active": true,
  "registrations": [
    {"agentId": 42, "agentRegistry": "eip155:8453:0x8004A818..."}
  ]
}
```

## References

- [EIP-8004: Trustless Agents](https://eips.ethereum.org/EIPS/eip-8004)
- [x402 Protocol](https://www.x402.org/)
- [Understanding x402 & ERC-8004](https://thegraph.com/blog/understanding-x402-erc8004/)
