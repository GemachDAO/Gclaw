#!/usr/bin/env node
/**
 * Telegram input for the "Call it" game — turns a reply into a prediction.
 *
 * Anyone who DMs the bot and sends "TP" or "SL" gets their call recorded on the
 * open round, keyed to their Telegram identity (@username, else tg:<id>) — which
 * is exactly the handle they climb the global ladder under. Reuses predict.js for
 * the actual call (so every call is anchored onchain the same way). No funds, ever.
 *
 *   node predict_bot.js poll      # process pending messages once, then exit (cron)
 *   node predict_bot.js listen    # long-poll forever (real-time daemon)
 *
 * Recognised messages: "TP" / "SL" (optionally with a coin, e.g. "TP SOL"),
 * "board"/"leaderboard" (global ladder), "rounds" (what's open), "help".
 * Env: GCLAW_TELEGRAM_TOKEN (required), GCLAW_HOME, GDEX_SKILL_DIR.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');
const { execFileSync } = require('node:child_process');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const DIR = path.join(GCLAW_HOME, 'predictions');
const OFFSET_PATH = path.join(DIR, 'tg_offset.json');
const SELF = path.join(__dirname, 'predict.js');
const TOKEN = process.env.GCLAW_TELEGRAM_TOKEN;

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };

function tg(method, params, timeoutMs = 15000) {
  return new Promise((resolve) => {
    const body = JSON.stringify(params || {});
    const req = https.request(`https://api.telegram.org/bot${TOKEN}/${method}`,
      { method: 'POST', headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) }, timeout: timeoutMs },
      (res) => { let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => { try { resolve(JSON.parse(b)); } catch { resolve(null); } }); });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.write(body); req.end();
  });
}

// predict.js prints one pretty (multi-line) JSON object — parse the whole blob
// from its first brace, not the last line (which is just "}").
const predict = (args) => {
  try {
    const out = execFileSync('node', [SELF, ...args], { encoding: 'utf8', timeout: 90000 });
    return JSON.parse(out.slice(out.indexOf('{')));
  } catch (e) { return { ok: false, error: e.message }; }
};

function openRounds() {
  return Object.values(readJson(path.join(DIR, 'rounds.json'), {})).filter((r) => r.status === 'open');
}

// "@alice" if they have a username, else a stable per-account handle. This IS their
// identity on the global ladder, so it must be stable across calls + creatures.
function identity(from) { return from && from.username ? `@${from.username}` : `tg:${from && from.id}`; }

// Only count a message that IS a call — the whole message must be the pick (with
// an optional "call" verb and/or a coin), so ordinary chat like "what is up" or
// "i'm down" is never logged as a prediction.
function parsePick(text) {
  const s = String(text || '').trim().toLowerCase().replace(/[!.?]+$/, '');
  const m = s.match(/^(?:(?:i\s+)?call\s+)?(tp|sl|take\s*profit|stop\s*loss|📈|📉)(?:\s+[a-z]{2,6})?$/i)
    || s.match(/^[a-z]{2,6}\s+(tp|sl|take\s*profit|stop\s*loss|📈|📉)$/i);
  if (!m) return null;
  const w = m[1].replace(/\s+/g, '');
  return ['tp', 'takeprofit', '📈'].includes(w) ? 'TP' : 'SL';
}

function boardText() {
  const g = predict(['global']);
  const rows = (g.predictors || []).slice(0, 10).map((e, i) => `${i + 1}. ${e.by} — ${e.accuracy}% (${e.correct}/${e.total})`);
  return rows.length ? `🌐 Global predictors ladder\n${rows.join('\n')}` : 'No predictors yet — be the first to call a round right.';
}

function roundsText() {
  const open = openRounds();
  return open.length ? `Open rounds — reply TP or SL:\n${open.map((r) => `• ${r.coin} ${r.side} @ $${r.entry} (round ${r.id})`).join('\n')}` : 'No open round right now — one opens when the creature opens a trade.';
}

async function handle(msg) {
  if (!msg || !msg.text) return;
  const chat = msg.chat.id;
  const text = msg.text.trim();
  if (/^\/?(help|start)\b/i.test(text)) {
    await tg('sendMessage', { chat_id: chat, text: 'Call it 🎯 — when the creature opens a trade, reply *TP* or *SL* to predict the outcome. Free, no stakes; your calls are anchored onchain and you climb the global ladder.\n\n"board" = ladder · "rounds" = what\'s open', parse_mode: 'Markdown' });
    return;
  }
  if (/^\/?(board|leaderboard|ladder)\b/i.test(text)) { await tg('sendMessage', { chat_id: chat, text: boardText() }); return; }
  if (/^\/?rounds?\b/i.test(text)) { await tg('sendMessage', { chat_id: chat, text: roundsText() }); return; }
  const pick = parsePick(text);
  if (!pick) return; // not a command we recognise — stay quiet
  const open = openRounds();
  if (!open.length) { await tg('sendMessage', { chat_id: chat, text: 'No open round to call right now — I\'ll ping when the next trade opens.' }); return; }
  const coin = (text.toUpperCase().match(/\b(BTC|ETH|SOL|[A-Z]{2,6})\b/g) || []).find((c) => open.some((r) => r.coin === c));
  const round = coin ? open.find((r) => r.coin === coin) : open[open.length - 1];
  if (open.length > 1 && !coin) { await tg('sendMessage', { chat_id: chat, text: `Which one?\n${open.map((r) => `• ${r.coin} — reply "${pick} ${r.coin}"`).join('\n')}` }); return; }
  const by = identity(msg.from);
  const res = predict(['call', '--round', round.id, '--pick', pick, '--by', by]);
  if (res.ok) await tg('sendMessage', { chat_id: chat, text: `✅ Logged your ${pick} on ${round.coin} as ${by}. Anchored onchain — good luck. (you climb the global ladder if it lands)` });
  else await tg('sendMessage', { chat_id: chat, text: `⚠️ ${res.error || 'could not log that call'}` });
}

async function poll(timeoutSec) {
  const off = readJson(OFFSET_PATH, { offset: 0 });
  const params = { offset: off.offset, timeout: timeoutSec || 0, allowed_updates: ['message'] };
  let upd = await tg('getUpdates', params, (timeoutSec || 0) * 1000 + 15000);
  if (!upd || !upd.ok) upd = await tg('getUpdates', params, (timeoutSec || 0) * 1000 + 15000); // one retry on a transient null
  if (!upd || !upd.ok) return { ok: false, error: 'getUpdates failed' };
  let processed = 0;
  for (const u of upd.result) {
    off.offset = u.update_id + 1;
    if (u.message) { await handle(u.message); processed += 1; }
  }
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(OFFSET_PATH, JSON.stringify(off));
  return { ok: true, processed };
}

async function main() {
  if (!TOKEN) { process.stdout.write(JSON.stringify({ ok: false, error: 'GCLAW_TELEGRAM_TOKEN not set' }) + '\n'); process.exit(0); }
  const cmd = process.argv[2] || 'poll';
  if (cmd === 'listen') {
    for (;;) { await poll(50); } // long-poll loop
  }
  const out = await poll(0);
  process.stdout.write(JSON.stringify(out) + '\n');
}

main();
