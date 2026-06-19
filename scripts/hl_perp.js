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
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

const HL_CHAIN_ID = 42161; // sign in on Arbitrum for HyperLiquid
const MIN_NOTIONAL = 11; // HyperLiquid minimum order value (USD)
const DEFAULT_LEVERAGE = 3; // default requested leverage; clamped to the EARNED cap below
const SZ_DECIMALS = { BTC: 5, ETH: 4, SOL: 2 }; // fallback size precision if meta is unavailable

// Leverage is EARNED: the cap rises with goodwill. Keep this ladder in sync with forge.py.
const LEVERAGE_LADDER = [[0, 3], [50, 5], [200, 10], [500, 15], [1000, 20]];

function earnedLeverageCap() {
  try {
    const home = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
    const meta = JSON.parse(fs.readFileSync(path.join(home, 'metabolism.json'), 'utf8'));
    const goodwill = Number(meta.goodwill || 0);
    let cap = LEVERAGE_LADDER[0][1];
    for (const [threshold, lev] of LEVERAGE_LADDER) if (goodwill >= threshold) cap = lev;
    return cap;
  } catch {
    return DEFAULT_LEVERAGE; // no metabolism state → conservative base
  }
}

// Builder/HIP-3 coins are `dex:ASSET` with a LOWERCASE dex prefix (xyz:NVDA); plain coins uppercase.
function normalizeCoin(coin) {
  const i = coin.indexOf(':');
  return i === -1 ? coin.toUpperCase() : coin.slice(0, i).toLowerCase() + ':' + coin.slice(i + 1).toUpperCase();
}

async function findAsset(skill, coin) {
  const a = await skill.getHlAllAssets();
  const arr = Array.isArray(a) ? a : a.data || a.assets || a.universe || [];
  return arr.find((x) => String(x.coin).toLowerCase() === coin.toLowerCase() || x.baseCoin === coin);
}

// getHlMarkPrice only covers the default dex; builder markets need getHlAllAssets.markPx.
async function markPriceFor(skill, coin) {
  const px = await skill.getHlMarkPrice(coin).catch(() => 0);
  if (px > 0) return px;
  const asset = await findAsset(skill, coin).catch(() => null);
  return Number(asset?.markPx) || 0;
}

async function szDecimalsFor(skill, coin) {
  try {
    const m = await findAsset(skill, coin);
    if (m && Number.isInteger(m.szDecimals)) return m.szDecimals;
  } catch {
    /* fall back to the static map below */
  }
  return SZ_DECIMALS[coin] ?? 2;
}

function mapPositions(aps) {
  return (aps || [])
    .map((p) => p.position || p)
    .filter((p) => Number(p.szi ?? p.size) !== 0)
    .map((p) => ({
      coin: p.coin,
      size: Number(p.szi ?? p.size),
      entryPx: Number(p.entryPx),
      unrealizedPnl: Number(p.unrealizedPnl),
      liquidationPx: p.liquidationPx ?? null,
    }));
}

// Builder/HIP-3 dex prefixes (xyz, flx, …) present in the tradable universe.
async function builderDexes(skill) {
  const a = await skill.getHlAllAssets().catch(() => []);
  const arr = Array.isArray(a) ? a : a.data || a.assets || a.universe || [];
  const set = new Set();
  for (const x of arr) {
    const c = String(x.coin || '');
    const i = c.indexOf(':');
    if (i !== -1) set.add(c.slice(0, i).toLowerCase());
  }
  return [...set];
}

// True equity + positions across default AND every builder dex. Builder/HIP-3
// positions (xyz:NVDA, …) live under their own dex, not `default`. The bundled
// "…StateAll" endpoint is stale (omits xyz), so query each dex explicitly via the
// object form `{ userAddress, dex }` — the only reliable way to see migrated collateral.
async function fullState(skill, managed) {
  const dexes = await builderDexes(skill);
  const [def, ...rest] = await Promise.all([
    skill.getHlClearinghouseState(managed).catch(() => null),
    ...dexes.map((dex) => skill.getHlClearinghouseState({ userAddress: managed, dex }).catch(() => null)),
  ]);
  const defRoot = def?.state || def || {};
  let accountValue = Number(defRoot.marginSummary?.accountValue || 0);
  const positions = mapPositions(defRoot.assetPositions);
  for (const cs of rest) {
    const root = cs?.state || cs;
    if (!root) continue;
    accountValue += Number(root.marginSummary?.accountValue || 0);
    positions.push(...mapPositions(root.assetPositions));
  }
  return { accountValue, positions, withdrawable: Number(defRoot.withdrawable || 0) };
}

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
  // Resilient: a transient non-JSON response on one read shouldn't fail the whole status.
  const [fullR, spotR, ordersR] = await Promise.allSettled([
    fullState(skill, wallet.managed),
    skill.getHlSpotState(wallet.managed),
    skill.getHlOpenOrders(wallet.managed),
  ]);
  const full = fullR.status === 'fulfilled' ? fullR.value : { accountValue: 0, positions: [], withdrawable: 0 };
  const spot = spotR.status === 'fulfilled' ? spotR.value : { balances: [] };
  const orders = ordersR.status === 'fulfilled' ? ordersR.value : [];
  const usdc = (spot.balances || []).find((b) => b.coin === 'USDC');
  const spotTotal = usdc ? Number(usdc.total) : 0;
  const spotHold = usdc ? Number(usdc.hold) : 0;
  const unrealized = (full.positions || []).reduce((s, p) => s + Number(p.unrealizedPnl || 0), 0);
  return {
    ok: true,
    managed: wallet.managed,
    // HL uses ONE unified USDC balance: spot `total` is the whole account, `hold`
    // is the slice already pledged as perp margin. Free collateral for NEW perps
    // is total - hold — perp `withdrawable` reads ~0 and is NOT the buying power.
    spotUsdc: spotTotal,
    spotHold,
    buyingPower: Math.max(0, spotTotal - spotHold),
    equity: spotTotal + unrealized, // true account equity for risk sizing
    accountValue: full.accountValue, // perp-committed margin only (legacy field)
    withdrawable: full.withdrawable,
    positions: full.positions, // includes builder-dex (xyz:*) positions
    openOrders: (orders || []).map((o) => ({ coin: o.coin, px: Number(o.limitPx), sz: Number(o.sz), reduceOnly: !!o.reduceOnly })),
  };
}

