// Manager-decision tests for the Book B carry floor (scripts/carry.js).
//
// carry.js is a DETERMINISTIC, delta-neutral funding harvester with NO LLM. The
// guarantees these tests pin (the whole point of the script):
//   - opens ONLY when the best major's annualized funding >= OPEN_APY,
//   - closes when its funding <= CLOSE_APY or has flipped negative,
//   - holds otherwise, ONE carry at a time (never opens a 2nd while one is open),
//   - never sizes above NOTIONAL (the hard cap), and refuses sub-$11-min legs,
//   - writes the riskguard exemption on open and removes it on close,
//   - places NO real order in dry-run (the default — GCLAW_CARRY_LIVE unset).
//
// The decision logic (`decide`) and sizing (`sizeLegs`) are pure, so they need no
// mock. The dry-run no-order guarantee is exercised through `doOpen`/`doClose`
// with GCLAW_CARRY_LIVE unset: those paths must touch neither the network/SDK nor
// the filesystem. We point GCLAW_HOME at a tmp dir so exemption writes are isolated.

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const CARRY_PATH = path.resolve(HERE, '..', '..', 'scripts', 'carry.js');

// Each test gets a fresh GCLAW_HOME so exemption/state files don't leak between
// tests, and a fresh module load so the env-derived tunables are re-read.
let tmpHome;
let carry;

function loadCarry() {
  delete require.cache[CARRY_PATH];
  return require(CARRY_PATH);
}

beforeEach(() => {
  tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-carry-'));
  process.env.GCLAW_HOME = tmpHome;
  delete process.env.GCLAW_CARRY_LIVE; // DRY-RUN is the default
  delete process.env.GCLAW_CARRY_OPEN_APY;
  delete process.env.GCLAW_CARRY_CLOSE_APY;
  delete process.env.GCLAW_CARRY_NOTIONAL;
  delete process.env.GCLAW_CARRY_LEVERAGE;
  carry = loadCarry();
});

afterEach(() => {
  try { fs.rmSync(tmpHome, { recursive: true, force: true }); } catch { /* best-effort */ }
});

// Helper: per-major funding map in the shape decide() consumes.
const fund = (apys) => Object.fromEntries(
  Object.entries(apys).map(([coin, apy]) => [coin, { apy, mark: 100 }]),
);

describe('annualizeFunding', () => {
  test('annualizes an hourly funding rate (×24×365×100)', () => {
    expect(carry.annualizeFunding(0.0000125)).toBeCloseTo(10.95, 1);
    expect(carry.annualizeFunding(0)).toBe(0);
    expect(carry.annualizeFunding(-0.00001)).toBeLessThan(0);
  });
});

describe('decide: OPEN gate (>= OPEN_APY, best major, mode != hibernate)', () => {
  test('opens the highest-funding major when it clears OPEN_APY (default 10)', () => {
    const d = carry.decide(null, fund({ BTC: 4, ETH: 8, SOL: 12 }), 'thrive');
    expect(d.action).toBe('open');
    expect(d.coin).toBe('SOL');
  });

  test('picks the HIGHEST among several that clear the threshold', () => {
    const d = carry.decide(null, fund({ BTC: 11, ETH: 25, SOL: 12 }), 'thrive');
    expect(d).toMatchObject({ action: 'open', coin: 'ETH' });
  });

  test('does NOT open when no major clears OPEN_APY', () => {
    const d = carry.decide(null, fund({ BTC: 4, ETH: 8, SOL: 9.9 }), 'thrive');
    expect(d.action).toBe('hold');
  });

  test('exactly AT the threshold opens (>= is inclusive)', () => {
    const d = carry.decide(null, fund({ BTC: 10, ETH: 2, SOL: 1 }), 'thrive');
    expect(d).toMatchObject({ action: 'open', coin: 'BTC' });
  });

  test('does NOT open in hibernate even with rich funding', () => {
    const d = carry.decide(null, fund({ SOL: 50 }), 'hibernate');
    expect(d.action).toBe('hold');
    expect(d.reason).toMatch(/hibernate/);
  });

  test('ignores non-majors entirely (memecoin funding never opens)', () => {
    const d = carry.decide(null, { DOGE: { apy: 99, mark: 1 } }, 'thrive');
    expect(d.action).toBe('hold');
  });
});

