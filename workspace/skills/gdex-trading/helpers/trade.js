#!/usr/bin/env node
/**
 * GDEX Trade Helper (v2 — @gdexsdk/gdex-skill)
 * Reads a JSON action descriptor from stdin, executes the trade, and writes JSON result to stdout.
 *
 * Input JSON:
 *   { "action": "buy"|"sell"|"limit_buy"|"limit_sell", "params": { ... } }
 *
 * Output JSON:
 *   { "success": true, "data": { ... } }  or  { "success": false, "error": "..." }
 *
 * Environment variables:
 *   GDEX_API_KEY    — required for all operations
 *   WALLET_ADDRESS  — required for limit orders (control wallet address)
 *   PRIVATE_KEY     — required for limit orders (EVM private key for signing)
 */

'use strict';

const {
  GdexSkill,
  GDEX_API_KEY_PRIMARY,
  generateGdexSessionKeyPair,
  buildGdexSignInMessage,
  buildGdexSignInComputedData,
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

// signIn performs the full managed-custody sign-in flow using the EVM private key.
// Returns { sessionPrivateKey, sessionKey, userId }.
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
      case 'buy':
        result = await skill.buyToken({
          chain: chainId,
          tokenAddress: params.token_address,
          amount: params.amount,
          slippage: params.slippage != null ? Number(params.slippage) : 1,
          ...(walletAddress ? { walletAddress } : {}),
        });
        break;

      case 'sell':
        result = await skill.sellToken({
          chain: chainId,
          tokenAddress: params.token_address,
          amount: params.amount,
          slippage: params.slippage != null ? Number(params.slippage) : 1,
          ...(walletAddress ? { walletAddress } : {}),
        });
        break;

      case 'limit_buy': {
        // Limit orders require full managed-custody sign-in.
        // Sign in with the chain ID of the trade.
        const { sessionPrivateKey, userId } = await signIn(skill, chainId);
        result = await skill.limitBuy({
          apiKey,
          userId,
          sessionPrivateKey,
          chainId,
          tokenAddress: params.token_address,
          amount: params.amount,
          triggerPrice: params.trigger_price,
          profitPercent: params.profit_percent != null ? String(params.profit_percent) : '0',
          lossPercent: params.loss_percent != null ? String(params.loss_percent) : '0',
        });
        break;
      }

      case 'limit_sell': {
        const { sessionPrivateKey, userId } = await signIn(skill, chainId);
        result = await skill.limitSell({
          apiKey,
          userId,
          sessionPrivateKey,
          chainId,
          tokenAddress: params.token_address,
          amount: params.amount,
          triggerPrice: params.trigger_price,
        });
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
