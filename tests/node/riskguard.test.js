// Safety-invariant tests for the deterministic risk guardrail (scripts/riskguard.js).
//
// riskguard.js is the LAST line of defence: the LLM bypasses the advisory sizing,
// so this trims every position over the per-trade (1.5%) or portfolio (4%) cap and
// flattens naked (stop-less) positions — every heartbeat, with hard-coded limits.
// It only ever REDUCES exposure, so it is safe to run unattended.
//
// HERMETICITY: enforce() reads live state by shelling out (child_process.execFileSync
// -> `node hl_perp.js status`). We MUST NOT let that hit the network. riskguard
// destructures `execFileSync` at load time, so we stub it on the shared CJS
// child_process module BEFORE (re)loading the script — then the script captures the
// stub, never the real subprocess. In dry mode enforce() returns the full action plan
// WITHOUT placing orders, so we replay the plan against the synthetic book and assert
// residual risk never exceeds the caps — for ANY status, including hostile ones.

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const os = require('node:os');
const fs = require('node:fs');
const cp = require('node:child_process');

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RG_PATH = path.resolve(HERE, '..', '..', 'scripts', 'riskguard.js');

let tmpHome;
let realExec;
let realEnv;

// Stub child_process.execFileSync, THEN load riskguard so its top-level
// `const { execFileSync } = require('node:child_process')` captures the stub.
// `respond(args)` decides each shelled call's stdout (status reads vs close orders).
function loadWith(respond) {
  cp.execFileSync = (_bin, args) => respond(Array.isArray(args) ? args : []);
  delete require.cache[RG_PATH];
  return require(RG_PATH);
}

// The default responder: return `status` for a status read, a no-op for any close.
function statusResponder(status) {
  return (args) => {
    if (args.includes('status')) return JSON.stringify(status);
    return JSON.stringify({ ok: true }); // a close() — must never fire in dry mode
  };
}

beforeEach(() => {
  realEnv = process.env.GCLAW_HOME;
  realExec = cp.execFileSync;
  tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-rg-'));
  process.env.GCLAW_HOME = tmpHome;
});

afterEach(() => {
  cp.execFileSync = realExec;
  delete require.cache[RG_PATH];
  if (realEnv === undefined) delete process.env.GCLAW_HOME;
  else process.env.GCLAW_HOME = realEnv;
  fs.rmSync(tmpHome, { recursive: true, force: true });
});

// Build a status payload. `stops` maps coin -> stop price (omit for a naked position).
function makeStatus(equity, positions, stops = {}) {
  const openOrders = [];
  for (const p of positions) {
    const stop = stops[p.coin];
    if (stop !== undefined) openOrders.push({ coin: p.coin, px: String(stop), reduceOnly: true });
  }
  return { ok: true, equity, positions, openOrders };
}

// Replay a dry-run plan onto the book; recompute each position's residual risk the
// way assess() defines it: |entry - stop| * remainingSize (naked = whole notional).
function residualRisk(status, plan) {
  const stopOf = {};
  for (const o of status.openOrders) if (o.reduceOnly) stopOf[o.coin] = Number(o.px);
  const reducedBy = {};
  const flattened = new Set();
  for (const act of plan.actions) {
    const a = act.action || {};
    if (a.wouldFlatten) flattened.add(act.coin);
    if (typeof a.wouldReduce === 'number') reducedBy[act.coin] = (reducedBy[act.coin] || 0) + a.wouldReduce;
  }
  const out = [];
  for (const p of status.positions) {
    if (flattened.has(p.coin)) continue;
    const size0 = Math.abs(Number(p.size));
    const entry = Number(p.entryPx);
    const remaining = Math.max(0, size0 - (reducedBy[p.coin] || 0));
    const stop = stopOf[p.coin];
    const risk = stop === undefined ? remaining * entry : Math.abs(entry - stop) * remaining;
    out.push({ coin: p.coin, risk });
  }
  return out;
}

