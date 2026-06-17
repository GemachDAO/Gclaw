#!/usr/bin/env node
/**
 * Gclaw HyperLiquid perp execution arm.
 *
 * The MCP write tools need a freshly-signed managed session, which an LLM cannot
 * cleanly thread through tool calls. This helper performs the proven sign-in flow
 * (fresh session keypair, generateGdexNonce, 0x-stripped signature, chainId 42161)
 * and exposes open / close / status as a CLI that emits JSON for the heartbeat.
 *
 * Funds and positions live under the per-chain MANAGED wallet (Arbitrum/HL), NOT
 * the control wallet — querying the control address shows $0 on a funded account.
 *
 * Env:
 *   GDEX_SKILL_DIR   SDK location (default ~/gdex-skill) — supplies dist + ethers
 *   GCLAW_WALLET     wallet JSON (default ~/gdex-test-wallet.json)
 *   GDEX_API_KEY     overrides the SDK's shared primary key
 *
 * Usage:
 *   node hl_perp.js status
 *   node hl_perp.js open  --coin ETH --side long --notional 12 --sl-pct 2 --tp-pct 3
 *   node hl_perp.js close --coin ETH
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || path.join(os.homedir(), 'gdex-test-wallet.json');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

const HL_CHAIN_ID = 42161; // sign in on Arbitrum for HyperLiquid
const MIN_NOTIONAL = 11; // HyperLiquid minimum order value (USD)
const SZ_DECIMALS = { BTC: 5, ETH: 4, SOL: 2 }; // size precision per major

function die(msg) {
  process.stdout.write(JSON.stringify({ ok: false, error: msg }) + '\n');
  process.exit(1);
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[(i += 1)] : 'true';
      out[key] = val;
    }
  }
  return out;
}

function loadWallet() {
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const managed = w.managed?.['Arbitrum (HyperLiquid)']?.address;
  if (!w.control?.address || !w.control?.privateKey) die('wallet missing control key');
  if (!managed) die('wallet missing managed Arbitrum (HyperLiquid) address');
  return { control: w.control.address, pk: w.control.privateKey, managed };
}

function roundSig(value, sig = 5) {
  if (value === 0) return 0;
  const mag = Math.ceil(Math.log10(Math.abs(value)));
  const factor = 10 ** (sig - mag);
  return Math.round(value * factor) / factor;
}

async function signedSkill(wallet) {
  const apiKey = process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY;
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(apiKey);
  const kp = SDK.generateGdexSessionKeyPair();
  const nonce = SDK.generateGdexNonce().toString();
  const sig = await new ethers.Wallet(wallet.pk).signMessage(
    SDK.buildGdexSignInMessage(wallet.control, nonce, kp.sessionKey),
  );
  const payload = SDK.buildGdexSignInComputedData({
    apiKey,
    userId: wallet.control,
    sessionKey: kp.sessionKey,
    nonce,
    signature: sig.replace(/^0x/, ''),
  });
  await skill.signInWithComputedData({ computedData: payload.computedData, chainId: HL_CHAIN_ID });
  return { skill, creds: { apiKey, walletAddress: wallet.control, sessionPrivateKey: kp.sessionPrivateKey } };
}

async function cmdStatus(wallet) {
  const { skill } = await signedSkill(wallet);
  const [state, spot, orders] = await Promise.all([
    skill.getHlAccountState(wallet.managed),
    skill.getHlSpotState(wallet.managed),
    skill.getHlOpenOrders(wallet.managed),
  ]);
  const usdc = (spot.balances || []).find((b) => b.coin === 'USDC');
  return {
    ok: true,
    managed: wallet.managed,
    spotUsdc: usdc ? Number(usdc.total) : 0,
    accountValue: Number(state.accountValue),
    positions: (state.positions || []).map((p) => ({
      coin: p.coin || p.position?.coin,
      size: Number(p.size ?? p.szi ?? p.position?.szi),
      entryPx: Number(p.entryPx ?? p.position?.entryPx),
      unrealizedPnl: Number(p.unrealizedPnl ?? p.position?.unrealizedPnl),
      liquidationPx: p.liquidationPx ?? p.position?.liquidationPx ?? null,
    })),
    openOrders: (orders || []).map((o) => ({ coin: o.coin, px: Number(o.limitPx), sz: Number(o.sz), reduceOnly: !!o.reduceOnly })),
  };
}

async function cmdOpen(wallet, args) {
  const coin = (args.coin || 'ETH').toUpperCase();
  const isLong = (args.side || 'long').toLowerCase() !== 'short';
  const notionalTarget = Math.max(MIN_NOTIONAL + 1, Number(args.notional || 12));
  const slPct = Number(args['sl-pct'] || 2);
  const tpPct = Number(args['tp-pct'] || 3);
  if (!args['sl-pct'] && slPct <= 0) die('a stop-loss is required (--sl-pct)');

  const { skill, creds } = await signedSkill(wallet);
  const px = await skill.getHlMarkPrice(coin);
  const dp = SZ_DECIMALS[coin] ?? 2;
  const size = Math.max(0, Number((notionalTarget / px).toFixed(dp)));
  const notional = px * size;
  if (notional < MIN_NOTIONAL) die(`notional $${notional.toFixed(2)} below $${MIN_NOTIONAL} min — raise --notional`);

  const sl = roundSig(isLong ? px * (1 - slPct / 100) : px * (1 + slPct / 100));
  const tp = roundSig(isLong ? px * (1 + tpPct / 100) : px * (1 - tpPct / 100));
  const res = await skill.hlCreateOrder({
    coin,
    isLong,
    price: String(px),
    size: String(size),
    reduceOnly: false,
    isMarket: true,
    tpPrice: String(tp),
    slPrice: String(sl),
    ...creds,
  });
  if (res && res.isSuccess === false) die(`open rejected: ${JSON.stringify(res)}`);
  return { ok: true, action: 'open', coin, side: isLong ? 'long' : 'short', mark: px, size, notional: Number(notional.toFixed(2)), sl, tp };
}

async function cmdClose(wallet, args) {
  const coin = (args.coin || 'ETH').toUpperCase();
  const { skill, creds } = await signedSkill(wallet);
  const state = await skill.getHlAccountState(wallet.managed);
  const pos = (state.positions || []).find((p) => (p.coin || p.position?.coin) === coin);
  const szi = pos ? Number(pos.size ?? pos.szi ?? pos.position?.szi) : 0;
  if (!szi) return { ok: true, action: 'close', coin, note: 'no open position' };
  const px = await skill.getHlMarkPrice(coin);
  const res = await skill.hlCreateOrder({
    coin,
    isLong: szi < 0, // opposite side to flatten
    price: String(px),
    size: String(Math.abs(szi)),
    reduceOnly: true,
    isMarket: true,
    tpPrice: '0',
    slPrice: '0',
    ...creds,
  });
  if (res && res.isSuccess === false) die(`close rejected: ${JSON.stringify(res)}`);
  return { ok: true, action: 'close', coin, closedSize: Math.abs(szi), mark: px };
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);
  const wallet = loadWallet();
  const handlers = { status: cmdStatus, open: cmdOpen, close: cmdClose };
  const handler = handlers[cmd];
  if (!handler) die(`unknown command '${cmd}'. Use: status | open | close`);
  const result = await handler(wallet, args);
  process.stdout.write(JSON.stringify(result) + '\n');
}

// The HL trader keeps a connection open; exit explicitly so we don't hang.
main()
  .then(() => process.exit(0))
  .catch((e) => die(e?.responseBody ? JSON.stringify(e.responseBody) : e.message || String(e)));
