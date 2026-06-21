#!/usr/bin/env node
/**
 * "Call it" — the free, custody-free, onchain-anchored prediction game.
 *
 * When a creature opens a trade, a prediction ROUND opens: anyone calls TP or SL
 * (free, no stake, no funds anywhere). The set of open rounds + their calls is
 * hashed into a `predictionsRoot` that the beacon anchors onchain BEFORE the
 * trade resolves — so a call can't be backdated and the operator can't fudge a
 * round. Resolution reads HyperLiquid's own fills, so the outcome is trustless.
 *
 *   node predict.js open               # open rounds for the creature's live trades
 *   node predict.js call --round <id> --pick TP|SL --by <handle> [--sig <sig>]
 *   node predict.js resolve            # score rounds whose trade has closed
 *   node predict.js root               # keccak root of open rounds+calls (for the beacon)
 *   node predict.js leaderboard        # rank this creature's predictors
 *   node predict.js global             # GLOBAL ladder — every predictor across every creature
 *
 * Pure clout: points are never money, never redeemable, never purchasable — so
 * it is not gambling and holds no funds. Env: GDEX_SKILL_DIR, GCLAW_WALLET, GCLAW_HOME.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
// Lazy keccak — only the root/roundId paths need ethers, so the file-io helpers
// (readJson/readJsonl/writeAtomic) and resolve logic stay unit-testable without it.
const ethers = () => require(path.join(GDEX_DIR, 'node_modules', 'ethers')).ethers;
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p));
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const DIR = path.join(GCLAW_HOME, 'predictions');
const SKILL_DIR = path.join(os.homedir(), '.claude', 'skills', 'gclaw', 'scripts');

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };
// Atomic write — the 2-min Telegram poll reads these files concurrently; a direct
// writeFileSync truncates-then-writes, so a concurrent reader can catch a half-file
// and drop a call. temp + rename is atomic on the same filesystem.
const writeAtomic = (p, data) => { const t = `${p}.tmp${process.pid}`; fs.writeFileSync(t, data); fs.renameSync(t, p); };
// Parse a JSONL ledger line-by-line, SKIPPING any torn/partial line rather than losing
// the whole file (an append-only log can have one half-written tail line after a crash).
const readJsonl = (p) => {
  let lines;
  try { lines = fs.readFileSync(p, 'utf8').split('\n'); } catch { return []; }
  const out = [];
  for (const l of lines) { if (!l.trim()) continue; try { out.push(JSON.parse(l)); } catch { /* skip the torn line */ } }
  return out;
};
const agentId = () => String(readJson(path.join(GCLAW_HOME, 'metabolism.json'), {}).onchain_identity?.agentId || '0');
const managed = () => JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8')).managed?.['Arbitrum (HyperLiquid)']?.address;