describe('per-trade cap', () => {
  test('a position risking 50% of equity is trimmed to the 1.5% cap', () => {
    const status = makeStatus(1000, [{ coin: 'BTC', size: '0.5', entryPx: '60000' }], { BTC: 59000 });
    const rg = loadWith(statusResponder(status));
    const plan = rg.enforce(true);
    const cap = 1000 * (rg.RISK_CAP_PCT / 100);
    for (const { risk } of residualRisk(status, plan)) {
      expect(risk).toBeLessThanOrEqual(cap * rg.TOLERANCE + 1e-6);
    }
  });

  // Property-style: over a grid of equities, sizes, and stop distances, no residual
  // per-trade risk may exceed the cap (within the anti-churn tolerance).
  const equities = [50, 137, 1000, 25000];
  const sizeMults = [0.01, 0.1, 1, 25];
  const stopDistPct = [0.5, 2, 9, 40];
  for (const eq of equities) {
    for (const sm of sizeMults) {
      for (const sd of stopDistPct) {
        test(`eq=${eq} sizeMult=${sm} stopDist=${sd}% stays under per-trade cap`, () => {
          const entry = 100;
          const size = (eq * sm) / entry; // notional ~ eq*sm
          const stop = entry * (1 - sd / 100); // long stop below entry
          const status = makeStatus(eq, [{ coin: 'ETH', size: String(size), entryPx: String(entry) }], { ETH: stop });
          const rg = loadWith(statusResponder(status));
          const plan = rg.enforce(true);
          const cap = eq * (rg.RISK_CAP_PCT / 100);
          for (const { risk } of residualRisk(status, plan)) {
            expect(risk).toBeLessThanOrEqual(cap * rg.TOLERANCE + 1e-6);
          }
        });
      }
    }
  }
});

describe('portfolio cap', () => {
  test('a book of three over-cap positions nets under the 4% portfolio cap', () => {
    const status = makeStatus(10000, [
      { coin: 'BTC', size: '1', entryPx: '1000' },
      { coin: 'ETH', size: '5', entryPx: '1000' },
      { coin: 'SOL', size: '10', entryPx: '1000' },
    ], { BTC: 950, ETH: 950, SOL: 950 });
    const rg = loadWith(statusResponder(status));
    const plan = rg.enforce(true);
    const portCap = 10000 * (rg.PORTFOLIO_CAP_PCT / 100);
    const total = residualRisk(status, plan).reduce((s, x) => s + x.risk, 0);
    expect(total).toBeLessThanOrEqual(portCap * rg.TOLERANCE + 1e-6);
  });
});

describe('naked positions', () => {
  test('a position with no protective stop is flattened, never trimmed', () => {
    const status = makeStatus(1000, [{ coin: 'BTC', size: '0.001', entryPx: '60000' }], {});
    const rg = loadWith(statusResponder(status));
    const plan = rg.enforce(true);
    const nakedAction = plan.actions.find((a) => a.coin === 'BTC');
    expect(nakedAction).toBeTruthy();
    expect(nakedAction.reason).toMatch(/NAKED/);
    expect(nakedAction.action.wouldFlatten).toBe(true);
  });

  test('assess() marks a stop-less position naked with whole-notional risk', () => {
    const status = makeStatus(1000, [{ coin: 'BTC', size: '0.5', entryPx: '60000' }], {});
    const rg = loadWith(statusResponder(status));
    const [p] = rg.assess(status);
    expect(p.naked).toBe(true);
    expect(p.risk).toBeCloseTo(0.5 * 60000, 6);
  });
});

