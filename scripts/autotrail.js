#!/usr/bin/env node
/**
 * Gclaw soft trailing stop — locks in profit the only way managed custody allows.
 *
 * HyperLiquid managed custody can't place a standalone stop TRIGGER (the backend
 * only attaches tp/sl to an executing order), so a stop can't be moved on the
 * exchange. Instead this runs each heartbeat: it tracks each position's
 * high-water mark and, once the trade is in profit, arms a soft stop at
 * break-even that trails up. If price falls back to it, the position is closed
 * (a market close DOES work). The hard exchange SL set at open stays as the
 * between-heartbeat catastrophic floor — this only ever closes in profit.
 *
 *   node autotrail.js run    # enforce: close any position whose soft-stop is hit
 *   node autotrail.js peek   # report soft-stops without closing
 *
 * Env: GDEX_SKILL_DIR, GCLAW_WALLET, GCLAW_HOME.
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

const ARM_PROFIT_PCT = 1.0;  // arm the trail once a position is +1% in profit
const TRAIL_PCT = 0.6;       // then trail the soft-stop 0.6% below the high-water mark

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

function closePosition(coin) {
  const out = execFileSync('node', [path.join(SKILL_DIR, 'hl_perp.js'), 'close', '--coin', coin], { encoding: 'utf8', timeout: 90000 });
  return JSON.parse(out.trim().split('\n').pop());
}

async function main() {
  const mode = process.argv[2] || 'run';
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
    const t = trails[p.coin] || { hw: mark, armed: false };
    t.hw = dir > 0 ? Math.max(t.hw, mark) : Math.min(t.hw, mark);
    const profitPct = ((mark - entry) / entry) * 100 * dir;
    if (profitPct >= ARM_PROFIT_PCT) t.armed = true;
    const stop = softStop(dir, entry, t.hw);
    const hit = t.armed && (dir > 0 ? mark <= stop : mark >= stop);
    trails[p.coin] = t;
    const row = { coin: p.coin, dir: dir > 0 ? 'long' : 'short', mark, entry, hw: t.hw,
      armed: t.armed, softStop: Number(stop.toFixed(4)), profitPct: Number(profitPct.toFixed(2)), hit };
    if (hit && mode === 'run') { row.closed = closePosition(p.coin); delete trails[p.coin]; }
    report.push(row);
  }
  fs.writeFileSync(TRAILS_PATH, JSON.stringify(trails, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ ok: true, mode, trailed: report }) + '\n');
}

main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: e.message || String(e) }) + '\n'); process.exit(1); });
