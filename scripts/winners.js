#!/usr/bin/env node
/**
 * Gclaw winner-forensics puller — READ-ONLY on-chain intel for the Scientist loop.
 *
 * Pulls the HyperLiquid month PnL leaderboard, drops the obvious junk with cheap
 * pre-filters, then for a handful of survivors pulls their raw fills + current
 * clearinghouse state and writes one combined JSON blob. This blob is later
 * decomposed (scripts/decompose.py) into size-invariant skill patterns the
 * Scientist LLM reverse-engineers from.
 *
 * This tool NEVER trades, settles, or moves funds. It only reads public HL data
 * through the GDEX SDK. Public reads need a shared-key login but no wallet.
 *
 * Env:
 *   GDEX_SKILL_DIR  SDK location (default ~/gdex-skill) — supplies dist
 *   GDEX_API_KEY    overrides the SDK's shared primary key
 *   GCLAW_HOME      state root (default ~/.gclaw) — output lands in $GCLAW_HOME/forge
 *
 * Usage:
 *   node winners.js pull [--max N]      # default N=12 survivors
 *
 * Verified live data facts (2026-07, pulled once before coding):
 *   - getHlTopTradersByPnl() -> {isSuccess, topTraders:{day,week,month,allTime}}.
 *     month is a list of {ethAddress, accountValue(string),
 *     windowPerformances:[["day",{pnl,roi,vlm}], ["week",...], ["month",...],
 *     ["allTime",{pnl,roi,vlm}]]}. ALL numbers are strings. vlm is "0.0" for
 *     some whales (unpopulated) — turnover filter must SKIP, not drop, those.
 *   - getHlTradeHistory(addr) -> array of up to 2000 fills (most recent). Fields:
 *     coin, px, sz, side("B"/"A"), time(ms), startPosition, dir, closedPnl,
 *     crossed(bool), fee — numerics are strings.
 *   - getHlClearinghouseState(addr) -> {isSuccess, dex, state:{marginSummary,
 *     assetPositions:[{position:{coin,szi,entryPx,unrealizedPnl,...}}], ...}}.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const FORGE_DIR = path.join(GCLAW_HOME, 'forge');
const OUT_PATH = path.join(FORGE_DIR, 'winners_raw.json');
const WATCHLIST_PATH = path.join(FORGE_DIR, 'watchlist.json');

const DEFAULT_MAX = 12;
const AV_MIN = 50000;
const AV_MAX = 50000000;
const TURNOVER_MAX = 20; // month.vlm / accountValue; skipped when vlm unavailable
const ALLTIME_SENTINEL = -500; // board placeholder for "no allTime record"
const PULL_DELAY_MS = 350; // gentle sequential pacing between per-wallet reads

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Load the GDEX SDK and return a shared-key-authenticated read client.
 *
 * Public HL reads still require a login (shared primary key), but no wallet or
 * session signature — nothing here can place an order.
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
 * Load the curated watchlist of HL wallet addresses, if present.
 *
 * The dollar-PnL board is dominated by un-clonable market-makers, so a curated
 * watchlist ($GCLAW_HOME/forge/watchlist.json — a JSON array of "0x…" addresses
 * or {address} objects) is the reliable universe of clonable directional traders.
 * Watchlisted wallets bypass the board pre-filters (they were vetted by hand).
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
 * Pull the [window, {pnl, roi, vlm}] pair for one window from an entry.
 *
 * @param {object} entry a month-board leaderboard entry.
 * @param {string} window one of "day"|"week"|"month"|"allTime".
 * @returns {object} the perf object (possibly empty if the window is absent).
 */
function windowPerf(entry, window) {
  for (const pair of entry.windowPerformances || []) {
    if (Array.isArray(pair) && pair[0] === window) return pair[1] || {};
  }
  return {};
}

/**
 * Apply the cheap board pre-filters and return the ordered survivor addresses.
 *
 * Drops allTime==-500 sentinels and turnover>20 wallets, keeps accountValue in
 * [50k, 50M]. A missing/zero vlm means turnover is unknown, so we KEEP the
 * wallet (the SDK leaves vlm at "0.0" for some entries) rather than drop it.
 *
 * @param {Array<object>} month the month leaderboard list.
 * @returns {{survivors: Array<object>, counts: object}} survivors + stage counts.
 */
