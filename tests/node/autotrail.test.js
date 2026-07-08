// Exit-policy tests for the exit manager (scripts/autotrail.js).
//
// decideExit(t, dir, entry, mark, nowMs) is the pure exit brain: it advances the
// per-position trail state and returns one of 'trail' (winner gives back its run),
// 'loser-timestop' (a never-worked trade stalled past its short leash), or 'hold'.
// It encodes the disposition-inverse discipline of proven winners — let winners run,
// cut losers fast. main() is guarded, so importing the module is side-effect-free.
//
// Defaults under test (env unset): LOSER_STOP_HOURS=6, LOSER_STOP_PCT=-0.8, ARM=+2.5%.

import { describe, expect, test } from 'vitest';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const { decideExit } = require(path.resolve(HERE, '..', '..', 'scripts', 'autotrail.js'));

const NOW = 1_800_000_000_000;
const hoursAgo = (h) => NOW - h * 3_600_000;

describe('loser time-stop', () => {
  test('cuts a never-armed, underwater, stalled long', () => {
    const t = { hw: 99, armed: false, opened: hoursAgo(7) };
    const d = decideExit(t, 1, 100, 99, NOW); // -1.0% past the -0.8% leash, 7h > 6h
    expect(d.action).toBe('loser-timestop');
  });

  test('cuts symmetrically on a short', () => {
    const t = { hw: 101, armed: false, opened: hoursAgo(7) };
    const d = decideExit(t, -1, 100, 101, NOW); // short +1 price = -1.0% pnl
    expect(d.action).toBe('loser-timestop');
  });

  test('holds a young loser (inside the leash)', () => {
    const t = { hw: 99, armed: false, opened: hoursAgo(2) };
    expect(decideExit(t, 1, 100, 99, NOW).action).toBe('hold');
  });

  test('holds a shallow loss (inside the noise band)', () => {
    const t = { hw: 99.7, armed: false, opened: hoursAgo(9) };
    const d = decideExit(t, 1, 100, 99.7, NOW); // -0.3% > -0.8% leash → noise
    expect(d.action).toBe('hold');
  });

  test('never cuts on first sight (age stamped to now → age 0)', () => {
    const t = { hw: 98, armed: false }; // no `opened`
    const d = decideExit(t, 1, 100, 98, NOW); // deep underwater but just seen
    expect(d.action).toBe('hold');
    expect(t.opened).toBe(NOW);
  });
});

describe('winners still trail, and armed positions are never time-stopped', () => {
  test('an armed winner that reverses to its soft-stop trails out', () => {
    const t = { hw: 103, armed: true, opened: hoursAgo(10) };
    const d = decideExit(t, 1, 100, 100.4, NOW); // below the 1.5% trail off the 103 HW
    expect(d.action).toBe('trail');
  });

  test('an armed trade deep underwater trails (not loser-timestop)', () => {
    const t = { hw: 105, armed: true, opened: hoursAgo(10) };
    const d = decideExit(t, 1, 100, 98, NOW);
    expect(d.action).toBe('trail'); // armed excludes the loser leash
  });

  test('a fresh push past +2.5% arms and holds while running', () => {
    const t = { hw: 100, armed: false, opened: hoursAgo(3) };
    const d = decideExit(t, 1, 100, 103, NOW); // +3% → arm, no reversal yet
    expect(t.armed).toBe(true);
    expect(d.action).toBe('hold');
  });
});