describe('drawdown breaker', () => {
  test('a 30% drawdown trips the breaker and flattens every position', () => {
    const status = makeStatus(700, [
      { coin: 'BTC', size: '0.5', entryPx: '60000' },
      { coin: 'ETH', size: '5', entryPx: '3000' },
    ], { BTC: 59000, ETH: 2900 });
    const rg = loadWith(statusResponder(status));
    fs.writeFileSync(path.join(tmpHome, 'breaker.json'), JSON.stringify({ hwm: 1000 }));
    const plan = rg.enforce(true);
    expect(plan.breaker_tripped).toBe(true);
    const flattenedCoins = plan.actions.filter((a) => a.action.wouldFlatten).map((a) => a.coin);
    expect(new Set(flattenedCoins)).toEqual(new Set(['BTC', 'ETH']));
  });

  test('breakerCheck never trips on a shallow (<25%) drawdown', () => {
    const rg = loadWith(statusResponder(makeStatus(800, [])));
    fs.writeFileSync(path.join(tmpHome, 'breaker.json'), JSON.stringify({ hwm: 1000 }));
    const { tripped } = rg.breakerCheck(800, [], true); // 20% drawdown
    expect(tripped).toBe(false);
  });

  // REGRESSION: the breaker must not trip on equity <= 0. enforce() aborts on a zero
  // equity read BEFORE breakerCheck, and breakerCheck's hwm>0 guard means a 0-equity
  // hwm yields drawdown 0. A spurious trip would flatten a healthy book on a bad read.
  test('breakerCheck does not trip when equity is 0 and there is no prior hwm', () => {
    const rg = loadWith(statusResponder(makeStatus(0, [])));
    const { tripped, drawdown } = rg.breakerCheck(0, [], true);
    expect(tripped).toBe(false);
    expect(drawdown).toBe(0);
  });

  // REGRESSION: a single transient high equity read (e.g. a double-counted balance)
  // must NOT poison the high-water mark and trip a false drawdown halt next read —
  // the un-capped Math.max here used to re-poison what forge.py's 20%-cap corrected,
  // and a tripped breaker FLATTENS the whole book. Each read may raise the hwm <=20%.
  test('a transient 2x equity spike cannot poison the hwm into a false flatten', () => {
    const rg = loadWith(statusResponder(makeStatus(200, [])));
    fs.writeFileSync(path.join(tmpHome, 'breaker.json'), JSON.stringify({ hwm: 200 }));
    // a phantom $404 read arrives (real equity is $200) — persist it (dry=false)
    const spike = rg.breakerCheck(404, [], false);
    expect(spike.hwm).toBeCloseTo(240, 5);   // capped to +20%, NOT 404
    // the real $200 read returns next cycle: drawdown from 240 is 16.7% < 25% → safe
    const real = rg.breakerCheck(200, [], true);
    expect(real.tripped).toBe(false);
    // contrast: an un-capped hwm of 404 would read 50% drawdown and flatten everything
  });
});

describe('fail-safe reads', () => {
  test('an unavailable status read skips enforcement instead of crashing', () => {
    const rg = loadWith(() => { throw new Error('SDK timeout'); }); // hl() catches -> null
    const out = rg.enforce(true);
    expect(out.ok).toBe(true);
    expect(out.skipped).toMatch(/status read unavailable/);
  });

  test('a malformed (non-JSON) status read skips enforcement', () => {
    const rg = loadWith(() => '<!DOCTYPE html> 503 from the edge'); // JSON.parse throws -> null
    const out = rg.enforce(true);
    expect(out.ok).toBe(true);
    expect(out.skipped).toMatch(/status read unavailable/);
  });

  test('a zero-equity read aborts enforcement (no divide-by-zero trims)', () => {
    const status = makeStatus(0, [{ coin: 'BTC', size: '0.5', entryPx: '60000' }], { BTC: 59000 });
    const rg = loadWith(statusResponder(status));
    const out = rg.enforce(true);
    expect(out.ok).toBe(false);
    expect(out.error).toMatch(/no equity/);
  });

  test('guardrail only ever reduces — no action opens or adds size', () => {
    const status = makeStatus(1000, [{ coin: 'BTC', size: '0.5', entryPx: '60000' }], { BTC: 59000 });
    const rg = loadWith(statusResponder(status));
    const plan = rg.enforce(true);
    for (const a of plan.actions) {
      const verbs = Object.keys(a.action);
      expect(verbs.some((v) => v === 'wouldReduce' || v === 'wouldFlatten' || v === 'coin')).toBe(true);
      expect(verbs).not.toContain('wouldOpen');
      expect(verbs).not.toContain('wouldAdd');
    }
  });
});
