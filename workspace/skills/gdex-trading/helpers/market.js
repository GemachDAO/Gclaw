#!/usr/bin/env node
/**
 * GDEX Market Data Helper
 * Reads a JSON action descriptor from stdin, fetches market data, and writes JSON result to stdout.
 *
 * Input JSON:
 *   { "action": "trending"|"search"|"price"|"holdings"|"scan"|"copy_trade"|"hl_balance"|"hl_positions",
 *     ...params at top level or in "params" key }
 *
 * Output JSON:
 *   { "success": true, "data": { ... } }  or  { "success": false, "error": "..." }
 */

'use strict';

// Redirect all console.log to stderr so SDK internal logging doesn't pollute stdout
// Only the final JSON result will be written to stdout
const _origLog = console.log;
console.log = (...args) => process.stderr.write(args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ') + '\n');

const { GDEXSDK, CryptoUtils, encrypt } = require('gdex.pro-sdk');
const { ethers } = require('ethers');

const API_URL = 'https://trade-api.gemach.io/v1';
const DEFAULT_CHAIN_ID = 622112261;

const rawApiKey = process.env.GDEX_API_KEY || '';
const apiKey = rawApiKey.split(',')[0].trim();
const walletAddress = process.env.GDEX_WALLET_ADDRESS || process.env.WALLET_ADDRESS || '';
const privateKey = process.env.GDEX_PRIVATE_KEY || process.env.PRIVATE_KEY || '';

if (!apiKey) {
  process.stdout.write(JSON.stringify({
    success: false,
    error: 'Missing required environment variable: GDEX_API_KEY',
  }));
  process.exit(1);
}

/**
 * loginSDK — authenticate with GDEX and return an active SDK session.
 *
 * Four requirements for correct GDEX authentication:
 *
 * 1. EIP-191 signing: use ethers.Wallet.signMessage(), NOT CryptoUtils.sign().
 *    The GDEX API verifies a personal_sign / eth_sign compatible signature.
 *
 * 2. ToS message format: the message to sign must be exactly:
 *    "By signing, you agree to GDEX Trading Terms of Use and Privacy Policy.
 *     Your GDEX log in message: <address_lowercase> <nonce> <publicKeyHex>"
 *    where publicKeyHex is the raw hex (no 0x prefix).
 *
 * 3. 0x prefix for sdk.user.login(): pass '0x' + publicKeyHex as the public
 *    key argument. Omitting the prefix causes an INVALID_ARGUMENT error.
 *
 * 4. Encrypted session key for read APIs: getHoldingsList (and other
 *    authenticated GET calls) expect encrypt('0x' + publicKeyHex, apiKey),
 *    not the raw public key string.
 *
 * Returns { sdk, sessionKeyHex } where sessionKeyHex is the encrypted session key for GET requests.
 */
async function loginSDK() {
  const sdk = new GDEXSDK(API_URL, { apiKey });
  const sessionKeyPair = CryptoUtils.getSessionKey();
  // publicKey/privateKey may be Uint8Array or Buffer; use Buffer.from() to normalize
  const publicKeyHex = Buffer.from(sessionKeyPair.publicKey).toString('hex');
  // SDK login() requires 0x-prefixed bytes, but message uses raw hex
  const publicKeyHex0x = '0x' + publicKeyHex;

  const nonce = CryptoUtils.generateUniqueNumber();
  // EIP-191 signing per GDEX API requirements (message uses raw hex without 0x)
  const message = `By signing, you agree to GDEX Trading Terms of Use and Privacy Policy. Your GDEX log in message: ${walletAddress.toLowerCase()} ${nonce} ${publicKeyHex}`;
  const wallet = new ethers.Wallet(privateKey);
  const signature = await wallet.signMessage(message);

  await sdk.user.login(walletAddress, nonce, publicKeyHex0x, signature, '', 1);
  // getHoldingsList and other read APIs expect an encrypted session key
  const encryptedSessionKey = encrypt(publicKeyHex0x, apiKey);

  return { sdk, sessionKeyHex: encryptedSessionKey };
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

  // Support both flat params and nested { action, params: {...} }
  const action = request.action;
  const params = request.params || request;

  if (!action) {
    process.stdout.write(JSON.stringify({ success: false, error: 'Missing "action" field in input JSON' }));
    process.exit(1);
  }

  try {
    let result;

    // Unauthenticated token actions - no login needed
    if (action === 'trending') {
      const sdk = new GDEXSDK(API_URL, { apiKey });
      const limit = params.limit ?? 10;
      result = await sdk.tokens.getTrendingTokens(limit);

    } else if (action === 'search') {
      const sdk = new GDEXSDK(API_URL, { apiKey });
      const query = params.query || params.search || '';
      const limit = params.limit ?? 20;
      result = await sdk.tokens.searchTokens(query, limit);

    } else if (action === 'price') {
      const sdk = new GDEXSDK(API_URL, { apiKey });
      const tokenAddress = params.token_address || params.tokenAddress;
      const chainId = params.chain_id || params.chainId || null;
      // getToken(tokenAddress, chainId, isAddress=true)
      result = await sdk.tokens.getToken(tokenAddress, chainId, true);

    } else if (action === 'scan') {
      // getNewestTokens - scan for newest tokens
      const sdk = new GDEXSDK(API_URL, { apiKey });
      const chainId = params.chain_id || params.chainId || DEFAULT_CHAIN_ID;
      const limit = params.limit ?? 20;
      result = await sdk.tokens.getNewestTokens(chainId, limit);

    } else if (action === 'hl_balance') {
      // Unauthenticated - just needs a wallet address
      const sdk = new GDEXSDK(API_URL, { apiKey });
      const address = params.wallet_address || params.address || walletAddress;
      result = await sdk.hyperLiquid.getHyperliquidUsdcBalance(address);

    } else if (action === 'hl_positions') {
      // Unauthenticated - just needs a wallet address
      const sdk = new GDEXSDK(API_URL, { apiKey });
      const address = params.wallet_address || params.address || walletAddress;
      result = await sdk.hyperLiquid.getHyperliquidClearinghouseState(address);

    } else if (action === 'holdings') {
      // Authenticated - requires login
      if (!walletAddress || !privateKey) {
        process.stdout.write(JSON.stringify({
          success: false,
          error: 'Missing required environment variables for authenticated call: GDEX_WALLET_ADDRESS, GDEX_PRIVATE_KEY',
        }));
        process.exit(1);
      }
      const { sdk, sessionKeyHex } = await loginSDK();
      const chainId = params.chain_id || params.chainId || DEFAULT_CHAIN_ID;
      result = await sdk.user.getHoldingsList(walletAddress, chainId, sessionKeyHex);

    } else if (action === 'copy_trade') {
      // Authenticated - requires login
      if (!walletAddress || !privateKey) {
        process.stdout.write(JSON.stringify({
          success: false,
          error: 'Missing required environment variables for authenticated call: GDEX_WALLET_ADDRESS, GDEX_PRIVATE_KEY',
        }));
        process.exit(1);
      }
      const { sdk } = await loginSDK();
      // createCopyTrade(walletAddress, traderWallet, copyTradeName, gasPrice, buyMode, chainId,
      //                 copyBuyAmount, isBuyExistingToken, lossPercent, profitPercent,
      //                 copySell, excludedTokens, privateKey)
      const traderWallet = params.target_address || params.trader_wallet;
      const name = params.name || 'Copy Trade';
      const gasPrice = params.gas_price || '0';
      const buyMode = params.buy_mode || 'fixed';
      const chainId = params.chain_id || params.chainId || DEFAULT_CHAIN_ID;
      const copyBuyAmount = params.amount || params.copy_buy_amount || '0.01';
      const isBuyExistingToken = params.buy_existing ?? false;
      const lossPercent = params.loss_percent ?? 0;
      const profitPercent = params.profit_percent ?? 0;
      const copySell = params.copy_sell ?? true;
      const excludedTokens = params.excluded_tokens || [];
      result = await sdk.copyTrade.createCopyTrade(
        walletAddress,
        traderWallet,
        name,
        gasPrice,
        buyMode,
        chainId,
        copyBuyAmount,
        isBuyExistingToken,
        lossPercent,
        profitPercent,
        copySell,
        excludedTokens,
        privateKey.replace(/^0x/, ''),
      );

    } else {
      process.stdout.write(JSON.stringify({ success: false, error: 'Unknown action: ' + action }));
      process.exit(1);
    }

    // Restore console.log for final JSON output
    console.log = _origLog;
    console.log(JSON.stringify({ success: true, data: result }));
  } catch (err) {
    // Restore console.log for final JSON output
    console.log = _origLog;
    const rawErr = err.message || String(err);
    const safeErr = rawErr.replace(/0x[0-9a-fA-F]{32,}/g, '[REDACTED]');
    console.log(JSON.stringify({ success: false, error: safeErr }));
    process.exit(1);
  }
});
