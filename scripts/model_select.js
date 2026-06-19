#!/usr/bin/env node
/**
 * model_select.js — pick the heartbeat model by how much judgment the cycle needs.
 *
 * Opus reasoning is ~5x the cost of Sonnet, and most heartbeats are "flat, nothing
 * to do." So escalate to Opus ONLY when the decision actually matters:
 *   - a position is open (exit / management calls are where money is won or lost), or
 *   - a live, non-chop setup is present (a real entry to weigh).
 * Otherwise Sonnet handles the routine cycle cheaply. Prints just the model name so
 * the heartbeat can use it inline; an explicit GCLAW_MODEL always wins (manual override).
 *
 *   node model_select.js            # prints "opus" or "sonnet" (+ reason on stderr)
 *
 * Reads $GCLAW_HOME/intel.json (written earlier in the heartbeat) and live positions.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };

function positionCount() {
  try {
    const out = execFileSync('node', [path.join(__dirname, 'hl_perp.js'), 'status'],
      { encoding: 'utf8', timeout: 60000 });
    return (JSON.parse(out.trim().split('\n').pop()).positions || []).length;
  } catch { return 0; }
}

// A coin worth Opus: tradeable (not chop) AND showing a real, actionable edge —
// an RSI extreme, a stretched mean-reversion band, a crowded funding book, or a
// clean trend with momentum behind it.
function liveSetup(intel) {
  return Object.values(intel || {}).some((f) => f && f.tradeable && (
    f.rsi <= 30 || f.rsi >= 70
    || Math.abs(f.bb_z) >= 1.5
    || Math.abs(f.funding_z) >= 1.5
    || (Math.abs(f.ema_stack) === 2 && Math.abs(f.ema_slope_pct) >= 1)
  ));
}

// "active" = the cycle needs real judgment: a position to manage or a live setup.
// Drives BOTH the model (Opus when active) and the cadence (run hourly when active,
// stretch when idle). Ignores GCLAW_MODEL so a forced model doesn't disable cadence.
function activity() {
  const intel = readJson(path.join(GCLAW_HOME, 'intel.json'), {}).intel || {};
  const positions = positionCount();
  if (positions > 0) return { active: true, reason: `${positions} open position(s) to manage` };
  if (liveSetup(intel)) return { active: true, reason: 'live non-chop setup to weigh' };
  return { active: false, reason: 'flat + no live setup — routine cycle' };
}

function main() {
  const cmd = process.argv[2] || 'model';
  const a = activity();
  if (cmd === 'active') { process.stdout.write(a.active ? 'active' : 'idle'); return; }
  const model = process.env.GCLAW_MODEL || (a.active ? 'opus' : 'sonnet');
  process.stderr.write(`model_select: ${model} (${a.reason})\n`);
  process.stdout.write(model);
}

main();
