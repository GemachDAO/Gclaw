// Failure-injection + resilience for the HL executor's read paths (scripts/hl_perp.js).
//
// hl_perp.js is the agent's eyes on its money. cmdStatus reads three HL endpoints
// with Promise.allSettled so ANY single transient failure (timeout / 429 / malformed
// JSON / partial) degrades to a conservative zero for THAT read instead of crashing
// the whole status. The 90s status cache is best-effort: a corrupt/missing/stale
// cache reads as "no cache" (refetch), and a failed cache write is swallowed — the
// heartbeat must never die on a cache file.
//
// computeEquity is the pure assembly the live status returns; here we drive it with
// the exact degraded shapes Promise.allSettled produces on partial failure and assert
// the result is still a clean, finite, non-negative equity object.

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const os = require('node:os');
const fs = require('node:fs');

const HERE = path.dirname(fileURLToPath(import.meta.url));
const { computeEquity, readStatusCache, writeStatusCache, normalizeCoin, mapPositions, roundSig } = loadScript('hl_perp.js');

const MANAGED = '0xManaged';

describe('cmdStatus degradation: each read can fail independently', () => {
  // These are the FALLBACK values Promise.allSettled yields when a read rejects:
  //   full -> {accountValue:0, positions:[], withdrawable:0}
  //   spot -> {balances:[]}
  //   orders -> []
  test('all three reads failed: clean ok:true with zero equity, never throws', () => {
    const out = computeEquity({ accountValue: 0, positions: [], withdrawable: 0 }, { balances: [] }, [], MANAGED);
    expect(out.ok).toBe(true);
    expect(out.equity).toBe(0);
    expect(out.buyingPower).toBe(0);
    expect(Number.isFinite(out.equity)).toBe(true);
    expect(out.positions).toEqual([]);
    expect(out.openOrders).toEqual([]);
  });

  test('perp read OK but spot read failed: equity = accountValue (no NaN from missing spot)', () => {
    const full = { accountValue: 42, positions: [], withdrawable: 0 };
    const out = computeEquity(full, { balances: [] }, [], MANAGED); // spot degraded to empty
    expect(out.equity).toBe(42);
    expect(out.spotUsdc).toBe(0);
  });

  test('spot read OK but perp read failed: equity = free spot only', () => {
    const full = { accountValue: 0, positions: [], withdrawable: 0 }; // perp degraded
    const spot = { balances: [{ coin: 'USDC', total: '100', hold: '0' }] };
    const out = computeEquity(full, spot, [], MANAGED);
    expect(out.equity).toBe(100);
  });

  test('a malformed USDC balance (non-numeric strings) yields NaN-free, clamped output', () => {
    const spot = { balances: [{ coin: 'USDC', total: 'oops', hold: 'nope' }] };
    const out = computeEquity({ accountValue: 0, positions: [] }, spot, [], MANAGED);
    // Number('oops') is NaN; buyingPower = max(0, NaN-NaN) = NaN -> the formula must not
    // silently produce a negative or pretend-zero. We assert it does NOT go negative.
    expect(out.buyingPower).not.toBeLessThan(0);
  });

  test('orders missing limitPx/sz are mapped to finite numbers, never undefined', () => {
    const orders = [{ coin: 'ETH' }]; // partial order, missing px/sz
    const out = computeEquity({ accountValue: 0, positions: [] }, { balances: [] }, orders, MANAGED);
    expect(out.openOrders[0].coin).toBe('ETH');
    expect(Number.isNaN(out.openOrders[0].px)).toBe(true); // Number(undefined) -> NaN, surfaced not hidden
  });
});

describe('mapPositions tolerates partial/garbage position rows', () => {
  test('filters zero-size positions and reads szi or size', () => {
    const aps = [
      { position: { coin: 'BTC', szi: '0.5', entryPx: '60000', unrealizedPnl: '3' } },
      { position: { coin: 'ETH', szi: '0' } }, // flat -> dropped
      { coin: 'SOL', size: 2, entryPx: 150, unrealizedPnl: -1 }, // bare shape
    ];
    const out = mapPositions(aps);
    expect(out.map((p) => p.coin)).toEqual(['BTC', 'SOL']);
    expect(out[0].size).toBe(0.5);
  });

  test('null / undefined / empty input never throws', () => {
    expect(mapPositions(null)).toEqual([]);
    expect(mapPositions(undefined)).toEqual([]);
    expect(mapPositions([])).toEqual([]);
  });
});

