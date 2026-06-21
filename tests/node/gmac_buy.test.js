// The GMAC buy-back reconcile gate (scripts/gmac_buy.js): a buy that confirmed on-chain
// but failed to record its treasury decrement must NOT let the next buy spend again.
// The treasury is the spend budget (--usd <treasury>); if it never went down, a repeat
// buy double-spends real ETH. reconcileSentinel() must retry the record and only clear
// the sentinel on success, otherwise REFUSE the next buy. recordSpend is injectable, so
// this drives the gate with no SDK / subprocess.

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';
import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const os = require('node:os');
const fs = require('node:fs');

let tmp;
let savedHome;
beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-gmac-'));
  savedHome = process.env.GCLAW_HOME;
  process.env.GCLAW_HOME = tmp;
});
afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
  if (savedHome === undefined) delete process.env.GCLAW_HOME;
  else process.env.GCLAW_HOME = savedHome;
});

const writeSentinel = (p) => fs.writeFileSync(path.join(tmp, 'gmac_unreconciled.json'), JSON.stringify(p));
const sentinelExists = () => fs.existsSync(path.join(tmp, 'gmac_unreconciled.json'));

describe('reconcileSentinel — an unrecorded prior buy cannot be silently re-spent', () => {
  test('no sentinel → nothing to do, buy may proceed', () => {
    const gmac = loadScript('gmac_buy.js');
    expect(gmac.reconcileSentinel(() => true)).toEqual({ reconciled: false });
  });

  test('a retry that records clears the sentinel and lets the buy proceed', () => {
    const gmac = loadScript('gmac_buy.js');
    writeSentinel({ usd: 7, tokens: 1234, tx: '0xabc' });
    const seen = [];
    const out = gmac.reconcileSentinel((usd, tokens, tx) => { seen.push([usd, tokens, tx]); return true; });
    expect(out.reconciled).toBe(true);
    expect(seen).toEqual([[7, 1234, '0xabc']]); // retried with the persisted spend
    expect(sentinelExists()).toBe(false);       // cleared
  });

  test('a retry that still fails THROWS — the next buy is refused, not double-spent', () => {
    const gmac = loadScript('gmac_buy.js');
    writeSentinel({ usd: 7, tokens: 1234, tx: '0xabc' });
    expect(() => gmac.reconcileSentinel(() => false)).toThrow(/unreconciled prior GMAC buy/);
    expect(sentinelExists()).toBe(true);        // left in place for manual resolution
  });
});