function preFilter(month) {
  const counts = { board_n: month.length, dropped_sentinel: 0, dropped_turnover: 0, dropped_av: 0 };
  const survivors = [];
  for (const entry of month) {
    if (Number(windowPerf(entry, 'allTime').pnl) === ALLTIME_SENTINEL) {
      counts.dropped_sentinel += 1;
      continue;
    }
    const accountValue = Number(entry.accountValue);
    if (!(accountValue >= AV_MIN && accountValue <= AV_MAX)) {
      counts.dropped_av += 1;
      continue;
    }
    const vlm = Number(windowPerf(entry, 'month').vlm);
    if (vlm > 0 && vlm / accountValue > TURNOVER_MAX) {
      counts.dropped_turnover += 1;
      continue;
    }
    survivors.push(entry);
  }
  counts.survivors_after_cheap = survivors.length;
  return { survivors, counts };
}

/**
 * Pull fills + clearinghouse state for one wallet, isolating failures.
 *
 * One bad wallet must never abort the run, so every SDK call is wrapped and any
 * error is recorded on the returned record instead of thrown.
 *
 * @param {object} skill authenticated read client.
 * @param {object} entry the leaderboard entry for this wallet.
 * @returns {Promise<object>} combined raw record (with `errors` if any).
 */
async function pullWallet(skill, entry) {
  const address = entry.ethAddress;
  const record = {
    address,
    accountValue: entry.accountValue,
    windowPerformances: entry.windowPerformances,
    source: entry.watchlist ? 'watchlist' : 'board',
    fills: [],
    clearinghouse: null,
    errors: [],
  };
  try {
    const history = await skill.getHlTradeHistory(address);
    record.fills = Array.isArray(history) ? history : (history && (history.fills || history.data)) || [];
  } catch (err) {
    record.errors.push(`tradeHistory: ${err && err.message ? err.message : String(err)}`);
  }
  // getHlClearinghouseStateAll spans the default + builder (HIP-3) dexes and carries
  // marginSummary (accountValue, totalNtlPos, totalMarginUsed) → implied leverage +
  // margin health, the sizing/leverage-discipline signal decompose.py scores.
  try {
    record.clearinghouse = await skill.getHlClearinghouseStateAll(address);
  } catch (err) {
    record.errors.push(`clearinghouse: ${err && err.message ? err.message : String(err)}`);
  }
  return record;
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

/**
 * Run the `pull` command: board -> cheap filter -> per-wallet raw pull -> write.
 *
 * @param {{max: number}} opts parsed options.
 * @returns {Promise<object>} the combined blob that was written.
 */
async function runPull(opts) {
  const skill = readClient();
  const board = await skill.getHlTopTradersByPnl();
  if (!board || !board.isSuccess || !board.topTraders || !Array.isArray(board.topTraders.month)) {
    throw new Error('getHlTopTradersByPnl returned no month board');
  }
  const { survivors, counts } = preFilter(board.topTraders.month);
  // Curated watchlist wallets lead the universe (hand-vetted, bypass board filters),
  // then board survivors fill the rest; dedup by address, cap at --max.
  const watchlist = loadWatchlist();
  counts.watchlist_n = watchlist.length;
  const seen = new Set();
  const universe = [];
  for (const addr of watchlist) {
    if (seen.has(addr)) continue;
    seen.add(addr);
    universe.push({ ethAddress: addr, accountValue: null, windowPerformances: [], watchlist: true });
  }
  for (const entry of survivors) {
    const addr = String(entry.ethAddress || '').toLowerCase();
    if (seen.has(addr)) continue;
    seen.add(addr);
    universe.push(entry);
  }
  const picked = universe.slice(0, opts.max);
  counts.pulled_n = picked.length;

  const wallets = [];
  for (const entry of picked) {
    const record = await pullWallet(skill, entry);
    wallets.push(record);
    await sleep(PULL_DELAY_MS);
  }

  const blob = {
    pulled_at: new Date().toISOString(),
    source: 'getHlTopTradersByPnl.month',
    filter_counts: counts,
    wallets,
  };

  fs.mkdirSync(FORGE_DIR, { recursive: true });
  fs.writeFileSync(OUT_PATH, JSON.stringify(blob) + '\n');
  const errN = wallets.filter((w) => w.errors.length).length;
  process.stderr.write(
    `winners: board ${counts.board_n} -> cheap ${counts.survivors_after_cheap} -> pulled ${counts.pulled_n}` +
      ` (${errN} with errors); wrote ${OUT_PATH}\n`,
  );
  return blob;
}

async function main() {
  const [, , cmd, ...rest] = process.argv;
  if (cmd !== 'pull') {
    process.stderr.write('usage: node winners.js pull [--max N]\n');
    process.exit(2);
  }
  const blob = await runPull(parseArgs(rest));
  process.stdout.write(JSON.stringify(blob) + '\n');
}

main().catch((err) => {
  process.stderr.write(`winners: fatal ${err && err.message ? err.message : String(err)}\n`);
  process.exit(1);
});
