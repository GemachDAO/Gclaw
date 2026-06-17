#!/usr/bin/env node
/**
 * Gclaw funding status — is the creature funded enough to come alive?
 *
 * Checks the two things a new player needs:
 *   1. trading capital — USDC on the managed HyperLiquid account
 *   2. gas — a little ETH on Base for the onchain identity mint
 *
 * Prints a friendly JSON verdict. No auth, no writes.
 *
 * Env: GDEX_SKILL_DIR, GCLAW_HOME, GCLAW_WALLET, BASE_RPC.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

function resolveWallet() {
  if (process.env.GCLAW_WALLET) return process.env.GCLAW_WALLET;
  const candidates = [path.join(GCLAW_HOME, 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')];
  return candidates.find(fs.existsSync) || candidates[0];
}

const MIN_TRADING_USDC = 11; // HL minimum order; below this it can't open a position
const MIN_BASE_ETH = 0.0003; // enough to mint the onchain identity

async function main() {
  const wpath = resolveWallet();
  if (!fs.existsSync(wpath)) {
    console.log(JSON.stringify({ ok: false, error: `no wallet at ${wpath} — run: gclaw wallet` }, null, 2));
    process.exit(0);
  }
  const w = JSON.parse(fs.readFileSync(wpath, 'utf8'));
  const control = w.control.address;
  const hl = w.managed?.['Arbitrum (HyperLiquid)']?.address;

  const skill = new SDK.GdexSkill({ timeout: 30000, maxRetries: 1 });
  skill.loginWithApiKey(process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY);

  // Trading capital can sit in the perp account (accountValue) or HL spot (USDC) —
  // a fresh deposit may land in either, so count both.
  let perpUsd = 0;
  let spotUsd = 0;
  try {
    const cs = await skill.getHlClearinghouseState(hl);
    perpUsd = Number(cs?.state?.marginSummary?.accountValue ?? cs?.accountValue ?? 0);
  } catch {
    /* leave 0 */
  }
  try {
    const ss = await skill.getHlSpotState(hl);
    const usdc = (ss?.balances || []).find((b) => b.coin === 'USDC');
    spotUsd = usdc ? Number(usdc.total) : 0;
  } catch {
    /* leave 0 */
  }
  const tradingUsdc = perpUsd + spotUsd;

  let baseEth = 0;
  let arbEth = 0;
  try {
    const baseP = new ethers.JsonRpcProvider(process.env.BASE_RPC || 'https://mainnet.base.org');
    baseEth = Number(ethers.formatEther(await baseP.getBalance(control)));
  } catch {
    /* leave 0 */
  }
  try {
    // ETH sent to the managed Arbitrum wallet can be auto-swapped to USDC + deposited.
    const arbP = new ethers.JsonRpcProvider(process.env.ARB_RPC || 'https://arb1.arbitrum.io/rpc');
    arbEth = Number(ethers.formatEther(await arbP.getBalance(hl)));
  } catch {
    /* leave 0 */
  }

  const convertibleEth = Math.max(0, arbEth - 0.0003); // minus a gas reserve
  const canTrade = tradingUsdc >= MIN_TRADING_USDC;
  const canMint = baseEth >= MIN_BASE_ETH;
  const verdict = {
    ok: true,
    ready: canTrade,
    tradingUsdc: Math.round(tradingUsdc * 100) / 100,
    arbitrumEth: arbEth,
    convertibleEth: Number(convertibleEth.toFixed(6)),
    baseEthGas: baseEth,
    canTrade,
    canMintIdentity: canMint,
    fund: {
      tradingCapital: canTrade
        ? '✓ funded'
        : convertibleEth > 0
          ? `≈ ${convertibleEth.toFixed(5)} ETH on Arbitrum to convert — run: gclaw autofund`
          : `→ send USDC (or ETH) on Arbitrum to ${hl}`,
      identityGas: canMint ? '✓ funded' : `→ send ~0.001 ETH on Base to ${control}`,
    },
    message: canTrade
      ? '✓ Ready to live — run: gclaw start'
      : convertibleEth > 0
        ? 'You sent ETH — run `gclaw autofund` to convert it to USDC and deposit to HL.'
        : 'Send USDC or ETH to the Arbitrum address, then `gclaw autofund`.',
  };
  console.log(JSON.stringify(verdict, null, 2));
}

main()
  .then(() => process.exit(0))
  .catch((e) => {
    console.log(JSON.stringify({ ok: false, error: e?.message || String(e) }));
    process.exit(1);
  });
