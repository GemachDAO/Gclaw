#!/usr/bin/env node
/**
 * intel.js — the agent's perception + regime engine.
 *
 * Turns raw HyperLiquid candles + funding into a rich, decision-grade feature
 * vector per coin: trend (EMA stack + slope), momentum (RSI), volatility (ATR%,
 * realized vol), mean-reversion (Bollinger z-score), funding z-score, open-interest
 * delta, BTC correlation, a candle-based flow-pressure proxy, and — the headline —
 * a REGIME label (trend_up / trend_down / range / chop) so techniques know when to
 * act and when to sit out. Pure read of the public API; holds no funds.
 *
 *   node intel.js scan --coins BTC,ETH,SOL      # full intel per coin (default majors)
 *   node intel.js regime --coins SOL            # just the regime labels
 *
 * Env: GCLAW_HOME (caches OI for delta), HL_INFO_URL (defaults to mainnet).
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const INFO_URL = process.env.HL_INFO_URL || 'https://api.hyperliquid.xyz/info';
const HOUR = 3600_000;

function info(body) {
  return new Promise((resolve) => {
    const d = JSON.stringify(body);
    const r = https.request(INFO_URL, { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(d) }, timeout: 20000 },
      (x) => { let b = ''; x.on('data', (c) => { b += c; }); x.on('end', () => { try { resolve(JSON.parse(b)); } catch { resolve(null); } }); });
    r.on('error', () => resolve(null)); r.on('timeout', () => { r.destroy(); resolve(null); });
    r.write(d); r.end();
  });
}

// --- math primitives -------------------------------------------------------
const mean = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0);
const stdev = (a) => { if (a.length < 2) return 0; const m = mean(a); return Math.sqrt(mean(a.map((x) => (x - m) ** 2))); };
const sma = (a, n) => mean(a.slice(-n));

function ema(values, n) {
  if (!values.length) return 0;
  const k = 2 / (n + 1);
  let e = values[0];
  for (let i = 1; i < values.length; i += 1) e = values[i] * k + e * (1 - k);
  return e;
}

function rsi(closes, n = 14) {
  if (closes.length <= n) return 50;
  let gain = 0; let loss = 0;
  for (let i = closes.length - n; i < closes.length; i += 1) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  if (loss === 0) return 100;
  const rs = (gain / n) / (loss / n);
  return 100 - 100 / (1 + rs);
}

function atrPct(candles, n = 14) {
  if (candles.length <= n) return 0;
  const trs = [];
  for (let i = candles.length - n; i < candles.length; i += 1) {
    const c = candles[i]; const prev = candles[i - 1];
    trs.push(Math.max(c.h - c.l, Math.abs(c.h - prev.c), Math.abs(c.l - prev.c)));
  }
  const last = candles[candles.length - 1].c;
  return last ? (mean(trs) / last) * 100 : 0;
}

// Kaufman efficiency ratio: net move / total path. ~1 = clean trend, ~0 = chop.
function efficiencyRatio(closes, n = 20) {
  if (closes.length <= n) return 0;
  const slice = closes.slice(-n - 1);
  const net = Math.abs(slice[slice.length - 1] - slice[0]);
  let path = 0;
  for (let i = 1; i < slice.length; i += 1) path += Math.abs(slice[i] - slice[i - 1]);
  return path ? net / path : 0;
}

function correlation(a, b) {
  const n = Math.min(a.length, b.length);
  if (n < 3) return 0;
  const x = a.slice(-n); const y = b.slice(-n);
  const mx = mean(x); const my = mean(y);
  let num = 0; let dx = 0; let dy = 0;
  for (let i = 0; i < n; i += 1) { num += (x[i] - mx) * (y[i] - my); dx += (x[i] - mx) ** 2; dy += (y[i] - my) ** 2; }
  return dx && dy ? num / Math.sqrt(dx * dy) : 0;
}

const returns = (closes) => closes.slice(1).map((c, i) => (closes[i] ? (c - closes[i]) / closes[i] : 0));

// --- data ------------------------------------------------------------------
async function candles(coin, interval, limit) {
  const now = Date.now();
  const from = now - HOUR * (limit + 2);
  const raw = await info({ type: 'candleSnapshot', req: { coin, interval, startTime: from, endTime: now } });
  return (raw || []).map((k) => ({ t: k.t, o: +k.o, h: +k.h, l: +k.l, c: +k.c, v: +k.v }));
}

async function fundingZ(coin) {
  const hist = await info({ type: 'fundingHistory', coin, startTime: Date.now() - HOUR * 24 * 14 });
  if (!Array.isArray(hist) || hist.length < 5) return { funding_z: 0, funding_now: 0 };
  const rates = hist.map((h) => Number(h.fundingRate));
  const now = rates[rates.length - 1]; const sd = stdev(rates);
  return { funding_z: sd ? (now - mean(rates)) / sd : 0, funding_now: now };
}

function classifyRegime(f) {
  // Classify on the Kaufman efficiency ratio (net move / total path) — scale- and
  // timeframe-free, unlike an absolute ATR threshold (1h ATR is ~1%, so the old
  // atr>4% chop test never fired). High ER = clean trend; very low ER = whipsaw to
  // sit out; the middle is an orderly range where mean-reversion has an edge.
  const trendER = Number(process.env.GCLAW_TREND_ER) || 0.40;
  const chopER = Number(process.env.GCLAW_CHOP_ER) || 0.18;
  if (f.efficiency >= trendER) return f.ema_stack >= 0 ? 'trend_up' : 'trend_down';
  if (f.efficiency < chopER) return 'chop';
  return 'range';
}

async function coinIntel(coin, ctx, btcReturns) {
  // Drop the last (currently-forming) candle — its OHLC mutates intra-hour, so
  // every indicator built on it would jitter and the "close" isn't a real close.
  const c1 = (await candles(coin, '1h', 121)).slice(0, -1);
  if (c1.length < 30) return null;
  const closes = c1.map((k) => k.c);
  const e9 = ema(closes.slice(-40), 9); const e21 = ema(closes.slice(-60), 21); const e50 = ema(closes, 50);
  const ema_stack = (e9 > e21 ? 1 : -1) + (e21 > e50 ? 1 : -1); // -2..+2
  const sd20 = stdev(closes.slice(-20));
  const bb_z = sd20 ? (closes[closes.length - 1] - sma(closes, 20)) / sd20 : 0;
  const last = c1[c1.length - 1];
  const flow_pressure = last.h > last.l ? ((last.c - last.l) / (last.h - last.l) - 0.5) * 2 : 0; // -1..+1
  const fz = await fundingZ(coin);
  const f = {
    coin,
    price: closes[closes.length - 1],
    ema_stack,
    ema_slope_pct: e50 ? ((e9 - e50) / e50) * 100 : 0,
    rsi: Math.round(rsi(closes) * 10) / 10,
    atr_pct: Math.round(atrPct(c1) * 100) / 100,
    realized_vol_pct: Math.round(stdev(returns(closes.slice(-24))) * 100 * 100) / 100,
    bb_z: Math.round(bb_z * 100) / 100,
    ...fz,
    funding_z: Math.round(fz.funding_z * 100) / 100,
    open_interest: ctx ? Number(ctx.openInterest) : null,
    premium: ctx ? Number(ctx.premium) : null,
    btc_corr: coin === 'BTC' ? 1 : Math.round(correlation(returns(closes.slice(-24)), btcReturns) * 100) / 100,
    flow_pressure: Math.round(flow_pressure * 100) / 100,
  };
  f.efficiency = Math.round(efficiencyRatio(closes) * 100) / 100;
  f.regime = classifyRegime(f);
  f.tradeable = f.regime !== 'chop';
  return f;
}

async function scan(coins) {
  const ctxResp = await info({ type: 'metaAndAssetCtxs' });
  const ctxByName = new Map();
  if (Array.isArray(ctxResp) && ctxResp[0]?.universe) ctxResp[0].universe.forEach((u, i) => ctxByName.set(u.name, ctxResp[1][i]));
  const btc = (await candles('BTC', '1h', 49)).slice(0, -1); // closed bars only
  const btcReturns = returns(btc.map((k) => k.c).slice(-24));
  const out = {};
  for (const coin of coins) out[coin] = await coinIntel(coin, ctxByName.get(coin), btcReturns);
  return out;
}

function parseArgs(a) { const o = {}; for (let i = 0; i < a.length; i += 1) if (a[i].startsWith('--')) { o[a[i].slice(2)] = a[i + 1] && !a[i + 1].startsWith('--') ? a[i += 1] : true; } return o; }

async function main() {
  const cmd = process.argv[2] || 'scan';
  const args = parseArgs(process.argv.slice(3));
  const coins = String(args.coins || 'BTC,ETH,SOL').split(',').map((s) => s.trim()).filter(Boolean);
  fs.mkdirSync(GCLAW_HOME, { recursive: true });
  const intel = await scan(coins);
  if (cmd === 'regime') {
    const out = Object.fromEntries(Object.entries(intel).map(([k, v]) => [k, v ? { regime: v.regime, efficiency: v.efficiency, tradeable: v.tradeable } : null]));
    process.stdout.write(JSON.stringify({ ok: true, regimes: out }) + '\n');
  } else {
    process.stdout.write(JSON.stringify({ ok: true, intel }) + '\n');
  }
}

main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: e.message }) + '\n'); process.exit(1); });
