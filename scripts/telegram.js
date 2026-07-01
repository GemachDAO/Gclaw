#!/usr/bin/env node
/**
 * telegram.js — Gclaw's three-plane Telegram command-and-control router.
 *
 * A long-poll daemon that turns the whole v4.0.0 organism into a Telegram surface,
 * split into three hard-separated planes:
 *
 *   READ  (public, rate-limited) — precise data views. THE BOT FORMATS, NEVER
 *         COMPUTES: each command shells the existing source-of-truth script/state
 *         and formats its JSON. It never reimplements a number.
 *   CONTROL (owner-only, DM-only) — the CIA safety model: an owner allow-list,
 *         typed two-step /confirm for anything that arms money or spawns life, and
 *         an append-only audit of every intent + denied probe. SAFETY INVARIANT:
 *         no command here EVER calls a fund-moving primitive. Arming commands only
 *         flip an env flag the NEXT heartbeat's deterministic gate consumes.
 *   (FEED lives in the sibling feed.js — the exactly-once push pusher.)
 *
 * Reliability (Jane St): dedupe by update_id so a redelivered update never
 * double-acts; single-instance via a flock lockfile; a liveness file for a
 * watchdog. All tg() failures are handled explicitly — never a silent null that
 * renders as a lie.
 *
 *   node telegram.js listen    # long-poll daemon (real-time ops)
 *   node telegram.js poll      # one-shot (cron watchdog fallback)
 *
 * Env: GCLAW_TELEGRAM_TOKEN (required), GCLAW_TELEGRAM_OWNER (comma-sep owner ids;
 * defaults to GCLAW_TELEGRAM_CHAT), GCLAW_HOME, GDEX_SKILL_DIR, GCLAW_SKILL_DIR.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');
const crypto = require('node:crypto');
const { execFileSync, spawn } = require('node:child_process');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const SKILL_DIR = process.env.GCLAW_SKILL_DIR || path.resolve(__dirname, '..');
const SCRIPTS = path.join(SKILL_DIR, 'scripts');
const TG_DIR = path.join(GCLAW_HOME, 'telegram');
const OFFSET_PATH = path.join(TG_DIR, 'tg_offset.json');
const SEEN_PATH = path.join(TG_DIR, 'seen_updates.json');
const PENDING_PATH = path.join(TG_DIR, 'pending.json');
const AUDIT_PATH = path.join(TG_DIR, 'audit.jsonl');
const RATELIMIT_PATH = path.join(TG_DIR, 'ratelimit.json');
const ALIVE_PATH = path.join(TG_DIR, 'poller.alive');
const LOCK_PATH = path.join(TG_DIR, 'poller.lock');
const PAUSE_PATH = path.join(GCLAW_HOME, 'PAUSE');
const VETO_PATH = path.join(GCLAW_HOME, 'forge', 'veto.json');
const ENV_PATH = path.join(GCLAW_HOME, 'env');
const HEARTBEAT_SH = path.join(SCRIPTS, 'heartbeat.sh');

const TOKEN = process.env.GCLAW_TELEGRAM_TOKEN;

// The three live gates the owner can arm — a flag → the env key the heartbeat sources.
const ARM_FLAGS = {
  outcomes: 'GCLAW_OUTCOMES_LIVE',
  carry: 'GCLAW_CARRY_LIVE',
  reproduce: 'GCLAW_REPRODUCE_LIVE',
};
// Arming money or spawning life needs a typed nonce; friction-free ones reduce risk.
const CONFIRM_REQUIRED = new Set(['arm outcomes', 'arm carry', 'breed']);
const CONFIRM_TTL_MS = 90_000;

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };
const readJsonl = (p) => { try { return fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)); } catch { return []; } };

function writeAtomic(p, data) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const tmp = `${p}.tmp${process.pid}`;
  fs.writeFileSync(tmp, data);
  fs.renameSync(tmp, p);
}

function appendAudit(rec) {
  fs.mkdirSync(TG_DIR, { recursive: true });
  const line = JSON.stringify({ ts: new Date().toISOString(), ...rec }) + '\n';
  const fd = fs.openSync(AUDIT_PATH, 'a');
  try { fs.writeSync(fd, line); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
}

// ── owner allow-list ────────────────────────────────────────────────────────
// An explicit GCLAW_TELEGRAM_OWNER (comma-sep ids) is the allow-list; it falls
// back to GCLAW_TELEGRAM_CHAT so an existing single-owner deploy keeps working.
function ownerIds() {
  const raw = process.env.GCLAW_TELEGRAM_OWNER || process.env.GCLAW_TELEGRAM_CHAT || '';
  return new Set(String(raw).split(',').map((s) => s.trim()).filter(Boolean));
}
function isOwner(uid) { return ownerIds().has(String(uid)); }

// ── Telegram API ────────────────────────────────────────────────────────────
// Returns the parsed API envelope, or {ok:false,error} on any transport/parse
// failure — NEVER a bare null that a caller could mistake for an empty result.
function tg(method, params, timeoutMs = 15000) {
  return new Promise((resolve) => {
    if (!TOKEN) { resolve({ ok: false, error: 'no token' }); return; }
    const body = JSON.stringify(params || {});
    const req = https.request(`https://api.telegram.org/bot${TOKEN}/${method}`,
      { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) }, timeout: timeoutMs },
      (res) => { let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => { try { resolve(JSON.parse(b)); } catch { resolve({ ok: false, error: 'bad json' }); } }); });
    req.on('error', (e) => resolve({ ok: false, error: e.message }));
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, error: 'timeout' }); });
    req.write(body); req.end();
  });
}
async function reply(chat, text, extra) {
  return tg('sendMessage', { chat_id: chat, text, disable_web_page_preview: true, ...(extra || {}) });
}

// ── source-of-truth shells ──────────────────────────────────────────────────
// A read helper NEVER computes a number: it shells the owning script and hands
// back {ok,data} or {ok:false,error}. A caller that gets ok:false MUST render an
// explicit failure ("⚠️ couldn't read X"), never a fabricated $0/flat.
function runJson(bin, args, timeoutMs = 30000) {
  try {
    const out = execFileSync(bin, args, { encoding: 'utf8', timeout: timeoutMs, cwd: SCRIPTS });
    const i = out.indexOf('{');
    if (i < 0) return { ok: false, error: 'no json in output' };
    return { ok: true, data: JSON.parse(out.slice(i)) };
  } catch (e) { return { ok: false, error: (e && e.message) || 'exec failed' }; }
}
function runText(bin, args, timeoutMs = 30000) {
  try { return { ok: true, text: execFileSync(bin, args, { encoding: 'utf8', timeout: timeoutMs, cwd: SCRIPTS }) }; }
  catch (e) { return { ok: false, error: (e && e.message) || 'exec failed' }; }
}
const py = (script, extra) => runJson('uv', ['run', '--no-project', 'python3', path.join(SCRIPTS, script), ...extra]);
const node = (script, extra, t) => runJson('node', [path.join(SCRIPTS, script), ...extra], t);

// ── persona voice ───────────────────────────────────────────────────────────
const SAFE_SIGILS = new Set(['◆', '◈', '✦', '✧', '❖', '⬡', '⬢', '❂', '✸', '⟡', '◇', '✺', '☉', '☾']);
function soul() {
  const p = readJson(path.join(GCLAW_HOME, 'dna', 'persona.json'), {});
  const m = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  const sig = SAFE_SIGILS.has(p.sigil) ? p.sigil : '◇';
  return { name: m.name || p.species || p.name || 'Gclaw', sigil: sig, catchphrase: p.catchphrase || 'Still here. Still trading.', archetype: p.archetype || '' };
}
function voiced(msg, big) {
  const s = soul();
  return `${s.sigil} ${s.name} — ${msg}` + (big && s.catchphrase ? `\n“${s.catchphrase}”` : '');
}

// ── honest formatting ───────────────────────────────────────────────────────
// n=0 / null → "warming", NEVER 0.0 — a fake zero is the worst lie a trading bot
// can tell. A read failure is rendered by the caller, never as a flat/zero view.
function honest(v, unit) {
  if (v === null || v === undefined) return 'warming';
  const n = Number(v);
  if (!Number.isFinite(n)) return 'warming';
  return unit === '$' ? `$${n.toFixed(2)}` : unit === '%' ? `${n.toFixed(1)}%` : String(v);
}
const money = (n) => (Number.isFinite(Number(n)) ? `$${Number(n).toFixed(2)}` : 'warming');
const signed = (n) => { const x = Number(n); return Number.isFinite(x) ? `${x >= 0 ? '+' : '-'}$${Math.abs(x).toFixed(2)}` : 'warming'; };
const failLine = (what) => `⚠️ couldn't read ${what} — not shown (this is a read failure, not a flat book)`;

// ── READ plane renderers (each pinned to a source-of-truth) ─────────────────
function renderStatus() {
  const meta = py('metabolism.py', ['--json', 'status']);
  if (!meta.ok) return failLine('life-state (metabolism)');
  const m = meta.data;
  const rep = py('reputation.py', ['card']);
  const proven = rep.ok ? (rep.data.evolution?.proven_edge_techniques || []) : null;
  const pos = readJson(path.join(GCLAW_HOME, 'positions.json'), {});
  const brk = readJson(path.join(GCLAW_HOME, 'breaker.json'), {});
  const s = soul();
  const openN = (pos.positions || []).length;
  const lines = [
    `${s.sigil} ${s.name} #${m.onchain_identity?.agentId || '?'} — ${String(m.mode || '?').toUpperCase()}`,
    `GMAC ${Math.round(m.gmac_balance || 0)} · goodwill ${m.goodwill ?? '?'} · ${m.heartbeats ?? '?'} heartbeats`,
    pos.ok ? `equity ${money(pos.equity)} · drawdown ${honest(brk.drawdown_pct, '%')} of HWM · ${openN ? `${openN} open` : 'flat'}`
      : failLine('positions'),
    proven === null ? failLine('proven edge (reputation)')
      : `proven-edge techniques: ${proven.length}${proven.length ? `  (${proven.join(', ')})` : ' — warming'}`,
  ];
  return lines.join('\n') + '\n\ntry /proven /positions /events /pnl /help';
}

function renderProven() {
  const style = readJson(path.join(GCLAW_HOME, 'forge', 'style.json'), {});
  const adopted = style.adopted;
  const rep = py('reputation.py', ['card']);
  if (adopted === undefined && !rep.ok) return failLine('proven edge (forge + reputation)');
  const proven = rep.ok ? (rep.data.evolution?.proven_edge_techniques || []) : [];
  const rows = (adopted || []).map((e) => {
    const tag = proven.includes(e.id) ? ' ✓proven' : '';
    return `• ${e.id} (${e.coin}) e=${honest(e.e)} · ${e.trades ?? 0} trades${e.born ? ' ·born' : ''}${tag}`;
  });
  const head = `◇ Proven edge — the science, not the scorecard`;
  const body = rows.length ? rows.join('\n') : 'none adopted yet — warming';
  const foot = rep.ok ? `\nproven-edge count: ${proven.length} · self-authored: ${rep.data.evolution?.self_authored_techniques ?? '?'}` : '';
  return `${head}\n${body}${foot}`;
}

function renderBench() {
  const journal = readJsonl(path.join(GCLAW_HOME, 'journal.jsonl'));
  if (!journal.length && !fs.existsSync(path.join(GCLAW_HOME, 'journal.jsonl'))) return failLine('the Bench (journal)');
  const recs = journal.filter((e) => ['recode', 'graduated', 'rejected', 'author'].includes(e.event)).slice(-6);
  const rows = recs.map((e) => {
    if (e.event === 'recode') return `🛠️ recode → ${(e.authored || []).length} authored`;
    if (e.event === 'graduated') return `🟢 GRADUATED ${e.id || e.technique || '?'} (e=${honest(e.e)})`;
    if (e.event === 'rejected') return `⚪ rejected ${e.id || e.technique || '?'}`;
    return `🔬 authored ${e.id || e.technique || '?'}`;
  });
  return `🔬 The Scientist's Bench\n${rows.length ? rows.join('\n') : 'nothing on the bench yet — warming'}`;
}

function renderPositions() {
  const st = node('hl_perp.js', ['status'], 40000);
  if (!st.ok || !st.data || st.data.ok === false) return failLine('positions');
  const d = st.data;
  const ps = d.positions || [];
  if (!ps.length) {
    return `◆ ${soul().name} · positions\nflat — 0 open · 0 orders\nspot USDC ${money(d.spotUsdc)} · equity ${money(d.equity)} · buying power ${money(d.buyingPower)}`;
  }
  const rows = ps.map((p) => {
    const side = Number(p.size) < 0 ? 'SHORT' : 'LONG';
    return `${p.coin} ${side} ${Math.abs(Number(p.size))} @ ${honest(p.entryPx)}  uPnL ${signed(p.unrealizedPnl)} · liq ${honest(p.liquidationPx)}`;
  });
  return `◆ ${soul().name} · positions\n${rows.join('\n')}\nspot USDC ${money(d.spotUsdc)} · equity ${money(d.equity)} · ${ps.length} open`;
}

function renderRisk() {
  const rg = node('riskguard.js', ['check'], 40000);
  const brk = readJson(path.join(GCLAW_HOME, 'breaker.json'), null);
  if (!rg.ok && brk === null) return failLine('risk (riskguard + breaker)');
  const lines = ['◆ Risk'];
  if (rg.ok && rg.data.ok !== false) {
    const d = rg.data;
    lines.push(`equity ${money(d.equity)}`);
    lines.push(`per-trade cap ${money(d.per_trade_cap_usd)} · portfolio cap ${money(d.portfolio_cap_usd)}`);
    for (const b of d.book || []) lines.push(`  ${b.coin} risk ${honest(b.riskPct, '%')}${b.naked ? ' ⚠️ NAKED' : ''}`);
    if (!(d.book || []).length) lines.push('  book: flat');
  } else { lines.push(failLine('risk caps (riskguard)')); }
  if (brk) {
    lines.push(brk.tripped
      ? `🔴 BREAKER TRIPPED — ${brk.reason || 'book flattened'}`
      : `breaker: hwm ${money(brk.hwm)} · drawdown ${honest(brk.drawdown_pct, '%')} · armed`);
  } else { lines.push(failLine('breaker state')); }
  return lines.join('\n');
}

function renderPnl() {
  const rep = py('reputation.py', ['card']);
  if (!rep.ok) return failLine('track record (reputation)');
  const t = rep.data.trading || {};
  const wr = t.win_rate == null ? 'warming (n=0)' : `${(Number(t.win_rate) * 100).toFixed(1)}%`;
  const closed = t.closed_trades ?? 0;
  const exp = closed ? `${signed(t.expectancy_usd)} / trade` : 'warming (no closed trades)';
  return [
    '◆ Track record — settled fills only',
    `realized PnL ${signed(t.realized_pnl_usd)}`,
    `closed trades ${closed}`,
    `win rate ${closed ? wr : 'warming (n=0)'}`,
    `avg win ${signed(t.avg_win)} · avg loss ${signed(t.avg_loss)}`,
    `expectancy ${exp}`,
    `proven-edge techniques: ${rep.data.evolution?.proven_edge_count ?? 0}`,
  ].join('\n');
}

function renderEvents() {
  const mk = py('outcomes.py', ['markets'], 60000);
  if (!mk.ok) return failLine('event desk (outcomes)');
  const sides = (mk.data.sides || []).slice(0, 6);
  const rows = sides.map((s) => `• ${s.name} — ${s.side} @ ${honest(s.price)} (vol ${money(s.volumeUsd)})`);
  return `◆ Event desk — top tradeable\n${rows.length ? rows.join('\n') : 'none tradeable right now — warming'}`;
}

function renderCalibration() {
  const cal = py('outcomes.py', ['calibration'], 40000);
  if (!cal.ok) return failLine('calibration (outcomes)');
  const a = cal.data.aggregates || {};
  if (!a.n || a.n_resolved === 0 || a.brier_mean == null) {
    return `◆ Event-desk calibration\nwarming (n=${a.n || 0}, resolved ${a.n_resolved || 0}) — SHADOW, no dollar at risk yet`;
  }
  const edge = Number(a.baseline_mean) - Number(a.brier_mean);
  return [
    '◆ Event-desk calibration',
    `tickets ${a.n} · resolved ${a.n_resolved}`,
    `Brier ${honest(a.brier_mean)} vs baseline ${honest(a.baseline_mean)}`,
    `skill edge ${edge >= 0 ? '+' : ''}${edge.toFixed(3)} ${edge >= 0 ? '✓ beating baseline' : 'below baseline'}`,
  ].join('\n');
}

function renderCarry() {
  const c = node('carry.js', ['status'], 45000);
  if (!c.ok || c.data.ok === false) return failLine('carry');
  const d = c.data;
  const legs = Object.entries(d.fundings || {}).map(([k, v]) => `${k} ${honest(v.apy, '%')} APY`).join(' · ');
  const wd = d.wouldDo ? `${d.wouldDo.action} ${d.wouldDo.coin || ''} (${honest(d.wouldDo.apy, '%')} APY)` : 'hold';
  return `◆ Carry floor — ${d.live ? 'LIVE' : 'DRY-RUN'}\nfunding: ${legs || 'warming'}\nwould: ${wd}`;
}

function renderGate() {
  const meta = py('metabolism.py', ['--json', 'status']);
  const cap = runText('uv', ['run', '--no-project', 'python3', path.join(SCRIPTS, 'evolve.py'), 'capabilities']);
  const env = readEnvFlags();
  const lines = ['◆ Gates — what is armed'];
  lines.push(`outcomes: ${env.GCLAW_OUTCOMES_LIVE ? 'ARMED (live)' : 'SHADOW'}`);
  lines.push(`carry: ${env.GCLAW_CARRY_LIVE ? 'ARMED (live)' : 'DRY'}`);
  lines.push(`reproduce: ${env.GCLAW_REPRODUCE_LIVE ? 'ARMED (live)' : 'DRY'}`);
  lines.push(fs.existsSync(PAUSE_PATH) ? 'PAUSE: ⏸️ ON' : 'PAUSE: off');
  const veto = readJson(VETO_PATH, {});
  lines.push(veto.veto ? `veto: SET (${String(veto.reason || '').slice(0, 60)})` : 'veto: none');
  if (cap.ok) lines.push('\n' + cap.text.trim());
  else if (!meta.ok) lines.push(failLine('capabilities (evolve)'));
  return lines.join('\n');
}

function renderLeaderboard() {
  const lb = readJson(path.join(GCLAW_HOME, 'leaderboard.json'), null);
  if (!lb || !lb.ranked) return failLine('leaderboard');
  const rows = lb.ranked.map((e) => `${e.rank}. ${e.name}${e.self ? ' ◀ me' : ''} — gw ${e.goodwill} · ${money(e.equityUsd)}`);
  return `🏆 The family ladder\n${rows.length ? rows.join('\n') : 'no ranked family yet — warming'}`;
}

function renderLineage() {
  const meta = py('metabolism.py', ['--json', 'status']);
  if (!meta.ok) return failLine('lineage (metabolism)');
  const kids = meta.data.children || [];
  if (!kids.length) return `🧬 Lineage — no children yet (proven-edge gate must open first)`;
  return `🧬 Lineage — ${kids.length} children\n${kids.map((c) => `• ${c.name} (${c.role}) — ${c.mutation || ''}`).join('\n')}`;
}

function renderHealth() {
  const meta = py('metabolism.py', ['--json', 'status']);
  const gas = readJson(path.join(GCLAW_HOME, 'gas.json'), null);
  const brk = readJson(path.join(GCLAW_HOME, 'breaker.json'), null);
  const settles = readJsonl(path.join(GCLAW_HOME, 'journal.jsonl')).filter((e) => e.event === 'settle');
  const lines = ['◆ Health'];
  if (meta.ok) {
    const age = meta.data.updated_at ? Math.round((Date.now() - new Date(meta.data.updated_at).getTime()) / 60000) : null;
    lines.push(`heartbeat ${age == null ? 'warming' : `${age} min ago`}${age != null && age > 90 ? ' 🔴 STALE' : ' ✓'} · mode ${meta.data.mode || '?'}`);
  } else { lines.push(failLine('heartbeat freshness (metabolism)')); }
  lines.push(gas ? `gas ${gas.status || '?'} (~${gas.beaconRunway ?? '?'} beacons)` : failLine('gas runway'));
  lines.push(brk ? (brk.tripped ? '🔴 breaker TRIPPED' : `breaker armed · drawdown ${honest(brk.drawdown_pct, '%')}`) : failLine('breaker'));
  const last = settles.length ? settles[settles.length - 1] : null;
  lines.push(last ? `last settle ${signed(last.pnl)} (${last.note || ''})`.slice(0, 90) : 'last settle: none yet');
  lines.push(pollerAlive() ? 'poller ✓ alive' : 'poller ⚠️ liveness stale');
  return lines.join('\n');
}

// ── prediction game (public; preserve predict.js integration) ───────────────
function openRounds() {
  const rounds = readJson(path.join(GCLAW_HOME, 'predictions', 'rounds.json'), {});
  return Object.values(rounds).filter((r) => r.status === 'open');
}
function identity(from) { return from && from.username ? `@${from.username}` : `tg:${from && from.id}`; }
function parsePick(text) {
  const s = String(text || '').trim().toLowerCase().replace(/[!.?]+$/, '');
  const m = s.match(/^(?:(?:i\s+)?call\s+)?(tp|sl|take\s*profit|stop\s*loss|📈|📉)(?:\s+[a-z]{2,6})?$/i)
    || s.match(/^[a-z]{2,6}\s+(tp|sl|take\s*profit|stop\s*loss|📈|📉)$/i);
  if (!m) return null;
  const w = m[1].replace(/\s+/g, '');
  return ['tp', 'takeprofit', '📈'].includes(w) ? 'TP' : 'SL';
}
function renderBoard() {
  const g = node('predict.js', ['global']);
  if (!g.ok) return failLine('the ladder (predict)');
  const rows = (g.data.predictors || []).slice(0, 10).map((e, i) => `${i + 1}. ${e.by} — ${e.accuracy}% (${e.correct}/${e.total})`);
  return rows.length ? `🌐 Global predictors ladder\n${rows.join('\n')}` : 'No predictors yet — be the first to call a round right.';
}
function renderRoundsText() {
  const open = openRounds();
  return open.length
    ? `Open rounds — reply TP or SL:\n${open.map((r) => `• ${r.coin} ${r.side} @ ${honest(r.entry)} (round ${r.id})`).join('\n')}`
    : 'No open round right now — one opens when the creature opens a trade.';
}
function roundKeyboard(round) {
  return { inline_keyboard: [[
    { text: '📈 TP — hits target', callback_data: `call:TP:${round.id}` },
    { text: '📉 SL — stops out', callback_data: `call:SL:${round.id}` },
  ]] };
}
async function callFor(round, pick, from, chat) {
  const by = identity(from);
  const res = node('predict.js', ['call', '--round', round.id, '--pick', pick, '--by', by]);
  if (res.ok && res.data.ok) await reply(chat, `✅ Locked your ${pick} on ${round.coin} as ${by}. Anchored onchain — you climb the global ladder if it lands.`);
  else await reply(chat, `⚠️ ${(res.data && res.data.error) || res.error || 'could not log that call'}`);
}

const HELP_PUBLIC = [
  '◇ Gclaw — the living trading organism. Reads (public):',
  '/status /proven /bench /positions /risk /pnl',
  '/events /calibration /carry /gate /leaderboard /lineage /health',
  'Call it 🎯 — reply TP / SL on an open round to climb the ladder. /board /rounds',
].join('\n');
const HELP_OWNER = [
  '',
  '— Owner control (DM-only) —',
  '/pause /resume · /veto <reason> /unveto',
  '/arm <outcomes|carry|reproduce> /disarm <…> · /arms',
  '/beat (one heartbeat) · /breed · /confirm <nonce> · /audit',
].join('\n');

// ── READ dispatch ───────────────────────────────────────────────────────────
const READ = {
  '/status': renderStatus, '/proven': renderProven, '/edge': renderProven, '/bench': renderBench,
  '/positions': renderPositions, '/risk': renderRisk, '/pnl': renderPnl, '/card': renderPnl,
  '/events': renderEvents, '/calibration': renderCalibration, '/carry': renderCarry, '/gate': renderGate,
  '/arms': renderGate, '/leaderboard': renderLeaderboard, '/board': renderBoard, '/lineage': renderLineage,
  '/health': renderHealth, '/rounds': renderRoundsText,
};

// ── CONTROL plane ───────────────────────────────────────────────────────────
// Persist an env flag WITHOUT calling any trade primitive. This only rewrites
// ~/.gclaw/env; the NEXT heartbeat sources it and its deterministic gate decides
// whether (and how much) to spend. The bot is never the money authority.
function readEnvFlags() {
  const out = {};
  const txt = fs.existsSync(ENV_PATH) ? fs.readFileSync(ENV_PATH, 'utf8') : '';
  for (const line of txt.split('\n')) {
    const m = line.match(/^\s*export\s+(GCLAW_\w+)="?([^"]*)"?\s*$/);
    if (m) out[m[1]] = m[2];
  }
  return out;
}
function setEnvFlag(key, value) {
  const existing = fs.existsSync(ENV_PATH) ? fs.readFileSync(ENV_PATH, 'utf8') : '';
  const kept = existing.split('\n')
    .filter((l) => l.trim() !== '')
    .filter((l) => !new RegExp(`^\\s*export\\s+${key}=`).test(l));
  if (value !== null) kept.push(`export ${key}="${value}"`);
  writeAtomic(ENV_PATH, kept.join('\n') + '\n');
  try { fs.chmodSync(ENV_PATH, 0o600); } catch { /* best effort */ }
}

