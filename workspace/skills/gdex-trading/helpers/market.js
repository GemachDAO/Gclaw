#!/usr/bin/env node
/**
 * GDEX Market Data Helper
 * Reads a JSON action descriptor from stdin, fetches market data, and writes JSON result to stdout.
 *
 * Input JSON:
 *   { "action": "trending"|"search"|"price"|"holdings"|"scan"|"copy_trade"|"hl_balance"|"hl_positions"|"hl_deposit"|"hl_create_order"|"hl_cancel_order",
 *     "params": { ... } }
 *
 * Output JSON:
 *   { "success": true, "data": { ... } }  or  { "success": false, "error": "..." }
 */

import { createHash, createCipheriv } from 'crypto';
import { createAuthenticatedSession, CryptoUtils } from 'gdex.pro-sdk';

const API_URL = 'https://trade-api.gemach.io/v1';

const HL_HEADERS = {
  'Origin': 'https://gdex.pro',
  'Referer': 'https://gdex.pro/',
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
  'Content-Type': 'application/json',
};

function encryptHL(data, key) {
  const keyHash = createHash('sha256').update(key).digest('hex');
  const aesKey = Buffer.from(keyHash.slice(0, 64), 'hex');
  const ivHash = createHash('sha256').update(keyHash).digest('hex').slice(0, 32);
  const iv = Buffer.from(ivHash, 'hex');
  const cipher = createCipheriv('aes-256-cbc', aesKey, iv);
  let encrypted = cipher.update(data, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  return encrypted;
}

const apiKey = process.env.GDEX_API_KEY;
const walletAddress = process.env.WALLET_ADDRESS;
const privateKey = process.env.PRIVATE_KEY;

if (!apiKey || !walletAddress || !privateKey) {
  process.stdout.write(JSON.stringify({
    success: false,
    error: 'Missing required environment variables: GDEX_API_KEY, WALLET_ADDRESS, PRIVATE_KEY',
  }));
  process.exit(1);
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

  try {
    const session = await createAuthenticatedSession({
      apiKey,
      walletAddress,
      privateKey,
    });

    let result;
    switch (action) {
      case 'trending':
        result = await session.getTrending({
          limit: params.limit ?? 10,
          chainId: params.chain_id,
        });
        break;
      case 'search':
        result = await session.searchTokens({
          query: params.query,
          limit: params.limit ?? 10,
        });
        break;
      case 'price':
        result = await session.getPrice({
          tokenAddress: params.token_address,
          chainId: params.chain_id,
        });
        break;
      case 'holdings':
        result = await session.getHoldings();
        break;
      case 'scan':
        result = await session.getNewest({
          chainId: params.chain_id ?? 622112261,
          limit: params.limit ?? 20,
        });
        break;
      case 'copy_trade':
        result = await session.setCopyTrade({
          targetAddress: params.target_address,
          name: params.name,
          amount: params.amount,
          chainId: params.chain_id ?? 622112261,
        });
        break;
      case 'hl_balance':
        result = await session.hlGetBalance();
        break;
      case 'hl_positions':
        result = await session.hlGetPositions();
        break;
      case 'hl_deposit': {
        const singleApiKey = apiKey.split(',')[0].trim();
        const userId = session.walletAddress.toLowerCase();
        const nonce = (Date.now() + Math.floor(Math.random() * 1000)).toString();
        const chainId = params.chain_id ?? 42161;
        const tokenAddress = params.token_address ?? '0xaf88d065e77c8cC2239327C5EDb3A432268e5831';
        const amount = params.amount ?? '10000000';
        const encodedData = CryptoUtils.encodeInputData('hl_deposit', {
          chainId, tokenAddress, amount, nonce,
        });
        const signature = CryptoUtils.sign(`hl_deposit-${userId}-${encodedData}`, session.tradingPrivateKey);
        const payload = { userId, data: encodedData, signature, apiKey: singleApiKey };
        const computedData = encryptHL(JSON.stringify(payload), singleApiKey);
        const res = await fetch(`${API_URL}/hl/deposit`, {
          method: 'POST', headers: HL_HEADERS,
          body: JSON.stringify({ computedData }),
        });
        result = await res.json();
        break;
      }
      case 'hl_create_order': {
        const singleApiKey = apiKey.split(',')[0].trim();
        const userId = session.walletAddress.toLowerCase();
        const nonce = (Date.now() + Math.floor(Math.random() * 1000)).toString();
        const orderParams = {
          coin: params.coin ?? 'ETH',
          isLong: params.is_long ?? true,
          price: params.price,
          size: params.size,
          reduceOnly: params.reduce_only ?? false,
          nonce,
          tpPrice: params.tp_price ?? '0',
          slPrice: params.sl_price ?? '0',
          isMarket: params.is_market ?? false,
        };
        const encodedData = CryptoUtils.encodeInputData('hl_create_order', orderParams);
        const signature = CryptoUtils.sign(`hl_create_order-${userId}-${encodedData}`, session.tradingPrivateKey);
        const payload = { userId, data: encodedData, signature, apiKey: singleApiKey };
        const computedData = encryptHL(JSON.stringify(payload), singleApiKey);
        const res = await fetch(`${API_URL}/hl/create_order`, {
          method: 'POST', headers: HL_HEADERS,
          body: JSON.stringify({ computedData }),
        });
        result = await res.json();
        break;
      }
      case 'hl_cancel_order': {
        const singleApiKey = apiKey.split(',')[0].trim();
        const userId = session.walletAddress.toLowerCase();
        const cancelNonce = (Date.now() + Math.floor(Math.random() * 1000)).toString();
        const cancelParams = {
          nonce: cancelNonce,
          coin: params.coin ?? 'ETH',
          orderId: params.order_id,
        };
        const encodedData = CryptoUtils.encodeInputData('hl_cancel_order', cancelParams);
        const signature = CryptoUtils.sign(`hl_cancel_order-${userId}-${encodedData}`, session.tradingPrivateKey);
        const payload = { userId, data: encodedData, signature, apiKey: singleApiKey };
        const computedData = encryptHL(JSON.stringify(payload), singleApiKey);
        const res = await fetch(`${API_URL}/hl/cancel_order`, {
          method: 'POST', headers: HL_HEADERS,
          body: JSON.stringify({ computedData, isCancelAll: false }),
        });
        result = await res.json();
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
