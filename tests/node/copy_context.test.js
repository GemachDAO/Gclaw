// Entry-context reconstruction (assune-2ol.11): makes the copy desk generative.
import { describe, test, expect } from 'vitest';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const cc = require('../../scripts/copy_context.js');

describe('dedupeOpens', () => {
  test('keeps opens only and dedupes partial fills by oid', () => {
    const fills = [
      { coin: 'BTC', time: 1, dir: 'Open Long', oid: 1 },
      { coin: 'BTC', time: 1, dir: 'Open Long', oid: 1 }, // partial of the same order
      { coin: 'ETH', time: 2, dir: 'Open Short', oid: 2 },
      { coin: 'BTC', time: 3, dir: 'Close Long', oid: 3 }, // a close — excluded
    ];
    const opens = cc.dedupeOpens(fills);
    expect(opens).toEqual([
      { coin: 'BTC', time: 1, long: true },
      { coin: 'ETH', time: 2, long: false },
    ]);
  });
});

describe('barAtTime', () => {
  const candles = [{ t: 10 }, { t: 20 }, { t: 30 }, { t: 40 }];
  test('finds the last bar at or before the target time', () => {
    expect(cc.barAtTime(candles, 25)).toBe(1);
    expect(cc.barAtTime(candles, 40)).toBe(3);
    expect(cc.barAtTime(candles, 5)).toBe(-1);
  });
});

describe('median / dominant', () => {
  test('median of odd/even and dominant category', () => {
    expect(cc.median([3, 1, 2])).toBe(2);
    expect(cc.median([1, 2, 3, 4])).toBe(2.5);
    expect(cc.dominant(['a', 'b', 'a', 'a', 'b'])).toBe('a');
  });
});

describe('reconstructEntry', () => {
  test('an uptrend window reads a positive ema_stack; too-short window is null', () => {
    const up = Array.from({ length: 130 }, (_, k) => ({ t: k, o: 100 + k, h: 101 + k, l: 99 + k, c: 100 + k }));
    const f = cc.reconstructEntry(up, 129);
    expect(f.ema_stack).toBe(2);
    expect(typeof f.regime).toBe('string');
    expect(cc.reconstructEntry(up, 5)).toBeNull();
  });
});

describe('aggregateContext', () => {
  test('summarises entry features per direction', () => {
    const enriched = [
      { long: true, f: { rsi: 40, efficiency: 0.2, bb_z: -1, regime: 'range' } },
      { long: true, f: { rsi: 44, efficiency: 0.3, bb_z: -0.8, regime: 'range' } },
      { long: false, f: { rsi: 60, efficiency: 0.5, bb_z: 1, regime: 'trend_up' } },
      { long: true, f: null },
    ];
    const c = cc.aggregateContext(enriched);
    expect(c.long).toMatchObject({ n: 2, dominant_regime: 'range' });
    expect(c.long.median_rsi).toBe(42);
    expect(c.short).toMatchObject({ n: 1, dominant_regime: 'trend_up' });
  });
});
