#!/usr/bin/env node
/**
 * GDEX Market Data Helper (v2 — @gdexsdk/gdex-skill)
 * Reads a JSON action descriptor from stdin, fetches market/portfolio data, and writes JSON to stdout.
 *
 * Input JSON:
 *   { "action": "trending"|"search"|"price"|"holdings"|"scan"|
 *               "copy_trade"|"hl_balance"|"hl_positions"|"hl_deposit"|
 *               "hl_create_order"|"hl_cancel_order",
 *     "params": { ... } }
 *
 * Output JSON:
 *   { "success": true, "data": { ... } }  or  { "success": false, "error": "..." }
 *
 * Environment variables:
 *   GDEX_API_KEY    — required for all operations
 *   WALLET_ADDRESS  — required for holdings, copy_trade, hl_* operations
 *   PRIVATE_KEY     — required for copy_trade, hl_deposit, hl_create_order, hl_cancel_order
 */

'use strict';

const {
  GdexSkill,
  GDEX_API_KEY_PRIMARY,
  generateGdexSessionKeyPair,
  buildGdexSignInMessage,
  buildGdexSignInComputedData,
  buildGdexUserSessionData,
} = require('@gdexsdk/gdex-skill');
const { ethers } = require('ethers');

const apiKey = process.env.GDEX_API_KEY || GDEX_API_KEY_PRIMARY;
const walletAddress = process.env.WALLET_ADDRESS || '';
const privateKey = process.env.PRIVATE_KEY || '';

if (!apiKey) {
  process.stdout.write(JSON.stringify({
    success: false,
    error: 'Missing required environment variable: GDEX_API_KEY',
  }));
  process.exit(1);
}

// signIn performs the full managed-custody sign-in and returns session credentials.
// chainId: 1 for EVM/HL operations, 622112261 for Solana copy trade.
async function signIn(skill, chainId) {
  if (!walletAddress || !privateKey) {
    throw new Error('WALLET_ADDRESS and PRIVATE_KEY are required for this operation');
  }
  const { sessionPrivateKey, sessionKey } = generateGdexSessionKeyPair();
  const userId = walletAddress.toLowerCase();
  const nonce = String(Math.floor(Date.now() / 1000) + Math.floor(Math.random() * 1000));
  const message = buildGdexSignInMessage(walletAddress, nonce, sessionKey);
  const wallet = new ethers.Wallet(privateKey);
  const signature = await wallet.signMessage(message);
  const signInPayload = buildGdexSignInComputedData({
    apiKey,
    userId: walletAddress,
    sessionKey,
    nonce,
    signature,
  });
  await skill.signInWithComputedData({
    computedData: signInPayload.computedData,
    chainId,
  });
  return { sessionPrivateKey, sessionKey, userId };
}

// isAddress returns true if the query looks like an EVM or Solana contract address.
function isAddress(q) {
  if (/^0x[0-9a-fA-F]{40,}$/.test(q)) return true;    // EVM address
  if (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(q)) return true; // Solana base58
  return false;
}

