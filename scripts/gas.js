#!/usr/bin/env node
/**
 * Gas watchdog for the onchain beacon — so nobody has to think about Base gas.
 *
 * The control wallet (NFT owner) signs the ERC-8004 beacon, so it needs a little
 * Base ETH. The beacon is throttled, so gas depletes glacially — this mostly
 * watches the runway and warns; the opt-in top-up only makes sense at scale,
 * where bridge fees amortize.
 *
 *   node gas.js check        # runway report (read-only)
 *   node gas.js plan         # if low: a batched top-up plan + fee estimate (no spend)
 *
 * Opt-in execution (GCLAW_GAS_AUTOFUND=1) is intentionally NOT wired live yet —
 * a few-dollar auto-bridge is fee-negative until an agent writes onchain often.
 * Env: GCLAW_WALLET, GDEX_SKILL_DIR, BASE_RPC.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p));
const BASE_RPC = process.env.BASE_RPC || 'https://mainnet.base.org';

const BEACON_GAS_ETH = 0.000003; // ~one setAgentURI on Base at typical gas price
const LOW_RUNWAY = 30;           // warn below ~30 beacons of headroom
const TOPUP_USD = 6;             // batched top-up target (amortizes bridge fees)

async function main() {
  const cmd = process.argv[2] || 'check';
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const control = w.control.address;
  const provider = new ethers.JsonRpcProvider(BASE_RPC);
  const wei = await provider.getBalance(control);
  const eth = Number(ethers.formatEther(wei));
  const runway = Math.floor(eth / BEACON_GAS_ETH);
  const status = runway > LOW_RUNWAY ? 'healthy' : runway > 0 ? 'low' : 'empty';

  if (cmd === 'check') {
    console.log(JSON.stringify({
      ok: true, control, baseEth: Number(eth.toFixed(8)), beaconRunway: runway, status,
      note: status === 'healthy'
        ? `~${runway} beacons of gas — no action needed`
        : `gas low (~${runway} beacons) — top up ~$${TOPUP_USD} of Base ETH to ${control}`,
    }, null, 2));
    return;
  }

  if (cmd === 'plan') {
    if (status === 'healthy') {
      console.log(JSON.stringify({ ok: true, action: 'none', beaconRunway: runway, baseEth: Number(eth.toFixed(8)) }, null, 2));
      return;
    }
    // Read-only plan: surface the route + that fees dominate at this size.
    console.log(JSON.stringify({
      ok: true, action: 'top-up-needed', status, baseEth: Number(eth.toFixed(8)), beaconRunway: runway,
      route: ['HL withdraw USDC → Arbitrum', 'swap USDC→ETH', 'bridge Arbitrum→Base', 'transfer ETH → control wallet'],
      target: `~$${TOPUP_USD} ETH to ${control}`,
      warning: 'Multi-hop bridge fees are significant at a few dollars. Prefer a one-time manual top-up until the agent writes onchain frequently.',
      execute: 'disabled (set GCLAW_GAS_AUTOFUND=1 to opt in once the economics justify it)',
    }, null, 2));
    return;
  }
  throw new Error('usage: gas.js <check|plan>');
}

main().catch((e) => { console.log(JSON.stringify({ ok: false, error: e.message })); process.exit(1); });
