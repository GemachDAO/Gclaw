#!/usr/bin/env node
/**
 * Gclaw HIP-3 outcome-market execution arm (defined-risk event bets).
 *
 * Outcome markets are HyperLiquid event markets (e.g. "June Fed rate change" →
 * Change / No Change). Each side is a coin you buy/sell at a price = implied
 * probability. Downside is bounded — good for survival mode.
 *
 * Uses the proven managed sign-in (chainId 42161, fresh session) like hl_perp.js,
 * then the SDK outcome methods. Emits JSON.
 *
 *   node hl_outcomes.js list [--limit 15]                       # active markets + volume
 *   node hl_outcomes.js markets [--status active]               # per-side {coin,price,volumeUsd} (joins meta+mids+coinVolumes)
 *   node hl_outcomes.js account --outcome <id>                  # your positions/balance in a market
 *   node hl_outcomes.js enable                                  # one-time: enable HL trading (required first)
 *   node hl_outcomes.js order --outcome <id> --coin <side> --buy --price <0..1> --size <n> [--market]
 *   node hl_outcomes.js close --outcome <id> --coin <side>
 *
 * Env: GDEX_SKILL_DIR, GCLAW_WALLET, GDEX_API_KEY.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

const HL_CHAIN_ID = 42161;

function die(msg) {
  process.stdout.write(JSON.stringify({ ok: false, error: msg }) + '\n');
  process.exit(1);
}

// Classify a market by its name + description into a coarse edgeability category.
// This is the ONLY place category is derived, so the rule is auditable in one spot.
// It never fabricates a probability — it only labels what HL already published, so the
// desk can tell a dated, clearly-resolved market (crypto price threshold, macro print)
// apart from an efficient sports/World-Cup market where an LLM has no informational edge.
//   - "crypto-price": HL price-binary markets (description class:priceBinary|underlying:...)
//   - "macro": FOMC/rate/CPI/inflation prints with a dated BLS/FOMC resolution
//   - "sports": World Cup / FIFA / champion / head-to-head match markets
//   - "other": anything else (fallbacks, unnamed recurring indices)
// Only "sports" is treated as presumptively efficient; the rest are candidate-edgeable.
function classifyMarket(name, description) {
  const n = String(name || '').toLowerCase();
  const d = String(description || '').toLowerCase();
  if (d.includes('class:pricebinary') || d.includes('underlying:')) return 'crypto-price';
  if (/\b(fomc|federal funds|cpi|inflation|bls|rate range|unemployment|gdp|jobs)\b/.test(d)) return 'macro';
  if (/\b(world cup|fifa|champion|vs |vs\.|round of)\b/.test(n + ' ' + d)) return 'sports';
  return 'other';
}

// Parse an HL price-binary description into its structured resolution terms so the LLM
// sees the actual bet (underlying, target price, expiry) instead of a bare "Recurring"
// label. Returns null for non-price-binary markets. Pure string parsing, no fabrication.
function parsePriceBinary(description) {
  const d = String(description || '');
  if (!d.includes('class:priceBinary') && !d.toLowerCase().includes('class:pricebinary')) return null;
  const terms = {};
  for (const part of d.split('|')) {
    const idx = part.indexOf(':');
    if (idx > 0) terms[part.slice(0, idx).trim()] = part.slice(idx + 1).trim();
  }
  return {
    underlying: terms.underlying || null,
    targetPrice: terms.targetPrice ? Number(terms.targetPrice) : null,
    expiry: terms.expiry || null,
    period: terms.period || null,
  };
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
  if (!w.control?.address || !managed) die('wallet missing control key or managed HL address');
  return { control: w.control.address, pk: w.control.privateKey, managed };
}

async function signedSkill(wallet) {
  const apiKey = process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY;
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(apiKey);
  const kp = SDK.generateGdexSessionKeyPair();
  const nonce = SDK.generateGdexNonce().toString();
  const sig = (
    await new ethers.Wallet(wallet.pk).signMessage(SDK.buildGdexSignInMessage(wallet.control, nonce, kp.sessionKey))
  ).replace(/^0x/, '');
  const payload = SDK.buildGdexSignInComputedData({
    apiKey,
    userId: wallet.control,
    sessionKey: kp.sessionKey,
    nonce,
    signature: sig,
  });
  await skill.signInWithComputedData({ computedData: payload.computedData, chainId: HL_CHAIN_ID });
  return { skill, creds: { apiKey, walletAddress: wallet.control, sessionPrivateKey: kp.sessionPrivateKey } };
}

function loginOnly() {
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY);
  return skill;
}

async function cmdList(_w, args) {
  const skill = loginOnly();
  const resp = await skill.getHlOutcomes({ status: 'active' });
  const all = resp?.data?.meta?.outcomes || [];
  const rows = all.slice(0, Number(args.limit || 15));
  return {
    ok: true,
    total: all.length,
    shown: rows.length,
    markets: rows.map((m) => ({
      outcomeId: m.outcome,
      name: m.name,
      sides: (m.sideSpecs || []).map((s) => s.name).filter(Boolean),
    })),
  };
}

async function cmdMarkets(_w, args) {
  // Join meta + mids + coinVolumes into one row per tradeable side. mids["#<id><side>"]
  // is the side's implied probability in [0,1]; coinVolumes is its 24h USD volume. No
  // signing required — a pure public read, so the deterministic gate in outcomes.py can
  // fetch the full board cheaply every cycle.
  const skill = loginOnly();
  const resp = await skill.getHlOutcomesWithVolume({ status: args.status || 'active' });
  const meta = resp?.data?.meta?.outcomes || [];
  const mids = resp?.data?.mids || {};
  const vols = resp?.data?.coinVolumes || {};
  const sides = [];
  for (const m of meta) {
    const specs = m.sideSpecs || [];
    const description = m.description || '';
    const category = classifyMarket(m.name, description);
    const resolution = parsePriceBinary(description);
    for (let s = 0; s < specs.length; s += 1) {
      const coin = `#${m.outcome}${s}`;
      const price = mids[coin];
      if (price === undefined || price === null) continue;
      sides.push({
        outcomeId: m.outcome,
        name: m.name,
        side: specs[s]?.name || String(s),
        coin,
        price: Number(price),
        volumeUsd: Number(vols[coin] || 0),
        // The resolution criteria + category: for "Recurring"-named price binaries the
        // description is the ONLY place the target/expiry lives, so the LLM cannot form a
        // calibrated probability without it. Passing it through is not a bet — it is the
        // read material the divergence gate then acts on.
        description,
        category,
        ...(resolution ? { resolution } : {}),
      });
    }
  }
  return { ok: true, total: meta.length, sides };
}

// Public HL info POST (no auth) — settlement fills are visible by address, the same
// userFills feed autosettle books PnL from. This is the DEFINITIVE resolution signal:
// HL emits a fill with dir:"Settlement" and the settled px (0 or 1) when an outcome
// position resolves — far more reliable than guessing from a live market's mid.
function hlInfo(body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = require('node:https').request(
      {
        hostname: 'api.hyperliquid.xyz', path: '/info', method: 'POST',
        headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(data) },
      },
      (res) => {
        let b = '';
        res.on('data', (c) => (b += c));
        res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
      },
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

async function cmdSettlements(wallet) {
  const fills = await hlInfo({ type: 'userFills', user: wallet.managed, aggregateByTime: false });
  const arr = Array.isArray(fills) ? fills : fills.fills || [];
  const settlements = arr
    .filter((f) => f.dir === 'Settlement' && String(f.coin).startsWith('#'))
    .map((f) => ({ coin: String(f.coin), settlePx: Number(f.px), closedPnl: Number(f.closedPnl || 0), time: f.time, tid: f.tid }));
  return { ok: true, settlements };
}

async function cmdAccount(wallet, args) {
  if (!args.outcome) die('--outcome <id> required');
  const { skill } = await signedSkill(wallet);
  const acct = await skill.getHlOutcomeAccount({ userAddress: wallet.managed, outcomeId: args.outcome });
  return { ok: true, outcomeId: args.outcome, account: acct };
}

async function cmdEnable(wallet) {
  const { skill, creds } = await signedSkill(wallet);
  try {
    const res = await skill.hlEnableTrading({ ...creds });
    return { ok: res?.isSuccess !== false, action: 'enable_trading', result: res };
  } catch (e) {
    const body = JSON.stringify(e?.responseBody || e?.message || '');
    if (body.includes('already enabled') || body.includes('104')) {
      return { ok: true, action: 'enable_trading', alreadyEnabled: true };
    }
    throw e;
  }
}

async function cmdOrder(wallet, args) {
  for (const k of ['outcome', 'coin', 'price', 'size']) if (!args[k]) die(`--${k} required`);
  const isBuy = !!args.buy && args.buy !== 'false';
  const { skill, creds } = await signedSkill(wallet);
  const res = await skill.createHlOutcomeOrder({
    outcomeId: args.outcome,
    coin: args.coin,
    isBuy,
    price: String(args.price),
    size: String(args.size),
    reduceOnly: false,
    isMarket: !!args.market && args.market !== 'false',
    ...creds,
  });
  if (res && res.isSuccess === false) die(`order rejected: ${JSON.stringify(res)}`);
  return { ok: true, action: 'order', outcomeId: args.outcome, coin: args.coin, side: isBuy ? 'buy' : 'sell', price: args.price, size: args.size };
}

async function cmdClose(wallet, args) {
  for (const k of ['outcome', 'coin']) if (!args[k]) die(`--${k} required`);
  const { skill, creds } = await signedSkill(wallet);
  const res = await skill.closeHlOutcomeOrder({ outcomeId: args.outcome, coin: args.coin, ...creds });
  if (res && res.isSuccess === false) die(`close rejected: ${JSON.stringify(res)}`);
  return { ok: true, action: 'close', outcomeId: args.outcome, coin: args.coin };
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);
  const handlers = { list: cmdList, markets: cmdMarkets, settlements: cmdSettlements, account: cmdAccount, enable: cmdEnable, order: cmdOrder, close: cmdClose };
  const handler = handlers[cmd];
  if (!handler) die(`unknown command '${cmd}'. Use: list | markets | account | enable | order | close`);
  // list/markets are public reads — don't require a wallet so the board fetch is cheap.
  const wallet = ['list', 'markets'].includes(cmd) ? null : loadWallet();
  const result = await handler(wallet, args);
  process.stdout.write(JSON.stringify(result) + '\n');
}

// The HL trader keeps a connection open; exit explicitly so we don't hang.
// Guard the auto-run so `require('hl_outcomes.js')` in a unit test loads the pure
// classifiers without firing a real sign-in / network call.
if (require.main === module) {
  main()
    .then(() => process.exit(0))
    .catch((e) => die(e?.responseBody ? JSON.stringify(e.responseBody) : e.message || String(e)));
}

module.exports = { classifyMarket, parsePriceBinary };
