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
  buildGdexManagedTradeComputedData,
  buildGdexUserSessionData,
} = require('@gdexsdk/gdex-skill');
const { ethers } = require('ethers');

const apiKey = process.env.GDEX_API_KEY || GDEX_API_KEY_PRIMARY;
const walletAddress = process.env.WALLET_ADDRESS || '';
const privateKey = process.env.PRIVATE_KEY || '';
const SOLANA_ADDRESS_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
const WSOL_MINT = 'So11111111111111111111111111111111111111112';

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
  const userId = walletAddress;
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

async function submitManagedSolanaPurchase(skill, params) {
  if (!params.token_address || typeof params.token_address !== 'string') {
    throw new Error('token_address is required');
  }
  if (params.token_address !== WSOL_MINT && !SOLANA_ADDRESS_RE.test(params.token_address)) {
    throw new Error(`Invalid Solana address format for token_address: "${params.token_address}"`);
  }
  if (!walletAddress || !privateKey) {
    throw new Error('WALLET_ADDRESS and PRIVATE_KEY are required for Solana managed purchases');
  }

  const { sessionPrivateKey, sessionKey, userId } = await signIn(skill, 622112261);
  const userData = buildGdexUserSessionData(sessionKey, apiKey);
  const user = await skill.getManagedUser({
    userId,
    data: userData,
    chainId: 622112261,
  });

  const managedAddress = user && user.address ? user.address : 'unknown';
  const balance = Number(user && user.balance ? user.balance : 0);
  const requested = Number(params.amount);
  if (!Number.isFinite(requested) || requested <= 0) {
    throw new Error(`Invalid SOL purchase amount: "${params.amount}"`);
  }
  if (!(balance > 0)) {
    throw new Error(`Managed Solana wallet ${managedAddress} has 0 SOL available; deposit SOL before trading`);
  }
  if (balance < requested) {
    throw new Error(`Managed Solana wallet ${managedAddress} balance ${balance} SOL is below requested buy amount ${params.amount} SOL`);
  }

  const amountLamports = ethers.parseUnits(String(params.amount), 9).toString();
  const trade = buildGdexManagedTradeComputedData({
    apiKey,
    action: 'purchase',
    userId,
    tokenAddress: params.token_address,
    amount: amountLamports,
    nonce: String(Math.floor(Date.now() / 1000) + Math.floor(Math.random() * 1000)),
    sessionPrivateKey,
  });
  return skill.submitManagedPurchase({
    computedData: trade.computedData,
    chainId: 622112261,
    slippage: params.slippage != null ? Number(params.slippage) : 1,
  });
}

function pickManagedAddress(user) {
  if (!user || typeof user !== 'object') return 'unknown';
  return String(
    user.address ||
    user.walletAddress ||
    user.evmAddress ||
    user.userWallet ||
    'unknown'
  );
}

function evmNativeSymbol(chainId) {
  switch (Number(chainId)) {
    case 56:
      return 'BNB';
    case 137:
      return 'MATIC';
    case 43114:
      return 'AVAX';
    default:
      return 'ETH';
  }
}

async function submitManagedEvmPurchase(skill, chainId, params) {
  if (!params.token_address || typeof params.token_address !== 'string') {
    throw new Error('token_address is required');
  }
  if (!walletAddress || !privateKey) {
    throw new Error('WALLET_ADDRESS and PRIVATE_KEY are required for EVM managed purchases');
  }

  const requested = Number(params.amount);
  if (!Number.isFinite(requested) || requested <= 0) {
    throw new Error(`Invalid native purchase amount: "${params.amount}"`);
  }

  const { sessionPrivateKey, sessionKey, userId } = await signIn(skill, chainId);
  const userData = buildGdexUserSessionData(sessionKey, apiKey);

  let user = null;
  try {
    user = await skill.getManagedUser({
      userId,
      data: userData,
      chainId,
    });
  } catch {
    // Fall through to the managed trade call if lookup is unavailable.
  }

  const managedAddress = pickManagedAddress(user);
  const nativeSymbol = evmNativeSymbol(chainId);
  const balance = Number(user && user.balance ? user.balance : Number.NaN);
  if (Number.isFinite(balance) && !(balance > 0)) {
    throw new Error(`Managed EVM wallet ${managedAddress} has 0 ${nativeSymbol} available on chain ${chainId}; deposit ${nativeSymbol} before trading`);
  }
  if (Number.isFinite(balance) && balance < requested) {
    throw new Error(`Managed EVM wallet ${managedAddress} balance ${balance} ${nativeSymbol} is below requested buy amount ${params.amount} ${nativeSymbol}`);
  }

  const amountWei = ethers.parseUnits(String(params.amount), 18).toString();
  const trade = buildGdexManagedTradeComputedData({
    apiKey,
    action: 'purchase',
    userId,
    tokenAddress: params.token_address,
    amount: amountWei,
    nonce: String(Math.floor(Date.now() / 1000) + Math.floor(Math.random() * 1000)),
    sessionPrivateKey,
  });
  return skill.submitManagedPurchase({
    computedData: trade.computedData,
    chainId,
    slippage: params.slippage != null ? Number(params.slippage) : 1,
  });
}

function normalizeSpotTradeChain(chainValue) {
  if (chainValue == null || chainValue === '') return 'solana';
  if (chainValue === 'solana' || chainValue === '622112261' || chainValue === 622112261) {
    return 'solana';
  }
  if (chainValue === 'sui') return 'sui';
  const numeric = Number(chainValue);
  return Number.isNaN(numeric) ? chainValue : numeric;
}

function normalizeChainId(chainValue) {
  if (chainValue == null || chainValue === '' || chainValue === 'solana' || chainValue === '622112261' || chainValue === 622112261) {
    return 622112261;
  }
  const numeric = Number(chainValue);
  return Number.isNaN(numeric) ? chainValue : numeric;
}

function formatHelperError(err) {
  const message = (err && err.message) ? err.message : String(err);
  const body = err && (err.responseBody || (err.response && err.response.data));
  if (!body) return message;

  let bodyText;
  if (typeof body === 'string') {
    bodyText = body;
  } else {
    try {
      bodyText = JSON.stringify(body);
    } catch {
      bodyText = String(body);
    }
  }

  bodyText = String(bodyText || '').trim();
  if (!bodyText || message.includes(bodyText)) return message;
  return `${message} | body: ${bodyText}`;
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
  const requestedChain = params.chain_id != null ? params.chain_id : params.chain;
  const chainId = normalizeChainId(requestedChain);
  const spotChain = normalizeSpotTradeChain(requestedChain);

  try {
    const skill = new GdexSkill({ timeout: 45000, maxRetries: 2 });
    skill.loginWithApiKey(apiKey);

    let result;
    switch (action) {
      case 'buy':
        if (spotChain === 'solana') {
          result = await submitManagedSolanaPurchase(skill, params);
        } else if (Number.isFinite(Number(chainId))) {
          result = await submitManagedEvmPurchase(skill, Number(chainId), params);
        } else {
          result = await skill.buyToken({
            chain: spotChain,
            tokenAddress: params.token_address,
            amount: params.amount,
            slippage: params.slippage != null ? Number(params.slippage) : 1,
            ...(walletAddress ? { walletAddress } : {}),
          });
        }
        break;

      case 'sell':
        result = await skill.sellToken({
          chain: spotChain,
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
    process.stdout.write(JSON.stringify({ success: false, error: formatHelperError(err) }));
    process.exit(1);
  }
});
