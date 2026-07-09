// Copy-trade skill-admission gate (assune-2ol.7): only skill-proven wallets survive.
import { describe, test, expect } from 'vitest';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { admitScorecard, applyAdmissionGate } = require('../../scripts/winners.js');

const SKILL = { address: '0xe1b8', n_trades: 179, expectancy: 73.9, luck_flag: false, method: 'flat_to_flat' };
const LUCK = { address: '0xa867', n_trades: 22, expectancy: 544.4, luck_flag: true, method: 'flat_to_flat' };
const LOSER = { address: '0xa40e', n_trades: 4, expectancy: -1275.3, luck_flag: true, method: 'flat_to_flat' };
const THIN = { address: '0x1111', n_trades: 8, expectancy: 5.0, luck_flag: false, method: 'flat_to_flat' };
const WRONG = { address: '0x2222', n_trades: 50, expectancy: 5.0, luck_flag: false, method: 'guess' };

describe('admitScorecard', () => {
  test('admits a skill-proven wallet (fair sample, +expectancy, no luck)', () => {
    expect(admitScorecard(SKILL)).toBe(true);
  });
  test('rejects luck-flagged, net-loser, thin-sample, and wrong-method wallets', () => {
    expect(admitScorecard(LUCK)).toBe(false);
    expect(admitScorecard(LOSER)).toBe(false);
    expect(admitScorecard(THIN)).toBe(false);
    expect(admitScorecard(WRONG)).toBe(false);
  });
});

describe('applyAdmissionGate', () => {
  test('keeps only admitted scorecards and records rejections', () => {
    const g = applyAdmissionGate({ scorecards: [SKILL, LUCK, LOSER], aggregate_features: [{ id: 'f' }] });
    expect(g.scorecards.map((s) => s.address)).toEqual(['0xe1b8']);
    expect(g.admission).toMatchObject({ pulled: 3, admitted: 1 });
    expect(g.admission.rejected).toEqual(['0xa867', '0xa40e']);
    expect(g.aggregate_features).toHaveLength(1);
  });
  test('clears the pattern set when zero wallets pass (never clone a luck cohort)', () => {
    const g = applyAdmissionGate({ scorecards: [LUCK, LOSER], aggregate_features: [{ id: 'f' }] });
    expect(g.scorecards).toHaveLength(0);
    expect(g.aggregate_features).toHaveLength(0);
  });
});
