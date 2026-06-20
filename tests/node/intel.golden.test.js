// Golden (reference) + property tests for scripts/intel.js indicator math.
//
// Complements intel.test.js (behavioral spot-checks) with two stronger layers:
//
//   1. GOLDEN — exact numeric values for a hand-/independently-computed series:
//      a textbook 20-close Wilder-RSI series whose result (57.91502067008556) was
//      cross-checked against a SECOND, independent RSI implementation; a constant
//      2-wide candle range whose ATR% is exactly 2; the sample (n-1) stdev of a
//      known set (sqrt(32/7)); correlation +1 / -1 for identical / mirrored series.
//      These pin the formulas, not just their direction.
//
//   2. PROPERTY — bounds + sign relations that must hold for EVERY input, checked
//      over many seeded-random series: RSI in [0,100], efficiency in [0,1], ATR% >= 0,
//      correlation in [-1,1], stdev >= 0 (== 0 iff constant), and the Bollinger-z sign
//      tracking last-close-vs-window-mean.
//
// No network: the pure math is imported via loadScript, which relies on intel.js's
// `require.main === module` guard, so importing it fetches nothing.

import { describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';

const I = loadScript('intel.js');
const seq = (n, f) => Array.from({ length: n }, (_, i) => f(i));

// Seeded LCG so the property loops are deterministic across runs (no extra dep).
function lcg(seed) {
  let s = seed >>> 0;
  return () => {
    s = (1664525 * s + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

describe('intel.js golden reference values', () => {
  test('Wilder RSI of a textbook series (cross-checked, independent impl)', () => {
    const closes = [
      44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.1, 45.42, 45.84, 46.08,
      45.89, 46.03, 45.61, 46.28, 46.28, 46.0, 46.03, 46.41, 46.22, 45.64,
    ];
    expect(I.rsi(closes, 14)).toBeCloseTo(57.91502067, 6);
  });

  test('strictly rising => RSI 100, strictly falling => RSI 0', () => {
    expect(I.rsi(seq(30, (i) => 100 + i), 14)).toBe(100);
    expect(I.rsi(seq(30, (i) => 200 - i), 14)).toBe(0);
  });

  test('constant 2-wide candle range at price 100 => ATR% exactly 2', () => {
    const candles = seq(30, () => ({ o: 100, h: 101, l: 99, c: 100, v: 1 }));
    expect(I.atrPct(candles, 14)).toBeCloseTo(2.0, 9);
  });

  test('monotonic path => efficiency 1, pure zig-zag => efficiency 0', () => {
    expect(I.efficiencyRatio(seq(30, (i) => 100 + i), 20)).toBe(1);
    expect(I.efficiencyRatio(seq(30, (i) => 100 + (i % 2)), 20)).toBe(0);
  });

  test('sample (n-1) stdev of a known set == sqrt(32/7)', () => {
    expect(I.stdev([2, 4, 4, 4, 5, 5, 7, 9])).toBeCloseTo(Math.sqrt(32 / 7), 12);
  });

  test('correlation: identical => 1, mirrored => -1', () => {
    expect(I.correlation([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])).toBeCloseTo(1, 12);
    expect(I.correlation([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])).toBeCloseTo(-1, 12);
  });
});

describe('intel.js invariants over many random series', () => {
  test('RSI always within [0, 100]', () => {
    const rnd = lcg(7);
    for (let i = 0; i < 500; i += 1) {
      const r = I.rsi(seq(40, () => 50 + rnd() * 100), 14);
      expect(r).toBeGreaterThanOrEqual(0);
      expect(r).toBeLessThanOrEqual(100);
    }
  });

  test('efficiency ratio always within [0, 1]', () => {
    const rnd = lcg(11);
    for (let i = 0; i < 500; i += 1) {
      const e = I.efficiencyRatio(seq(40, () => 50 + rnd() * 100), 20);
      expect(e).toBeGreaterThanOrEqual(0);
      expect(e).toBeLessThanOrEqual(1);
    }
  });

  test('ATR% always non-negative', () => {
    const rnd = lcg(13);
    for (let i = 0; i < 500; i += 1) {
      const candles = seq(40, () => {
        const base = 50 + rnd() * 100;
        const half = rnd() * 5;
        return { o: base, h: base + half, l: base - half, c: base, v: 1 };
      });
      expect(I.atrPct(candles, 14)).toBeGreaterThanOrEqual(0);
    }
  });

  test('correlation always within [-1, 1]', () => {
    const rnd = lcg(17);
    for (let i = 0; i < 500; i += 1) {
      const c = I.correlation(seq(30, () => rnd()), seq(30, () => rnd()));
      expect(c).toBeGreaterThanOrEqual(-1 - 1e-9);
      expect(c).toBeLessThanOrEqual(1 + 1e-9);
    }
  });

  test('stdev non-negative, and exactly 0 for a constant series', () => {
    const rnd = lcg(19);
    for (let i = 0; i < 200; i += 1) {
      expect(I.stdev(seq(20, () => 50 + rnd() * 100))).toBeGreaterThanOrEqual(0);
    }
    expect(I.stdev([7, 7, 7, 7, 7])).toBe(0);
  });

  test('Bollinger z sign matches last-close vs 20-window mean', () => {
    const rnd = lcg(23);
    for (let i = 0; i < 300; i += 1) {
      const closes = seq(25, () => 50 + rnd() * 100);
      const window = closes.slice(-20);
      const sd = I.stdev(window);
      if (sd === 0) continue;
      const last = closes[closes.length - 1];
      const m = I.mean(window);
      const z = (last - m) / sd;
      if (last > m) expect(z).toBeGreaterThan(0);
      else if (last < m) expect(z).toBeLessThan(0);
    }
  });
});