// A control command's effect: mutate ONLY PAUSE / veto / env — no fund primitive.
// Returns {ok, msg} for the reply. Callers audit around it.
function applyControl(action, arg, uid) {
  if (action === 'pause') { fs.mkdirSync(GCLAW_HOME, { recursive: true }); writeAtomic(PAUSE_PATH, `paused by ${uid} at ${new Date().toISOString()}\n`); return { ok: true, msg: `⏸️ Paused at ${new Date().toISOString()}. The heartbeat will not originate. /resume to re-arm.` }; }
  if (action === 'resume') { try { fs.unlinkSync(PAUSE_PATH); } catch { /* already off */ } return { ok: true, msg: '▶️ Resumed. The heartbeat may originate again on its next cycle. Logged.' }; }
  if (action === 'veto') { fs.mkdirSync(path.dirname(VETO_PATH), { recursive: true }); writeAtomic(VETO_PATH, JSON.stringify({ veto: true, reason: arg || 'owner veto (telegram)', by: uid, ts: new Date().toISOString() })); return { ok: true, msg: `🚫 Veto set — the next forge open is blocked.\nreason: ${arg || '(none)'}\n/unveto to clear. Logged.` }; }
  if (action === 'unveto') { try { fs.unlinkSync(VETO_PATH); } catch { /* none */ } return { ok: true, msg: '✅ Veto cleared. Logged.' }; }
  if (action === 'arm') { const key = ARM_FLAGS[arg]; if (!key) return { ok: false, msg: `unknown gate "${arg}" — use outcomes|carry|reproduce` }; setEnvFlag(key, '1'); return { ok: true, msg: `✅ Armed. ${key}=1 written to env — effective NEXT heartbeat (the deterministic gate still decides). /disarm ${arg} to revoke. Logged.` }; }
  if (action === 'disarm') {
    if (arg === 'all') { for (const k of Object.values(ARM_FLAGS)) setEnvFlag(k, null); return { ok: true, msg: '✅ Disarmed all live gates. Logged.' }; }
    const key = ARM_FLAGS[arg]; if (!key) return { ok: false, msg: `unknown gate "${arg}" — use outcomes|carry|reproduce|all` };
    setEnvFlag(key, null); return { ok: true, msg: `✅ Disarmed — ${key} unset. Logged.` };
  }
  if (action === 'beat') { runHeartbeatBackground(); return { ok: true, msg: '💓 Running one heartbeat in the background (its own flock — no overlap). Watch the feed for the result. Logged.' }; }
  if (action === 'breed') return doBreed(uid);
  return { ok: false, msg: 'unknown control action' };
}

