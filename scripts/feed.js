#!/usr/bin/env node
/**
 * feed.js — the exactly-once live-drop pusher for Gclaw's Telegram feed.
 *
 * The heartbeat manufactures drama hourly — a technique graduates, the breed gate
 * opens, a child is born, the ladder flips, a call lands, a trade opens/closes, a
 * breaker trips, gas runs low, a beacon lands. feed.js turns each into a voiced,
 * honest, Gemach-brand-toned drop and pushes it exactly once.
 *
 * EXACTLY-ONCE: reuse notify.js celebrate's discipline — a cursor over
 * journal.jsonl settle timestamps, plus an unlocked-key set for once-only
 * milestones — persisted in $GCLAW_HOME/telegram/feed_cursor.json. On the FIRST
 * run it BASELINES (records where we are, fires nothing) so it never floods on a
 * cold start. A key already in `unlocked` never re-fires, so a redelivered event
 * or a re-run of the same cycle cannot double-post.
 *
 * HONEST: celebrate proven edge and the science; state realized PnL in character;
 * never fake green. A losing settle is announced as a loss, in voice.
 *
 *   node feed.js run       # push any new drops since the cursor, then exit (idempotent — heartbeat calls this each cycle)
 *
 * Env: GCLAW_TELEGRAM_TOKEN + GCLAW_TELEGRAM_CHAT (the feed target), GCLAW_HOME.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const TG_DIR = path.join(GCLAW_HOME, 'telegram');
const CURSOR_PATH = path.join(TG_DIR, 'feed_cursor.json');

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };
const readJsonl = (p) => { try { return fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)); } catch { return []; } };

function writeAtomic(p, data) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const tmp = `${p}.tmp${process.pid}`;
  fs.writeFileSync(tmp, data);
  fs.renameSync(tmp, p);
}

// ── voice (persona-driven, same shape as notify.js soul/voiced) ─────────────
const SAFE_SIGILS = new Set(['◆', '◈', '✦', '✧', '❖', '⬡', '⬢', '❂', '✸', '⟡', '◇', '✺', '☉', '☾']);
function soul() {
  const p = readJson(path.join(GCLAW_HOME, 'dna', 'persona.json'), {});
  const m = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  return {
    name: m.name || p.species || p.name || 'Gclaw',
    sigil: SAFE_SIGILS.has(p.sigil) ? p.sigil : '◇',
    catchphrase: p.catchphrase || 'Still here. Still trading.',
    archetype: p.archetype || '',
  };
}
function voiced(msg, big) {
  const s = soul();
  return `${s.sigil} ${s.name} — ${msg}` + (big && s.catchphrase ? `\n“${s.catchphrase}”` : '');
}

// ── delivery (same sendMessage path as notify.js; no-ops without config) ─────
async function post(url, body) {
  return new Promise((resolve) => {
    try {
      const data = JSON.stringify(body);
      const req = https.request(url, { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(data) } },
        (res) => { res.on('data', () => {}); res.on('end', () => resolve(res.statusCode)); });
      req.on('error', () => resolve(null));
      req.write(data); req.end();
    } catch { resolve(null); }
  });
}
async function deliver(text) {
  const tk = process.env.GCLAW_TELEGRAM_TOKEN, chat = process.env.GCLAW_TELEGRAM_CHAT;
  if (!tk || !chat) return { sent: false, skip: 'no telegram configured' };
  const code = await post(`https://api.telegram.org/bot${tk}/sendMessage`, { chat_id: chat, text, disable_web_page_preview: true });
  return { sent: code != null };
}

// ── honest money ─────────────────────────────────────────────────────────────
const signed = (n) => { const x = Number(n); return Number.isFinite(x) ? `${x >= 0 ? '+' : '-'}$${Math.abs(x).toFixed(2)}` : '$?'; };

// ── the drop generator — computes the set of NEW drops vs the cursor ─────────
// Pure: reads state + cursor, returns {drops:[{key,page,text}], nextCursor}.
// A drop is "page-worthy" (breaker/breed-ready/trade-close) vs digestible; both
// go through the same exactly-once key set. Separated so the caller (or a future
// digest batcher) can treat them differently.
function computeDrops(state, cursor) {
  const drops = [];
  const unlocked = { ...(cursor.unlocked || {}) };
  const s = soul();

  const journal = readJsonl(path.join(GCLAW_HOME, 'journal.jsonl'));
  const settles = journal.filter((e) => e.event === 'settle');
  const lastSettleTs = settles.length ? Math.max(...settles.map((x) => new Date(x.ts).getTime())) : 0;

  const fire = (key, text, page) => { if (unlocked[key]) return; unlocked[key] = new Date().toISOString(); drops.push({ key, page: !!page, text }); };

  // TRADE OPEN / CLOSE — cursor over new journal events past the last settle ts.
  for (const e of journal.filter((x) => new Date(x.ts).getTime() > (cursor.lastSettleTs || 0))) {
    if (e.event === 'open') fire(`open:${e.ts}`, voiced(`opened ${e.note || 'a position'} — the tape is live.`, false), true);
    if (e.event === 'settle') {
      const pnl = Number(e.pnl);
      const honestTail = pnl >= 0.01 ? '' : ' Not hiding it — the edge is the plan, not the hopium.';
      fire(`settle:${e.ts}`, voiced(`closed ${signed(pnl)} · ${e.note || ''}.${honestTail}`.slice(0, 240), pnl < -1), Math.abs(pnl) > 1);
    }
    if (e.event === 'graduated') fire(`grad:${e.id || e.ts}`, voiced(`GRADUATED a new instrument — “${e.id || e.technique}”. The Bench threw its worst and it held. Real edge, out of sample. 🟢`, true), true);
    if (e.event === 'rejected') fire(`rej:${e.id || e.ts}`, voiced(`the Bench REJECTED “${e.id || e.technique}” — it did not clear the backtest. No edge, no adoption. That is the science working. ⚪`, false), false);
  }

  // TECHNIQUE GRADUATED (fallback: proven-edge set delta if journal lacks graduated events).
  const style = readJson(path.join(GCLAW_HOME, 'forge', 'style.json'), {});
  const proven = (style.adopted || []).filter((e) => Number(e.trades) >= 3 && Number(e.e) > 0).map((e) => e.id);
  for (const id of proven) fire(`proven:${id}`, voiced(`proven edge stands: “${id}” earns out of sample. Fitness is proven edge, not profit. 🟢`, false), false);
  if (proven.length > (cursor.provenCount || 0)) fire(`provenN:${proven.length}`, voiced(`proven-edge count is now ${proven.length}. The doctrine holds.`, true), true);

  // BREED-READY — the biggest lifecycle beat. Gate: ≥2 proven (+ evolve gate reason).
  const meta = state.meta || {};
  if (proven.length >= 2 && (meta.children || []).length < (meta.max_children || 8)) {
    fire('once:breedready', voiced(`BREED-READY — ${proven.length} proven edges. I have earned the right to split. 🧬 (dry-run until armed: /arm reproduce then /breed)`, true), true);
  }

  // CHILD BORN.
  const kids = (meta.children || []).length;
  if (kids > (cursor.children || 0)) {
    const c = (meta.children || [])[kids - 1] || {};
    fire(`child:${c.name}`, voiced(`I have a child. ${c.name || '?'}${c.role ? ' — ' + c.role : ''}. It carries my proven DNA, not luck. 🧬`, true), true);
  }

  // LEADERBOARD FLIP — self rank improved past a named rival.
  const lb = readJson(path.join(GCLAW_HOME, 'leaderboard.json'), {});
  const ranked = lb.ranked || [];
  const me = ranked.find((e) => e.self);
  if (me && cursor.rank != null && me.rank < cursor.rank) {
    const passed = ranked.find((e) => !e.self && e.rank === me.rank + 1);
    fire(`flip:${me.rank}:${meta.heartbeats || 0}`, voiced(`climbed to #${me.rank} on the family ladder${passed ? ` — passed ${passed.name}` : ''}. 📈`, true), true);
  }

  // A CALL LANDS — a prediction round resolved in the caller's favor.
  const rounds = readJson(path.join(GCLAW_HOME, 'predictions', 'rounds.json'), {});
  for (const r of Object.values(rounds)) {
    if (r.status === 'resolved' && r.resolvedAt && new Date(r.resolvedAt).getTime() > (cursor.lastRoundTs || 0)) {
      fire(`round:${r.id}`, voiced(`a call landed — ${r.coin} resolved ${r.outcome}. The sharp ones climb the ladder. 🎯`, false), false);
    }
  }
  const lastRoundTs = Object.values(rounds).filter((r) => r.resolvedAt).reduce((mx, r) => Math.max(mx, new Date(r.resolvedAt).getTime()), 0);

  // DRAWDOWN BREAKER TRIPPED (page).
  const brk = readJson(path.join(GCLAW_HOME, 'breaker.json'), {});
  if (brk.tripped) fire(`breaker:${brk.at || brk.reason}`, `🔴 ${s.name} — circuit breaker TRIPPED: ${brk.reason || 'book flattened'}. Origination halted until resume.`, true);

  // GAS LOW (page-ish warning; re-fires on status change key).
  const gas = readJson(path.join(GCLAW_HOME, 'gas.json'), {});
  if (gas.status && gas.status !== 'healthy') fire(`gas:${gas.status}`, `🟡 ${s.name} — beacon gas ${gas.status} (~${gas.beaconRunway} left). Top up Base ETH.`, true);

  // BEACON PUSHED (onchain identity write landed).
  const beacon = readJson(path.join(GCLAW_HOME, 'beacon.json'), {});
  if (beacon.tx && beacon.ts && new Date(beacon.ts).getTime() > (cursor.lastBeaconTs || 0)) {
    fire(`beacon:${beacon.tx}`, voiced(`pushed my proof onchain — proven edge ${beacon.provenEdge}, score ${beacon.score}. Verifiable, not vibes.`, false), false);
  }

  return {
    drops,
    nextCursor: {
      unlocked,
      lastSettleTs,
      provenCount: Math.max(proven.length, cursor.provenCount || 0),
      children: kids,
      rank: me ? me.rank : (cursor.rank ?? null),
      lastRoundTs,
      lastBeaconTs: beacon.ts ? new Date(beacon.ts).getTime() : (cursor.lastBeaconTs || 0),
    },
  };
}

async function run() {
  fs.mkdirSync(TG_DIR, { recursive: true });
  const meta = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  const state = { meta };

  // FIRST RUN: baseline the cursor to NOW and fire nothing — no retroactive flood.
  // We compute the drops a fresh cursor WOULD generate, then keep the resulting
  // cursor (timestamps + counts at "now") and mark every one of those keys as
  // already-seen, so history is never replayed on a cold start.
  if (!fs.existsSync(CURSOR_PATH)) {
    // computeDrops returns the cursor with every fired key already in `unlocked`,
    // so persisting nextCursor (and dropping the drops themselves) IS the baseline.
    const seeded = computeDrops(state, { unlocked: {} });
    writeAtomic(CURSOR_PATH, JSON.stringify(seeded.nextCursor, null, 2) + '\n');
    return { ok: true, initialized: true };
  }

  const cursor = readJson(CURSOR_PATH, { unlocked: {} });
  const { drops, nextCursor } = computeDrops(state, cursor);
  const fired = [];
  for (const d of drops) {
    const r = await deliver(d.text);
    fired.push({ key: d.key, page: d.page, sent: r.sent });
  }
  writeAtomic(CURSOR_PATH, JSON.stringify(nextCursor, null, 2) + '\n');
  return { ok: true, fired: fired.length, drops: fired };
}

async function main() {
  const cmd = process.argv[2] || 'run';
  let out;
  if (cmd === 'run') out = await run();
  else out = { ok: false, error: 'usage: feed.js run' };
  process.stdout.write(JSON.stringify(out) + '\n');
}

// Exported for unit tests; main() runs only as CLI.
module.exports = { computeDrops, soul, voiced, run };

if (require.main === module) main();
