# GDEX Trading Skill

GDEX is a universal DeFi aggregation SDK that enables trading across multiple chains (Solana, Base, Arbitrum, and more) through a unified interface.

## Authentication Architecture

All chains use EVM-style wallet credentials:

- **`GDEX_API_KEY`** — Your GDEX API key (comma-separated for load balancing: `"key1,key2,key3"`)
- **`WALLET_ADDRESS`** — Your EVM wallet address (0x...)
- **`PRIVATE_KEY`** — Your wallet private key (for signing transactions)

### Session Keys vs Wallet Keys

- **Session keys** — Short-lived keys generated per session for convenience; lower security but easy rotation.
- **Wallet keys** — Full private key of your wallet; required for on-chain signing. Keep secure, never commit.

### Quick Start: `createAuthenticatedSession()`

```js
import { createAuthenticatedSession } from 'gdex.pro-sdk';

const session = await createAuthenticatedSession({
  apiKey: process.env.GDEX_API_KEY,
  walletAddress: process.env.WALLET_ADDRESS,
  privateKey: process.env.PRIVATE_KEY,
});
```

> **Important**: Always include `'User-Agent': 'Mozilla/5.0'` in your request headers, or requests may be blocked.

---

## Trading Operations

### Market Buy

```js
const result = await session.buy({
  tokenAddress: '0xTokenAddress',
  amount: '1000000',        // in smallest unit (lamports for Solana, wei for EVM)
  chainId: 622112261,       // Solana default
});
```

### Market Sell

```js
const result = await session.sell({
  tokenAddress: '0xTokenAddress',
  amount: '1000000',
  chainId: 622112261,
});
```

### Limit Buy

```js
const result = await session.limitBuy({
  tokenAddress: '0xTokenAddress',
  amount: '1000000',
  triggerPrice: '0.0001',
  profitPercent: 50,   // optional: take profit at +50%
  lossPercent: 20,     // optional: stop loss at -20%
  chainId: 622112261,
});
```

### Limit Sell

```js
const result = await session.limitSell({
  tokenAddress: '0xTokenAddress',
  amount: '1000000',
  triggerPrice: '0.0002',
  chainId: 622112261,
});
```

---

## Market Data

### Trending Tokens

```js
const trending = await session.getTrending({ limit: 10, chainId: 622112261 });
```

### Search Tokens

```js
const results = await session.searchTokens({ query: 'PEPE', limit: 10 });
```

### Token Price

```js
const price = await session.getPrice({ tokenAddress: '0x...', chainId: 8453 });
```

### Portfolio Holdings

```js
const holdings = await session.getHoldings();
```

### Newest Tokens (Scan)

```js
const newest = await session.getNewest({ chainId: 622112261, limit: 20 });
```

---

## Copy Trading

Set up copy trading to mirror another wallet's trades:

```js
await session.setCopyTrade({
  targetAddress: '0xTargetWallet',
  name: 'whale-tracker',
  amount: '500000',      // amount to copy per trade
  chainId: 622112261,
});
```

---

## HyperLiquid Perpetuals

### Deposit USDC

```js
await session.hlDeposit({ amount: '100' }); // 100 USDC
```

### Check Balance

```js
const balance = await session.hlGetBalance();
```

### Get Open Positions

```js
const positions = await session.hlGetPositions();
```

---

## WebSocket Real-Time Streaming

```js
import { createWebSocketStream } from 'gdex.pro-sdk';
import WebSocket from 'ws'; // polyfill required in Node.js

const stream = createWebSocketStream({ apiKey: process.env.GDEX_API_KEY });

stream.on('trade', (trade) => {
  console.log('New trade:', trade);
});

stream.on('price', (update) => {
  console.log('Price update:', update);
});

stream.connect();
```

> **WebSocket Polyfill**: In Node.js environments, you must import `ws` before using WebSocket streaming. The SDK does not bundle a WebSocket implementation.

---

## Amount Formatting

| Chain    | Native Unit | 1 token = |
|----------|------------|-----------|
| Solana   | lamports   | 1,000,000,000 lamports |
| Base/EVM | wei        | 10^18 wei |
| USDC     | micro-USDC | 1,000,000 units = 1 USDC |

```js
// Solana: 0.01 SOL
const lamports = 0.01 * 1e9; // = 10000000

// EVM: 0.001 ETH
const wei = BigInt('1000000000000000'); // 0.001 ETH in wei

// USDC: 50 USDC
const usdc = 50 * 1e6; // = 50000000
```

---

## Supported Networks

| Network       | Chain ID    | Notes                   |
|---------------|-------------|-------------------------|
| Solana        | 622112261   | Default; lamports       |
| Base          | 8453        | EVM L2; wei             |
| Arbitrum      | 42161       | EVM L2; wei             |
| Ethereum      | 1           | Mainnet; wei            |
| BNB Chain     | 56          | EVM; wei                |
| Avalanche     | 43114       | EVM; wei                |

---

## Common Gotchas

1. **User-Agent headers** — Always set `'User-Agent': 'Mozilla/5.0'` on API calls or you may get 403 errors.
2. **Session keys** — Session keys expire; re-authenticate if you get auth errors.
3. **Comma-separated API keys** — Pass multiple API keys as `"key1,key2,key3"` for automatic load balancing.
4. **WebSocket polyfill** — Import `ws` package before using streaming in Node.js (`import WebSocket from 'ws'`).
5. **Amount precision** — Always use the correct smallest unit for each chain (lamports for Solana, wei for EVM). Passing human-readable values will result in incorrectly small or large trades.
6. **Chain ID required** — For `gdex_price` and EVM chains, always supply `chain_id`. Defaults to Solana (622112261) for trade tools.

---

## Environment Variables

```bash
export GDEX_API_KEY="your-api-key"           # Required
export WALLET_ADDRESS="0x..."                # Required
export PRIVATE_KEY="your-private-key"        # Required for trades
```

---

## Helper Scripts

This skill includes Node.js helper scripts in the `helpers/` directory:

- **`trade.js`** — Executes buy/sell/limit orders. Called by Go trade tools.
- **`market.js`** — Fetches market data. Called by Go market data tools.
- **`package.json`** — NPM dependencies (`gdex.pro-sdk`, `ethers`, `ws`).
- **`setup.sh`** — Run once to install NPM dependencies: `bash setup.sh`

Run `bash workspace/skills/gdex-trading/helpers/setup.sh` before using GDEX tools.