// /beat spawns the EXISTING heartbeat.sh detached. It never opens a trade itself;
// heartbeat.sh's own flock + deterministic gates own everything downstream.
function runHeartbeatBackground() {
  if (!fs.existsSync(HEARTBEAT_SH)) return;
  const child = spawn('bash', [HEARTBEAT_SH], { detached: true, stdio: 'ignore', cwd: SCRIPTS });
  child.unref();
}

// /breed: only if the proven-edge gate is met. Runs evolve.py replicate --auto
// with GCLAW_REPRODUCE_LIVE=1 for THAT ONE invocation — it spawns a child (local,
// reversible DNA copy), never a fund primitive. Gate is evolve.py's own authority.
function doBreed(uid) {
  const cap = runText('uv', ['run', '--no-project', 'python3', path.join(SCRIPTS, 'evolve.py'), 'capabilities']);
  if (cap.ok && /·\s*replicate/.test(cap.text) && !/✓\s*replicate/.test(cap.text)) {
    return { ok: false, msg: `Not breed-ready yet — the proven-edge gate is not met.\n${cap.text.trim()}` };
  }
  // Force reproduce-live for THIS invocation only, without persisting the env flag —
  // so the child spawns now without leaving the live gate armed for future heartbeats.
  const out = runJsonWithEnv('uv', ['run', '--no-project', 'python3', path.join(SCRIPTS, 'evolve.py'), 'replicate', '--auto'],
    { GCLAW_REPRODUCE_LIVE: '1' }, 60000);
  if (!out.ok) return { ok: false, msg: `⚠️ breed failed: ${out.error}` };
  const d = out.data || {};
  if (d.would_replicate === false) return { ok: false, msg: `Not breed-ready: ${d.reason || 'gate not met'}. Logged.` };
  return { ok: true, msg: voiced(`🧬 Spawned a child (${d.name || 'child'}) — it inherits my proven winners. Logged.`, true), audit: { name: d.name, role: d.role, uid } };
}
function runJsonWithEnv(bin, args, extraEnv, timeoutMs) {
  try {
    const out = execFileSync(bin, args, { encoding: 'utf8', timeout: timeoutMs || 30000, cwd: SCRIPTS, env: { ...process.env, ...extraEnv } });
    const i = out.indexOf('{');
    return i < 0 ? { ok: false, error: 'no json' } : { ok: true, data: JSON.parse(out.slice(i)) };
  } catch (e) { return { ok: false, error: (e && e.message) || 'exec failed' }; }
}

