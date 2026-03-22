#!/usr/bin/env node
/**
 * GDEX Market Data Helper (v2 — @gdexsdk/gdex-skill)
 * Reads a JSON action descriptor from stdin, fetches market/portfolio data, and writes JSON to stdout.
 *
 * Input JSON:
 *   { "action": "trending"|"search"|"price"|"holdings"|"scan"|
 *               "copy_trade"|"hl_balance"|"hl_positions"|"hl_deposit"|
 *               "hl_withdraw"|"hl_create_order"|"hl_cancel_order"|
 *               "bridge_estimate"|"bridge_request"|"bridge_orders",
 *     "params": { ... } }
 *
 * Output JSON:
 *   { "success": true, "data": { ... } }  or  { "success": false, "error": "..." }
 *
 * Environment variables:
 *   GDEX_API_KEY    — required for all operations
 *   WALLET_ADDRESS  — required for holdings, copy_trade, hl_* operations, bridge_request, bridge_orders
 *   PRIVATE_KEY     — required for copy_trade, hl_deposit, hl_create_order, hl_cancel_order, bridge_request, bridge_orders
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
const ARBITRUM_CHAIN_ID = 42161;
const ARBITRUM_USDC = '0xaf88d065e77c8cc2239327c5edb3a432268e5831';
const ARBITRUM_WETH = '0x82af49447d8a07e3bd95bd0d56f35241523fbab1';

if (!apiKey) {
  process.stdout.write(JSON.stringify({
    success: false,
    error: 'Missing required environment variable: GDEX_API_KEY',
  }));
  process.exit(1);
}

// signIn performs the full managed-custody sign-in and returns session credentials.
// chainId: 1 for EVM/HyperLiquid/bridge auth context, 622112261 for Solana copy trade.
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

function pickManagedAddress(user) {
  if (!user || typeof user !== 'object') return '';
  return String(
    user.evmAddress ||
    user.address ||
    user.walletAddress ||
    user.userWallet ||
    ''
  );
}

async function explainHlOrderFailure(skill, sessionKey, err) {
  const formatted = formatHelperError(err);
  if (!/User or API Wallet .* does not exist/i.test(formatted) || !sessionKey || !walletAddress) {
    return err;
  }

  try {
    const data = buildGdexUserSessionData(sessionKey, apiKey);
    const user = await skill.getManagedUser({
      userId: walletAddress,
      data,
      chainId: 42161,
    });
    const managedAddress = pickManagedAddress(user);
    if (!managedAddress) {
      return err;
    }

    const state = await skill.getHlAccountState(managedAddress);
    const accountValue = Number(state?.accountValue || 0);
    const withdrawable = Number(state?.withdrawable || 0);
    const positions = Array.isArray(state?.positions) ? state.positions.length : 0;
    if (accountValue <= 0 && withdrawable <= 0 && positions === 0) {
      return new Error(
        `HyperLiquid account ${managedAddress} is not funded yet. Deposit at least 10 USDC on Arbitrum with gdex_hl_deposit; if only ETH is funded on Arbitrum, gdex_hl_deposit can auto-swap ETH into USDC first.`
      );
    }
  } catch {
    // Keep the backend error if the diagnostic probe fails.
  }

  return err;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toFiniteNumber(value) {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : Number.NaN;
  }
  if (typeof value === 'string') {
    const parsed = Number(value.trim());
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }
  return Number.NaN;
}

function boolParam(value, fallback) {
  if (value == null) return fallback;
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (['false', '0', 'no', 'n'].includes(normalized)) return false;
    if (['true', '1', 'yes', 'y'].includes(normalized)) return true;
  }
  return Boolean(value);
}

function formatAmount(value, decimals = 6) {
  const numeric = toFiniteNumber(value);
  if (!Number.isFinite(numeric)) return String(value);
  return numeric.toFixed(decimals).replace(/\.?0+$/, '') || '0';
}

function extractManagedTradeRequestId(result) {
  if (!result || typeof result !== 'object') return '';
  const requestId = String(result.requestId || result.jobId || '').trim();
  return requestId;
}

function isManagedTradeFinal(status) {
  return ['completed', 'confirmed', 'success', 'failed', 'error', 'cancelled'].includes(String(status || '').toLowerCase());
}

async function pollManagedTradeStatus(skill, requestId, waitSeconds) {
  const safeWaitSeconds = Number.isFinite(waitSeconds) && waitSeconds > 0 ? waitSeconds : 90;
  const intervalMs = 2000;
  const attempts = Math.max(1, Math.ceil((safeWaitSeconds * 1000) / intervalMs));
  let last = null;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (attempt > 0) {
      await sleep(intervalMs);
    }
    try {
      last = await skill.getManagedTradeStatus(requestId);
    } catch {
      continue;
    }
    if (isManagedTradeFinal(last?.status)) {
      return last;
    }
  }

  return last;
}

function flattenPortfolioEntries(node) {
  if (Array.isArray(node)) {
    return node.flatMap(flattenPortfolioEntries);
  }
  if (!node || typeof node !== 'object') {
    return [];
  }

  const tokenAddress = String(
    node.tokenAddress ||
    node.token_address ||
    node.address ||
    ''
  ).trim();
  const symbol = String(node.symbol || node.name || '').trim();
  const directBalance = toFiniteNumber(
    node.balance ??
    node.amount ??
    node.uiAmount ??
    node.ui_amount ??
    node.quantity ??
    node.tokenAmount ??
    node.token_amount ??
    node.humanAmount ??
    node.human_amount
  );
  const usdValue = toFiniteNumber(node.usdValue ?? node.usd_value ?? node.valueUsd ?? node.value_usd);
  const priceUsd = toFiniteNumber(node.priceUsd ?? node.price_usd ?? node.usdPrice ?? node.usd_price);

  if (tokenAddress || symbol || Number.isFinite(directBalance) || (Number.isFinite(usdValue) && Number.isFinite(priceUsd) && priceUsd > 0)) {
    return [node];
  }

  const children = [];
  for (const key of ['data', 'balances', 'tokens', 'items', 'results', 'pairs', 'holding']) {
    if (node[key] != null) {
      children.push(...flattenPortfolioEntries(node[key]));
    }
  }
  return children;
}

function entryBalance(entry) {
  const direct = toFiniteNumber(
    entry.balance ??
    entry.amount ??
    entry.uiAmount ??
    entry.ui_amount ??
    entry.quantity ??
    entry.tokenAmount ??
    entry.token_amount ??
    entry.humanAmount ??
    entry.human_amount
  );
  if (Number.isFinite(direct)) {
    return direct;
  }

  const usdValue = toFiniteNumber(entry.usdValue ?? entry.usd_value ?? entry.valueUsd ?? entry.value_usd);
  const priceUsd = toFiniteNumber(entry.priceUsd ?? entry.price_usd ?? entry.usdPrice ?? entry.usd_price);
  if (Number.isFinite(usdValue) && Number.isFinite(priceUsd) && priceUsd > 0) {
    return usdValue / priceUsd;
  }
  return 0;
}

function tokenMatches(entry, tokenAddress, symbols = []) {
  const normalizedAddress = String(
    entry.tokenAddress ||
    entry.token_address ||
    entry.tokenInfo?.address ||
    entry.address ||
    ''
  ).trim().toLowerCase();
  if (normalizedAddress && normalizedAddress === tokenAddress.toLowerCase()) {
    return true;
  }

  const symbol = String(
    entry.symbol ||
    entry.name ||
    entry.tokenInfo?.symbol ||
    entry.tokenInfo?.name ||
    ''
  ).trim().toUpperCase();
  return symbol !== '' && symbols.map((item) => item.toUpperCase()).includes(symbol);
}

function findTokenBalance(entries, tokenAddress, symbols = []) {
  return entries.reduce((best, entry) => {
    if (!tokenMatches(entry, tokenAddress, symbols)) {
      return best;
    }
    return Math.max(best, entryBalance(entry));
  }, 0);
}

async function getPortfolioEntries(skill, sessionKey, chainId) {
  const data = buildGdexUserSessionData(sessionKey, apiKey);
  const portfolio = await skill.client.get('/v1/portfolio', {
    userId: walletAddress,
    chainId,
    data,
  });
  return flattenPortfolioEntries(portfolio);
}

async function getManagedUserForChain(skill, sessionKey, chainId) {
  const data = buildGdexUserSessionData(sessionKey, apiKey);
  return skill.getManagedUser({
    userId: walletAddress,
    data,
    chainId,
  });
}

async function getArbitrumETHPriceUSD(skill) {
  const gdexTargets = [
    { chain: ARBITRUM_CHAIN_ID, tokenAddress: ARBITRUM_WETH },
    { chain: 1, tokenAddress: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2' },
  ];
  for (const target of gdexTargets) {
    try {
      const token = await skill.getTokenDetails({
        chain: target.chain,
        tokenAddress: target.tokenAddress,
      });
      const candidates = []
        .concat(token?.tokens || [])
        .concat(token?.token ? [token.token] : [])
        .concat(token ? [token] : []);
      for (const candidate of candidates) {
        const price = toFiniteNumber(candidate?.priceUsd ?? candidate?.price_usd ?? candidate?.usdPrice ?? candidate?.usd_price);
        if (price > 0) {
          return price;
        }
      }
    } catch {
      // Fall through to the next source.
    }
  }

  const externalTargets = [
    async () => {
      const response = await fetch('https://api.coinbase.com/v2/prices/ETH-USD/spot');
      if (!response.ok) return Number.NaN;
      const payload = await response.json();
      return toFiniteNumber(payload?.data?.amount);
    },
    async () => {
      const response = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd');
      if (!response.ok) return Number.NaN;
      const payload = await response.json();
      return toFiniteNumber(payload?.ethereum?.usd);
    },
  ];

  for (const fetchPrice of externalTargets) {
    try {
      const price = await fetchPrice();
      if (price > 0) {
        return price;
      }
    } catch {
      // Try the next endpoint.
    }
  }

  throw new Error('Unable to price Arbitrum ETH for HyperLiquid auto-funding');
}

function buildManagedPurchasePayload(userId, tokenAddress, nativeAmount, sessionPrivateKey) {
  const amountWei = ethers.parseUnits(formatAmount(nativeAmount, 18), 18).toString();
  return buildGdexManagedTradeComputedData({
    apiKey,
    action: 'purchase',
    userId,
    tokenAddress,
    amount: amountWei,
    nonce: String(Math.floor(Date.now() / 1000) + Math.floor(Math.random() * 1000)),
    sessionPrivateKey,
  });
}

async function prepareHyperLiquidDeposit(skill, sessionKey, sessionPrivateKey, params) {
  const requestedAmount = toFiniteNumber(params.amount);
  if (!(requestedAmount > 0)) {
    throw new Error(`Invalid HyperLiquid deposit amount: "${params.amount}"`);
  }

  const depositChainId = params.chain_id != null ? Number(params.chain_id) : ARBITRUM_CHAIN_ID;
  const depositTokenAddress = String(params.token_address || ARBITRUM_USDC).trim().toLowerCase();
  if (depositChainId !== ARBITRUM_CHAIN_ID || depositTokenAddress !== ARBITRUM_USDC) {
    return { depositAmount: formatAmount(requestedAmount), prefund: null };
  }

  const entriesBefore = await getPortfolioEntries(skill, sessionKey, ARBITRUM_CHAIN_ID);
  const usdcBefore = findTokenBalance(entriesBefore, ARBITRUM_USDC, ['USDC']);
  if (usdcBefore >= requestedAmount) {
    return { depositAmount: formatAmount(requestedAmount), prefund: null };
  }

  const autoFundFromNative = boolParam(params.auto_fund_from_native, true);
  if (!autoFundFromNative) {
    return { depositAmount: formatAmount(requestedAmount), prefund: null };
  }

  const user = await getManagedUserForChain(skill, sessionKey, ARBITRUM_CHAIN_ID);
  const managedAddress = pickManagedAddress(user) || 'unknown';
  const nativeBalance = toFiniteNumber(user?.balance);
  if (!(nativeBalance > 0)) {
    throw new Error(
      `Managed Arbitrum wallet ${managedAddress} needs ${formatAmount(requestedAmount - usdcBefore)} more USDC for HyperLiquid funding and has no ETH available to auto-swap`
    );
  }

  const deficitUSDC = Math.max(requestedAmount - usdcBefore, 0);
  const ethPriceUSD = await getArbitrumETHPriceUSD(skill);
  const bufferPercent = Math.max(toFiniteNumber(params.prefund_buffer_percent), 0);
  const effectiveBufferPercent = Number.isFinite(bufferPercent) ? bufferPercent : 3;
  const nativeSpend = (deficitUSDC / ethPriceUSD) * (1 + effectiveBufferPercent / 100);
  if (!(nativeSpend > 0)) {
    return { depositAmount: formatAmount(requestedAmount), prefund: null };
  }
  if (nativeBalance < nativeSpend) {
    throw new Error(
      `Managed Arbitrum wallet ${managedAddress} has ${formatAmount(nativeBalance, 6)} ETH but needs about ${formatAmount(nativeSpend, 6)} ETH to auto-fund ${formatAmount(deficitUSDC)} USDC for HyperLiquid`
    );
  }

  const slippage = params.prefund_slippage != null ? Number(params.prefund_slippage) : 1;
  const waitSeconds = params.prefund_wait_seconds != null ? Number(params.prefund_wait_seconds) : 90;
  const trade = buildManagedPurchasePayload(walletAddress, ARBITRUM_USDC, nativeSpend, sessionPrivateKey);
  const purchase = await skill.submitManagedPurchase({
    computedData: trade.computedData,
    chainId: ARBITRUM_CHAIN_ID,
    slippage: Number.isFinite(slippage) ? slippage : 1,
  });
  const requestId = extractManagedTradeRequestId(purchase);
  const purchaseStatus = requestId ? await pollManagedTradeStatus(skill, requestId, waitSeconds) : null;
  const purchaseState = String(purchaseStatus?.status || purchase?.status || '').toLowerCase();
  if (purchaseState === 'failed' || purchaseState === 'error' || purchaseState === 'cancelled') {
    throw new Error(
      `Auto-funding swap ${requestId || 'unknown'} failed with status ${purchaseState || 'unknown'}`
    );
  }

  let usdcAfter = usdcBefore;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    if (attempt > 0) {
      await sleep(2000);
    }
    const entries = await getPortfolioEntries(skill, sessionKey, ARBITRUM_CHAIN_ID);
    usdcAfter = findTokenBalance(entries, ARBITRUM_USDC, ['USDC']);
    if (usdcAfter >= requestedAmount || usdcAfter >= 10) {
      break;
    }
  }

  const depositAmount = Math.min(requestedAmount, usdcAfter);
  if (!(depositAmount >= 10)) {
    if (requestId) {
      throw new Error(
        `Auto-funding swap ${requestId} is ${purchaseState || 'pending'} but no usable USDC balance is visible yet; rerun gdex_hl_deposit after settlement`
      );
    }
    throw new Error(
      `Auto-swap from Arbitrum ETH completed but only ${formatAmount(usdcAfter)} USDC is available for HyperLiquid funding; minimum deposit is 10 USDC`
    );
  }

  return {
    depositAmount: formatAmount(depositAmount),
    prefund: {
      sourceChainId: ARBITRUM_CHAIN_ID,
      sourceAsset: 'ETH',
      targetAsset: 'USDC',
      requestedAmount: formatAmount(requestedAmount),
      depositAmount: formatAmount(depositAmount),
      usdcBefore: formatAmount(usdcBefore),
      usdcAfter: formatAmount(usdcAfter),
      nativeSpent: formatAmount(nativeSpend, 18),
      purchase,
      purchaseStatus,
    },
  };
}

async function prepareHyperLiquidWithdraw(skill, sessionKey, params) {
  const requestedAmount = toFiniteNumber(params.amount);
  if (!(requestedAmount > 0)) {
    throw new Error(`Invalid HyperLiquid withdraw amount: "${params.amount}"`);
  }

  // The backend currently rounds HL withdrawals to one decimal place and applies
  // about a 1 USDC fee, so tiny withdrawals and near-full-balance requests fail.
  const roundedAmount = Number(requestedAmount.toFixed(1));
  if (!(roundedAmount > 1)) {
    throw new Error(
      `HyperLiquid withdraw amount must round above 1.0 USDC because the backend currently applies about a 1 USDC withdraw fee`
    );
  }

  try {
    const user = await getManagedUserForChain(skill, sessionKey, ARBITRUM_CHAIN_ID);
    const managedAddress = pickManagedAddress(user) || 'unknown';
    if (managedAddress && managedAddress !== 'unknown') {
      const state = await skill.getHlAccountState(managedAddress);
      const withdrawable = toFiniteNumber(state?.withdrawable);
      if (withdrawable > 0 && roundedAmount + 1 > withdrawable) {
        throw new Error(
          `HyperLiquid withdraw ${formatAmount(roundedAmount, 1)} USDC plus the current 1 USDC fee exceeds withdrawable ${formatAmount(withdrawable, 6)} USDC on managed wallet ${managedAddress}`
        );
      }
    }
  } catch (err) {
    if (err instanceof Error) {
      throw err;
    }
  }

  return { withdrawAmount: formatAmount(roundedAmount, 1) };
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
        const portfolio = await skill.client.get('/v1/portfolio', {
          userId: walletAddress,
          chainId,
          data,
        });
        result = portfolio?.balances || portfolio?.tokens || portfolio;
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

      // ── HyperLiquid Write (EVM sign-in, Arbitrum settlement) ──────────────

      case 'hl_deposit': {
        const { sessionPrivateKey, sessionKey } = await signIn(skill, 1);
        const funding = await prepareHyperLiquidDeposit(skill, sessionKey, sessionPrivateKey, params);
        const deposit = await skill.perpDeposit({
          amount: funding.depositAmount,
          tokenAddress: params.token_address || ARBITRUM_USDC,
          chainId: params.chain_id != null ? Number(params.chain_id) : ARBITRUM_CHAIN_ID,
          apiKey,
          walletAddress,
          sessionPrivateKey,
        });
        result = funding.prefund ? {
          prefund: funding.prefund,
          deposit,
        } : deposit;
        break;
      }

      case 'hl_withdraw': {
        const { sessionPrivateKey, sessionKey } = await signIn(skill, 1);
        const withdraw = await prepareHyperLiquidWithdraw(skill, sessionKey, params);
        result = await skill.perpWithdraw({
          amount: withdraw.withdrawAmount,
          apiKey,
          walletAddress,
          sessionPrivateKey,
        });
        break;
      }

      case 'hl_create_order': {
        const { sessionPrivateKey, sessionKey } = await signIn(skill, 1);
        try {
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
        } catch (err) {
          throw await explainHlOrderFailure(skill, sessionKey, err);
        }
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

      // ── Cross-chain Bridge ────────────────────────────────────────────────

      case 'bridge_estimate': {
        if (params.from_chain_id == null || params.to_chain_id == null || !params.amount) {
          process.stdout.write(JSON.stringify({
            success: false,
            error: 'from_chain_id, to_chain_id, and amount are required',
          }));
          process.exit(1);
        }
        result = await skill.estimateBridge({
          fromChainId: Number(params.from_chain_id),
          toChainId: Number(params.to_chain_id),
          amount: String(params.amount),
        });
        break;
      }

      case 'bridge_request': {
        if (params.from_chain_id == null || params.to_chain_id == null || !params.amount) {
          process.stdout.write(JSON.stringify({
            success: false,
            error: 'from_chain_id, to_chain_id, and amount are required',
          }));
          process.exit(1);
        }
        const { sessionPrivateKey } = await signIn(skill, 1);
        result = await skill.requestBridge({
          fromChainId: Number(params.from_chain_id),
          toChainId: Number(params.to_chain_id),
          amount: String(params.amount),
          userId: walletAddress,
          apiKey,
          sessionPrivateKey,
        });
        break;
      }

      case 'bridge_orders': {
        const { sessionKey } = await signIn(skill, 1);
        result = await skill.getBridgeOrders({
          userId: walletAddress,
          data: buildGdexUserSessionData(sessionKey, apiKey),
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
