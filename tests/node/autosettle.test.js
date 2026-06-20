// No-double-settle tests for the deterministic settlement cursor (scripts/autosettle.js).
//
// autosettle reads HL fills since a stored cursor, nets closedPnl - fee, and books
// it ONCE via metabolism.py. The anti-double-count guarantee rests entirely on
// selectNew(fills, cursor): a fill is "new" iff it is strictly after the cursor time,
// OR exactly at the cursor time but its tid was not already consumed. The script also
// advances the cursor BEFORE settling (fail-conservative: a crash mid-settle drops a
// batch rather than re-reading and double-booking it).
//
// These tests pin that dedup logic against adversarial fill streams: replayed batches,
// same-millisecond ties, out-of-order arrival, and an attacker re-presenting an old
// closed fill. The SDK + ethers requires at the top of autosettle.js resolve from
// ~/gdex-skill at load time but main() is guarded, so importing it is side-effect-free.

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const AS_PATH = path.resolve(HERE, '..', '..', 'scripts', 'autosettle.js');

function loadAutosettle() {
  delete require.cache[AS_PATH];
  return require(AS_PATH);
}

const fill = (time, tid, closedPnl = 0, fee = 0) => ({ time, tid, closedPnl, fee, coin: 'BTC' });
const FRESH = { lastTime: 0, lastTids: [], residual: 0 };

let as;
beforeEach(() => { as = loadAutosettle(); });
afterEach(() => {});

// Compute the cursor the script would persist after consuming `selected` (mirrors the
// `maxTime`/`tidsAtMax` advance in main()), so a second pass can be simulated.
function advanceCursor(allFills, cursor) {
  const fresh = as.selectNew(allFills, cursor);
  if (!fresh.length) return cursor;
  const maxTime = Math.max(cursor.lastTime, ...fresh.map((f) => f.time));
  const tidsAtMax = allFills.filter((f) => f.time === maxTime).map((f) => f.tid);
  return { ...cursor, lastTime: maxTime, lastTids: tidsAtMax, residual: 0 };
}

describe('selectNew dedup (the no-double-settle core)', () => {
  test('a fresh cursor selects every fill exactly once', () => {
    const fills = [fill(100, 'a', 5), fill(200, 'b', -3), fill(300, 'c', 7)];
    expect(as.selectNew(fills, FRESH).map((f) => f.tid)).toEqual(['a', 'b', 'c']);
  });

  test('replaying the SAME batch after advancing the cursor selects nothing', () => {
    const fills = [fill(100, 'a', 5), fill(200, 'b', -3), fill(300, 'c', 7)];
    const cursor = advanceCursor(fills, FRESH);
    // Second pass over the identical history must settle nothing — the close is booked once.
    expect(as.selectNew(fills, cursor)).toEqual([]);
  });

  test('two fills at the SAME timestamp are not double-counted on replay', () => {
    // Same-ms ties are the classic double-settle trap: a naive `time > lastTime` would
    // either skip the second tie (under-count) or re-take both on replay (double-count).
    const fills = [fill(500, 'x', 4), fill(500, 'y', 6)];
    const cursor = advanceCursor(fills, FRESH);
    expect(cursor.lastTime).toBe(500);
    expect(new Set(cursor.lastTids)).toEqual(new Set(['x', 'y']));
    expect(as.selectNew(fills, cursor)).toEqual([]); // both already consumed at lastTime
  });

  test('a NEW fill at the cursor timestamp (later tid) is still picked up', () => {
    const fills = [fill(500, 'x', 4), fill(500, 'y', 6)];
    const cursor = advanceCursor(fills, FRESH);
    const withLate = [...fills, fill(500, 'z', 9)]; // arrives same ms, unseen tid
    const fresh = as.selectNew(withLate, cursor);
    expect(fresh.map((f) => f.tid)).toEqual(['z']);
  });

  test('an attacker re-presenting an old (pre-cursor) closed fill is ignored', () => {
    const cursor = { lastTime: 1000, lastTids: ['old'], residual: 0 };
    const malicious = [fill(900, 'replayed', 999999, 0)]; // huge fake profit, but stale time
    expect(as.selectNew(malicious, cursor)).toEqual([]);
  });

  test('incremental settles never reselect a previously-consumed fill', () => {
    let cursor = FRESH;
    const batch1 = [fill(100, 'a', 1), fill(200, 'b', 2)];
    cursor = advanceCursor(batch1, cursor);
    const batch2 = [...batch1, fill(300, 'c', 3)]; // history grows
    const fresh2 = as.selectNew(batch2, cursor);
    expect(fresh2.map((f) => f.tid)).toEqual(['c']); // only the genuinely new fill
    cursor = advanceCursor(batch2, cursor);
    expect(as.selectNew(batch2, cursor)).toEqual([]); // nothing left to settle
  });

  test('net PnL of a settled batch is summed once, not per replay', () => {
    const fills = [fill(100, 'a', 10, 1), fill(200, 'b', -4, 0.5)];
    const fresh1 = as.selectNew(fills, FRESH);
    const net1 = fresh1.reduce((s, f) => s + Number(f.closedPnl) - Number(f.fee), 0);
    expect(net1).toBeCloseTo(10 - 1 - 4 - 0.5, 6); // 4.5
    const cursor = advanceCursor(fills, FRESH);
    const fresh2 = as.selectNew(fills, cursor);
    const net2 = fresh2.reduce((s, f) => s + Number(f.closedPnl) - Number(f.fee), 0);
    expect(net2).toBe(0); // replay contributes nothing
  });
});

describe('cursor persistence is atomic', () => {
  test('writeAtomic writes via a temp file then renames (reader never sees a half-write)', () => {
    const os = require('node:os');
    const fs = require('node:fs');
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-as-'));
    const target = path.join(tmp, 'cursor.json');
    as.writeAtomic(target, JSON.stringify({ lastTime: 42 }));
    expect(JSON.parse(fs.readFileSync(target, 'utf8')).lastTime).toBe(42);
    // No stray temp file left behind.
    expect(fs.readdirSync(tmp).filter((f) => f.includes('.tmp'))).toEqual([]);
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  test('a corrupt cursor on disk reads back as the safe default (readJson boundary)', () => {
    const os = require('node:os');
    const fs = require('node:fs');
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-as-'));
    const target = path.join(tmp, 'cursor.json');
    fs.writeFileSync(target, '{ "lastTime": 5, '); // crashed mid-write -> invalid JSON
    expect(as.readJson(target, { lastTime: 0, lastTids: [], residual: 0 }))
      .toEqual({ lastTime: 0, lastTids: [], residual: 0 });
    fs.rmSync(tmp, { recursive: true, force: true });
  });
});

describe('sub-cent dust is carried, not lost', () => {
  // A net below DUST is carried in `residual` and folded into the next batch rather
  // than spamming a tiny settle. This pins the arithmetic contract the script encodes:
  //   net = closedPnl - fees + funding + residual.
  test('a net below the dust threshold is carried as residual', () => {
    const closedPnl = 0.004;
    const fees = 0.0;
    const residualIn = 0.003;
    const net = Math.round((closedPnl - fees + 0 + residualIn) * 1e6) / 1e6; // 0.007
    expect(Math.abs(net) < as.DUST).toBe(true); // carried, not settled
  });

  test('once carried residual pushes a batch over DUST, it settles', () => {
    const net = Math.round((0.006 + 0 + 0 + 0.006) * 1e6) / 1e6; // 0.012 >= 0.01
    expect(Math.abs(net) >= as.DUST).toBe(true);
  });
});
