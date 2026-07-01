#!/usr/bin/env node
/**
 * carry.js — Book B, the CARRY FLOOR.
 *
 * A deterministic, delta-neutral funding-carry harvester. NO LLM. Pure rules.
 *
 * The strategy (quant dossier §1.2 / §4 Book B): cash-and-carry. When a liquid
 * major's perp funding is sufficiently positive, hold spot LONG + perp SHORT of
 * EQUAL notional → delta-neutral (price risk cancels) → collect funding (positive
 * funding pays shorts) for days. Close when funding compresses or flips. Small
 * fixed sleeve, ≤2x leverage. "Positive-carry ballast that can't blow up", not a
 * big earner.
 *
 * SAFETY — DRY-RUN BY DEFAULT. Real spot/perp orders are placed ONLY when env
 * GCLAW_CARRY_LIVE=1. Unset (default) = dry-run: compute and LOG the intended
 * action + the funding math, place NO order. Mirrors outcomes.py's shadow/live.
 *
 * ACCOUNTING — carry.js NEVER settles PnL. autosettle.js already nets closedPnl
 * AND fundingPnl coin-agnostically across all fills, so carry funding + close PnL
 * settle into the metabolism AUTOMATICALLY. Settling here would double-count.
 *
 * RISK — the perp short has NO stop (the spot leg is the hedge, held for days,
 * closed on funding compression — not a price stop). So it is opened DIRECTLY via
 * the SDK (signedSkill + hlCreateOrder), NOT through hl_perp.js cmdOpen (which
 * mandates TP/SL and is origination-locked). The stopless short is EXEMPTED from
 * riskguard by appending {coin, entry} to riskguard_exempt.json — riskguard's
 * janitor auto-prunes it when the position closes.
 *
 *   node carry.js status   # JSON: legs, best-major funding APYs, what run would do
 *   node carry.js run      # the manager: open / hold / close (dry-run by default)
 *
 * Env:
 *   GCLAW_CARRY_LIVE        '1' to place REAL orders; anything else = dry-run
 *   GCLAW_CARRY_OPEN_APY    annualized funding %% to OPEN at        (default 10)
 *   GCLAW_CARRY_CLOSE_APY   annualized funding %% to CLOSE at/below (default 3)
 *   GCLAW_CARRY_NOTIONAL    HARD per-leg notional cap, USD          (default 40)
 *   GCLAW_CARRY_LEVERAGE    perp-short leverage, clamped to 2       (default 2)
 *   GCLAW_HOME, plus whatever the SDK needs (wallet/SDK) for live legs.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET
  || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')]
    .find((p) => fs.existsSync(p))
  || path.join(os.homedir(), 'gdex-test-wallet.json');

const CARRY_PATH = path.join(GCLAW_HOME, 'carry.json');
const EXEMPT_PATH = path.join(GCLAW_HOME, 'riskguard_exempt.json');

// Liquid majors only — never a memecoin in the carry book.
const MAJORS = ['BTC', 'ETH', 'SOL'];
// HL spot majors are UNIT-bridged tokens (UBTC/UETH/USOL), NOT the perp symbol.
// The spot order coin is the pair name "UTOKEN/USDC"; see resolveSpotPair().
const SPOT_TOKEN = { BTC: 'UBTC', ETH: 'UETH', SOL: 'USOL' };
const SZ_DECIMALS = { BTC: 5, ETH: 4, SOL: 2 }; // fallback size precision

const HL_CHAIN_ID = 42161;
const MAX_LEVERAGE = 2; // delta-neutral ballast — never above 2x (hard clamp)

// ── tunables (env-overridable, bounded in code) ──────────────────────────────
const OPEN_APY = Number(process.env.GCLAW_CARRY_OPEN_APY || 10); // % annualized
const CLOSE_APY = Number(process.env.GCLAW_CARRY_CLOSE_APY || 3); // % annualized
const NOTIONAL = Number(process.env.GCLAW_CARRY_NOTIONAL || 40); // USD HARD CAP / leg
const LEVERAGE = Math.max(1, Math.min(MAX_LEVERAGE, Number(process.env.GCLAW_CARRY_LEVERAGE || 2)));
const MIN_NOTIONAL = 11; // HL minimum order value (USD)

function liveMode() {
  return process.env.GCLAW_CARRY_LIVE === '1';
}

// ── pure helpers (no network / no SDK — unit-testable) ───────────────────────

/** Annualized funding %, given HL's hourly funding rate. funding*24*365*100. */
function annualizeFunding(hourlyFunding) {
  return Number(hourlyFunding) * 24 * 365 * 100;
}