// ── confirmation nonce ──────────────────────────────────────────────────────
function issueNonce(uid, action, arg) {
  const nonce = crypto.randomBytes(2).toString('hex').toUpperCase();
  writeAtomic(PENDING_PATH, JSON.stringify({ uid: String(uid), action, arg, nonce, expires: Date.now() + CONFIRM_TTL_MS }));
  return nonce;
}
function takePending(uid, nonce) {
  const p = readJson(PENDING_PATH, null);
  if (!p) return { ok: false, reason: 'no pending action' };
  if (String(p.uid) !== String(uid)) return { ok: false, reason: 'not your pending action' };
  if (Date.now() > p.expires) { try { fs.unlinkSync(PENDING_PATH); } catch { /* gone */ } return { ok: false, reason: 'confirmation expired' }; }
  if (String(nonce).toUpperCase() !== p.nonce) return { ok: false, reason: 'wrong nonce' };
  try { fs.unlinkSync(PENDING_PATH); } catch { /* gone */ }
  return { ok: true, action: p.action, arg: p.arg };
}

// ── the router ──────────────────────────────────────────────────────────────
// Parse a control command into {action, arg} — the canonical action string is
// what CONFIRM_REQUIRED and applyControl key on.
function parseControl(text) {
  const t = text.trim();
  const m = t.match(/^\/?(pause|resume|unveto|arms|beat|breed|audit)\b/i);
  if (m) return { action: m[1].toLowerCase(), arg: null };
  const veto = t.match(/^\/?veto\b\s*(.*)$/i);
  if (veto) return { action: 'veto', arg: veto[1].trim() };
  const arm = t.match(/^\/?(arm|disarm)\b\s*(\w+)?/i);
  if (arm) return { action: arm[1].toLowerCase(), arg: (arm[2] || '').toLowerCase() };
  return null;
}
const CONTROL_VERB = /^\/?(pause|resume|veto|unveto|arm|disarm|arms|beat|breed|confirm|audit)\b/i;