describe('decide: CLOSE gate (<= CLOSE_APY or negative)', () => {
  const open = { coin: 'SOL', spotSize: 0.5, perpSize: 0.5, entryPx: 100 };

  test('closes when funding compresses to <= CLOSE_APY (default 3)', () => {
    const d = carry.decide(open, fund({ SOL: 2.5 }), 'thrive');
    expect(d).toMatchObject({ action: 'close', coin: 'SOL' });
  });

  test('closes when funding flips negative', () => {
    const d = carry.decide(open, fund({ SOL: -1 }), 'thrive');
    expect(d.action).toBe('close');
    expect(d.reason).toMatch(/negative/);
  });

  test('exactly AT CLOSE_APY closes (<= is inclusive)', () => {
    const d = carry.decide(open, fund({ SOL: 3 }), 'thrive');
    expect(d.action).toBe('close');
  });

  test('HOLDS while funding is still above CLOSE_APY but below OPEN_APY', () => {
    const d = carry.decide(open, fund({ SOL: 5 }), 'thrive');
    expect(d.action).toBe('hold');
  });

  test('HOLDS (does not crash/close) when the funding read is unavailable', () => {
    const d = carry.decide(open, {}, 'thrive');
    expect(d.action).toBe('hold');
  });
});

describe('decide: ONE carry at a time', () => {
  test('with a carry open, never proposes opening a 2nd — only hold/close', () => {
    // SOL carry open; BTC funding is sky-high. Must NOT open BTC.
    const d = carry.decide({ coin: 'SOL', spotSize: 1, perpSize: 1, entryPx: 100 },
      fund({ SOL: 8, BTC: 80 }), 'thrive');
    expect(d.action).toBe('hold');
    expect(d.coin).toBe('SOL');
  });
});

describe('sizeLegs: NOTIONAL hard cap + capital constraint + min', () => {
  test('never exceeds NOTIONAL even with abundant capital', () => {
    const s = carry.sizeLegs(10000, 10000, 2);
    expect(s.ok).toBe(true);
    expect(s.notional).toBeLessThanOrEqual(carry.NOTIONAL);
    expect(s.notional).toBe(carry.NOTIONAL);
  });

  test('caps to spot buying power when spot is the binding constraint', () => {
    const s = carry.sizeLegs(25, 10000, 2);
    expect(s.notional).toBe(25);
  });

  test('caps to perp capacity (perpBP × leverage) when perp is binding', () => {
    const s = carry.sizeLegs(10000, 10, 2); // 10 × 2 = 20
    expect(s.notional).toBe(20);
  });

  test('refuses a sub-min ($11) leg rather than placing dust', () => {
    const s = carry.sizeLegs(10000, 4, 2); // 4 × 2 = 8 < 11
    expect(s.ok).toBe(false);
    expect(s.reason).toMatch(/min/);
  });

  test('honors a raised NOTIONAL env cap on reload', () => {
    process.env.GCLAW_CARRY_NOTIONAL = '25';
    const c2 = loadCarry();
    const s = c2.sizeLegs(10000, 10000, 2);
    expect(s.notional).toBe(25);
  });
});

describe('leverage is clamped to <= 2 (delta-neutral ballast)', () => {
  test('an env request for 5x is clamped to MAX_LEVERAGE (2)', () => {
    process.env.GCLAW_CARRY_LEVERAGE = '5';
    const c2 = loadCarry();
    expect(c2.LEVERAGE).toBe(2);
  });
});

