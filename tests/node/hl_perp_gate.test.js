// Deterministic ENTRY GATE for the HL executor (scripts/hl_perp.js).
//
// The live trade record exposed two -EV leaks the model rationalized its way into:
//   1. counter-trend entries — 12/12 longs opened in trend_down lost (p < 0.001);
//   2. discretionary opens — gut trades with no proven, regime-matched basis (the
//      -7R "discretionary" cluster).
// cmdOpen is the single chokepoint every signed entry flows through, so entryGate()
// enforces both as code the model cannot skip. These tests pin the gate's verdicts and
// the on-disk loaders (proven pairs from style.json + proven_markets.json; live regime
// from intel.json) that feed it.

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const os = require('node:os');
const fs = require('node:fs');

const { entryGate, loadProvenPairs, liveRegime } = loadScript('hl_perp.js');

// A proven set with one adopted coin (SOL, blanket-trusted) and one auto-proven
// (technique, coin) pair (vol-momentum on xyz:MU).
const PROVEN = { coins: new Set(['SOL']), pairs: new Set(['vol-momentum|xyz:MU']) };

describe('entryGate #1 — trend alignment (never fade a trend)', () => {
  test('long in trend_down is refused (the proven -EV leak)', () => {
    const g = entryGate({ side: 'long', regime: 'trend_down', coin: 'SOL', basis: 'x', proven: PROVEN });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/counter-trend/);
  });

  test('short in trend_up is refused', () => {
    const g = entryGate({ side: 'short', regime: 'trend_up', coin: 'SOL', basis: 'x', proven: PROVEN });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/counter-trend/);
  });

  test('chop is refused outright (DNA invariant)', () => {
    const g = entryGate({ side: 'long', regime: 'chop', coin: 'SOL', basis: 'x', proven: PROVEN });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/chop/);
  });

  test('long WITH an uptrend passes (given a proven basis)', () => {
    expect(entryGate({ side: 'long', regime: 'trend_up', coin: 'SOL', basis: 'any', proven: PROVEN }).ok).toBe(true);
  });

  test('short WITH a downtrend passes (given a proven basis)', () => {
    expect(entryGate({ side: 'short', regime: 'trend_down', coin: 'SOL', basis: 'any', proven: PROVEN }).ok).toBe(true);
  });

  test('range allows either direction (no trend to fade)', () => {
    expect(entryGate({ side: 'long', regime: 'range', coin: 'SOL', basis: 'a', proven: PROVEN }).ok).toBe(true);
    expect(entryGate({ side: 'short', regime: 'range', coin: 'SOL', basis: 'a', proven: PROVEN }).ok).toBe(true);
  });

  test('unknown regime (null) cannot prove a violation, so #1 does not block', () => {
    // forge always supplies --regime; a missing intel snapshot must not wedge entries.
    expect(entryGate({ side: 'long', regime: null, coin: 'SOL', basis: 'a', proven: PROVEN }).ok).toBe(true);
  });
});

describe('entryGate #2 — discretionary block (require a proven, named basis)', () => {
  test('no basis is refused as discretionary', () => {
    const g = entryGate({ side: 'long', regime: 'range', coin: 'SOL', basis: '', proven: PROVEN });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/discretionary/);
  });

  test('undefined basis is refused as discretionary', () => {
    expect(entryGate({ side: 'long', regime: 'range', coin: 'SOL', proven: PROVEN }).ok).toBe(false);
  });

  test('a basis not proven for the coin is refused', () => {
    // vol-momentum is proven on xyz:MU, NOT on xyz:NVDA.
    const g = entryGate({ side: 'long', regime: 'range', coin: 'xyz:NVDA', basis: 'vol-momentum', proven: PROVEN });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/not proven/);
  });

  test('an adopted coin is blanket-trusted for any basis', () => {
    // SOL is an adopted coin → any basis may trade it (mirrors forge proven-coins).
    expect(entryGate({ side: 'long', regime: 'range', coin: 'SOL', basis: 'whatever', proven: PROVEN }).ok).toBe(true);
  });

  test('an auto-proven (technique, coin) pair passes', () => {
    expect(entryGate({ side: 'long', regime: 'range', coin: 'xyz:MU', basis: 'vol-momentum', proven: PROVEN }).ok).toBe(true);
  });

  test('coin casing is normalized before the proven check', () => {
    expect(entryGate({ side: 'long', regime: 'range', coin: 'xyz:mu', basis: 'vol-momentum', proven: PROVEN }).ok).toBe(true);
  });
});

describe('loadProvenPairs + liveRegime read the forge/intel state from disk', () => {
  let tmp;
  let realHome;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-gate-'));
    realHome = process.env.GCLAW_HOME;
    process.env.GCLAW_HOME = tmp;
    fs.mkdirSync(path.join(tmp, 'forge'), { recursive: true });
  });
  afterEach(() => {
    if (realHome === undefined) delete process.env.GCLAW_HOME;
    else process.env.GCLAW_HOME = realHome;
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  test('adopted coins and proven_markets pairs both load', () => {
    fs.writeFileSync(path.join(tmp, 'forge', 'style.json'),
      JSON.stringify({ adopted: [{ id: 'stop-hunt-revert', coin: 'SOL' }, { id: 'funding-fade', coin: 'BTC' }] }));
    fs.writeFileSync(path.join(tmp, 'forge', 'proven_markets.json'),
      JSON.stringify({ pairs: [{ technique: 'vol-momentum', coin: 'xyz:MU' }] }));
    const p = loadProvenPairs(tmp);
    expect(p.coins.has('SOL')).toBe(true);
    expect(p.coins.has('BTC')).toBe(true);
    expect(p.pairs.has('stop-hunt-revert|SOL')).toBe(true); // native pair from style
    expect(p.pairs.has('vol-momentum|xyz:MU')).toBe(true); // auto-proven pair
  });

  test('missing forge state reads as an empty proven set, never throws', () => {
    const p = loadProvenPairs(tmp);
    expect(p.coins.size).toBe(0);
    expect(p.pairs.size).toBe(0);
  });

  test('liveRegime reads a coin regime from intel.json', () => {
    fs.writeFileSync(path.join(tmp, 'intel.json'),
      JSON.stringify({ intel: { SOL: { regime: 'trend_down' }, 'xyz:MU': { regime: 'range' } } }));
    expect(liveRegime('SOL', tmp)).toBe('trend_down');
    expect(liveRegime('xyz:mu', tmp)).toBe('range'); // normalized lookup
  });

  test('liveRegime returns null on missing/corrupt intel (gate then leans on --regime)', () => {
    expect(liveRegime('SOL', tmp)).toBeNull();
    fs.writeFileSync(path.join(tmp, 'intel.json'), '{ broken');
    expect(liveRegime('SOL', tmp)).toBeNull();
  });

  test('end to end: a proven coin in trend_down still blocks a long', () => {
    // The integration the audit demands: SOL proven + adopted, but a long in its live
    // downtrend is refused — provenness does NOT override trend alignment.
    fs.writeFileSync(path.join(tmp, 'forge', 'style.json'),
      JSON.stringify({ adopted: [{ id: 'stop-hunt-revert', coin: 'SOL' }] }));
    fs.writeFileSync(path.join(tmp, 'intel.json'),
      JSON.stringify({ intel: { SOL: { regime: 'trend_down' } } }));
    const g = entryGate({
      side: 'long', regime: liveRegime('SOL', tmp), coin: 'SOL',
      basis: 'stop-hunt-revert', proven: loadProvenPairs(tmp),
    });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/counter-trend/);
  });
});