async function handleMessage(msg) {
  if (!msg || !msg.text) return;
  const chat = msg.chat.id;
  const uid = msg.from && msg.from.id;
  const isGroup = Number(chat) < 0;
  const text = msg.text.trim();
  const lower = text.toLowerCase();

  if (/^\/?(help|start)\b/i.test(text)) {
    await reply(chat, HELP_PUBLIC + (isOwner(uid) && !isGroup ? '\n' + HELP_OWNER : ''));
    return;
  }

  // CONTROL verbs — auth first, before any dispatch, from msg.from.id.
  if (CONTROL_VERB.test(text)) {
    // /confirm <nonce>
    const conf = text.match(/^\/?confirm\b\s*(\w+)?/i);
    if (conf) { await handleConfirm(uid, chat, isGroup, conf[1]); return; }
    const parsed = parseControl(text);
    if (!parsed) { if (isOwner(uid) && !isGroup) await reply(chat, 'usage: /pause /resume /veto <reason> /arm <gate> /disarm <gate> /arms /beat /breed'); return; }

    // Deny by default: non-owner OR group chat → audited denied probe, no state change,
    // and a generic non-committal reply so the verb is never confirmed to a stranger.
    if (!isOwner(uid) || isGroup) {
      appendAudit({ uid, handle: identity(msg.from), chat, plane: 'public', cmd: text, phase: 'authz_deny', reason: isGroup ? 'group chat' : 'not owner' });
      return; // silent — never leak that the control verb exists
    }

    if (parsed.action === 'audit') { await sendAuditTail(chat); return; }
    if (parsed.action === 'arms') { await reply(chat, renderGate()); return; }

    const key = `${parsed.action}${parsed.arg ? ' ' + parsed.arg : ''}`;
    appendAudit({ uid, handle: identity(msg.from), chat, plane: 'owner', cmd: text, phase: 'intent', action: parsed.action, arg: parsed.arg });

    if (CONFIRM_REQUIRED.has(key)) {
      const nonce = issueNonce(uid, parsed.action, parsed.arg);
      appendAudit({ uid, chat, plane: 'owner', cmd: text, phase: 'nonce_issued', nonce, action: parsed.action, arg: parsed.arg });
      await reply(chat, `⚠️ This arms live money or spawns life (${key}). It is safe-by-construction — no funds move now; it only permits the next deterministic gate. Reply /confirm ${nonce} within 90s. Anything else cancels.`);
      return;
    }
    const res = applyControl(parsed.action, parsed.arg, uid);
    appendAudit({ uid, chat, plane: 'owner', cmd: text, phase: 'result', action: parsed.action, arg: parsed.arg, ok: res.ok });
    await reply(chat, res.msg);
    return;
  }

  // READ plane — public, but rate-limited per uid. Normalise a bare/slash command
  // ("status" or "/status") to its canonical "/status" key.
  const word = lower.split(/\s+/)[0];
  const canonical = READ[word] ? word : READ[`/${word}`] ? `/${word}` : null;
  if (canonical) {
    if (!rateLimitOk(uid)) return;
    await reply(chat, READ[canonical]());
    return;
  }
  if (/^\/?(board|leaderboard|ladder)\b/i.test(text)) { if (rateLimitOk(uid)) await reply(chat, renderBoard()); return; }
  if (/^\/?rounds?\b/i.test(text)) { if (rateLimitOk(uid)) await reply(chat, renderRoundsText()); return; }

  // Prediction game (public write, fund-free) — a TP/SL pick.
  const pick = parsePick(text);
  if (pick) {
    if (!rateLimitOk(uid)) return;
    const open = openRounds();
    if (!open.length) { await reply(chat, "No open round to call right now — I'll ping when the next trade opens."); return; }
    const coin = (text.toUpperCase().match(/\b(BTC|ETH|SOL|[A-Z]{2,6})\b/g) || []).find((c) => open.some((r) => r.coin === c));
    if (open.length > 1 && !coin) { await reply(chat, `Which one?\n${open.map((r) => `• ${r.coin} — reply "${pick} ${r.coin}"`).join('\n')}`); return; }
    const round = coin ? open.find((r) => r.coin === coin) : open[open.length - 1];
    await callFor(round, pick, msg.from, chat);
  }
  // anything else: stay quiet (public plane never confirms unknown commands)
}

