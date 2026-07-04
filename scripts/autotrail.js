#!/usr/bin/env node
/**
 * Gclaw exit manager — enforces the disposition-inverse discipline of proven winners:
 * let winners run, cut losers fast.
 *
 * HyperLiquid managed custody can't place a standalone stop TRIGGER (the backend
 * only attaches tp/sl to an executing order), so a stop can't be moved on the
 * exchange. Instead this runs each heartbeat over the open book:
 *
 *  1. WINNERS — track each position's high-water mark; once solidly in profit (~1R)
 *     arm a soft stop at break-even that trails up. If price falls back to it, close
 *     in profit (a market close DOES work).
 *  2. LOSERS — a position that never worked (never armed), is genuinely underwater,
 *     and has stalled past its short leash is time-stopped: closed early at a small
 *     loss rather than left to run to the full hard stop. Reverse-engineered from
 *     skill-proven wallets, which hold winners ~3.47x longer than losers.
 *
 * The hard exchange SL set at open stays as the between-heartbeat catastrophic floor.
 *
 *   node autotrail.js run    # enforce: close any position whose exit rule fires
 *   node autotrail.js peek   # report exit decisions without closing
 *
 * Env: GDEX_SKILL_DIR, GCLAW_WALLET, GCLAW_HOME, GCLAW_LOSER_STOP_H, GCLAW_LOSER_STOP_PCT.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');
const { execFileSync } = require('node:child_process');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const SKILL_DIR = path.join(os.homedir(), '.claude', 'skills', 'gclaw', 'scripts');
const TRAILS_PATH = path.join(GCLAW_HOME, 'trails.json');

// Let winners RUN to their take-profit. Arming at +1% and trailing 0.6% choked every
// winner to ~break-even (avg +$0.14) while losers ran to the full hard stop (avg -$1.42)
// — a structurally -EV asymmetry. The hard SL/TP set at open are the primary brackets;
// this soft trail only protects a position that has run solidly into profit (~1R) and
// then reverses hard, so it can't fire on ordinary hourly noise before the TP is reached.
const ARM_PROFIT_PCT = 2.5;  // arm only once a position is +2.5% (well past noise, near 1R)
const TRAIL_PCT = 1.5;       // then trail 1.5% below the high-water — wider than a normal pullback

// Loser time-stop: cut a trade that never worked. Winners run to TP (arm + trail, hours
// to days); a loser that never armed, is genuinely underwater, and has stalled past this
// short leash is closed early at a small loss. LEASH ~= a slow-book winner's hold / 3.47
// (the measured winner:loser hold ratio of skill-proven wallets). Widen the leash or set
// GCLAW_LOSER_STOP_H=0 to disable.
const LOSER_STOP_HOURS = Number(process.env.GCLAW_LOSER_STOP_H || 6);
const LOSER_STOP_PCT = -Math.abs(Number(process.env.GCLAW_LOSER_STOP_PCT || 0.8));

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };

function allMids() {
  return new Promise((resolve) => {
    const body = JSON.stringify({ type: 'allMids' });
    const req = https.request('https://api.hyperliquid.xyz/info',
      { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': body.length } },
      (res) => { let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => { try { resolve(JSON.parse(b)); } catch { resolve({}); } }); });
    req.on('error', () => resolve({}));
    req.write(body); req.end();
  });
}

function positions() {
  // Best-effort: a transient status failure means "nothing to trail this cycle"
  // (the hard exchange SL still protects), never an error that noise-spams the log.
  try {
    const out = execFileSync('node', [path.join(SKILL_DIR, 'hl_perp.js'), 'status', '--cache'], { encoding: 'utf8', timeout: 90000 });
    return JSON.parse(out.trim().split('\n').pop()).positions || [];
  } catch {
    return [];
  }
}

function softStop(dir, entry, hw) {
  // Floored at break-even, trails by TRAIL_PCT below (long) / above (short) the high-water.
  const trailed = dir > 0 ? hw * (1 - TRAIL_PCT / 100) : hw * (1 + TRAIL_PCT / 100);
  return dir > 0 ? Math.max(entry, trailed) : Math.min(entry, trailed);
}

/**
 * Decide the exit action for one position and advance its trail state in place.
 *
 * Pure over (t, dir, entry, mark, nowMs) so the exit policy is unit-testable. Mutates
 * `t.hw`/`t.armed`/`t.opened`; returns the decision without touching the exchange.
 *
 * @param {{hw:number, armed:boolean, opened?:number}} t - per-position trail state.
 * @param {number} dir - +1 long, -1 short.
 * @param {number} entry - entry price.
 * @param {number} mark - current mark price.
 * @param {number} nowMs - current epoch ms (position age reference).
 * @returns {{action:string, profitPct:number, softStop:number, ageH:number}} the decision.
 */
function decideExit(t, dir, entry, mark, nowMs) {
  if (!t.opened) t.opened = nowMs;
  t.hw = dir > 0 ? Math.max(t.hw, mark) : Math.min(t.hw, mark);
  const profitPct = ((mark - entry) / entry) * 100 * dir;
  if (profitPct >= ARM_PROFIT_PCT) t.armed = true;
  const stop = softStop(dir, entry, t.hw);
  const trailHit = t.armed && (dir > 0 ? mark <= stop : mark >= stop);
  const ageH = (nowMs - t.opened) / 3_600_000;
  // A trade that never armed (never worked), is truly underwater, and has stalled past
  // the short leash is cut early — the disposition-inverse rule from proven winners.
  const loserTimeout =
    LOSER_STOP_HOURS > 0 && !t.armed && profitPct <= LOSER_STOP_PCT && ageH >= LOSER_STOP_HOURS;
  const action = trailHit ? 'trail' : loserTimeout ? 'loser-timestop' : 'hold';
  return { action, profitPct, softStop: stop, ageH };
}

function closePosition(coin) {
  const out = execFileSync('node', [path.join(SKILL_DIR, 'hl_perp.js'), 'close', '--coin', coin], { encoding: 'utf8', timeout: 90000 });
  return JSON.parse(out.trim().split('\n').pop());
}

async function main() {
  const mode = process.argv[2] || 'run';
  const now = Date.now();
  const mids = await allMids();
  const trails = readJson(TRAILS_PATH, {});
  const pos = positions();
  const live = new Set(pos.map((p) => p.coin));
  for (const k of Object.keys(trails)) if (!live.has(k)) delete trails[k];  // forget closed

  const report = [];
  for (const p of pos) {
    const dir = Number(p.size) > 0 ? 1 : -1;
    const entry = Number(p.entryPx);
    const mark = Number(mids[p.coin]) || (entry + Number(p.unrealizedPnl || 0) / Number(p.size));
    const t = trails[p.coin] || { hw: mark, armed: false, opened: now };
    const d = decideExit(t, dir, entry, mark, now);
    trails[p.coin] = t;
    const row = { coin: p.coin, dir: dir > 0 ? 'long' : 'short', mark, entry, hw: t.hw,
      armed: t.armed, softStop: Number(d.softStop.toFixed(4)), profitPct: Number(d.profitPct.toFixed(2)),
      ageH: Number(d.ageH.toFixed(1)), action: d.action };
    if (d.action !== 'hold' && mode === 'run') { row.closed = closePosition(p.coin); delete trails[p.coin]; }
    report.push(row);
  }
  fs.writeFileSync(TRAILS_PATH, JSON.stringify(trails, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ ok: true, mode, trailed: report }) + '\n');
}

if (require.main === module) {
  main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: e.message || String(e) }) + '\n'); process.exit(1); });
}

module.exports = { decideExit, softStop };