let inputData = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => { inputData += chunk; });
process.stdin.on('end', async () => {
  let request;
  try {
    request = JSON.parse(inputData);
  } catch (e) {
    process.stdout.write(JSON.stringify({ success: false, error: 'Invalid JSON input: ' + e.message }));
    process.exit(1);
  }

  const { action, params } = request;
  const chainId = params.chain_id != null ? Number(params.chain_id) : 622112261;

  try {
    const skill = new GdexSkill({ timeout: 45000, maxRetries: 2 });
    skill.loginWithApiKey(apiKey);

    let result;
    switch (action) {

      // ── Market Data (API key only) ───────────────────────────────────────

      case 'trending':
        result = await skill.getTrendingTokens({
          chain: chainId,
          period: params.period || '24h',
          limit: params.limit != null ? Number(params.limit) : 10,
        });
        break;

      case 'search': {
        const query = params.query;
        if (!query) {
          process.stdout.write(JSON.stringify({ success: false, error: 'query is required' }));
          process.exit(1);
        }
        if (isAddress(query)) {
          result = await skill.getTokenDetails({ chain: chainId, tokenAddress: query });
        } else {
          // No direct name-search endpoint — return trending tokens as discovery aid.
          const trending = await skill.getTrendingTokens({
            chain: chainId,
            period: '24h',
            limit: params.limit != null ? Number(params.limit) : 20,
          });
          const q = query.toLowerCase();
          const filtered = trending.filter(
            (t) =>
              (t.symbol && t.symbol.toLowerCase().includes(q)) ||
              (t.name && t.name.toLowerCase().includes(q))
          );
          result = filtered.length > 0 ? filtered : trending.slice(0, params.limit ?? 10);
        }
        break;
      }

      case 'price':
        result = await skill.getTokenDetails({
          chain: chainId,
          tokenAddress: params.token_address,
        });
        break;

      case 'scan':
        // Return recent trending tokens (1h period = most recently active tokens).
        result = await skill.getTrendingTokens({
          chain: chainId,
          period: '1h',
          limit: params.limit != null ? Number(params.limit) : 20,
        });
        break;

      // ── Portfolio / Holdings ─────────────────────────────────────────────

      case 'holdings': {
        // Portfolio queries require a session key per the backend API contract.
        // Requires WALLET_ADDRESS + PRIVATE_KEY for full session-based auth.
        const { sessionKey } = await signIn(skill, chainId);
        const data = buildGdexUserSessionData(sessionKey, apiKey);
        result = await skill.client.get('/v1/balances', {
          params: { userId: walletAddress.toLowerCase(), chainId, data },
        });
        break;
      }

      // ── Copy Trading (Solana, full sign-in) ───────────────────────────────

      case 'copy_trade': {
        // Solana copy trades sign in with the Solana chain ID.
        const { sessionPrivateKey, userId } = await signIn(skill, 622112261);
        result = await skill.createCopyTrade({
          apiKey,
          userId,
          sessionPrivateKey,
          chainId: 622112261,
          traderWallet: params.target_address,
          copyTradeName: params.name,
          buyMode: 1,
          copyBuyAmount: params.amount,
          lossPercent: params.loss_percent != null ? String(params.loss_percent) : '50',
          profitPercent: params.profit_percent != null ? String(params.profit_percent) : '100',
          copySell: true,
          isBuyExistingToken: true,
          excludedDexNumbers: [],
        });
        break;
      }

      // ── HyperLiquid Read (no auth, reads from HL L1) ──────────────────────

      case 'hl_balance': {
        const addr = params.wallet_address || walletAddress;
        if (!addr) {
          process.stdout.write(JSON.stringify({
            success: false,
            error: 'wallet_address param or WALLET_ADDRESS env var is required',
          }));
          process.exit(1);
        }
        result = await skill.getHlAccountState(addr);
        break;
      }

      case 'hl_positions': {
        const addr = params.wallet_address || walletAddress;
        if (!addr) {
          process.stdout.write(JSON.stringify({
            success: false,
            error: 'wallet_address param or WALLET_ADDRESS env var is required',
          }));
          process.exit(1);
        }
        result = await skill.getPerpPositions({
          walletAddress: addr,
          coin: params.coin,
        });
        break;
      }

      // ── HyperLiquid Write (full sign-in with EVM chainId=1) ───────────────

      case 'hl_deposit': {
        const { sessionPrivateKey } = await signIn(skill, 1);
        result = await skill.perpDeposit({
          amount: params.amount,
          tokenAddress: params.token_address || '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
          chainId: params.chain_id != null ? Number(params.chain_id) : 42161,
          apiKey,
          walletAddress,
          sessionPrivateKey,
        });
        break;
      }

      case 'hl_create_order': {
        const { sessionPrivateKey } = await signIn(skill, 1);
        result = await skill.hlCreateOrder({
          coin: params.coin || 'ETH',
          isLong: params.is_long != null ? Boolean(params.is_long) : true,
          price: params.price || '0',
          size: params.size,
          reduceOnly: params.reduce_only != null ? Boolean(params.reduce_only) : false,
          isMarket: params.is_market != null ? Boolean(params.is_market) : false,
          tpPrice: params.tp_price || '0',
          slPrice: params.sl_price || '0',
          apiKey,
          walletAddress,
          sessionPrivateKey,
        });
        break;
      }

      case 'hl_cancel_order': {
        const { sessionPrivateKey } = await signIn(skill, 1);
        if (params.cancel_all) {
          result = await skill.hlCancelAllOrders({
            apiKey,
            walletAddress,
            sessionPrivateKey,
          });
        } else {
          result = await skill.hlCancelOrder({
            coin: params.coin || 'ETH',
            orderId: params.order_id,
            apiKey,
            walletAddress,
            sessionPrivateKey,
          });
        }
        break;
      }

      default:
        process.stdout.write(JSON.stringify({ success: false, error: 'Unknown action: ' + action }));
        process.exit(1);
    }

    process.stdout.write(JSON.stringify({ success: true, data: result }));
  } catch (err) {
    process.stdout.write(JSON.stringify({ success: false, error: err.message || String(err) }));
    process.exit(1);
  }
});