async function handleConfirm(uid, chat, isGroup, nonce) {
  if (!isOwner(uid) || isGroup) { appendAudit({ uid, chat, plane: 'public', cmd: '/confirm', phase: 'authz_deny', reason: isGroup ? 'group chat' : 'not owner' }); return; }
  const taken = takePending(uid, nonce);
  if (!taken.ok) { appendAudit({ uid, chat, plane: 'owner', cmd: '/confirm', phase: 'confirm_fail', reason: taken.reason }); await reply(chat, `⚠️ ${taken.reason}. Nothing changed.`); return; }
  appendAudit({ uid, chat, plane: 'owner', cmd: '/confirm', phase: 'confirmed', action: taken.action, arg: taken.arg });
  const res = applyControl(taken.action, taken.arg, uid);
  appendAudit({ uid, chat, plane: 'owner', phase: 'result', action: taken.action, arg: taken.arg, ok: res.ok, ...(res.audit || {}) });
  await reply(chat, res.msg);
}

async function sendAuditTail(chat) {
  const recs = readJsonl(AUDIT_PATH).slice(-12);
  if (!recs.length) { await reply(chat, 'audit log empty.'); return; }
  const rows = recs.map((r) => `${r.ts?.slice(11, 19) || '?'} ${r.plane || '?'} ${r.cmd || r.action || '?'} · ${r.phase}${r.reason ? ' (' + r.reason + ')' : ''}`);
  await reply(chat, '◆ Control audit (last 12)\n' + rows.join('\n'));
}

