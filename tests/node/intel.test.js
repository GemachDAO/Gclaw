// Exemplar: a pure-logic node unit test for the intel.js indicator engine.
//
// The test file is ESM (vitest 4 requires it); it loads the CommonJS intel.js via
// the createRequire-based helper. The script must have the `require.main === module`
// guard + `module.exports` added (see helpers.js PATTERN). We test the *behavior*
// of the indicators and the regime classifier against hand-built series, with NO
// network — pure functions don't fetch, so no mock is needed here.

import { describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';

const intel = loadScript('intel.js');

describe('rsi', () => {
  test('returns the neutral 50 when there is not enough data', () => {
    expect(intel.rsi([1, 2, 3], 14)).toBe(50);
  });

  test('is 100 on a monotonic climb (no down moves)', () => {
    const climbing = Array.from({ length: 30 }, (_, i) => 100 + i);
    expect(intel.rsi(climbing)).toBe(100);
  });

  test('reads oversold (<30) on a sustained decline', () => {
    const falling = Array.from({ length: 30 }, (_, i) => 100 - i);
    expect(intel.rsi(falling)).toBeLessThan(30);
  });
});

describe('atrPct', () => {
  test('is zero with too few candles to seed Wilder smoothing', () => {
    const few = Array.from({ length: 5 }, () => ({ h: 1, l: 1, c: 1 }));
    expect(intel.atrPct(few, 14)).toBe(0);
  });

  test('is positive and scaled to price for a volatile series', () => {
    const candles = Array.from({ length: 30 }, (_, i) => ({
      h: 102 + i,
      l: 98 + i,
      c: 100 + i,
    }));
    const atr = intel.atrPct(candles);
    expect(atr).toBeGreaterThan(0);
    expect(atr).toBeLessThan(20); // ~4-wide range on ~100 price => single-digit %
  });
});

describe('efficiencyRatio', () => {
  test('approaches 1 for a clean straight-line trend', () => {
    const line = Array.from({ length: 30 }, (_, i) => 100 + i);
    expect(intel.efficiencyRatio(line)).toBeCloseTo(1, 5);
  });

  test('approaches 0 for a perfect zig-zag (all path, no net move)', () => {
    const zigzag = Array.from({ length: 30 }, (_, i) => (i % 2 ? 101 : 100));
    expect(intel.efficiencyRatio(zigzag)).toBeLessThan(0.1);
  });
});

describe('classifyRegime', () => {
  // Table-driven: efficiency + ema_stack -> regime label. Thresholds are the
  // documented defaults (trend>=0.40, chop<0.18); the table is the spec.
  const cases = [
    { name: 'high efficiency, bullish stack -> trend_up', f: { efficiency: 0.6, ema_stack: 2 }, want: 'trend_up' },
    { name: 'high efficiency, bearish stack -> trend_down', f: { efficiency: 0.6, ema_stack: -2 }, want: 'trend_down' },
    { name: 'very low efficiency -> chop (sit out)', f: { efficiency: 0.1, ema_stack: 1 }, want: 'chop' },
    { name: 'middle efficiency -> range (mean-revert)', f: { efficiency: 0.3, ema_stack: 0 }, want: 'range' },
    // High efficiency but a CONFLICTING (zero) EMA stack is not a trend — calling it
    // trend_up biased the gate long on noise. It must read as range.
    { name: 'high efficiency, conflicting (0) stack -> range, not a fake trend', f: { efficiency: 0.4, ema_stack: 0 }, want: 'range' },
    { name: 'high efficiency, weak-but-clear bull stack (1) -> trend_up', f: { efficiency: 0.5, ema_stack: 1 }, want: 'trend_up' },
    { name: 'high efficiency, weak-but-clear bear stack (-1) -> trend_down', f: { efficiency: 0.5, ema_stack: -1 }, want: 'trend_down' },
  ];
  for (const { name, f, want } of cases) {
    test(name, () => {
      expect(intel.classifyRegime(f)).toBe(want);
    });
  }
});
