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

const { entryGate, loadProvenSurface, liveRegime } = loadScript('hl_perp.js');

// A proven surface: adopted coin SOL (technique stop-hunt-revert), and xyz:MU
// auto-proven via vol-momentum. coins = tradeable surface; techniques = known basis ids.
const PROVEN = {
  coins: new Set(['SOL', 'xyz:MU']),
  techniques: new Set(['stop-hunt-revert', 'vol-momentum']),
};

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
    expect(entryGate({ side: 'long', regime: 'trend_up', coin: 'SOL', basis: 'stop-hunt-revert', proven: PROVEN }).ok).toBe(true);
  });

  test('short WITH a downtrend passes (given a proven basis)', () => {
    expect(entryGate({ side: 'short', regime: 'trend_down', coin: 'SOL', basis: 'stop-hunt-revert', proven: PROVEN }).ok).toBe(true);
  });

  test('range allows either direction (no trend to fade)', () => {
    expect(entryGate({ side: 'long', regime: 'range', coin: 'SOL', basis: 'stop-hunt-revert', proven: PROVEN }).ok).toBe(true);
    expect(entryGate({ side: 'short', regime: 'range', coin: 'SOL', basis: 'stop-hunt-revert', proven: PROVEN }).ok).toBe(true);
  });

  test('unknown regime (null) cannot prove a violation, so #1 does not block', () => {
    // forge always supplies --regime; a missing intel snapshot must not wedge entries.
    expect(entryGate({ side: 'long', regime: null, coin: 'SOL', basis: 'stop-hunt-revert', proven: PROVEN }).ok).toBe(true);
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

  test('a junk basis (not a known technique) is refused even on a surface coin', () => {
    // The discretionary leak was un-vetted gut trades — a made-up basis is rejected.
    const g = entryGate({ side: 'long', regime: 'range', coin: 'SOL', basis: 'whatever', proven: PROVEN });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/not a known technique/);
  });

  test('a coin outside the proven surface is refused', () => {
    // xyz:NVDA is not adopted and not auto-proven → no proof we can trade it.
    const g = entryGate({ side: 'long', regime: 'range', coin: 'xyz:NVDA', basis: 'vol-momentum', proven: PROVEN });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/proven surface/);
  });

  test('a known basis on an adopted coin passes', () => {
    expect(entryGate({ side: 'long', regime: 'range', coin: 'SOL', basis: 'stop-hunt-revert', proven: PROVEN }).ok).toBe(true);
  });

  test('a known basis on an auto-proven coin passes (any-contributor, mirrors forge)', () => {
    // The audit fix: the basis need not be THE technique proven on the coin — forge can
    // execute a dominant technique on a coin proven via a weaker contributor. Coin-level
    // surface membership is what counts, so this is not false-blocked.
    expect(entryGate({ side: 'long', regime: 'range', coin: 'xyz:MU', basis: 'stop-hunt-revert', proven: PROVEN }).ok).toBe(true);
    expect(entryGate({ side: 'long', regime: 'range', coin: 'xyz:MU', basis: 'vol-momentum', proven: PROVEN }).ok).toBe(true);
  });

  test('coin casing is normalized before the proven check', () => {
    expect(entryGate({ side: 'long', regime: 'range', coin: 'xyz:mu', basis: 'vol-momentum', proven: PROVEN }).ok).toBe(true);
  });
});

describe('loadProvenSurface + liveRegime read the forge/intel state from disk', () => {
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

  test('adopted coins + proven_markets coins and all technique ids load', () => {
    fs.writeFileSync(path.join(tmp, 'forge', 'style.json'),
      JSON.stringify({ adopted: [{ id: 'stop-hunt-revert', coin: 'SOL' }, { id: 'funding-fade', coin: 'BTC' }] }));
    fs.writeFileSync(path.join(tmp, 'forge', 'proven_markets.json'),
      JSON.stringify({ pairs: [{ technique: 'vol-momentum', coin: 'xyz:MU' }] }));
    const p = loadProvenSurface(tmp);
    expect(p.coins.has('SOL')).toBe(true);
    expect(p.coins.has('BTC')).toBe(true);
    expect(p.coins.has('xyz:MU')).toBe(true); // auto-proven coin joins the surface
    expect(p.techniques.has('stop-hunt-revert')).toBe(true);
    expect(p.techniques.has('funding-fade')).toBe(true);
    expect(p.techniques.has('vol-momentum')).toBe(true); // known basis from proven_markets
  });

  test('missing forge state reads as an empty surface, never throws', () => {
    const p = loadProvenSurface(tmp);
    expect(p.coins.size).toBe(0);
    expect(p.techniques.size).toBe(0);
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
      basis: 'stop-hunt-revert', proven: loadProvenSurface(tmp),
    });
    expect(g.ok).toBe(false);
    expect(g.reason).toMatch(/counter-trend/);
  });
});