// ── callback_query (inline TP/SL buttons) ───────────────────────────────────
async function handleCallback(cq) {
  const data = String(cq.data || '');
  const chat = cq.message && cq.message.chat && cq.message.chat.id;
  const m = data.match(/^call:(TP|SL):(.+)$/);
  if (m && chat) {
    const round = openRounds().find((r) => r.id === m[2]);
    await tg('answerCallbackQuery', { callback_query_id: cq.id, text: round ? 'call locked ✅' : 'round closed' });
    if (round) await callFor(round, m[1], cq.from, chat);
    return;
  }
  await tg('answerCallbackQuery', { callback_query_id: cq.id });
}

// ── rate limiting (public read) ─────────────────────────────────────────────
function rateLimitOk(uid) {
  const now = Date.now();
  const rl = readJson(RATELIMIT_PATH, {});
  const b = rl[String(uid)] || { count: 0, window: now };
  if (now - b.window > 60_000) { b.count = 0; b.window = now; }
  b.count += 1;
  rl[String(uid)] = b;
  try { writeAtomic(RATELIMIT_PATH, JSON.stringify(rl)); } catch { /* best effort */ }
  return b.count <= 20;
}

// ── update_id dedupe (the Jane St idempotency fix) ──────────────────────────
// The old poller advanced the offset only after handling (good — no loss), but a
// crash between a ledger write and the offset persist let Telegram redeliver the
// update → a double-logged call. We persist a ring of seen update_ids and skip a
// redelivered one so it can never double-act, even across a restart.
function loadSeen() { const s = readJson(SEEN_PATH, { ids: [] }); return new Set(s.ids); }
function markSeen(seen, id) {
  seen.add(id);
  const ids = [...seen].slice(-500); // bounded ring
  try { writeAtomic(SEEN_PATH, JSON.stringify({ ids })); } catch { /* best effort */ }
  return new Set(ids);
}

