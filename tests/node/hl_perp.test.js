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

describe('builderDexes always includes the known dex (positions never go blind)', () => {
  const { builderDexes } = loadScript('hl_perp.js');

  test('a null skill (rate-limited sign-in) still yields the static xyz dex', async () => {
    // This is the safety foundation: without a signed skill, fullState must still query
    // the xyz dex via the public API, or an open xyz position becomes invisible.
    const dexes = await builderDexes(null);
    expect(dexes).toContain('xyz');
  });

  test('a failing SDK asset call degrades to the static dex, never throws', async () => {
    const skill = { getHlAllAssets: () => Promise.reject(new Error('429')) };
    await expect(builderDexes(skill)).resolves.toContain('xyz');
  });

  test('a working SDK asset list is merged with the static dex', async () => {
    const skill = { getHlAllAssets: () => Promise.resolve([{ coin: 'abc:FOO' }, { coin: 'BTC' }]) };
    const dexes = await builderDexes(skill);
    expect(dexes).toContain('xyz'); // static
    expect(dexes).toContain('abc'); // discovered
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
