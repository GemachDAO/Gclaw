#!/usr/bin/env node
/**
 * GDEX Trade Helper
 * Reads a JSON action descriptor from stdin, executes the trade, and writes JSON result to stdout.
 *
 * Input JSON:
 *   { "action": "buy"|"sell"|"limit_buy"|"limit_sell", "params": { ... } }
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
      case 'buy':
        result = await session.buy({
          tokenAddress: params.token_address,
          amount: params.amount,
          chainId: params.chain_id ?? 622112261,
        });
        break;
      case 'sell':
        result = await session.sell({
          tokenAddress: params.token_address,
          amount: params.amount,
          chainId: params.chain_id ?? 622112261,
        });
        break;
      case 'limit_buy':
        result = await session.limitBuy({
          tokenAddress: params.token_address,
          amount: params.amount,
          triggerPrice: params.trigger_price,
          profitPercent: params.profit_percent,
          lossPercent: params.loss_percent,
          chainId: params.chain_id ?? 622112261,
        });
        break;
      case 'limit_sell':
        result = await session.limitSell({
          tokenAddress: params.token_address,
          amount: params.amount,
          triggerPrice: params.trigger_price,
          chainId: params.chain_id ?? 622112261,
        });
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
