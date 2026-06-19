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
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const SDK = require(path.join(GDEX_DIR, 'dist'));

const CURSOR_PATH = path.join(GCLAW_HOME, 'autosettle.json');
const DUST = 0.01; // carry remainders below 1 cent rather than spam tiny settles

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };

// One regime read per settle for the coins that just closed — tags each memory
// record with the market conditions it happened in.
function fetchRegimes(coins) {
  if (!coins.length) return {};
  try {
    const out = execFileSync('node', [path.join(__dirname, 'intel.js'), 'regime', '--coins', coins.join(',')],
      { env: { ...process.env, GCLAW_HOME }, timeout: 30000 }).toString();
    const r = JSON.parse(out.slice(out.indexOf('{'))).regimes || {};
    return Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v && v.regime]));
  } catch { return {}; }
}

function loadCursor() {
  if (!fs.existsSync(CURSOR_PATH)) return { lastTime: 0, lastTids: [], residual: 0 };
  return JSON.parse(fs.readFileSync(CURSOR_PATH, 'utf8'));
}

function writeAtomic(p, data) {
  const tmp = `${p}.tmp${process.pid}`;
  fs.writeFileSync(tmp, data);
  fs.renameSync(tmp, p); // atomic on the same filesystem — a reader never sees a half-write
}

function saveCursor(c) {
  writeAtomic(CURSOR_PATH, JSON.stringify(c, null, 2) + '\n');
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

// Perp funding (longs pay shorts hourly) is realized PnL too, but never appears
// as a fill — pull it from HL's public ledger so the books don't drift.
async function fetchFunding(address, startTime) {
  const res = await fetch('https://api.hyperliquid.xyz/info', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ type: 'userFunding', user: address, startTime: Math.max(0, startTime || 0) }),
  });
  if (!res.ok) return [];
  const rows = await res.json();
  return (Array.isArray(rows) ? rows : []).map((x) => ({ time: x.time, usdc: Number(x.delta?.usdc || 0) }));
}

function selectNew(fills, cursor) {
  const seen = new Set(cursor.lastTids);
  return fills.filter((f) => f.time > cursor.lastTime || (f.time === cursor.lastTime && !seen.has(f.tid)));
}

function settle(pnl, note) {
  // Use `uv run --no-project python3` — bare python3 is blocked on this box and is
  // not guaranteed on PATH. This is the only path that books PnL and awards goodwill,
  // so it must not fail silently; surface stderr if metabolism.py errors.
  execFileSync('uv', ['run', '--no-project', 'python3', path.join(__dirname, 'metabolism.py'),
    'settle', '--pnl', String(pnl), '--note', note], {
    env: { ...process.env, GCLAW_HOME },
    stdio: ['ignore', 'ignore', 'inherit'],
  });
}

