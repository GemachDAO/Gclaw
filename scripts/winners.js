#!/usr/bin/env node
/**
 * Gclaw reverse-engineering feed — thin wrapper over the shared GDEX SDK.
 *
 * The forensics logic (pull skill-proven wallets, decompose them into
 * size-invariant patterns) now lives in the GDEX product as
 * `GdexSkill.reverseEngineerWinners()` + the `reverse_engineer_winners` MCP tool,
 * so every agent shares one implementation. This wrapper is gclaw's downstream
 * consumer: it runs the method with the local watchlist and writes the artifact
 * the briefing's Reverse-engineering desk reads.
 *
 * READ-ONLY — the SDK method only reads public HL data; it never trades.
 *
 * Env:
 *   GDEX_SKILL_DIR  SDK location (default ~/gdex-skill) — supplies dist
 *   GDEX_API_KEY    overrides the SDK's shared primary key
 *   GCLAW_HOME      state root (default ~/.gclaw) — output lands in $GCLAW_HOME/forge
 *
 * Usage:
 *   node winners.js pull [--max N]      # default N=12; writes forge/winner_intel.json
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const FORGE_DIR = path.join(GCLAW_HOME, 'forge');
const OUT_PATH = path.join(FORGE_DIR, 'winner_intel.json');
const WATCHLIST_PATH = path.join(FORGE_DIR, 'watchlist.json');
const DEFAULT_MAX = 12;

/**
 * Load the curated watchlist of HL wallet addresses, if present.
 *
 * The dollar-PnL board is dominated by un-clonable market-makers, so a curated
 * watchlist ($GCLAW_HOME/forge/watchlist.json — a JSON array of "0x…" addresses
 * or {address} objects) is the reliable universe of clonable directional traders.
 *
 * @returns {Array<string>} lowercased addresses (empty if the file is absent/bad).
 */
function loadWatchlist() {
  try {
    const raw = JSON.parse(fs.readFileSync(WATCHLIST_PATH, 'utf8'));
    const list = Array.isArray(raw) ? raw : raw.wallets || [];
    return list
      .map((w) => (typeof w === 'string' ? w : w && w.address))
      .filter((a) => typeof a === 'string' && /^0x[0-9a-fA-F]{40}$/.test(a))
      .map((a) => a.toLowerCase());
  } catch {
    return [];
  }
}

/**
 * Load the GDEX SDK and return a shared-key-authenticated read client.
 *
 * @returns {object} an authenticated GdexSkill instance.
 */
function readClient() {
  const SDK = require(path.join(GDEX_DIR, 'dist'));
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY);
  return skill;
}

/**
 * Parse `pull` argv into options.
 *
 * @param {Array<string>} argv process argv slice after the subcommand.
 * @returns {{max: number}} parsed options.
 */
function parseArgs(argv) {
  let max = DEFAULT_MAX;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--max') {
      max = Math.max(1, parseInt(argv[i + 1], 10) || DEFAULT_MAX);
      i += 1;
    }
  }
  return { max };
}

async function main() {
  const [, , cmd, ...rest] = process.argv;
  if (cmd !== 'pull') {
    process.stderr.write('usage: node winners.js pull [--max N]\n');
    process.exit(2);
  }
  const { max } = parseArgs(rest);
  const watchlist = loadWatchlist();
  const skill = readClient();
  const intel = await skill.reverseEngineerWinners({ watchlist, max });

  fs.mkdirSync(FORGE_DIR, { recursive: true });
  fs.writeFileSync(OUT_PATH, JSON.stringify(intel) + '\n');
  const u = (intel && intel.universe) || {};
  process.stderr.write(
    `winners: watchlist ${watchlist.length} · board ${u.board_n ?? '?'} -> ` +
      `${u.survivors_n ?? '?'} clonable · ${(intel.aggregate_features || []).length} features; wrote ${OUT_PATH}\n`,
  );
  // The HL SDK transport holds a keep-alive socket that keeps the event loop
  // alive after the result resolves; exit explicitly once the artifact is written.
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`winners: fatal ${err && err.message ? err.message : String(err)}\n`);
  process.exit(1);
});
