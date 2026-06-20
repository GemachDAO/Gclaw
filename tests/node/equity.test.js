/**
 * THE EQUITY REGRESSION TABLE — the marquee guard.
 *
 * HyperLiquid has TWO wallets: spot (USDC total/hold) and perp
 * (marginSummary.accountValue, which already bakes in margin + unrealized).
 * Correct equity = (spotTotal - spotHold) + accountValue.
 *
 * History:
 *   - BUG: `spot + unrealized` dropped the whole perp wallet → a $42 perp-funded
 *     account read as $0.17.
 *   - ALT: `spot + accountValue` double-counts the margin (hold ≈ accountValue).
 *
 * This locks the correct formula for cross / perp-funded / pure-spot accounts and
 * proves both legacy formulas are wrong, so the bug can never silently return.
 *
 * ESM test file (vitest 4) loading CommonJS sources via the createRequire helper —
 * see helpers.js. `hl_perp.js` must export `computeEquity` and guard `main()`.
 */
import { describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';
import { createRequire } from 'node:module';

const { computeEquity } = loadScript('hl_perp.js');
const { ACCOUNTS } = createRequire(import.meta.url)('./fixtures/hl_accounts.js');

const MANAGED = '0xManaged';

describe('computeEquity (hl_perp.js cmdStatus) — two-wallet equity', () => {
  for (const [name, acc] of Object.entries(ACCOUNTS)) {
    test(`${name}: equity = (spotTotal - spotHold) + accountValue`, () => {
      const out = computeEquity(acc.full, acc.spot, acc.orders, MANAGED);
      expect(out.ok).toBe(true);
      expect(out.equity).toBeCloseTo(acc.correctEquity, 6);
      // buyingPower never goes negative (hold can exceed total transiently).
      expect(out.buyingPower).toBeGreaterThanOrEqual(0);
      // accountValue passes through untouched (the perp wallet value).
      expect(out.accountValue).toBe(acc.full.accountValue);
    });
  }

  test('perp-funded account does NOT read as ~$0 (the original field bug)', () => {
    const out = computeEquity(ACCOUNTS.perpFunded.full, ACCOUNTS.perpFunded.spot, [], MANAGED);
    expect(out.equity).toBeCloseTo(42.17, 2);
    expect(out.equity).toBeGreaterThan(40); // would have been 0.17 under the bug
  });

  test('the legacy `spot + unrealized` formula is WRONG on perp-funded', () => {
    const acc = ACCOUNTS.perpFunded;
    // The bug's value (0.17) must NOT equal the correct equity (42.17).
    expect(acc.legacy_spot_plus_unrealized).not.toBeCloseTo(acc.correctEquity, 2);
  });

  test('the legacy `spot + accountValue` formula DOUBLE-COUNTS margin', () => {
    const acc = ACCOUNTS.crossMargin;
    // alt = 81, correct = 51 — the $30 margin counted twice.
    expect(acc.legacy_spot_plus_accountValue).toBeGreaterThan(acc.correctEquity);
  });

  test('hard-divergence: all three formulas differ, only correct survives', () => {
    const acc = ACCOUNTS.hardDiverge;
    const out = computeEquity(acc.full, acc.spot, acc.orders, MANAGED);
    expect(out.equity).toBe(220);
    expect(acc.legacy_spot_plus_unrealized).toBe(205);
    expect(acc.legacy_spot_plus_accountValue).toBe(340);
    // The three are pairwise distinct — no coincidental pass.
    const vals = new Set([out.equity, acc.legacy_spot_plus_unrealized, acc.legacy_spot_plus_accountValue]);
    expect(vals.size).toBe(3);
  });
});

// The dashboard live-sync recomputes equity client-side in a JS string. Mirror the
// EXACT reducer here and run it over the same table — the two equity sites must agree.
function liveSyncEquity(spot, perp) {
  const u = (spot.balances || []).filter((b) => b.coin === 'USDC')[0];
  const freeSpot = u ? Math.max(0, Number(u.total) - Number(u.hold || 0)) : 0;
  const acct = Number((perp.marginSummary || {}).accountValue || 0);
  return freeSpot + acct; // the dashboard's `var eq=freeSpot+acct`
}

describe('dashboard live-sync equity reducer agrees with hl_perp', () => {
  for (const [name, acc] of Object.entries(ACCOUNTS)) {
    test(`${name}: dashboard live equity == server equity`, () => {
      const perp = { marginSummary: { accountValue: acc.full.accountValue } };
      const server = computeEquity(acc.full, acc.spot, acc.orders, MANAGED).equity;
      expect(liveSyncEquity(acc.spot, perp)).toBeCloseTo(server, 6);
    });
  }
});