async function main() {
  const mode = process.argv[2] || 'run';
  if (!['run', 'peek'].includes(mode)) throw new Error('usage: autosettle.js <run|peek>');
  const firstRun = !fs.existsSync(CURSOR_PATH);
  const cursor = loadCursor();
  const address = managedAddress();
  const fills = await fetchFills(address);
  const funding = await fetchFunding(address, firstRun ? 0 : cursor.lastFundingTime || 0);

  // First ever run: baseline the cursors to the latest existing fill/funding and
  // settle nothing — pre-baseline history must not count.
  if (firstRun && mode === 'run' && fills.length) {
    const maxTime = Math.max(...fills.map((f) => f.time));
    const maxFunding = funding.length ? Math.max(...funding.map((x) => x.time)) : 0;
    saveCursor({ lastTime: maxTime, lastTids: fills.filter((f) => f.time === maxTime).map((f) => f.tid), residual: 0, lastFundingTime: maxFunding });
    process.stdout.write(JSON.stringify({ ok: true, initialized: true, baselineFills: fills.length, settled: false }) + '\n');
    return;
  }

  const fresh = selectNew(fills, cursor);
  const freshFunding = funding.filter((x) => x.time > (cursor.lastFundingTime || 0));

  const closedPnl = fresh.reduce((s, f) => s + Number(f.closedPnl || 0), 0);
  const fees = fresh.reduce((s, f) => s + Number(f.fee || 0), 0);
  const fundingPnl = freshFunding.reduce((s, x) => s + x.usdc, 0);
  const net = Math.round((closedPnl - fees + fundingPnl + (cursor.residual || 0)) * 1e6) / 1e6;
  const closes = fresh.filter((f) => Number(f.closedPnl || 0) !== 0).length;
  const maxFundingTime = freshFunding.reduce((m, x) => Math.max(m, x.time), cursor.lastFundingTime || 0);

  const summary = {
    ok: true,
    newFills: fresh.length,
    closes,
    closedPnl: Math.round(closedPnl * 1e6) / 1e6,
    fees: Math.round(fees * 1e6) / 1e6,
    fundingPnl: Math.round(fundingPnl * 1e6) / 1e6,
    netRealizedUsd: net,
  };

  if (mode === 'peek' || (fresh.length === 0 && freshFunding.length === 0)) {
    summary.settled = false;
    process.stdout.write(JSON.stringify(summary) + '\n');
    return;
  }

  // advance time cursors over all consumed fills + funding
  const maxTime = Math.max(cursor.lastTime, ...(fresh.length ? fresh.map((f) => f.time) : [cursor.lastTime]));
  const tidsAtMax = fills.filter((f) => f.time === maxTime).map((f) => f.tid);
  const willSettle = Math.abs(net) >= DUST;
  let residual = willSettle ? 0 : net;
  let settled = false;
  // Advance the cursor BEFORE settling so a crash between settle() and the cursor
  // write can't re-read the same fills and double-book the PnL. Fail-conservative:
  // a crash mid-settle drops this batch (under-counts) rather than double-counting.
  saveCursor({ lastTime: maxTime, lastTids: tidsAtMax, residual, lastFundingTime: maxFundingTime });
  if (willSettle) {
    settle(net, `auto-settle: ${fresh.length} fills, ${closes} closes, funding ${summary.fundingPnl}`);
    settled = true;
    const closers = fresh.filter((x) => Number(x.closedPnl || 0) !== 0);
    const regimes = fetchRegimes([...new Set(closers.map((f) => f.coin))]);
    const openRisk = readJson(path.join(GCLAW_HOME, 'open_risk.json'), {});
    // Auto-attribute each closing fill to its technique's author (royalty) AND
    // record the outcome to the trade-memory (technique x regime -> R) so the agent
    // learns which techniques actually work in which conditions.
    for (const f of closers) {
      let technique = '';
      try {
        const out = execFileSync('uv', ['run', '--no-project', 'python3', path.join(__dirname, 'forge.py'),
          'royalty', '--coin', String(f.coin), '--pnl', String(f.closedPnl), '--auto'],
        { env: { ...process.env, GCLAW_HOME }, stdio: ['ignore', 'pipe', 'ignore'] });
        technique = JSON.parse(out.toString()).technique || '';
      } catch { /* attribution is best-effort */ }
      try {
        // open_risk.json entry may be a bare risk number or {risk, technique} the
        // agent labelled at entry. Fall back to "discretionary" (a learnable bucket).
        const orec = openRisk[f.coin];
        const labelled = orec && typeof orec === 'object' ? orec : { risk: orec };
        const notional = Math.abs(Number(f.sz || 0)) * Number(f.px || 0);
        const risk = labelled.risk || notional * 0.015 || 0.25; // sized risk, else 1.5%-stop estimate
        const tech = technique || labelled.technique || 'discretionary';
        const side = String(f.dir || '').includes('Short') ? 'short' : 'long';
        execFileSync('uv', ['run', '--no-project', 'python3', path.join(__dirname, 'memory.py'),
          'record', '--coin', String(f.coin), '--technique', String(tech),
          '--regime', regimes[f.coin] || 'unknown', '--side', side,
          '--pnl', String(f.closedPnl), '--risk', String(risk)],
        { env: { ...process.env, GCLAW_HOME }, stdio: ['ignore', 'ignore', 'ignore'] });
      } catch { /* memory record is best-effort */ }
    }
  }
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