function hlInfo(body) {
  return new Promise((resolve) => {
    const d = JSON.stringify(body);
    const r = https.request('https://api.hyperliquid.xyz/info', { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': d.length } },
      (x) => { let b = ''; x.on('data', (c) => { b += c; }); x.on('end', () => { try { resolve(JSON.parse(b)); } catch { resolve(null); } }); });
    r.on('error', () => resolve(null));
    r.write(d); r.end();
  });
}

function position() {
  const { execFileSync } = require('node:child_process');
  try {
    const out = execFileSync('node', [path.join(SKILL_DIR, 'hl_perp.js'), 'status', '--cache'], { encoding: 'utf8', timeout: 90000 });
    return JSON.parse(out.trim().split('\n').pop());
  } catch { return { positions: [], openOrders: [] }; }
}

function soulName() {
  const m = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  const p = readJson(path.join(GCLAW_HOME, 'dna', 'persona.json'), {});
  return m.name || p.species || 'Gclaw';
}
async function announce(text) {
  const tg = process.env.GCLAW_TELEGRAM_TOKEN, chat = process.env.GCLAW_TELEGRAM_CHAT, hook = process.env.GCLAW_ALERT_WEBHOOK;
  const post = (url, body) => new Promise((res) => { const d = JSON.stringify(body); const r = https.request(url, { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': d.length } }, (x) => { x.on('data', () => {}); x.on('end', res); }); r.on('error', res); r.write(d); r.end(); });
  if (tg && chat) await post(`https://api.telegram.org/bot${tg}/sendMessage`, { chat_id: chat, text });
  if (hook) await post(hook, { text, content: text });
}

const roundsPath = () => path.join(DIR, 'rounds.json');
const callsPath = () => path.join(DIR, 'calls.jsonl');
const predictorsPath = () => path.join(DIR, 'predictors.json');

function roundId(coin, entry) { return ethers().id(`${agentId()}|${coin}|${entry}`).slice(0, 12); }

// keccak of the open rounds + their calls — anchored onchain so nothing backdates.
function writeRoot() {
  const rounds = readJson(roundsPath(), {});
  const open = Object.values(rounds).filter((r) => r.status === 'open').sort((a, b) => a.id.localeCompare(b.id));
  const calls = readJsonl(callsPath());
  const payload = open.map((r) => ({ id: r.id, coin: r.coin, side: r.side, entry: r.entry, openedAt: r.openedAt,
    calls: calls.filter((c) => c.roundId === r.id).map((c) => `${c.by}:${c.pick}:${c.ts}`).sort() }));
  const root = ethers().id(JSON.stringify(payload));
  writeAtomic(path.join(DIR, 'root.json'), JSON.stringify({ root, openRounds: open.map((r) => r.id), updatedAt: new Date().toISOString() }, null, 2) + '\n');
  return root;
}

async function cmdOpen(args) {
  fs.mkdirSync(DIR, { recursive: true });
  const st = position();
  const rounds = readJson(roundsPath(), {});
  const opened = [];
  for (const p of st.positions || []) {
    const id = roundId(p.coin, p.entryPx);
    if (rounds[id]) continue;
    const dir = Number(p.size) > 0 ? 'long' : 'short';
    const orders = (st.openOrders || []).filter((o) => o.coin === p.coin).map((o) => Number(o.px));
    rounds[id] = { id, agentId: agentId(), coin: p.coin, side: dir, entry: Number(p.entryPx),
      tp: dir === 'long' ? Math.max(...orders, 0) || null : Math.min(...orders) || null,
      sl: dir === 'long' ? Math.min(...orders) || null : Math.max(...orders, 0) || null,
      openedAt: new Date().toISOString(), status: 'open', outcome: null };
    opened.push(rounds[id]);
  }
  writeAtomic(roundsPath(), JSON.stringify(rounds, null, 2));
  writeRoot();
  if (args.announce) for (const r of opened) await announce(`🎯 ${soulName()} just opened ${r.coin} ${r.side} @ $${r.entry}.\nCall it — reply TP or SL. (round ${r.id})`);
  return { ok: true, opened, openRounds: Object.values(rounds).filter((r) => r.status === 'open').map((r) => ({ id: r.id, coin: r.coin, side: r.side })) };
}

function cmdCall(args) {
  const rounds = readJson(roundsPath(), {});
  const r = rounds[args.round];
  if (!r) return { ok: false, error: `no round ${args.round}` };
  if (r.status !== 'open') return { ok: false, error: 'round already resolved — calls closed' };
  const pick = String(args.pick || '').toUpperCase();
  if (!['TP', 'SL'].includes(pick)) return { ok: false, error: 'pick must be TP or SL' };
  const by = String(args.by || 'anon').slice(0, 40);
  const calls = readJsonl(callsPath());
  if (calls.some((c) => c.roundId === r.id && c.by === by)) return { ok: false, error: 'already called this round' };
  const entry = { roundId: r.id, by, pick, ts: new Date().toISOString(), sig: args.sig || null };
  fs.appendFileSync(callsPath(), JSON.stringify(entry) + '\n');
  writeRoot();
  return { ok: true, called: entry };
}

async function cmdResolve(args) {
  const rounds = readJson(roundsPath(), {});
  const ttlMs = (Number(process.env.GCLAW_ROUND_TTL_DAYS) || 14) * 24 * 3600 * 1000;
  // Prune terminal rounds past the TTL so rounds.json can't grow unbounded — and so a
  // re-entry at the same price isn't blocked by a stale same-id round (roundId is keyed
  // on entry price). The durable record is the predictors ladder + calls.jsonl, not this
  // working set. Runs before the open-rounds early return so it can't be starved.
  const cutoff = Date.now() - ttlMs;
  let pruned = 0;
  for (const [id, r] of Object.entries(rounds)) {
    if (r.status !== 'open' && new Date(r.resolvedAt || r.openedAt).getTime() < cutoff) {
      delete rounds[id]; pruned += 1;
    }
  }
  const open = Object.values(rounds).filter((r) => r.status === 'open');
  if (!open.length) {
    if (pruned) writeAtomic(roundsPath(), JSON.stringify(rounds, null, 2));
    return { ok: true, resolved: [], ...(pruned ? { pruned } : {}) };
  }
  const live = new Set((position().positions || []).map((p) => p.coin));
  const fills = (await hlInfo({ type: 'userFills', user: managed() })) || [];
  const calls = readJsonl(callsPath());
  const predictors = readJson(predictorsPath(), {});
  const resolved = [];
  const expired = [];
  for (const r of open) {
    if (live.has(r.coin)) {
      // A coin that's still (or perpetually) a live position can't resolve. Expire
      // a stale one so it stops bloating the root + open list forever. No scoring.
      if (Date.now() - new Date(r.openedAt).getTime() > ttlMs) {
        r.status = 'expired'; r.resolvedAt = new Date().toISOString(); expired.push(r.id);
      }
      continue;
    }
    const since = new Date(r.openedAt).getTime();
    const close = fills.filter((f) => f.coin === r.coin && Number(f.closedPnl || 0) !== 0 && f.time >= since)
      .reduce((s, f) => s + Number(f.closedPnl), 0);
    const outcome = close > 0 ? 'TP' : 'SL';
    r.status = 'resolved'; r.outcome = outcome; r.pnl = Math.round(close * 100) / 100; r.resolvedAt = new Date().toISOString();
    for (const c of calls.filter((x) => x.roundId === r.id)) {
      const p = predictors[c.by] || { correct: 0, total: 0, streak: 0, best: 0 };
      p.total += 1;
      if (c.pick === outcome) { p.correct += 1; p.streak += 1; p.best = Math.max(p.best, p.streak); } else { p.streak = 0; }
      predictors[c.by] = p;
    }
    const winners = calls.filter((x) => x.roundId === r.id && x.pick === outcome).map((x) => x.by);
    resolved.push({ id: r.id, coin: r.coin, outcome, pnl: r.pnl, winners });
    if (args && args.announce) {
      const who = winners.length ? `${winners.slice(0, 5).join(', ')} called it right ✅` : 'nobody saw it coming';
      await announce(`🏁 ${soulName()}'s ${r.coin} → ${outcome} (${r.pnl >= 0 ? '+' : ''}$${r.pnl}).\n${who}`);
    }
  }
  writeAtomic(roundsPath(), JSON.stringify(rounds, null, 2));
  writeAtomic(predictorsPath(), JSON.stringify(predictors, null, 2));
  writeRoot();
  return { ok: true, resolved, ...(expired.length ? { expired } : {}), ...(pruned ? { pruned } : {}) };
}

function cmdLeaderboard() {
  const predictors = readJson(predictorsPath(), {});
  const board = Object.entries(predictors).map(([by, p]) => ({ by, ...p,
    accuracy: p.total ? Math.round((p.correct / p.total) * 100) : 0 }))
    .sort((a, b) => b.accuracy - a.accuracy || b.correct - a.correct);
  board.forEach((e, i) => { e.rank = i + 1; });
  return { ok: true, predictors: board };
}

// The GLOBAL ladder: sum every predictor's record across EVERY creature — peers
// read from their onchain cards (peers_roster.json), self from the freshest local
// tallies. A handle that called on several creatures aggregates into one rank, so
// the board ranks humans community-wide, not per-creature.
function cmdGlobal() {
  const agg = {};
  const add = (by, c, t) => { const k = String(by); const e = agg[k] || { correct: 0, total: 0, creatures: 0 }; e.correct += c; e.total += t; e.creatures += t > 0 ? 1 : 0; agg[k] = e; };
  for (const a of readJson(path.join(GCLAW_HOME, 'peers_roster.json'), {}).roster || []) {
    if (a.self) continue; // self folded from fresh local tallies below (avoids double-count + lag)
    for (const p of a.predictors || []) add(p.by, p.c || 0, p.t || 0);
  }
  for (const [by, v] of Object.entries(readJson(predictorsPath(), {}))) add(by, v.correct || 0, v.total || 0);
  const board = Object.entries(agg).map(([by, e]) => ({ by, correct: e.correct, total: e.total, creatures: e.creatures,
    accuracy: e.total ? Math.round((e.correct / e.total) * 100) : 0 }))
    .filter((e) => e.total > 0).sort((a, b) => b.accuracy - a.accuracy || b.correct - a.correct);
  board.forEach((e, i) => { e.rank = i + 1; });
  return { ok: true, global: true, predictors: board };
}

function parseArgs(a) { const o = {}; for (let i = 0; i < a.length; i += 1) if (a[i].startsWith('--')) { o[a[i].slice(2)] = a[i + 1] && !a[i + 1].startsWith('--') ? a[i += 1] : true; } return o; }

async function main() {
  const cmd = process.argv[2];
  const args = parseArgs(process.argv.slice(3));
  let out;
  if (cmd === 'open') out = await cmdOpen(args);
  else if (cmd === 'call') out = cmdCall(args);
  else if (cmd === 'resolve') out = await cmdResolve(args);
  else if (cmd === 'root') out = { ok: true, ...readJson(path.join(DIR, 'root.json'), { root: writeRoot() }) };
  else if (cmd === 'leaderboard') out = cmdLeaderboard();
  else if (cmd === 'global') out = cmdGlobal();
  else out = { ok: false, error: 'usage: predict.js <open|call|resolve|root|leaderboard|global>' };
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

// Pure / file-io helpers exported for unit testing; main() runs only as a CLI.
module.exports = { readJson, readJsonl, writeAtomic, cmdCall, cmdResolve };

if (require.main === module) {
  main().then(() => process.exit(0)).catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: e.message }) + '\n'); process.exit(1); });
}
