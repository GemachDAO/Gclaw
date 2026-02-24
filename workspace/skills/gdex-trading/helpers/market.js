#!/usr/bin/env node
/**
 * GDEX Market Data Helper
 * Reads a JSON action descriptor from stdin, fetches market data, and writes JSON result to stdout.
 *
 * Input JSON:
 *   { "action": "trending"|"search"|"price"|"holdings"|"scan"|"copy_trade"|"hl_balance"|"hl_positions",
 *     "params": { ... } }
 *
 * Output JSON:
 *   { "success": true, "data": { ... } }  or  { "success": false, "error": "..." }
 */

import { createAuthenticatedSession } from 'gdex.pro-sdk';

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
