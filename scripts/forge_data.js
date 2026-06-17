#!/usr/bin/env node
/**
 * Market-data bridge for the technique forge (read-only, no auth).
 *
 * Pulls HyperLiquid perp candles and current asset contexts straight from the
 * public info API so the Python forge can backtest and run techniques without
 * the SDK or a signed session. Emits JSON on stdout.
 *
 *   node forge_data.js candles  --coin BTC --interval 1h --limit 500
 *   node forge_data.js features --coins BTC,ETH,SOL
 *
 * candleSnapshot needs a time window, so --limit is converted to [from, now]
 * using the interval; HL caps a response at ~5000 candles.
 */
'use strict';

const INFO_URL = 'https://api.hyperliquid.xyz/info';

const INTERVAL_MS = {
  '1m': 60_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000,
  '1h': 3_600_000, '4h': 14_400_000, '1d': 86_400_000,
};

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

function die(msg) {
  process.stdout.write(JSON.stringify({ ok: false, error: msg }) + '\n');
  process.exit(1);
}

async function info(body) {
  const res = await fetch(INFO_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HL info ${res.status}`);
  return res.json();
}

async function candles(coin, interval, limit) {
  const step = INTERVAL_MS[interval];
  if (!step) die(`unknown interval '${interval}'`);
  const now = Date.now();
  const from = now - step * (limit + 2);
  const raw = await info({ type: 'candleSnapshot', req: { coin, interval, startTime: from, endTime: now } });
  return (raw || []).map((k) => ({
    t: k.t, o: Number(k.o), h: Number(k.h), l: Number(k.l), c: Number(k.c), v: Number(k.v),
  }));
}

async function features(coins) {
  const [meta, ctxs] = await info({ type: 'metaAndAssetCtxs' });
  const byName = new Map();
  meta.universe.forEach((u, i) => byName.set(u.name, ctxs[i]));
  const out = {};
  for (const coin of coins) {
    const c = byName.get(coin);
    if (!c) { out[coin] = null; continue; }
    out[coin] = {
      mark: Number(c.markPx),
      oracle: Number(c.oraclePx),
      funding: Number(c.funding),
      openInterest: Number(c.openInterest),
      premium: Number(c.premium),
      prevDayPx: Number(c.prevDayPx),
      dayNtlVlm: Number(c.dayNtlVlm),
    };
  }
  return out;
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);
  if (cmd === 'candles') {
    const data = await candles(args.coin || 'BTC', args.interval || '1h', Number(args.limit || 500));
    process.stdout.write(JSON.stringify({ ok: true, coin: args.coin || 'BTC', interval: args.interval || '1h', candles: data }) + '\n');
  } else if (cmd === 'features') {
    const coins = String(args.coins || 'BTC,ETH,SOL').split(',').map((s) => s.trim()).filter(Boolean);
    process.stdout.write(JSON.stringify({ ok: true, features: await features(coins) }) + '\n');
  } else {
    die(`unknown command '${cmd}'. Use: candles | features`);
  }
}

main().catch((e) => die(e.message));
