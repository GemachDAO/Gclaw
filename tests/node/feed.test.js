// Guards for scripts/feed.js — the exactly-once live-drop pusher.
//
// What these lock:
//   - BASELINE ON FIRST RUN: a cold start fires NOTHING (no retroactive flood) and
//     records where we are.
//   - EXACTLY-ONCE: a drop keyed once never re-fires on a re-run of the same cycle
//     (the redelivery / idempotency guarantee, mirrored from notify.js celebrate).
//   - A NEW event past the cursor fires exactly one drop.
//   - HONEST: a losing settle is announced as a loss, never fake green.
//
// No real network: GCLAW_TELEGRAM_TOKEN/_CHAT are unset so deliver() no-ops, and
// computeDrops is a pure function we can drive directly with state on disk.

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const fs = require('node:fs');
const os = require('node:os');

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.resolve(HERE, '..', '..', 'scripts', 'feed.js');

let tmp;
let savedEnv;

function loadFresh() { delete require.cache[SCRIPT]; return require(SCRIPT); }
function write(rel, obj) {
  const p = path.join(tmp, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, typeof obj === 'string' ? obj : JSON.stringify(obj));
}
function cursor() { return JSON.parse(fs.readFileSync(path.join(tmp, 'telegram', 'feed_cursor.json'), 'utf8')); }

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-feed-'));
  savedEnv = { ...process.env };
  process.env.GCLAW_HOME = tmp;
  delete process.env.GCLAW_TELEGRAM_TOKEN; // deliver() no-ops → no network
  delete process.env.GCLAW_TELEGRAM_CHAT;
  write('metabolism.json', { name: 'Zephlith', heartbeats: 100, children: [] });
  write('dna/persona.json', { species: 'Zephlith', catchphrase: 'Still here. Still trading.', sigil: '◇' });
});
afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
  process.env = savedEnv;
});

describe('feed exactly-once', () => {
  test('first run baselines and fires nothing (no retroactive flood)', async () => {
    // a settle already exists at baseline time — it must NOT be replayed
    write('journal.jsonl', JSON.stringify({ event: 'settle', ts: '2026-06-30T00:00:00Z', pnl: -1.5, note: 'old close' }) + '\n');
    const feed = loadFresh();
    const out = await feed.run();
    expect(out.initialized).toBe(true);
    expect(fs.existsSync(path.join(tmp, 'telegram', 'feed_cursor.json'))).toBe(true);
    // the historical settle is already marked seen at baseline
    expect(Object.keys(cursor().unlocked)).toContain('settle:2026-06-30T00:00:00Z');
  });

  test('a re-run of the same cycle fires no duplicate (dedupe by key)', async () => {
    write('journal.jsonl', JSON.stringify({ event: 'settle', ts: '2026-06-30T00:00:00Z', pnl: -1.5, note: 'old' }) + '\n');
    const feed = loadFresh();
    await feed.run(); // baseline
    const r1 = await feed.run();
    const r2 = await feed.run();
    expect(r1.fired).toBe(0);
    expect(r2.fired).toBe(0); // nothing changed → nothing re-fires
  });

  test('a NEW settle past the cursor fires exactly one drop, and it is honest about a loss', () => {
    const feed = loadFresh();
    // baseline cursor as of an empty journal
    const base = feed.computeDrops({ meta: { children: [] } }, { unlocked: {} }).nextCursor;
    // now a new losing settle arrives
    write('journal.jsonl', JSON.stringify({ event: 'settle', ts: '2026-07-01T12:00:00Z', pnl: -3.2, note: 'SOL stop' }) + '\n');
    const { drops } = feed.computeDrops({ meta: { children: [] } }, base);
    const settleDrops = drops.filter((d) => d.key.startsWith('settle:'));
    expect(settleDrops.length).toBe(1);
    expect(settleDrops[0].text).toMatch(/-\$3\.20/); // stated as a loss
    expect(settleDrops[0].text).not.toMatch(/\+\$/); // never fake green
  });

  test('a child-born event fires once and not again', () => {
    const feed = loadFresh();
    const empty = { meta: { children: [] } };
    const base = feed.computeDrops(empty, { unlocked: {} }).nextCursor;
    const withKid = { meta: { children: [{ name: 'Cub', role: 'scout' }] } };
    const first = feed.computeDrops(withKid, base);
    expect(first.drops.some((d) => d.key === 'child:Cub')).toBe(true);
    // re-run with the same cursor advanced → no re-fire
    const second = feed.computeDrops(withKid, first.nextCursor);
    expect(second.drops.some((d) => d.key === 'child:Cub')).toBe(false);
  });

  test('a tripped breaker is a page-worthy drop', () => {
    const feed = loadFresh();
    write('breaker.json', { tripped: true, reason: 'drawdown 26%', at: '2026-07-01T12:00:00Z' });
    const { drops } = feed.computeDrops({ meta: { children: [] } }, { unlocked: {} });
    const brk = drops.find((d) => d.key.startsWith('breaker:'));
    expect(brk).toBeTruthy();
    expect(brk.page).toBe(true);
  });
});