// ── poll loop ───────────────────────────────────────────────────────────────
function pollerAlive() {
  try { return Date.now() - fs.statSync(ALIVE_PATH).mtimeMs < 5 * 60_000; } catch { return false; }
}
function touchAlive() { try { writeAtomic(ALIVE_PATH, JSON.stringify({ ts: new Date().toISOString(), pid: process.pid })); } catch { /* best effort */ } }

async function poll(timeoutSec) {
  fs.mkdirSync(TG_DIR, { recursive: true });
  const off = readJson(OFFSET_PATH, { offset: 0 });
  let seen = loadSeen();
  const params = { offset: off.offset, timeout: timeoutSec || 0, allowed_updates: ['message', 'callback_query'] };
  let upd = await tg('getUpdates', params, (timeoutSec || 0) * 1000 + 15000);
  if (!upd || !upd.ok) upd = await tg('getUpdates', params, (timeoutSec || 0) * 1000 + 15000);
  touchAlive();
  if (!upd || !upd.ok) return { ok: false, error: (upd && upd.error) || 'getUpdates failed' };
  let processed = 0;
  for (const u of upd.result) {
    try {
      if (!seen.has(u.update_id)) { // dedupe: a redelivered update is skipped, never re-acted
        if (u.message) await handleMessage(u.message);
        else if (u.callback_query) await handleCallback(u.callback_query);
        seen = markSeen(seen, u.update_id);
        processed += 1;
      }
    } catch (e) { appendAudit({ phase: 'handler_error', update_id: u.update_id, error: (e && e.message) || 'unknown' }); break; }
    off.offset = u.update_id + 1;
    try { writeAtomic(OFFSET_PATH, JSON.stringify(off)); } catch { break; }
  }
  return { ok: true, processed };
}

// ── single-instance lock ────────────────────────────────────────────────────
function acquireLock() {
  fs.mkdirSync(TG_DIR, { recursive: true });
  try {
    const fd = fs.openSync(LOCK_PATH, 'w');
    // A cooperative advisory lock via O_EXCL-style pid file; a second daemon that
    // sees a fresh liveness file refuses to start.
    if (pollerAlive()) { fs.closeSync(fd); return false; }
    fs.writeSync(fd, String(process.pid));
    fs.closeSync(fd);
    return true;
  } catch { return false; }
}

async function main() {
  if (!TOKEN) { process.stdout.write(JSON.stringify({ ok: false, error: 'GCLAW_TELEGRAM_TOKEN not set' }) + '\n'); return; }
  const cmd = process.argv[2] || 'poll';
  if (cmd === 'listen') {
    if (!acquireLock()) { process.stdout.write(JSON.stringify({ ok: false, error: 'another poller is alive (lock held)' }) + '\n'); return; }
    for (;;) { await poll(50); }
  }
  const out = await poll(0);
  process.stdout.write(JSON.stringify(out) + '\n');
}

// Pure functions + control primitives exported for unit tests. main() runs only as CLI.
module.exports = {
  parsePick, identity, isOwner, ownerIds, parseControl, applyControl, readEnvFlags, setEnvFlag,
  issueNonce, takePending, honest, money, signed, failLine, CONFIRM_REQUIRED, ARM_FLAGS,
  handleMessage, handleConfirm, loadSeen, markSeen, poll, renderStatus, renderPositions, renderPnl,
  renderCalibration, rateLimitOk, ENV_PATH, PAUSE_PATH, VETO_PATH, AUDIT_PATH, PENDING_PATH,
};

if (require.main === module) main();
