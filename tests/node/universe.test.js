// Dynamic universe discovery (scripts/intel.js pickLiquid): the agent must build its
// tradeable universe FROM the venue, liquidity-filtered, instead of a hand-kept list —
// otherwise a real market (e.g. Brent oil) is invisible just because nobody added it.
// pickLiquid keeps the majors, drops dust below the floor, and caps the scan breadth.

import { beforeEach, describe, expect, test } from 'vitest';

describe('pickLiquid — majors + liquid markets, dust dropped, breadth capped', () => {
  let pickLiquid;
  beforeEach(async () => {
    process.env.GCLAW_LIQ_FLOOR = '1000000'; // $1M daily notional floor
    process.env.GCLAW_UNIVERSE_CAP = '5';    // 3 majors + top 2 liquid
    const { loadScript } = await import('./helpers.js');
    ({ pickLiquid } = loadScript('intel.js')); // re-read so env-driven consts apply
  });

  // impactPxs = [bid, ask] impact prices; spread = (ask-bid)/mid must be <= 10bp (SPREAD_CAP).
  const univ = [
    { name: 'xyz:BRENTOIL' }, { name: 'xyz:NATGAS' }, { name: 'xyz:SILVER' },
    { name: 'xyz:DUST' }, { name: 'xyz:WIDE' }, { name: 'HYPE' },
  ];
  const ctxs = [
    { dayNtlVlm: 34_000_000, midPx: 80, impactPxs: ['79.99', '80.01'] },   // BRENTOIL — liquid, ~2.5bp
    { dayNtlVlm: 250_000, midPx: 3, impactPxs: ['2.999', '3.001'] },       // NATGAS — below floor, dropped
    { dayNtlVlm: 13_000_000, midPx: 30, impactPxs: ['29.998', '30.002'] }, // SILVER — liquid, ~1.3bp
    { dayNtlVlm: 0, midPx: 1, impactPxs: ['1', '1'] },                     // DUST — below floor, dropped
    { dayNtlVlm: 99_000_000, midPx: 10, impactPxs: ['9.95', '10.05'] },    // WIDE — huge vol but 100bp spread
    { dayNtlVlm: 40_000_000, midPx: 72, impactPxs: ['71.99', '72.01'] },   // HYPE — liquid native crypto alt
  ];

  test('keeps liquid + tight markets above the floor, drops dust and wide spreads', () => {
    const u = pickLiquid(univ, ctxs);
    expect(u.slice(0, 3)).toEqual(['BTC', 'ETH', 'SOL']); // majors always first
    expect(u).toContain('xyz:BRENTOIL');
    expect(u).toContain('HYPE'); // native crypto alt admitted alongside stocks
    expect(u).not.toContain('xyz:NATGAS'); // below the liquidity floor
    expect(u).not.toContain('xyz:DUST');
    expect(u).not.toContain('xyz:WIDE'); // 100bp spread rejected despite the highest volume
  });

  test('ranks by volume under the cap; the widest-spread name never wins a slot', () => {
    // cap 5 → majors(3) + top 2 by volume among tight books: HYPE(40M), BRENTOIL(34M).
    // WIDE(99M) is highest volume but excluded on spread, so it never takes a slot.
    expect(pickLiquid(univ, ctxs)).toEqual(['BTC', 'ETH', 'SOL', 'HYPE', 'xyz:BRENTOIL']);
  });

  test('never duplicates a major that also appears in the discovered universe', () => {
    const withBtc = [{ name: 'BTC' }, { name: 'HYPE' }];
    const c = [
      { dayNtlVlm: 9e9, midPx: 60000, impactPxs: ['59999', '60001'] },
      { dayNtlVlm: 40_000_000, midPx: 72, impactPxs: ['71.99', '72.01'] },
    ];
    const u = pickLiquid(withBtc, c);
    expect(u.filter((x) => x === 'BTC')).toHaveLength(1); // BTC from MAJORS only, not re-added
  });

  test('a missing / malformed venue response yields null (caller falls back)', () => {
    expect(pickLiquid(null, null)).toBeNull();
    expect(pickLiquid([{ name: 'x' }], undefined)).toBeNull();
  });
});