describe('riskguard exemption contract', () => {
  test('addExemption writes {coin, entry}; removeExemption clears it', () => {
    carry.addExemption('SOL', 100);
    let list = JSON.parse(fs.readFileSync(path.join(tmpHome, 'riskguard_exempt.json'), 'utf8'));
    expect(list).toContainEqual({ coin: 'SOL', entry: 100 });
    carry.removeExemption('SOL');
    list = JSON.parse(fs.readFileSync(path.join(tmpHome, 'riskguard_exempt.json'), 'utf8'));
    expect(list.find((e) => e.coin === 'SOL')).toBeUndefined();
  });

  test('addExemption is idempotent (no duplicate within 0.1%)', () => {
    carry.addExemption('ETH', 2000);
    carry.addExemption('ETH', 2000.5); // within 0.1%
    const list = JSON.parse(fs.readFileSync(path.join(tmpHome, 'riskguard_exempt.json'), 'utf8'));
    expect(list.filter((e) => e.coin === 'ETH')).toHaveLength(1);
  });

  test('addExemption preserves a pre-existing exemption for another coin', () => {
    fs.writeFileSync(path.join(tmpHome, 'riskguard_exempt.json'), JSON.stringify([{ coin: 'BTC', entry: 50000 }]));
    carry.addExemption('SOL', 100);
    const list = JSON.parse(fs.readFileSync(path.join(tmpHome, 'riskguard_exempt.json'), 'utf8'));
    expect(list).toContainEqual({ coin: 'BTC', entry: 50000 });
    expect(list).toContainEqual({ coin: 'SOL', entry: 100 });
  });
});

describe('DRY-RUN is the default: doOpen/doClose place NO real order', () => {
  // Make any network read or SDK load throw, so a test fails loudly if the dry-run
  // path ever reaches the network/SDK. https is the funding/spotMeta boundary;
  // the SDK is loaded via require() of ~/gdex-skill.
  let httpsSpy;
  beforeEach(() => {
    const https = require('node:https');
    httpsSpy = vi.spyOn(https, 'request').mockImplementation(() => {
      throw new Error('NETWORK TOUCHED IN DRY-RUN — must not happen');
    });
  });
  afterEach(() => { httpsSpy.mockRestore(); });

  test('liveMode() is false when GCLAW_CARRY_LIVE is unset', () => {
    expect(carry.liveMode()).toBe(false);
  });

  test('doOpen in dry-run returns a plan, places no order, writes no state/exemption', async () => {
    const fundings = { SOL: { apy: 12, mark: 100 } };
    const res = await carry.doOpen('SOL', 12, fundings);
    expect(res.ok).toBe(true);
    expect(res.live).toBe(false);
    expect(res.dryRun).toBe(true);
    expect(res.plan).toMatch(/DRY-RUN/);
    // The dry-run open plan is capped at NOTIONAL.
    expect(res.plannedNotional).toBeLessThanOrEqual(carry.NOTIONAL);
    // NOTHING written: no carry.json, no exemption.
    expect(fs.existsSync(path.join(tmpHome, 'carry.json'))).toBe(false);
    expect(fs.existsSync(path.join(tmpHome, 'riskguard_exempt.json'))).toBe(false);
  });

  test('doClose in dry-run returns a plan, places no order, leaves state untouched', async () => {
    const open = { coin: 'SOL', spotSize: 0.5, perpSize: 0.5, entryPx: 100 };
    fs.writeFileSync(path.join(tmpHome, 'carry.json'), JSON.stringify(open));
    const res = await carry.doClose(open, 'compressed', { SOL: { apy: 2, mark: 100 } });
    expect(res.ok).toBe(true);
    expect(res.live).toBe(false);
    expect(res.dryRun).toBe(true);
    expect(res.plan).toMatch(/DRY-RUN/);
    // Dry-run must not place an order; carry.json is left for the live path to clear.
    expect(fs.existsSync(path.join(tmpHome, 'carry.json'))).toBe(true);
  });
});

describe('metabolismMode', () => {
  test('reads mode from metabolism.json', () => {
    fs.writeFileSync(path.join(tmpHome, 'metabolism.json'), JSON.stringify({ mode: 'survive' }));
    expect(carry.metabolismMode()).toBe('survive');
  });

  test('defaults to thrive when unreadable', () => {
    expect(carry.metabolismMode()).toBe('thrive');
  });
});
