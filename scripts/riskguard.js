#!/usr/bin/env node
/**
 * riskguard.js — the deterministic risk guardrail.
 *
 * The risk brain (sizing.py) is advisory and the model bypasses it, so positions
 * get opened far over their risk budget (the −$4 / −$6 blow-ups). This enforces the
 * cap AFTER the fact, every heartbeat, with hard-coded limits the model cannot argue
 * with: it reads each position's real stop, computes the $ at risk, and physically
 * TRIMS anything over the per-trade or portfolio cap. Naked positions (no stop) are
 * flattened. It only ever REDUCES exposure — never opens, never adds — so it is safe
 * to run unattended under the anti-drain model.
 *
 *   node riskguard.js run        # enforce now (trims over-cap positions)
 *   node riskguard.js check      # dry-run: report what it WOULD do, trade nothing
 *
 * Env: GCLAW_HOME, plus whatever hl_perp.js needs (wallet/SDK).
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { execFileSync } = require('node:child_process');

const SKILL_DIR = __dirname;
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const RISK_CAP_PCT = 1.5;       // max % of equity at risk on a single trade
const PORTFOLIO_CAP_PCT = 4.0;  // max total % of equity at risk across all trades
const TOLERANCE = 1.15;         // don't churn a position for being <15% over
const MIN_NOTIONAL = 11;        // HL min — below this we flatten rather than dust-trim

function hl(args) {
  // The HL SDK status read transiently fails; never let that crash the guardrail —
  // a failed read just means "skip enforcement this cycle", handled by the caller.
  try {
    const out = execFileSync('node', [path.join(SKILL_DIR, 'hl_perp.js'), ...args],
      { encoding: 'utf8', timeout: 90000 });
    return JSON.parse(out.trim().split('\n').pop());
  } catch { return null; }
}

// The protective stop is the reduce-only order on the LOSS side: above entry for a
// short, below entry for a long. Nearest such order is what triggers first.
function stopFor(coin, entry, isShort, orders) {
  const lossSide = orders.filter((o) => o.coin === coin && o.reduceOnly
    && (isShort ? Number(o.px) > entry : Number(o.px) < entry));
  if (!lossSide.length) return null;
  const pxs = lossSide.map((o) => Number(o.px));
  return isShort ? Math.min(...pxs) : Math.max(...pxs);
}

// A specific open position can be grandfathered (left to its own stop) by listing
// {coin, entry} in riskguard_exempt.json. Matched by coin + entry (0.1% tolerance),
// so a LATER trade on the same coin at a different entry is still enforced.
function isExempt(coin, entry) {
  let list = [];
  try { list = JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'riskguard_exempt.json'), 'utf8')); } catch { return false; }
  return list.some((e) => e.coin === coin && Math.abs(Number(e.entry) - entry) / entry < 0.001);
}

function assess(st) {
  const eq = Number(st.equity) || 0;
  const orders = st.openOrders || [];
  return (st.positions || []).filter((p) => !isExempt(p.coin, Number(p.entryPx))).map((p) => {
    const size = Math.abs(Number(p.size));
    const entry = Number(p.entryPx);
    const isShort = Number(p.size) < 0;
    const stop = stopFor(p.coin, entry, isShort, orders);
    const notional = size * entry;
    const risk = stop == null ? notional : Math.abs(entry - stop) * size; // naked = whole notional
    return { coin: p.coin, size, entry, isShort, stop, notional, risk,
      riskPct: eq ? (risk / eq) * 100 : 0, naked: stop == null };
  });
}

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };
const writeAtomic = (p, data) => { const t = `${p}.tmp${process.pid}`; fs.writeFileSync(t, data); fs.renameSync(t, p); };

// Janitor: position-keyed state files (open_risk, riskguard_exempt) are written at
// entry but never cleaned, so a stale entry mis-attributes the next trade or
// silently exempts a re-entry from the cap. Drop any entry with no matching live
// position so each only ever describes trades that actually exist.
function pruneState(positions) {
  const liveAt = (coin, entry) => positions.some((p) => p.coin === coin
    && Math.abs(Number(p.entryPx) - Number(entry)) / Number(p.entryPx) < 0.001);
  const liveCoin = new Set(positions.map((p) => p.coin));
  const exPath = path.join(GCLAW_HOME, 'riskguard_exempt.json');
  const exempt = readJson(exPath, null);
  if (Array.isArray(exempt)) {
    const kept = exempt.filter((e) => liveAt(e.coin, e.entry));
    if (kept.length !== exempt.length) writeAtomic(exPath, JSON.stringify(kept));
  }
  const orPath = path.join(GCLAW_HOME, 'open_risk.json');
  const orisk = readJson(orPath, null);
  if (orisk && typeof orisk === 'object') {
    const kept = Object.fromEntries(Object.entries(orisk).filter(([coin]) => liveCoin.has(coin)));
    if (Object.keys(kept).length !== Object.keys(orisk).length) writeAtomic(orPath, JSON.stringify(kept));
  }
}

// Deterministic circuit breaker: halt + flatten everything on a drawdown from the
// high-water mark. The advisory forge breaker was never enforced; this is.
function breakerCheck(eq, positions, dry) {
  const bpath = path.join(GCLAW_HOME, 'breaker.json');
  const dd = Number(process.env.GCLAW_BREAKER_DD) || 0.25;
  const prev = readJson(bpath, {});
  // Cap each read's HWM rise to 20% so a single transient high equity read (e.g. a
  // double-counted balance) can't poison the high-water mark and trip a false drawdown
  // halt — which here FLATTENS the whole book. MUST match forge.py's circuit_breaker:
  // both write this same file, so if the logic differs one re-poisons what the other
  // corrected (the un-capped Math.max here silently undid forge's fix every heartbeat).
  const prevHwm = Number(prev.hwm) || 0;
  const hwm = prevHwm > 0 ? Math.max(prevHwm, Math.min(eq, prevHwm * 1.20)) : eq;
  const drawdown = hwm > 0 ? (hwm - eq) / hwm : 0;
  const tripped = drawdown >= dd;
  if (!dry) {
    writeAtomic(bpath, JSON.stringify({ hwm: Math.round(hwm * 100) / 100, equity: Math.round(eq * 100) / 100,
      drawdown_pct: Math.round(drawdown * 1000) / 10, tripped, reason: tripped ? `drawdown ${(drawdown * 100).toFixed(1)}% >= ${dd * 100}%` : null,
      at: new Date().toISOString() }, null, 2) + '\n');
  }
  return { hwm, drawdown, tripped };
}

function reduce(coin, size, dry) {
  if (dry) return { coin, wouldReduce: Number(size.toFixed(6)) };
  return hl(['close', '--coin', coin, '--size', String(size)]);
}

function flatten(coin, dry) {
  if (dry) return { coin, wouldFlatten: true };
  return hl(['close', '--coin', coin]);
}

function enforce(dry) {
  const st = hl(['status']);
  if (!st) return { ok: true, skipped: 'status read unavailable this cycle' };
  const eq = Number(st.equity) || 0;
  if (!eq) return { ok: false, error: 'no equity read' };
  if (!dry) pruneState(st.positions || []); // clean stale position-keyed state first

  // Circuit breaker: on a drawdown halt, flatten EVERYTHING (exemptions don't apply
  // to a breaker) and stop — no per-trade fiddling when the book must be de-risked.
  const brk = breakerCheck(eq, st.positions || [], dry);
  if (brk.tripped) {
    const actions = (st.positions || []).map((p) => ({ coin: p.coin, reason: `BREAKER drawdown ${(brk.drawdown * 100).toFixed(1)}%`, action: flatten(p.coin, dry) }));
    return { ok: true, dry: !!dry, equity: Math.round(eq * 100) / 100, breaker_tripped: true, drawdown_pct: Math.round(brk.drawdown * 1000) / 10, actions };
  }
  const cap = eq * (RISK_CAP_PCT / 100);
  const portCap = eq * (PORTFOLIO_CAP_PCT / 100);
  const actions = [];
  let positions = assess(st);

  // 1. Naked positions (no protective stop) — flatten immediately.
  for (const p of positions.filter((x) => x.naked)) {
    actions.push({ coin: p.coin, reason: 'NAKED — no stop', action: flatten(p.coin, dry), riskPct: Math.round(p.riskPct * 10) / 10 });
  }
  positions = positions.filter((x) => !x.naked);

  // 2. Per-trade cap — trim each over-cap position down to the cap.
  for (const p of positions) {
    if (p.risk <= cap * TOLERANCE) continue;
    const targetSize = p.size * (cap / p.risk);
    const reduceBy = p.size - targetSize;
    const flat = targetSize * p.entry < MIN_NOTIONAL; // would leave dust → flatten
    actions.push({ coin: p.coin, reason: `per-trade ${p.riskPct.toFixed(1)}% > ${RISK_CAP_PCT}% cap`,
      from_risk: Math.round(p.risk * 100) / 100, to_risk: Math.round(cap * 100) / 100,
      action: flat ? flatten(p.coin, dry) : reduce(p.coin, reduceBy, dry) });
    p.risk = flat ? 0 : cap; // updated for the portfolio pass
  }

  // 3. Portfolio cap — if the book still risks too much, trim the largest first.
  let total = positions.reduce((s, p) => s + p.risk, 0);
  const order = [...positions].sort((a, b) => b.risk - a.risk);
  for (const p of order) {
    if (total <= portCap * TOLERANCE) break;
    if (!p.risk) continue;
    const cut = Math.min(p.risk, total - portCap);
    const reduceBy = p.size * (cut / p.risk);
    actions.push({ coin: p.coin, reason: `portfolio ${(total / eq * 100).toFixed(1)}% > ${PORTFOLIO_CAP_PCT}% cap`,
      action: reduce(p.coin, reduceBy, dry) });
    total -= cut;
  }

  return { ok: true, dry: !!dry, equity: Math.round(eq * 100) / 100,
    per_trade_cap_usd: Math.round(cap * 100) / 100, portfolio_cap_usd: Math.round(portCap * 100) / 100,
    book: positions.map((p) => ({ coin: p.coin, riskPct: Math.round(p.riskPct * 10) / 10 })),
    actions };
}

function main() {
  const cmd = process.argv[2] || 'check';
  // `cap` exposes the hard caps as JSON so other tools (forge.py sizing) size to the
  // SAME limits this guard enforces — one source of truth, no duplicated constant.
  if (cmd === 'cap') {
    process.stdout.write(JSON.stringify({ ok: true, risk_cap_pct: RISK_CAP_PCT,
      portfolio_cap_pct: PORTFOLIO_CAP_PCT, tolerance: TOLERANCE, min_notional: MIN_NOTIONAL }) + '\n');
    return;
  }
  const out = enforce(cmd !== 'run');
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

// Pure / file-only functions + the hard caps exported for unit testing;
// main() runs only as a CLI.
module.exports = {
  stopFor, assess, breakerCheck, pruneState, enforce, hl,
  RISK_CAP_PCT, PORTFOLIO_CAP_PCT, TOLERANCE, MIN_NOTIONAL,
};

if (require.main === module) {
  main();
}