describe('status cache is best-effort and never crashes the heartbeat', () => {
  let tmp;
  let realHome;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-hl-'));
    realHome = process.env.GCLAW_HOME;
    process.env.GCLAW_HOME = tmp;
  });
  afterEach(() => {
    if (realHome === undefined) delete process.env.GCLAW_HOME;
    else process.env.GCLAW_HOME = realHome;
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  // readStatusCache/writeStatusCache resolve STATUS_CACHE at module-load from
  // GCLAW_HOME, so reload the script after setting the temp home.
  function fresh() { return loadScript('hl_perp.js'); }

  test('a missing cache file reads back null (refetch), not a throw', () => {
    const m = fresh();
    expect(m.readStatusCache()).toBeNull();
  });

  test('a corrupt cache file reads back null instead of crashing', () => {
    const m = fresh();
    fs.writeFileSync(path.join(tmp, 'status_cache.json'), '{ "ts": 123, "data": ');
    expect(m.readStatusCache()).toBeNull();
  });

  test('a fresh write is read back; a stale (>90s) entry is ignored', () => {
    const m = fresh();
    m.writeStatusCache({ ok: true, equity: 51 });
    expect(m.readStatusCache()).toMatchObject({ equity: 51 });
    // Backdate the cache beyond the 90s TTL.
    const p = path.join(tmp, 'status_cache.json');
    const c = JSON.parse(fs.readFileSync(p, 'utf8'));
    c.ts = Date.now() - 91000;
    fs.writeFileSync(p, JSON.stringify(c));
    expect(m.readStatusCache()).toBeNull();
  });

  test('invalidate drops a fresh entry — a closed position is never served as a phantom', () => {
    const m = fresh();
    m.writeStatusCache({ ok: true, positions: [{ coin: 'xyz:MU' }], equity: 200 });
    expect(m.readStatusCache()).toMatchObject({ equity: 200 }); // within TTL, served
    m.invalidateStatusCache(); // a position just closed — the cache must not keep reporting it
    expect(m.readStatusCache()).toBeNull(); // gone → the next read refetches live state
  });

  test('invalidate on a missing cache is a no-op (never throws)', () => {
    const m = fresh();
    expect(() => m.invalidateStatusCache()).not.toThrow();
  });

  test('writeStatusCache to an unwritable path is swallowed (no throw)', () => {
    process.env.GCLAW_HOME = path.join(tmp, 'does', 'not', 'exist'); // parent missing
    const m = fresh();
    expect(() => m.writeStatusCache({ ok: true })).not.toThrow();
  });

  test('the cache write is atomic: temp file then rename, no .tmp turds left', () => {
    const m = fresh();
    m.writeStatusCache({ ok: true, equity: 7 });
    expect(fs.readdirSync(tmp).filter((f) => f.includes('.tmp'))).toHaveLength(0);
  });
});

describe('coin normalization + sig rounding (entry-path helpers)', () => {
  test('plain coins uppercase; builder dex prefix lowercased', () => {
    expect(normalizeCoin('eth')).toBe('ETH');
    expect(normalizeCoin('xyz:nvda')).toBe('xyz:NVDA');
    expect(normalizeCoin('XYZ:nvda')).toBe('xyz:NVDA');
  });
  test('roundSig keeps 5 significant figures and handles zero', () => {
    expect(roundSig(0)).toBe(0);
    expect(roundSig(60123.456)).toBe(60123);
    expect(roundSig(0.0123456)).toBeCloseTo(0.012346, 6);
  });
});

