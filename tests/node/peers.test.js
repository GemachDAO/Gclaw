// Discovery parses UNTRUSTED registry-log data (scripts/peers.js). A single malformed
// log — a missing/garbage topic1, junk data — must never abort the crawl: the cursor is
// advanced AFTER the loop, so a throw would leave lastBlock un-advanced and re-hit the
// same bad log every heartbeat, stalling discovery forever. gclawIdsFromLogs must skip
// the bad record and keep the good ones.

import { describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { Buffer } = require('node:buffer');

const { gclawIdsFromLogs, decodeString, isGclawUri } = loadScript('peers.js');

const TOPIC = '0xca52e62c367d81bb2e328eb795f7c7ba24afb478408a26c0e201d155c449bc4a';
const idTopic = (n) => '0x' + n.toString(16).padStart(64, '0');

// ABI-encode a string the way decodeString reads it: offset(0x20) + length + data.
function abiString(s) {
  const hex = Buffer.from(s, 'utf8').toString('hex');
  const off = (32).toString(16).padStart(64, '0');
  const len = Buffer.byteLength(s).toString(16).padStart(64, '0');
  return '0x' + off + len + hex.padEnd(Math.ceil(hex.length / 64) * 64, '0');
}

describe('decodeString / isGclawUri round-trip', () => {
  test('decodes an ABI string and recognizes the gclaw signature', () => {
    const data = abiString('Zephlith — a creature that learned to trade to survive');
    expect(decodeString(data)).toContain('trade to survive');
    expect(isGclawUri(decodeString(data))).toBe(true);
  });
  test('empty / 0x data decodes to null without throwing', () => {
    expect(decodeString('0x')).toBeNull();
    expect(decodeString(null)).toBeNull();
  });
});

describe('gclawIdsFromLogs — one bad log never aborts the batch', () => {
  test('keeps the valid gclaw ids and skips malformed / non-gclaw logs', () => {
    const logs = [
      { topics: [TOPIC, idTopic(55624)], data: abiString('gclaw — trade to survive') },
      { topics: [TOPIC], data: abiString('x') },                       // missing topic1 → BigInt throws
      { topics: [TOPIC, '0xnothex'], data: abiString('y') },           // garbage topic1 → BigInt throws
      { topics: [TOPIC, idTopic(99999)], data: abiString('some other agent') }, // valid, not gclaw
      { topics: [TOPIC, idTopic(55700)], data: abiString('also a creature that will trade to survive') },
      {},                                                              // totally empty log
    ];
    const ids = gclawIdsFromLogs(logs, null, new Set());
    expect(ids).toEqual([55624, 55700]); // both good ones survive; bad/irrelevant skipped
  });

  test('excludes self and already-known ids, and de-dups within a batch', () => {
    const logs = [
      { topics: [TOPIC, idTopic(55624)], data: abiString('trade to survive') },
      { topics: [TOPIC, idTopic(55624)], data: abiString('trade to survive') }, // dup in same batch
      { topics: [TOPIC, idTopic(42)], data: abiString('trade to survive') },     // self
      { topics: [TOPIC, idTopic(100)], data: abiString('trade to survive') },    // already known
    ];
    expect(gclawIdsFromLogs(logs, 42, new Set([100]))).toEqual([55624]);
  });

  test('an empty / null log list yields nothing', () => {
    expect(gclawIdsFromLogs([], null, new Set())).toEqual([]);
    expect(gclawIdsFromLogs(null, null, new Set())).toEqual([]);
  });
});
