#!/usr/bin/env node
/**
 * model_select.js — pick the heartbeat model by how much judgment the cycle needs.
 *
 * Opus reasoning is ~5x the cost of Sonnet, and most heartbeats are "flat, nothing
 * to do." Origination is forge-only, so the LLM does not open on setups it sees — it
 * needs Opus ONLY when a position is open (exit / management calls are where money is
 * won or lost). A flat book is the Scientist's research cycle and runs on Sonnet.
 * Prints just the model name so the heartbeat can use it inline; an explicit
 * GCLAW_MODEL always wins (manual override).
 *
 *   node model_select.js            # prints "opus" or "sonnet" (+ reason on stderr)
 *
 * Reads $GCLAW_HOME/intel.json (written earlier in the heartbeat) and live positions.
 */
'use strict';

const path = require('node:path');
const { execFileSync } = require('node:child_process');

// GCLAW_HOME is read from the environment by the hl_perp.js child (inherited via execFileSync),
// so it is intentionally not referenced here — position state is the only input this needs.
function positionCount() {
  try {
    const out = execFileSync('node', [path.join(__dirname, 'hl_perp.js'), 'status', '--cache'],
      { encoding: 'utf8', timeout: 60000 });
    return (JSON.parse(out.trim().split('\n').pop()).positions || []).length;
  } catch { return 0; }
}

// Escalating to Opus on a raw market dislocation was the bug behind 442/442 Opus
// cycles (assune-d39.10): with ~18 coins scanned, some coin always showed an RSI
// extreme or a stretched band, so the "live setup" trigger fired every hour and the
// Sonnet idle path never once ran. But origination is forge-only now — the LLM does
// NOT open on a setup it sees, so a raw dislocation is not actionable work for it.
// The LLM needs Opus only when there is a POSITION to manage (where exits win/lose
// money); a flat book is the Scientist's research cycle, which runs fine on Sonnet
// (and the fixed backtest JUDGE rigorously validates whatever it authors). If the
// forge opened this cycle, that shows up as an open position below.

// Pinned model ids — never the CLI's floating `sonnet`/`opus` aliases, so a CLI update can't
// silently swap the heartbeat onto a different model. Sonnet 5 for idle research cycles,
// Opus 4.8 for judgment-heavy active management.
const SONNET = 'claude-sonnet-5';
const OPUS = 'claude-opus-4-8';

// "active" = the cycle needs real judgment: a position to manage or a live setup.
// Drives BOTH the model (Opus when active) and the cadence (run hourly when active,
// stretch when idle). Ignores GCLAW_MODEL so a forced model doesn't disable cadence.
function activity() {
  const positions = positionCount();
  if (positions > 0) return { active: true, reason: `${positions} open position(s) to manage` };
  return { active: false, reason: 'flat book — Scientist research cycle (Sonnet)' };
}

function main() {
  const cmd = process.argv[2] || 'model';
  const a = activity();
  if (cmd === 'active') { process.stdout.write(a.active ? 'active' : 'idle'); return; }
  const model = process.env.GCLAW_MODEL || (a.active ? OPUS : SONNET);
  process.stderr.write(`model_select: ${model} (${a.reason})\n`);
  process.stdout.write(model);
}

main();
