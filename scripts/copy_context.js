#!/usr/bin/env node
/**
 * Entry-context reconstruction (assune-2ol.11) — makes the reverse-engineering desk
 * GENERATIVE. Given a skill-proven wallet's opens, reconstruct the intel feature vector at
 * each entry bar (same senses intel.js coinIntel computes), so the desk reports the CONDITIONS
 * a winner enters under (median RSI, dominant regime, efficiency) — an ENCODABLE pattern the
 * scientist can author, not just "this wallet trades". Pure reconstruction is exported for
 * tests; the network I/O (userFills + candleSnapshot) is orchestrated in buildEntryContext.
 */
'use strict';

const https = require('node:https');
const { rsi, ema, efficiencyRatio, atrPct, stdev, sma, classifyRegime } = require('./intel.js');

const HOUR = 3600 * 1000;

function hlInfo(body) {
  return new Promise((resolve) => {
    const d = JSON.stringify(body);
    const req = https.request('https://api.hyperliquid.xyz/info',
      { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(d) }, timeout: 20000 },
      (res) => { let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => { try { resolve(JSON.parse(b)); } catch { resolve(null); } }); });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.write(d); req.end();
  });
}

// Distinct entries from a fills list: keep opens, dedupe partial fills by order id.
function dedupeOpens(fills) {
  const seen = new Set();
  const opens = [];
  for (const f of fills || []) {
    const dir = String(f.dir || '');
    if (!dir.includes('Open')) continue;
    const key = f.oid != null ? `oid:${f.oid}` : `${f.coin}:${f.time}`;
    if (seen.has(key)) continue;
    seen.add(key);
    opens.push({ coin: f.coin, time: Number(f.time), long: dir.includes('Long') });
  }
  return opens;
}

// Feature vector at bar i over a 120-bar window, mirroring intel.js coinIntel's price senses.
function reconstructEntry(candles, i) {
  const window = candles.slice(Math.max(0, i - 119), i + 1);
  if (window.length < 30) return null;
  const closes = window.map((k) => k.c);
  const e9 = ema(closes.slice(-40), 9); const e21 = ema(closes.slice(-60), 21); const e50 = ema(closes, 50);
  const sd20 = stdev(closes.slice(-20));
  const f = {
    rsi: Math.round(rsi(closes) * 10) / 10,
    ema_stack: (e9 > e21 ? 1 : -1) + (e21 > e50 ? 1 : -1),
    efficiency: Math.round(efficiencyRatio(closes) * 100) / 100,
    atr_pct: Math.round(atrPct(window) * 100) / 100,
    bb_z: sd20 ? Math.round((closes[closes.length - 1] - sma(closes, 20)) / sd20 * 100) / 100 : 0,
  };
  f.regime = classifyRegime(f);
  return f;
}

// Index of the last bar with t <= target (candles ascending by .t); -1 if none.
function barAtTime(candles, t) {
  let lo = 0; let hi = candles.length - 1; let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (candles[mid].t <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

function median(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2 * 100) / 100;
}

function dominant(xs) {
  const c = {};
  for (const x of xs) c[x] = (c[x] || 0) + 1;
  const top = Object.entries(c).sort((a, b) => b[1] - a[1])[0];
  return top ? top[0] : null;
}

// Per-direction summary of the entry features: the encodable "how this wallet enters".
function aggregateContext(enriched) {
  const byDir = { long: [], short: [] };
  for (const e of enriched) if (e.f) byDir[e.long ? 'long' : 'short'].push(e.f);
  const summ = (fs) => (fs.length ? {
    n: fs.length,
    median_rsi: median(fs.map((f) => f.rsi)),
    median_efficiency: median(fs.map((f) => f.efficiency)),
    median_bb_z: median(fs.map((f) => f.bb_z)),
    dominant_regime: dominant(fs.map((f) => f.regime)),
  } : { n: 0 });
  return { long: summ(byDir.long), short: summ(byDir.short) };
}

async function fetchCandlesFor(coin, opens) {
  const times = opens.map((o) => o.time);
  const from = Math.min(...times) - 130 * HOUR; // room for the 120-bar window before the earliest open
  const to = Math.max(...times) + HOUR;
  const raw = await hlInfo({ type: 'candleSnapshot', req: { coin, interval: '1h', startTime: from, endTime: to } });
  return (raw || []).map((k) => ({ t: k.t, o: +k.o, h: +k.h, l: +k.l, c: +k.c, v: +k.v }));
}

// Orchestrate: pull the wallet's opens, reconstruct entry features on its most-traded coins.
async function buildEntryContext(address, { maxCoins = 6 } = {}) {
  const opens = dedupeOpens(await hlInfo({ type: 'userFills', user: address }));
  if (!opens.length) return null;
  const byCoin = {};
  for (const o of opens) (byCoin[o.coin] = byCoin[o.coin] || []).push(o);
  const coins = Object.entries(byCoin).sort((a, b) => b[1].length - a[1].length).slice(0, maxCoins);
  const enriched = [];
  for (const [coin, os] of coins) {
    const candles = await fetchCandlesFor(coin, os);
    if (!candles.length) continue;
    for (const o of os) {
      const i = barAtTime(candles, o.time);
      enriched.push({ coin, long: o.long, f: i >= 30 ? reconstructEntry(candles, i) : null });
    }
  }
  return { address, opens: opens.length, reconstructed: enriched.filter((e) => e.f).length, context: aggregateContext(enriched) };
}

module.exports = { dedupeOpens, reconstructEntry, barAtTime, aggregateContext, median, dominant, buildEntryContext };