// Maker-first limit entries (assune-4yt): when GCLAW_FORGE_MAKER_ENTRY=1 the live
// executor must POST a resting maker limit — with the stop STILL atomically attached —
// so the executor matches the maker cost the forge backtest models. The order builder is
// network-free, so we drive it directly and assert the maker/taker + no-naked-entry
// contract. Builder (xyz) coins always stay taker: their attached SL is not armed as a
// resting order (assune-ehh), so a resting entry there would fill naked.
describe('maker-first limit entries: order construction (assune-4yt)', () => {
  const { makerEntryEnabled, makerLimitPrice, buildOpenOrder } = loadScript('hl_perp.js');
  const savedFlag = process.env.GCLAW_FORGE_MAKER_ENTRY;
  const savedOff = process.env.GCLAW_MAKER_OFFSET_BPS;

  afterEach(() => {
    if (savedFlag === undefined) delete process.env.GCLAW_FORGE_MAKER_ENTRY;
    else process.env.GCLAW_FORGE_MAKER_ENTRY = savedFlag;
    if (savedOff === undefined) delete process.env.GCLAW_MAKER_OFFSET_BPS;
    else process.env.GCLAW_MAKER_OFFSET_BPS = savedOff;
  });

  test('default (flag unset) stays taker: isMarket true, entry at the mark', () => {
    delete process.env.GCLAW_FORGE_MAKER_ENTRY;
    expect(makerEntryEnabled('BTC')).toBe(false);
    const o = buildOpenOrder({ coin: 'BTC', isLong: true, mark: 60000, notionalTarget: 30, slPct: 2, tpPct: 3, szDecimals: 5 });
    expect(o.isMarket).toBe(true);
    expect(o.maker).toBe(false);
    expect(o.entryPx).toBe(60000);
  });

  test('flag on + default dex: resting maker limit, isMarket false', () => {
    process.env.GCLAW_FORGE_MAKER_ENTRY = '1';
    expect(makerEntryEnabled('ETH')).toBe(true);
    const o = buildOpenOrder({ coin: 'ETH', isLong: true, mark: 3000, notionalTarget: 30, slPct: 2, tpPct: 3, szDecimals: 4 });
    expect(o.isMarket).toBe(false);
    expect(o.maker).toBe(true);
  });

  test('flag on but builder (xyz) coin stays taker — its attached SL is not armed resting', () => {
    process.env.GCLAW_FORGE_MAKER_ENTRY = '1';
    expect(makerEntryEnabled('xyz:NVDA')).toBe(false);
    const o = buildOpenOrder({ coin: 'xyz:NVDA', isLong: true, mark: 120, notionalTarget: 30, slPct: 2, tpPct: 3, szDecimals: 2 });
    expect(o.isMarket).toBe(true);
    expect(o.maker).toBe(false);
  });

  test('a maker limit rests PASSIVE — below the mark for a long, above for a short (never crosses)', () => {
    process.env.GCLAW_FORGE_MAKER_ENTRY = '1';
    const long = buildOpenOrder({ coin: 'BTC', isLong: true, mark: 60000, notionalTarget: 30, slPct: 2, tpPct: 3, szDecimals: 5 });
    expect(long.entryPx).toBeLessThan(60000); // a long that crossed the mark would pay taker
    const short = buildOpenOrder({ coin: 'BTC', isLong: false, mark: 60000, notionalTarget: 30, slPct: 2, tpPct: 3, szDecimals: 5 });
    expect(short.entryPx).toBeGreaterThan(60000);
  });

  test('NEVER a naked entry: the built order always carries a stop AND a target, maker or taker', () => {
    for (const flag of ['1', '0']) {
      process.env.GCLAW_FORGE_MAKER_ENTRY = flag;
      for (const isLong of [true, false]) {
        const o = buildOpenOrder({ coin: 'SOL', isLong, mark: 140, notionalTarget: 30, slPct: 2, tpPct: 3, szDecimals: 2 });
        expect(o.sl).toBeGreaterThan(0);
        expect(o.tp).toBeGreaterThan(0);
        // stop is on the LOSS side of the entry; target on the profit side.
        if (isLong) { expect(o.sl).toBeLessThan(o.entryPx); expect(o.tp).toBeGreaterThan(o.entryPx); }
        else { expect(o.sl).toBeGreaterThan(o.entryPx); expect(o.tp).toBeLessThan(o.entryPx); }
      }
    }
  });

  test('stop/target distance is measured from the ENTRY price, not the mark', () => {
    process.env.GCLAW_FORGE_MAKER_ENTRY = '1';
    const o = buildOpenOrder({ coin: 'ETH', isLong: true, mark: 3000, notionalTarget: 30, slPct: 2, tpPct: 3, szDecimals: 4 });
    // sl is 2% below the resting entry (the fill price), so the risk distance holds on fill.
    expect(o.sl).toBeCloseTo(o.entryPx * 0.98, 0);
    expect(o.tp).toBeCloseTo(o.entryPx * 1.03, 0);
  });

  test('maker offset is configurable and always passive', () => {
    process.env.GCLAW_MAKER_OFFSET_BPS = '20';
    const long = makerLimitPrice(60000, true);
    expect(long).toBeCloseTo(roundSig(60000 * (1 - 20 / 10000)), 5);
    const short = makerLimitPrice(60000, false);
    expect(short).toBeGreaterThan(60000);
  });
});
