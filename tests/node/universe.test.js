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

  const univ = [
    { name: 'xyz:BRENTOIL' }, { name: 'xyz:NATGAS' }, { name: 'xyz:SILVER' }, { name: 'xyz:DUST' },
  ];
  const ctxs = [
    { dayNtlVlm: 34_000_000 }, // BRENTOIL — liquid
    { dayNtlVlm: 250_000 },    // NATGAS — below floor, dropped
    { dayNtlVlm: 13_000_000 }, // SILVER — liquid
    { dayNtlVlm: 0 },          // DUST — dropped
  ];

  test('prepends the majors and keeps only markets above the liquidity floor', () => {
    const u = pickLiquid(univ, ctxs);
    expect(u.slice(0, 3)).toEqual(['BTC', 'ETH', 'SOL']); // majors always first
    expect(u).toContain('xyz:BRENTOIL'); // Brent shows up automatically — the whole point
    expect(u).toContain('xyz:SILVER');
    expect(u).not.toContain('xyz:NATGAS'); // dust below the floor is skipped
    expect(u).not.toContain('xyz:DUST');
  });

  test('ranks by volume and respects the cap (no churning through everything)', () => {
    // cap 5 → majors(3) + top 2 by volume → BRENTOIL(34M) before SILVER(13M)
    expect(pickLiquid(univ, ctxs)).toEqual(['BTC', 'ETH', 'SOL', 'xyz:BRENTOIL', 'xyz:SILVER']);
  });

  test('a missing / malformed venue response yields null (caller falls back)', () => {
    expect(pickLiquid(null, null)).toBeNull();
    expect(pickLiquid([{ name: 'x' }], undefined)).toBeNull();
  });
});
