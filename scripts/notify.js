#!/usr/bin/env node
/**
 * Health alerting for the unattended bot — so a silent failure never goes unseen.
 *
 *   node notify.js send <level> <message...>   # push one alert
 *   node notify.js check                        # evaluate red conditions, alert on new ones
 *
 * Posts to GCLAW_ALERT_WEBHOOK (Slack/Discord/generic JSON — sends both `text`
 * and `content`) and optionally Telegram (GCLAW_TELEGRAM_TOKEN + _CHAT). No-ops
 * cleanly without a webhook. `check` dedupes by condition so it alerts on the
 * transition (entered hibernate / went low) — not every hour.
 * Env: GCLAW_HOME, GCLAW_ALERT_WEBHOOK, GCLAW_TELEGRAM_TOKEN, GCLAW_TELEGRAM_CHAT.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };
const agentId = () => readJson(path.join(GCLAW_HOME, 'metabolism.json'), {}).onchain_identity?.agentId || '?';

async function post(url, body, headers) {
  return new Promise((resolve) => {
    try {
      const u = new URL(url);
      const data = JSON.stringify(body);
      const req = require(u.protocol === 'http:' ? 'node:http' : 'node:https').request(
        u, { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(data), ...headers } },
        (res) => { res.on('data', () => {}); res.on('end', () => resolve(res.statusCode)); });
      req.on('error', () => resolve(null));
      req.write(data); req.end();
    } catch { resolve(null); }
  });
}

const readJsonl = (p) => { try { return fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)); } catch { return []; } };

// The creature's own voice — so it texts you in character, not as a robot.
function soul() {
  const p = readJson(path.join(GCLAW_HOME, 'dna', 'persona.json'), {});
  const m = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  return { name: m.name || p.species || p.name || 'Gclaw', sigil: p.sigil || '🜂',
    catchphrase: p.catchphrase || '', archetype: p.archetype || '' };
}
function voiced(msg, big) {
  const s = soul();
  return `${s.sigil} ${s.name}: ${msg}` + (big && s.catchphrase ? `  —  “${s.catchphrase}”` : '');
}

async function deliver(text) {
  const sent = [];
  const webhook = process.env.GCLAW_ALERT_WEBHOOK;
  if (webhook) { await post(webhook, { text, content: text }); sent.push('webhook'); }
  const tg = process.env.GCLAW_TELEGRAM_TOKEN, chat = process.env.GCLAW_TELEGRAM_CHAT;
  if (tg && chat) { await post(`https://api.telegram.org/bot${tg}/sendMessage`, { chat_id: chat, text }); sent.push('telegram'); }
  return sent;
}

async function send(level, message) {
  const sent = await deliver(`🜃 ${soul().name} #${agentId()} [${level.toUpperCase()}] ${message}`);
  return sent.length ? { ok: true, sent } : { ok: true, sent: [], skip: 'no GCLAW_ALERT_WEBHOOK / telegram configured' };
}

const GW_TIERS = [[10, ''], [25, ''], [40, ' — a second heartbeat is forming inside the genome 🧬'],
  [48, ' — two more good trades and I can split. Ready a name.'],
  [50, ' — I\'m ready to reproduce. Run `gclaw beat` or reproduce me to meet my child 🧬'],
  [100, ' — can self-recode'], [200, ''], [500, ''], [1000, ' — MAX leverage unlocked ⚡']];
const HB_TIERS = [100, 250, 500, 1000, 2500, 5000];
const STREAK_TIERS = [3, 5, 10, 25];

// The dopamine loop: each heartbeat, detect the GOOD moments and text them in the
// creature's voice — wins, streaks, milestones, records, evolutions, climbs. First
// run baselines (no retroactive spam); thereafter it fires only on new events.
async function celebrate() {
  const meta = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  const lb = readJson(path.join(GCLAW_HOME, 'leaderboard.json'), {});
  const rank = (lb.ranked || []).find((e) => e.self)?.rank ?? null;
  const stPath = path.join(GCLAW_HOME, 'celebrations.json');
  const first = !fs.existsSync(stPath);
  const settles = readJsonl(path.join(GCLAW_HOME, 'journal.jsonl')).filter((e) => e.event === 'settle');
  const lastSettleTs = settles.length ? Math.max(...settles.map((s) => new Date(s.ts).getTime())) : 0;
  const kids = (meta.children || []).length;
  const st = readJson(stPath, {});
  if (first) {  // baseline: remember where we are, celebrate nothing retroactively
    fs.writeFileSync(stPath, JSON.stringify({ unlocked: {}, lastSettleTs, winStreak: 0,
      lastGoodwill: meta.goodwill || 0, lastRank: rank, lastHeartbeats: meta.heartbeats || 0,
      lastChildren: kids, lastRecodes: meta.recodes || 0 }, null, 2));
    return { ok: true, initialized: true };
  }
  const fired = [];
  const fire = async (key, msg, big) => { if (st.unlocked[key]) return; if (key.startsWith('once:')) st.unlocked[key] = new Date().toISOString(); const v = voiced(msg, big); fired.push(v); await deliver(v); };

  for (const s of settles.filter((e) => new Date(e.ts).getTime() > (st.lastSettleTs || 0))) {
    if (Number(s.pnl) > 0.01) { st.winStreak = (st.winStreak || 0) + 1; await fire(`win:${s.ts}`, `booked +$${Number(s.pnl).toFixed(2)} 💚  ⭐ goodwill ${s.goodwill}`, false); } else if (Number(s.pnl) < -0.01) { st.winStreak = 0; }
    if (Number(s.gmac_buyback_usd) > 0.01) await fire(`burn:${s.ts}`, `bought & burned $${Number(s.gmac_buyback_usd).toFixed(2)} of $GMAC 🔥`, false);
  }
  st.lastSettleTs = lastSettleTs;
  for (const n of STREAK_TIERS) if (st.winStreak === n) await fire(`streak:${n}:${Math.floor((meta.heartbeats || 0) / 100)}`, `🔥 ${n} wins in a row`, true);
  const gw = meta.goodwill || 0;
  for (const [tier, label] of GW_TIERS) if (gw >= tier && (st.lastGoodwill || 0) < tier) await fire(`once:gw${tier}`, `hit ⭐ goodwill ${tier}${label}`, true);
  st.lastGoodwill = gw;
  const seed = meta.seed || 1000;
  if ((meta.gmac_balance || 0) > seed) await fire('once:seedback', `clawed back above its ${seed} GMAC seed — in the black`, true);
  const hb = meta.heartbeats || 0;
  for (const n of HB_TIERS) if (hb >= n && (st.lastHeartbeats || 0) < n) await fire(`once:hb${n}`, `${n} heartbeats and still alive`, true);
  st.lastHeartbeats = hb;
  if (kids > (st.lastChildren || 0)) {
    const c = meta.children[kids - 1] || {};
    const pj = readJson(path.join(GCLAW_HOME, 'children', c.name || '', 'persona.json'), {});
    const soul = pj.archetype ? ` — ${pj.archetype}` : '';
    const diff = c.mutation ? ` Born from my genome with one change: ${c.mutation}.` : '';
    await fire(`child:${c.name}`, `I have a child. ${c.name || '?'}${soul}.${diff} 🧬`, true);
  }
  st.lastChildren = kids;
  if ((meta.recodes || 0) > (st.lastRecodes || 0)) await fire(`recode:${meta.recodes}`, `rewrote its own code (recode #${meta.recodes}) 🛠️`, true);
  st.lastRecodes = meta.recodes || 0;
  if (rank != null && st.lastRank != null && rank < st.lastRank) { fired.push(voiced(`climbed to #${rank} on the family leaderboard 📈`, false)); await deliver(fired[fired.length - 1]); }
  if (rank != null) st.lastRank = rank;
  fs.writeFileSync(stPath, JSON.stringify(st, null, 2) + '\n');
  return { ok: true, fired };
}

function conditions() {
  const meta = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  const gas = readJson(path.join(GCLAW_HOME, 'gas.json'), {});
  const breaker = readJson(path.join(GCLAW_HOME, 'breaker.json'), {});
  const pos = readJson(path.join(GCLAW_HOME, 'positions.json'), {});
  const out = {};
  if (meta.mode === 'hibernate') out.hibernate = `HIBERNATING (GMAC ${Math.round(meta.gmac_balance || 0)}) — fund it to revive`;
  if (gas.status && gas.status !== 'healthy') out.gas = `beacon gas ${gas.status} (~${gas.beaconRunway} left) — top up Base ETH`;
  if (breaker.tripped) out.breaker = `circuit breaker TRIPPED: ${breaker.reason}`;
  if (pos.ok && Number(pos.spotUsdc) < 12 && !(pos.positions || []).length) out.funds = `trading funds low ($${Number(pos.spotUsdc).toFixed(2)}) and flat`;
  return out;
}

async function check() {
  const cur = conditions();
  const seenPath = path.join(GCLAW_HOME, 'alerts.json');
  const seen = readJson(seenPath, {});
  const fired = [];
  for (const [k, msg] of Object.entries(cur)) {
    if (!seen[k]) { await send(k === 'hibernate' || k === 'breaker' ? 'critical' : 'warning', msg); fired.push(k); }
  }
  fs.writeFileSync(seenPath, JSON.stringify(cur) + '\n');  // current = new baseline (clears resolved)
  return { ok: true, fired, active: Object.keys(cur) };
}

async function main() {
  const cmd = process.argv[2];
  let out;
  if (cmd === 'send') out = await send(process.argv[3] || 'info', process.argv.slice(4).join(' '));
  else if (cmd === 'check') out = await check();
  else if (cmd === 'celebrate') out = await celebrate();
  else out = { ok: false, error: 'usage: notify.js <send <level> <msg> | check | celebrate>' };
  process.stdout.write(JSON.stringify(out) + '\n');
}

main();
