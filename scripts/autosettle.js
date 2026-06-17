#!/usr/bin/env node
/**
 * Gclaw auto-settle — deterministically settle realized PnL from HL fills.
 *
 * When a position closes (TP/SL fires or a manual close), HyperLiquid records a
 * fill carrying `closedPnl`. This reads new fills for the managed account since a
 * stored cursor, nets `closedPnl - fee`, and calls `metabolism.py settle` exactly
 * once per close — no double counting, no reliance on the model reconciling by hand.
 *
 * Sub-cent remainders are carried in the cursor so nothing is lost or spammed.
 *
 *   node autosettle.js run      # settle new realized PnL, advance the cursor
 *   node autosettle.js peek     # report what would settle, without changing state
 *
 * Env: GDEX_SKILL_DIR, GCLAW_WALLET, GCLAW_HOME.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || path.join(os.homedir(), 'gdex-test-wallet.json');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const SDK = require(path.join(GDEX_DIR, 'dist'));

const CURSOR_PATH = path.join(GCLAW_HOME, 'autosettle.json');
const DUST = 0.01; // carry remainders below 1 cent rather than spam tiny settles

function loadCursor() {
  if (!fs.existsSync(CURSOR_PATH)) return { lastTime: 0, lastTids: [], residual: 0 };
  return JSON.parse(fs.readFileSync(CURSOR_PATH, 'utf8'));
}

function saveCursor(c) {
  fs.writeFileSync(CURSOR_PATH, JSON.stringify(c, null, 2) + '\n');
}

function managedAddress() {
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const a = w.managed?.['Arbitrum (HyperLiquid)']?.address;
  if (!a) throw new Error('wallet missing managed HL address');
  return a;
}

async function fetchFills(address) {
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY);
  const h = await skill.getHlTradeHistory(address);
  return Array.isArray(h) ? h : h.data || h.fills || h.history || [];
}

function selectNew(fills, cursor) {
  const seen = new Set(cursor.lastTids);
  return fills.filter((f) => f.time > cursor.lastTime || (f.time === cursor.lastTime && !seen.has(f.tid)));
}

function settle(pnl, note) {
  execFileSync('python3', [path.join(__dirname, 'metabolism.py'), 'settle', '--pnl', String(pnl), '--note', note], {
    env: { ...process.env, GCLAW_HOME },
    stdio: 'ignore',
  });
}

async function main() {
  const mode = process.argv[2] || 'run';
  if (!['run', 'peek'].includes(mode)) throw new Error('usage: autosettle.js <run|peek>');
  const firstRun = !fs.existsSync(CURSOR_PATH);
  const cursor = loadCursor();
  const fills = await fetchFills(managedAddress());

  // First ever run: baseline the cursor to the latest existing fill and settle
  // nothing — pre-baseline history (other sessions, old test trades) must not count.
  if (firstRun && mode === 'run' && fills.length) {
    const maxTime = Math.max(...fills.map((f) => f.time));
    saveCursor({ lastTime: maxTime, lastTids: fills.filter((f) => f.time === maxTime).map((f) => f.tid), residual: 0 });
    process.stdout.write(JSON.stringify({ ok: true, initialized: true, baselineFills: fills.length, settled: false }) + '\n');
    return;
  }

  const fresh = selectNew(fills, cursor);

  const closedPnl = fresh.reduce((s, f) => s + Number(f.closedPnl || 0), 0);
  const fees = fresh.reduce((s, f) => s + Number(f.fee || 0), 0);
  const net = Math.round((closedPnl - fees + (cursor.residual || 0)) * 1e6) / 1e6;
  const closes = fresh.filter((f) => Number(f.closedPnl || 0) !== 0).length;

  const summary = {
    ok: true,
    newFills: fresh.length,
    closes,
    closedPnl: Math.round(closedPnl * 1e6) / 1e6,
    fees: Math.round(fees * 1e6) / 1e6,
    netRealizedUsd: net,
  };

  if (mode === 'peek' || fresh.length === 0) {
    summary.settled = false;
    process.stdout.write(JSON.stringify(summary) + '\n');
    return;
  }

  // advance time cursor over all consumed fills
  const maxTime = Math.max(cursor.lastTime, ...fresh.map((f) => f.time));
  const tidsAtMax = fills.filter((f) => f.time === maxTime).map((f) => f.tid);
  let residual = net;
  let settled = false;
  if (Math.abs(net) >= DUST) {
    settle(net, `auto-settle: ${fresh.length} fills, ${closes} closes`);
    residual = 0;
    settled = true;
  }
  saveCursor({ lastTime: maxTime, lastTids: tidsAtMax, residual });
  summary.settled = settled;
  summary.carriedResidual = residual;
  process.stdout.write(JSON.stringify(summary) + '\n');
}

// The GDEX/HL SDK keeps a connection open that holds the event loop, so exit
// explicitly once the work is done instead of hanging until a timeout.
main()
  .then(() => process.exit(0))
  .catch((e) => {
    process.stdout.write(JSON.stringify({ ok: false, error: e.message || String(e) }) + '\n');
    process.exit(1);
  });
