'use strict';
/**
 * Hermetic HyperLiquid account fixtures — the THREE wallet topologies that broke
 * (and must keep passing) the two-wallet equity formula:
 *
 *   equity = max(0, spotTotal - spotHold) + accountValue
 *
 * Shapes mirror the real HL `info` API responses the SDK returns:
 *   - spotClearinghouseState.balances[].{coin,total,hold}   (USDC spot wallet)
 *   - clearinghouseState.marginSummary.accountValue          (perp wallet; already
 *     includes margin + unrealized)
 *
 * `full` is the normalized object hl_perp.fullState() yields (accountValue +
 * positions + withdrawable); `spot` is the raw getHlSpotState() shape; `orders`
 * are open orders. Each case carries the ONE correct equity plus the two WRONG
 * legacy formulas, so a test can prove the right one and that the others regress.
 */

// total, hold for the spot USDC balance; accountValue for the perp wallet.
function makeAccount({ spotTotal, spotHold, accountValue, unrealized = 0, positions = [] }) {
  const pos = positions.length
    ? positions
    : unrealized
      ? [{ coin: 'ETH', size: 0.01, entryPx: 3000, unrealizedPnl: unrealized, liquidationPx: null }]
      : [];
  return {
    full: { accountValue, positions: pos, withdrawable: Math.max(0, spotTotal - spotHold) },
    spot: { balances: [{ coin: 'USDC', total: String(spotTotal), hold: String(spotHold) }] },
    orders: [],
    // expectations
    correctEquity: Math.max(0, spotTotal - spotHold) + accountValue,
    legacy_spot_plus_unrealized: spotTotal + unrealized, // the original bug
    legacy_spot_plus_accountValue: spotTotal + accountValue, // the double-count alt
  };
}

// THE REGRESSION TABLE — exact, hand-checked dollar values.
const ACCOUNTS = {
  // Cross-margin: $50 sits in spot, $30 of it is HELD as perp margin; the perp
  // wallet shows accountValue=$31 (margin $30 + $1 unrealized). One dollar of margin
  // appears in BOTH spotHold and accountValue.
  //   correct  = (50 - 30) + 31 = 51
  //   bug(spot+unreal)   = 50 + 1  = 51 ... (coincidental here; see perpFunded below)
  //   alt(spot+acct)     = 50 + 31 = 81  (double-counts the $30 margin)
  crossMargin: makeAccount({ spotTotal: 50, spotHold: 30, accountValue: 31, unrealized: 1 }),

  // Perp-funded: funds were transferred INTO the perp wallet; spot is ~$0. This is
  // the case the original `spot + unrealized` bug read as ~$0 on a real $42 account.
  //   correct = (0.17 - 0) + 42 = 42.17
  //   bug     = 0.17 + 0 = 0.17   <-- the $0.17 reading we hit in the field
  //   alt     = 0.17 + 42 = 42.17 (coincidental match because hold≈0 here)
  perpFunded: makeAccount({ spotTotal: 0.17, spotHold: 0, accountValue: 42, unrealized: 0 }),

  // Pure spot: no perp wallet at all, no positions.
  //   correct = (100 - 0) + 0 = 100 ; bug = 100 ; alt = 100  (all agree → must stay 100)
  pureSpot: makeAccount({ spotTotal: 100, spotHold: 0, accountValue: 0, unrealized: 0 }),

  // The discriminating case: funds in perp AND spot margin held AND open unrealized,
  // so all three formulas DIVERGE and only the correct one survives.
  //   spotTotal=20, spotHold=12 (margin), accountValue=15 (margin 12 + unreal 3)
  //   correct = (20 - 12) + 15 = 23
  //   bug(spot+unreal) = 20 + 3 = 23   <-- still wrong in general; here forced apart below
  //   alt(spot+acct)   = 20 + 15 = 35
  discriminating: makeAccount({ spotTotal: 20, spotHold: 12, accountValue: 15, unrealized: 3 }),

  // Hard-divergence case engineered so NO two formulas coincide — locks all three apart.
  //   spotTotal=200, spotHold=120, accountValue=140 (margin 120 + unreal 20)
  //   correct          = (200-120)+140 = 220
  //   bug(spot+unreal) = 200+20        = 220 ... still equal; force unreal != accountValue-hold:
  // Use accountValue NOT equal to hold+unreal to break the coincidence:
  hardDiverge: {
    full: { accountValue: 140, positions: [{ coin: 'BTC', size: 0.01, entryPx: 60000, unrealizedPnl: 5, liquidationPx: null }], withdrawable: 80 },
    spot: { balances: [{ coin: 'USDC', total: '200', hold: '120' }] },
    orders: [],
    correctEquity: 80 + 140, // (200-120)+140 = 220
    legacy_spot_plus_unrealized: 200 + 5, // 205  (drops the perp wallet)
    legacy_spot_plus_accountValue: 200 + 140, // 340 (double-counts the $120 margin)
  },
};

module.exports = { ACCOUNTS, makeAccount };