/**
 * Pick the best liquid major to OPEN: highest annualized funding among MAJORS,
 * provided it clears OPEN_APY. Returns null if none qualifies.
 *
 * @param {Record<string, {apy:number, mark:number}>} fundings per-major funding
 * @returns {{coin:string, apy:number, mark:number}|null}
 */
function bestOpenCandidate(fundings) {
  let best = null;
  for (const coin of MAJORS) {
    const f = fundings[coin];
    if (!f || !(f.apy >= OPEN_APY)) continue;
    if (!best || f.apy > best.apy) best = { coin, apy: f.apy, mark: f.mark };
  }
  return best;
}

/**
 * The manager DECISION — pure. Given the open carry (or null), the per-major
 * funding read, and the metabolism mode, return exactly one of:
 *   {action:'open', coin, apy, mark}  — no carry open and a major clears OPEN_APY
 *   {action:'close', coin, apy, reason} — carry open and its funding <= CLOSE_APY or negative
 *   {action:'hold', ...}              — otherwise
 * ONE carry at a time: if a carry is open we only ever hold or close it.
 *
 * @param {object|null} carry current carry state (carry.json) or null
 * @param {Record<string, {apy:number, mark:number}>} fundings
 * @param {string} mode metabolism life mode (hibernate/survive/thrive)
 */
function decide(carry, fundings, mode) {
  if (carry && carry.coin) {
    const f = fundings[carry.coin];
    const apy = f ? f.apy : null;
    if (apy == null) return { action: 'hold', coin: carry.coin, reason: 'funding read unavailable — hold' };
    if (apy < 0) return { action: 'close', coin: carry.coin, apy, reason: `funding flipped negative (${apy.toFixed(2)}%)` };
    if (apy <= CLOSE_APY) return { action: 'close', coin: carry.coin, apy, reason: `funding compressed to ${apy.toFixed(2)}% <= ${CLOSE_APY}%` };
    return { action: 'hold', coin: carry.coin, apy, reason: `funding ${apy.toFixed(2)}% > ${CLOSE_APY}% close — hold` };
  }
  // No carry open. Opening is paused in hibernate (survival floor first).
  if (mode === 'hibernate') return { action: 'hold', reason: 'hibernate — no new carry' };
  const cand = bestOpenCandidate(fundings);
  if (!cand) return { action: 'hold', reason: `no major clears OPEN_APY ${OPEN_APY}%` };
  return { action: 'open', coin: cand.coin, apy: cand.apy, mark: cand.mark };
}

/**
 * Size the EQUAL-notional legs to AVAILABLE capital, capped by NOTIONAL.
 *
 * Spot→perp margin reality: USDC sits in SPOT; the perp wallet has little buying
 * power and this SDK has NO spot↔perp USD transfer. So the legs are sized to what
 * each wallet can actually fund RIGHT NOW: the spot leg can't exceed spot buying
 * power; the perp short's margin can't exceed perp buying power (notional =
 * margin*leverage). Equal notional = min(NOTIONAL, spotBP, perpBP*leverage).
 *
 * @returns {{notional:number, ok:boolean, reason?:string}}
 */
