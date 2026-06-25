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
const https = require('node:https');

// HL's PUBLIC info API — authoritative, auth-free state read. We use it for equity
// because the authenticated SDK's clearinghouseState returns the shared account
// collateral as `accountValue` when FLAT (which then double-counts against spot), and
// because it can't be throttled by the GDEX sign-in rate limit.
function hlInfo(body) {
  return new Promise((resolve) => {
    const d = JSON.stringify(body);
    const req = https.request('https://api.hyperliquid.xyz/info',
      { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(d) }, timeout: 15000 },
      (res) => { let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => { try { resolve(JSON.parse(b)); } catch { resolve(null); } }); });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.write(d); req.end();
  });
}

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
// Loaded lazily inside signedSkill so the module's pure functions can be unit
// tested without the SDK/ethers (and without ever reaching the network).
const loadSdk = () => ({
  ethers: require(path.join(GDEX_DIR, 'node_modules', 'ethers')).ethers,
  SDK: require(path.join(GDEX_DIR, 'dist')),
});

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

function gclawHome() {
  return process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
}

// The proven SURFACE this creature may open on, read from the same files the forge
// writes: adopted coins (style.json) + coins auto-proven on the wider universe
// (proven_markets.json), and the set of known technique ids across both. This mirrors
// forge's proven-definition — "coin in proven_coins OR any contributor proven on the
// coin" — at the COIN level, so the executor never false-blocks a legitimate
// multi-contributor execute whose dominant technique differs from the proven one.
// A missing/corrupt file reads as empty (fail-closed: an un-proven entry is refused).
function loadProvenSurface(home = gclawHome()) {
  const coins = new Set();
  const techniques = new Set();
  try {
    const style = JSON.parse(fs.readFileSync(path.join(home, 'forge', 'style.json'), 'utf8'));
    for (const e of style.adopted || []) {
      const c = normalizeCoin(String(e.coin || ''));
      if (c) coins.add(c);
      if (e.id) techniques.add(e.id);
    }
  } catch { /* no style yet → nothing adopted */ }
  try {
    const reg = JSON.parse(fs.readFileSync(path.join(home, 'forge', 'proven_markets.json'), 'utf8'));
    for (const p of reg.pairs || []) {
      if (p.coin) coins.add(normalizeCoin(String(p.coin)));
      if (p.technique) techniques.add(p.technique);
    }
  } catch { /* no proven markets yet */ }
  return { coins, techniques };
}

// The live regime for a coin from the heartbeat's freshest perception snapshot.
// null when unknown (missing/corrupt intel) — the gate treats unknown as "can't
// prove counter-trend" and leans on the explicit --regime forge passes instead.
function liveRegime(coin, home = gclawHome()) {
  try {
    const intel = JSON.parse(fs.readFileSync(path.join(home, 'intel.json'), 'utf8'));
    return intel.intel?.[normalizeCoin(coin)]?.regime || null;
  } catch { return null; }
}

