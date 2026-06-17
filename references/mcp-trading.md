# MCP-driven execution (primary path)

Trade through the **gdex MCP** — it keeps warm connections and is smoother than a
cold SDK call. Managed custody never gives the MCP the control private key, so the
ONLY local step is signing the sign-in message; everything else is MCP tool calls.

## Signed-session flow (run once per heartbeat that trades)

1. **Sign locally (instant, pure crypto):**
   `node scripts/gdex_sign.js` →
   `{ apiKey, userId, sessionKey, sessionPrivateKey, nonce, signature }`
   `userId` is the control address; `sessionPrivateKey` is needed for the trade calls.
2. **Build the payload (MCP):** `mcp__gdex__build_sign_in_payload`
   with `{ apiKey, userId, sessionKey, nonce, signature }` → `computedData`.
3. **Sign in (MCP):** `mcp__gdex__managed_sign_in` with `{ computedData, chainId: 42161 }`.
   The response `address` is the **managed HL wallet** (where funds/positions live) —
   use it for all balance/position reads.

The session is now live. Keep `sessionPrivateKey` and `apiKey` for the trade calls below.

## Reads (no auth, use the managed address from step 3)

- `mcp__gdex__get_hl_clearinghouse_state` `{ userAddress: <managed> }` — perp equity, positions, withdrawable. Authoritative.
- `mcp__gdex__get_hl_spot_state` `{ walletAddress: <managed> }` — spot USDC (where idle capital sits).
- `mcp__gdex__get_hl_open_orders` `{ walletAddress: <managed> }` — resting TP/SL legs.
- `mcp__gdex__get_mark_price` `{ coin }` · `mcp__gdex__get_hl_meta_and_asset_ctxs` — marks, funding, OI.

## Writes (use control address as walletAddress + the session)

- **Open:** `mcp__gdex__open_perp_position`
  `{ apiKey, walletAddress: <control/userId>, sessionPrivateKey, coin, isLong, price: <mark>, size, tpPrice, slPrice }`.
  `size` is in contracts (coin units). Enforce HL's **$11 min notional** and **always** pass tp/sl.
- **Leverage (optional):** `mcp__gdex__set_leverage` `{ apiKey, walletAddress, sessionPrivateKey, coin, leverage, isCross: true }`.
  HL defaults to ~20x cross; risk is bounded by the stop, so this is rarely needed.
- **Close:** `mcp__gdex__close_perp_position` `{ apiKey, walletAddress, sessionPrivateKey, coin }` —
  realizes PnL; read it back from `get_hl_clearinghouse_state` and `settle` into metabolism.

## Sizing

`size = round(targetNotionalUsd / mark, szDecimals)`. `hl_perp.js` fetches `szDecimals`
per asset from `getHlAllAssets` (falling back to BTC 5 / ETH 4 / SOL 2), so any HL asset
works without edits. Keep `targetNotionalUsd ≥ 12` so it clears the $11 floor after
rounding. Stop/TP prices to ~5 significant figures.

## Fallback

`scripts/hl_perp.js {status|open|close}` does the whole flow via the SDK in one process
(it can be slow to connect). Use it only if the MCP path is unavailable.