async function cmdOpen(wallet, args) {
  const coin = normalizeCoin(args.coin || 'ETH');
  const isLong = (args.side || 'long').toLowerCase() !== 'short';
  const notionalTarget = Math.max(MIN_NOTIONAL + 1, Number(args.notional || 12));
  const slPct = Number(args['sl-pct'] || 2);
  const tpPct = Number(args['tp-pct'] || 3);
  if (!args['sl-pct'] && slPct <= 0) die('a stop-loss is required (--sl-pct)');

  // Leverage is a real, settable order field, clamped to the EARNED cap (goodwill ladder).
  const cap = earnedLeverageCap();
  const leverage = Math.max(1, Math.min(cap, Math.round(Number(args.leverage || DEFAULT_LEVERAGE))));

  const { skill, creds } = await signedSkill(wallet);
  const px = await markPriceFor(skill, coin);
  const dp = await szDecimalsFor(skill, coin);
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
    leverage,
    ...creds,
  });
  if (res && res.isSuccess === false) die(`open rejected: ${JSON.stringify(res)}`);
  return { ok: true, action: 'open', coin, side: isLong ? 'long' : 'short', leverage, leverageCap: cap, mark: px, size, notional: Number(notional.toFixed(2)), sl, tp };
}

// Resolve a position's signed size from the coin's own dex (builder coins live
// under their dex's isolated account, not the default clearinghouse).
async function positionSize(skill, managed, coin) {
  const i = coin.indexOf(':');
  if (i === -1) {
    const state = await skill.getHlAccountState(managed);
    const pos = (state.positions || []).find(
      (p) => String(p.coin || p.position?.coin).toLowerCase() === coin.toLowerCase(),
    );
    return pos ? Number(pos.size ?? pos.szi ?? pos.position?.szi) : 0;
  }
  const cs = await skill
    .getHlClearinghouseState({ userAddress: managed, dex: coin.slice(0, i).toLowerCase() })
    .catch(() => null);
  const pos = mapPositions((cs?.state || cs)?.assetPositions).find(
    (p) => String(p.coin).toLowerCase() === coin.toLowerCase(),
  );
  return pos ? pos.size : 0;
}

async function cmdClose(wallet, args) {
  const coin = normalizeCoin(args.coin || 'ETH');
  const { skill, creds } = await signedSkill(wallet);
  const szi = await positionSize(skill, wallet.managed, coin);
  if (!szi) return { ok: true, action: 'close', coin, note: 'no open position' };
  // Optional partial reduce: --size <amount> closes only that much (reduceOnly),
  // clamped to the open size. Omitted → flatten the whole position.
  const want = args.size ? Math.min(Math.abs(Number(args.size)), Math.abs(szi)) : Math.abs(szi);
  const px = await markPriceFor(skill, coin);
  const res = await skill.hlCreateOrder({
    coin,
    isLong: szi < 0, // opposite side to flatten
    price: String(px),
    size: String(want),
    reduceOnly: true,
    isMarket: true,
    tpPrice: '0',
    slPrice: '0',
    ...creds,
  });
  if (res && res.isSuccess === false) die(`close rejected: ${JSON.stringify(res)}`);
  return { ok: true, action: 'close', coin, closedSize: want, partial: want < Math.abs(szi), mark: px };
}

async function cmdCancel(wallet, args) {
  // Cancel ONE resting order by id — the SDK managed cancel works where the MCP
  // cancel_perp_order returns Unauthorized. Deliberately requires an explicit
  // --oid: cancelling by any heuristic risks removing the stop and leaving the
  // position naked (learned the hard way). Read oids from `status`/open orders.
  const coin = normalizeCoin(args.coin || 'ETH');
  if (!args.oid) die('cancel requires --oid <orderId> (never cancel by heuristic — it can drop your stop)');
  const { skill, creds } = await signedSkill(wallet);
  const r = await skill.hlCancelOrder({ coin, orderId: String(args.oid), ...creds });
  if (r && r.isSuccess === false) die(`cancel rejected: ${JSON.stringify(r)}`);
  return { ok: true, action: 'cancel', coin, oid: String(args.oid) };
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);
  const wallet = loadWallet();
  const handlers = { status: cmdStatus, open: cmdOpen, close: cmdClose, cancel: cmdCancel };
  const handler = handlers[cmd];
  if (!handler) die(`unknown command '${cmd}'. Use: status | open | close`);
  const result = await handler(wallet, args);
  process.stdout.write(JSON.stringify(result) + '\n');
}

// The HL trader keeps a connection open; exit explicitly so we don't hang.
main()
  .then(() => process.exit(0))
  .catch((e) => die(e?.responseBody ? JSON.stringify(e.responseBody) : e.message || String(e)));