function sizeLegs(spotBuyingPower, perpBuyingPower, leverage) {
  const perpCapacity = Math.max(0, perpBuyingPower) * leverage;
  const notional = Math.min(NOTIONAL, Math.max(0, spotBuyingPower), perpCapacity);
  if (notional < MIN_NOTIONAL) {
    return {
      notional: Number(notional.toFixed(2)),
      ok: false,
      reason: `sized notional $${notional.toFixed(2)} < $${MIN_NOTIONAL} min `
        + `(spotBP $${spotBuyingPower.toFixed(2)}, perpBP $${perpBuyingPower.toFixed(2)} × ${leverage}x)`,
    };
  }
  return { notional: Number(Math.min(notional, NOTIONAL).toFixed(2)), ok: true };
}

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };

function writeAtomic(p, obj) {
  const tmp = `${p}.tmp${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2) + '\n');
  fs.renameSync(tmp, p);
}

function loadCarry() {
  const c = readJson(CARRY_PATH, null);
  return c && c.coin ? c : null;
}

function clearCarry() {
  try { fs.unlinkSync(CARRY_PATH); } catch { /* already gone */ }
}

/** The metabolism life mode (hibernate/survive/thrive); 'thrive' if unreadable. */
function metabolismMode() {
  const m = readJson(path.join(GCLAW_HOME, 'metabolism.json'), null);
  return (m && typeof m.mode === 'string') ? m.mode : 'thrive';
}

// ── riskguard exemption contract ─────────────────────────────────────────────
// riskguard.js flattens any stopless ("naked") position. The carry short is
// deliberately stopless (the spot leg is its hedge), so it must be exempted by
// appending {coin, entry} to riskguard_exempt.json. riskguard matches by coin +
// entry within 0.1%, and its janitor (pruneState) removes the entry once the
// position is gone — so we add on open and remove on close, idempotently.

function addExemption(coin, entry) {
  const list = readJson(EXEMPT_PATH, []);
  const arr = Array.isArray(list) ? list : [];
  const exists = arr.some((e) => e.coin === coin && Math.abs(Number(e.entry) - entry) / entry < 0.001);
  if (!exists) arr.push({ coin, entry: Number(entry) });
  writeAtomic(EXEMPT_PATH, arr);
  return arr;
}

function removeExemption(coin) {
  const list = readJson(EXEMPT_PATH, []);
  if (!Array.isArray(list)) { writeAtomic(EXEMPT_PATH, []); return []; }
  const kept = list.filter((e) => e.coin !== coin);
  if (kept.length !== list.length) writeAtomic(EXEMPT_PATH, kept);
  return kept;
}

// ── network: public funding read (no auth) ───────────────────────────────────

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

/**
 * Read each MAJOR's annualized funding APY + mark from the PUBLIC metaAndAssetCtxs
 * endpoint (no auth). Returns {} if the read fails (caller treats as "hold").
 */
async function readFundings() {
  const m = await hlInfo({ type: 'metaAndAssetCtxs' });
  if (!Array.isArray(m) || m.length < 2) return {};
  const [meta, ctxs] = m;
  const universe = (meta && meta.universe) || [];
  const out = {};
  for (const coin of MAJORS) {
    const i = universe.findIndex((u) => u.name === coin);
    if (i === -1 || !ctxs[i]) continue;
    const c = ctxs[i];
    out[coin] = { apy: annualizeFunding(c.funding), mark: Number(c.markPx), funding: Number(c.funding) };
  }
  return out;
}

// ── SDK / live legs (only reached when GCLAW_CARRY_LIVE=1) ────────────────────

const loadSdk = () => ({
  ethers: require(path.join(GDEX_DIR, 'node_modules', 'ethers')).ethers,
  SDK: require(path.join(GDEX_DIR, 'dist')),
});

function loadWallet() {
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const managed = w.managed && w.managed['Arbitrum (HyperLiquid)'] && w.managed['Arbitrum (HyperLiquid)'].address;
  if (!w.control || !w.control.address || !w.control.privateKey) throw new Error('wallet missing control key');
  if (!managed) throw new Error('wallet missing managed Arbitrum (HyperLiquid) address');
  return { control: w.control.address, pk: w.control.privateKey, managed };
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
    apiKey, userId: wallet.control, sessionKey: kp.sessionKey, nonce, signature: sig.replace(/^0x/, ''),
  });
  await skill.signInWithComputedData({ computedData: payload.computedData, chainId: HL_CHAIN_ID });
  return { skill, SDK, creds: { apiKey, walletAddress: wallet.control, sessionPrivateKey: kp.sessionPrivateKey } };
}

/**
 * Read free USDC in the SPOT wallet (the spot-leg buying power) and the perp
 * wallet's withdrawable (the short-leg margin). Public-API perp read mirrors
 * hl_perp.js; spot read via the authenticated SDK.
 */
async function readCapital(skill, managed) {
  const [spotR, perpR] = await Promise.allSettled([
    skill.getHlSpotState(managed),
    hlInfo({ type: 'clearinghouseState', user: managed }),
  ]);
  const spot = spotR.status === 'fulfilled' ? spotR.value : { balances: [] };
  const usdc = (spot.balances || []).find((b) => b.coin === 'USDC');
  const spotTotal = usdc ? Number(usdc.total) : 0;
  const spotHold = usdc ? Number(usdc.hold) : 0;
  const spotBuyingPower = Math.max(0, spotTotal - spotHold);
  const perp = perpR.status === 'fulfilled' ? perpR.value : null;
  const perpBuyingPower = perp ? Number(perp.withdrawable || 0) : 0;
  return { spotBuyingPower, perpBuyingPower };
}

/**
 * Resolve a major's HL SPOT pair into the order coin + assetId. HL spot pairs are
 * UTOKEN/USDC (e.g. UBTC/USDC); the order asset id is 10000 + the pair index.
 * THE GOTCHA: spot symbols differ from perp symbols (UBTC, not BTC) AND the
 * bundled SDK trader ships a perp-only static asset table with NO spot entries,
 * so executeSpot can't find a spot asset by default — we register it ourselves.
 */
async function resolveSpotPair(token) {
  const sm = await hlInfo({ type: 'spotMeta' });
  if (!sm || !Array.isArray(sm.universe) || !Array.isArray(sm.tokens)) return null;
  const tokIdx = {};
  for (const t of sm.tokens) tokIdx[t.index] = t.name;
  const pair = sm.universe.find((p) => (p.tokens || []).map((i) => tokIdx[i]).includes(token)
    && (p.tokens || []).map((i) => tokIdx[i]).includes('USDC'));
  if (!pair) return null;
  return { name: pair.name, assetId: 10000 + pair.index, index: pair.index, szDecimals: 0 };
}

/**
 * Place the SPOT leg LIVE. Builds a fresh trader instance and registers the spot
 * asset (the SDK's skill.hlExecuteSpot uses a perp-only table that lacks spot
 * pairs), then submits an IOC market order. Returns the SDK response.
 */
async function placeSpotLeg(SDK, wallet, coin, isBuy, px, size) {
  const token = SPOT_TOKEN[coin];
  const spotAsset = await resolveSpotPair(token);
  if (!spotAsset) throw new Error(`could not resolve HL spot pair for ${token}/USDC`);
  const { createHlTrader } = require(path.join(GDEX_DIR, 'dist', 'actions', 'perpTrade.js'));
  const trader = await createHlTrader();
  trader.setAssets([{ name: spotAsset.name, assetId: spotAsset.assetId }]);
  return trader.executeSpot(wallet.pk, {
    coin: spotAsset.name, isBuy, price: String(px), size: String(size),
  }, true);
}

/** Place the PERP SHORT leg LIVE — stopless, ≤2x, directly via hlCreateOrder. */
async function placePerpShort(skill, creds, coin, px, size, leverage) {
  const res = await skill.hlCreateOrder({
    coin, isLong: false, price: String(px), size: String(size),
    reduceOnly: false, isMarket: true, tpPrice: '0', slPrice: '0', leverage, ...creds,
  });
  if (res && res.isSuccess === false) throw new Error(`perp short rejected: ${JSON.stringify(res)}`);
  return res;
}

/** Close the PERP SHORT leg LIVE (reduce-only buy to flatten). */
async function closePerpShort(skill, creds, coin, px, size) {
  const res = await skill.hlCreateOrder({
    coin, isLong: true, price: String(px), size: String(size),
    reduceOnly: true, isMarket: true, tpPrice: '0', slPrice: '0', ...creds,
  });
  if (res && res.isSuccess === false) throw new Error(`perp close rejected: ${JSON.stringify(res)}`);
  return res;
}

function sizeFor(coin, notional, px) {
  const dp = SZ_DECIMALS[coin] ?? 2;
  return Math.max(0, Number((notional / px).toFixed(dp)));
}

// ── manager actions ──────────────────────────────────────────────────────────

/**
 * OPEN a carry: spot buy + equal-notional perp short, write the riskguard
 * exemption, save state. Dry-run by default — logs the plan, touches nothing.
 */
async function doOpen(coin, apy, fundings) {
  const live = liveMode();
  const mark = fundings[coin] ? fundings[coin].mark : null;
  if (!mark) return { ok: false, action: 'open', coin, error: 'no mark price' };

  if (!live) {
    // Dry-run: size against a conservative assumed-available NOTIONAL (no SDK call),
    // log the full plan + funding math, place NOTHING.
    const sized = sizeLegs(NOTIONAL, NOTIONAL / LEVERAGE, LEVERAGE);
    const size = sizeFor(coin, sized.notional, mark);
    return {
      ok: true, action: 'open', live: false, dryRun: true, coin, apy: round2(apy),
      mark, leverage: LEVERAGE, plannedNotional: sized.notional, plannedSize: size,
      plan: `DRY-RUN: would spot-buy ${size} ${SPOT_TOKEN[coin]} (~$${sized.notional}) `
        + `+ perp-short ${size} ${coin} @ ${LEVERAGE}x, exempt from riskguard, save carry.json. `
        + `Set GCLAW_CARRY_LIVE=1 to arm.`,
      funding: { apy: round2(apy), openApy: OPEN_APY },
    };
  }

  // LIVE — place real orders, LEG-ATOMICALLY. The perp short (the leg that can fail
  // on margin) goes FIRST and is exempted from riskguard immediately; only then the
  // spot hedge. If the spot hedge fails, UNWIND the short — we must never sit half-
  // hedged, since a lone stopless short (or lone spot long) is exactly the directional
  // risk this strategy exists to avoid. State is saved only after BOTH legs fill.
  const wallet = loadWallet();
  const { skill, SDK, creds } = await signedSkill(wallet);
  const { spotBuyingPower, perpBuyingPower } = await readCapital(skill, wallet.managed);
  const sized = sizeLegs(spotBuyingPower, perpBuyingPower, LEVERAGE);
  if (!sized.ok) return { ok: false, action: 'open', coin, error: sized.reason };
  const size = sizeFor(coin, sized.notional, mark);
  if (size <= 0) return { ok: false, action: 'open', coin, error: 'computed size 0' };

  const perpRes = await placePerpShort(skill, creds, coin, mark, size, LEVERAGE);
  addExemption(coin, mark); // shield the stopless short from riskguard before anything else
  let spotRes;
  try {
    spotRes = await placeSpotLeg(SDK, wallet, coin, true, mark, size);
  } catch (e) {
    try { await closePerpShort(skill, creds, coin, mark, size); } catch { /* best-effort unwind */ }
    removeExemption(coin);
    return { ok: false, action: 'open', coin, error: `spot hedge failed; perp short unwound: ${e.message}` };
  }
  const state = {
    coin, spotSize: size, perpSize: size, entryPx: mark, openedAt: new Date().toISOString(),
    apyAtOpen: round2(apy), live: true,
  };
  writeAtomic(CARRY_PATH, state);
  return { ok: true, action: 'open', live: true, coin, size, notional: sized.notional, leverage: LEVERAGE, entryPx: mark, spotRes, perpRes, state };
}

/**
 * CLOSE the carry: sell spot, close perp, remove the riskguard exemption, clear
 * state. Dry-run by default. Always clears state + exemption (even in dry-run the
 * exemption removal is safe — the janitor would prune a closed position anyway).
 */
async function doClose(carry, reason, fundings) {
  const live = liveMode();
  if (!live) {
    return {
      ok: true, action: 'close', live: false, dryRun: true, coin: carry.coin, reason,
      plan: `DRY-RUN: would sell ${carry.spotSize} ${SPOT_TOKEN[carry.coin]} spot `
        + `+ close ${carry.perpSize} ${carry.coin} perp short, remove riskguard exemption, clear carry.json. `
        + `Set GCLAW_CARRY_LIVE=1 to arm.`,
    };
  }
  const wallet = loadWallet();
  const { skill, SDK, creds } = await signedSkill(wallet);
  const mark = fundings[carry.coin] ? fundings[carry.coin].mark : carry.entryPx;
  // Close the LEVERAGED leg first to drop liquidation exposure immediately; if the
  // spot sell then fails, the state is left intact so the next cycle retries — a lone
  // spot long carries no liquidation risk, unlike a lone short.
  const perpRes = await closePerpShort(skill, creds, carry.coin, mark, carry.perpSize);
  const spotRes = await placeSpotLeg(SDK, wallet, carry.coin, false, mark, carry.spotSize);
  removeExemption(carry.coin);
  clearCarry();
  return { ok: true, action: 'close', live: true, coin: carry.coin, reason, spotRes, perpRes };
}

const round2 = (x) => Math.round(Number(x) * 100) / 100;

// ── CLI commands ─────────────────────────────────────────────────────────────

async function cmdStatus() {
  const carry = loadCarry();
  const fundings = await readFundings();
  const mode = metabolismMode();
  const decision = decide(carry, fundings, mode);
  return {
    ok: true,
    live: liveMode(),
    mode,
    thresholds: { openApy: OPEN_APY, closeApy: CLOSE_APY, notional: NOTIONAL, leverage: LEVERAGE },
    carry,
    fundings: Object.fromEntries(Object.entries(fundings).map(([k, v]) => [k, { apy: round2(v.apy), mark: v.mark }])),
    wouldDo: decision,
  };
}

async function cmdRun() {
  const carry = loadCarry();
  const fundings = await readFundings();
  const mode = metabolismMode();
  const decision = decide(carry, fundings, mode);

  if (decision.action === 'open') {
    return { ...(await doOpen(decision.coin, decision.apy, fundings)), decision };
  }
  if (decision.action === 'close') {
    return { ...(await doClose(carry, decision.reason, fundings)), decision };
  }
  return { ok: true, action: 'hold', live: liveMode(), mode, reason: decision.reason, carry, decision };
}

async function main() {
  const cmd = process.argv[2] || 'status';
  const handlers = { status: cmdStatus, run: cmdRun };
  const handler = handlers[cmd];
  if (!handler) {
    process.stdout.write(JSON.stringify({ ok: false, error: `unknown command '${cmd}'. Use: status | run` }) + '\n');
    process.exit(1);
  }
  const out = await handler();
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

// Pure / file-only functions + the tunables exported for unit testing;
// main() runs only as a CLI (require.main guard) so importing is side-effect-free.
module.exports = {
  annualizeFunding, bestOpenCandidate, decide, sizeLegs,
  addExemption, removeExemption, loadCarry, clearCarry, metabolismMode,
  doOpen, doClose, liveMode, resolveSpotPair, sizeFor,
  OPEN_APY, CLOSE_APY, NOTIONAL, LEVERAGE, MAX_LEVERAGE, MIN_NOTIONAL, MAJORS, SPOT_TOKEN,
  CARRY_PATH, EXEMPT_PATH,
};

if (require.main === module) {
  main()
    .then(() => process.exit(0))
    .catch((e) => {
      process.stdout.write(JSON.stringify({ ok: false, error: e && e.message ? e.message : String(e) }) + '\n');
      process.exit(1);
    });
}