// Deterministic entry gate — the single chokepoint every signed open flows through.
// The live record proved two -EV leaks the model talked itself into: (1) counter-trend
// entries (12/12 losing longs in trend_down, p<0.001) and (2) discretionary opens with
// no proven, regime-matched basis (the -7R "discretionary" cluster). Enforcing here, in
// the executor, makes the fix code the model cannot skip — not a prompt it can rationalize
// past. Pure for unit testing; returns { ok } or { ok:false, reason }.
function entryGate({ side, regime, coin, basis, proven }) {
  const isLong = String(side).toLowerCase() !== 'short';
  // #1 Trend alignment. Unknown regime (null) can't prove a violation, so it passes
  // here — forge always supplies --regime, and chop is already vetoed upstream.
  if (regime === 'chop') return { ok: false, reason: 'no entries in chop (DNA invariant)' };
  if (regime === 'trend_down' && isLong) return { ok: false, reason: 'counter-trend blocked: long in trend_down' };
  if (regime === 'trend_up' && !isLong) return { ok: false, reason: 'counter-trend blocked: short in trend_up' };
  // #2 Discretionary block — an open must name a KNOWN technique as its basis and
  // land on a coin in the proven surface. Mirrors forge's proven-definition at the
  // coin level (any-contributor), so a forge execute is never false-blocked, while a
  // hand-typed gut trade (no basis, junk basis, or un-proven coin) is refused.
  if (!basis) {
    return { ok: false, reason: 'discretionary entry blocked: --basis <proven technique> required (route entries through forge.py run --execute)' };
  }
  if (!proven.techniques.has(basis)) {
    return { ok: false, reason: `basis '${basis}' is not a known technique — discretionary entry refused` };
  }
  const c = normalizeCoin(coin);
  if (!proven.coins.has(c)) {
    return { ok: false, reason: `${c} is not in the proven surface — prove it before trading it` };
  }
  return { ok: true };
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
// The builder dexes the agent trades. ALWAYS includes these statically so a position on
// xyz is read from the public API even when the (signed) SDK asset list is unavailable —
// otherwise a rate-limited sign-in would hide an open xyz position from the safety reads.
const KNOWN_BUILDER_DEXES = (process.env.GCLAW_BUILDER_DEXES || 'xyz')
  .split(',').map((s) => s.trim()).filter(Boolean);

async function builderDexes(skill) {
  const set = new Set(KNOWN_BUILDER_DEXES);
  const a = skill ? await skill.getHlAllAssets().catch(() => []) : [];
  const arr = Array.isArray(a) ? a : a.data || a.assets || a.universe || [];
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
  const dexes = await builderDexes(skill).catch(() => []);
  // Public API per dex: accountValue is the REAL perp-wallet value (0 when flat,
  // the deployed margin + unrealized when positioned) — not the spot-mirrored value
  // the SDK returns when flat. builderDexes still comes from the SDK asset list.
  const [def, ...rest] = await Promise.all([
    hlInfo({ type: 'clearinghouseState', user: managed }),
    ...dexes.map((dex) => hlInfo({ type: 'clearinghouseState', user: managed, dex })),
  ]);
  let accountValue = Number(def?.marginSummary?.accountValue || 0);
  const positions = mapPositions(def?.assetPositions);
  for (const root of rest) {
    if (!root) continue;
    accountValue += Number(root.marginSummary?.accountValue || 0);
    positions.push(...mapPositions(root.assetPositions));
  }
  return { accountValue, positions, withdrawable: Number(def?.withdrawable || 0) };
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
  const { ethers, SDK } = loadSdk();
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

// Pure equity assembly — the one place the HL two-wallet equity formula lives.
// Kept free of any network call so it can be regression-tested against the
// cross-margin / perp-funded / pure-spot account table (the equity bug we fixed).
//
// Equity = FREE spot + perp accountValue. The perp margin is double-represented:
// it shows as spot `hold` AND inside `accountValue` (margin + unrealized). Adding
// spot total + accountValue would count it twice; spot total + unrealized drops
// the whole perp wallet (so a perp-funded account with ~$0 spot reads as ~$0).
// (total - hold) + accountValue counts each dollar once and works for cross,
// isolated, perp-funded, and pure-spot accounts alike.
function computeEquity(full, spot, orders, managed) {
  const usdc = (spot.balances || []).find((b) => b.coin === 'USDC');
  const spotTotal = usdc ? Number(usdc.total) : 0;
  const spotHold = usdc ? Number(usdc.hold) : 0;
  const buyingPower = Math.max(0, spotTotal - spotHold);
  return {
    ok: true,
    managed,
    spotUsdc: spotTotal,
    spotHold,
    buyingPower,
    equity: buyingPower + Number(full.accountValue || 0),
    accountValue: full.accountValue, // perp wallet value (margin + unrealized)
    withdrawable: full.withdrawable,
    positions: full.positions, // includes builder-dex (xyz:*) positions
    openOrders: (orders || []).map((o) => ({ coin: o.coin, px: Number(o.limitPx), sz: Number(o.sz), reduceOnly: !!o.reduceOnly })),
  };
}

async function cmdStatus(wallet) {
  // Positions + equity come from the PUBLIC HL API (fullState, no auth), so a rate-limited
  // sign-in can NEVER blind the status — riskguard and the briefing must always see open
  // risk. The signed skill only enriches free spot balance + open orders; sign-in failure
  // degrades those (flagged by ordersOk) but never hides a position. This is the fix for the
  // naked-position-went-unguarded incident: a blind read used to flatten or skip silently.
  const skill = await signedSkill(wallet).then((r) => r.skill).catch(() => null);
  const [fullR, spotR, ordersR] = await Promise.allSettled([
    fullState(skill, wallet.managed),
    skill ? skill.getHlSpotState(wallet.managed) : Promise.resolve({ balances: [] }),
    skill ? skill.getHlOpenOrders(wallet.managed) : Promise.resolve(null),
  ]);
  const full = fullR.status === 'fulfilled' ? fullR.value : { accountValue: 0, positions: [], withdrawable: 0 };
  const spot = spotR.status === 'fulfilled' ? spotR.value : { balances: [] };
  const ordersOk = ordersR.status === 'fulfilled' && Array.isArray(ordersR.value);
  const out = computeEquity(full, spot, ordersOk ? ordersR.value : [], wallet.managed);
  out.positionsOk = fullR.status === 'fulfilled'; // false => even the public read failed
  out.ordersOk = ordersOk; // false => open orders unknown this cycle; don't infer "naked"
  // spotOk false => the free-balance (SDK) read failed, so buyingPower read 0 and EQUITY is
  // understated (just margin). Consumers must not infer "funds low" or trip the breaker on it.
  out.spotOk = !!skill && spotR.status === 'fulfilled';
  return out;
}

async function cmdOpen(wallet, args) {
  // SAFETY: require coin/side/notional explicitly — NO defaults. Previously these
  // defaulted to a live $12 ETH long, so a stray invocation (a --help probe, a typo)
  // opened a REAL position. A trade must be fully, deliberately specified.
  if (args.help || !args.coin || !args.side || args.notional == null) {
    return die('usage: open --coin <SYM> --side <long|short> --notional <USD> '
      + '[--leverage N] [--sl-pct P] [--tp-pct P] — coin/side/notional are required (no defaults)');
  }
  const coin = normalizeCoin(args.coin);
  const isLong = String(args.side).toLowerCase() !== 'short';

  // Deterministic entry gate BEFORE any network call — refuse counter-trend and
  // discretionary entries at the executor, the single path every signed open takes.
  const regime = args.regime || liveRegime(coin);
  const gate = entryGate({ side: args.side, regime, coin, basis: args.basis, proven: loadProvenSurface() });
  if (!gate.ok) die(`entry refused — ${gate.reason}`);

  const notionalTarget = Math.max(MIN_NOTIONAL + 1, Number(args.notional));
  const slPct = Number(args['sl-pct'] || 2);
  const tpPct = Number(args['tp-pct'] || 3);
  if (slPct <= 0) die('a stop-loss is required (--sl-pct)');

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

// Cache the status read so the several callers in one heartbeat (autotrail,
// model_select, riskguard, predict) share a single network fetch. The 90s TTL is
// short enough that the post-LLM callers re-read fresh state (the LLM cycle takes
// minutes), so a trade just opened is never served stale.
const STATUS_CACHE = path.join(process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw'), 'status_cache.json');
const STATUS_TTL_MS = 90000;

function readStatusCache() {
  try {
    const c = JSON.parse(fs.readFileSync(STATUS_CACHE, 'utf8'));
    return Date.now() - c.ts < STATUS_TTL_MS ? c.data : null;
  } catch { return null; }
}

function writeStatusCache(data) {
  try {
    const tmp = `${STATUS_CACHE}.tmp${process.pid}`;
    fs.writeFileSync(tmp, JSON.stringify({ ts: Date.now(), data }));
    fs.renameSync(tmp, STATUS_CACHE);
  } catch { /* cache is best-effort */ }
}

// Drop the cache the instant the position set changes (open/close), so a --cache read
// can't keep reporting a position that just closed (a phantom) — or miss one just opened —
// for the rest of the 90s TTL. The next read does a fresh fetch.
function invalidateStatusCache() {
  try { fs.unlinkSync(STATUS_CACHE); } catch { /* nothing to clear */ }
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);
  if (cmd === 'status' && args.cache) {
    const cached = readStatusCache();
    if (cached) { process.stdout.write(JSON.stringify(cached) + '\n'); return; }
  }
  const wallet = loadWallet();
  const handlers = { status: cmdStatus, open: cmdOpen, close: cmdClose, cancel: cmdCancel };
  const handler = handlers[cmd];
  if (!handler) die(`unknown command '${cmd}'. Use: status | open | close`);
  const result = await handler(wallet, args);
  if (cmd === 'status' && result.ok) writeStatusCache(result); // never cache a failed/partial read
  if ((cmd === 'open' || cmd === 'close') && result && result.ok !== false) invalidateStatusCache();
  process.stdout.write(JSON.stringify(result) + '\n');
}

// Pure functions are exported for unit testing; main() runs only as a CLI.
module.exports = {
  computeEquity, mapPositions, normalizeCoin, earnedLeverageCap, roundSig,
  readStatusCache, writeStatusCache, invalidateStatusCache, parseArgs,
  entryGate, loadProvenSurface, liveRegime, builderDexes,
};

// The HL trader keeps a connection open; exit explicitly so we don't hang.
if (require.main === module) {
  main()
    .then(() => process.exit(0))
    .catch((e) => die(e?.responseBody ? JSON.stringify(e.responseBody) : e.message || String(e)));
}
