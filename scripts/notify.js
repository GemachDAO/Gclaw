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

async function send(level, message) {
  const text = `🜃 Gclaw #${agentId()} [${level.toUpperCase()}] ${message}`;
  const out = { ok: true, sent: [] };
  const webhook = process.env.GCLAW_ALERT_WEBHOOK;
  if (webhook) { await post(webhook, { text, content: text, level, message }); out.sent.push('webhook'); }
  const tg = process.env.GCLAW_TELEGRAM_TOKEN, chat = process.env.GCLAW_TELEGRAM_CHAT;
  if (tg && chat) { await post(`https://api.telegram.org/bot${tg}/sendMessage`, { chat_id: chat, text }); out.sent.push('telegram'); }
  if (!out.sent.length) out.skip = 'no GCLAW_ALERT_WEBHOOK / telegram configured';
  return out;
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
  else out = { ok: false, error: 'usage: notify.js <send <level> <msg> | check>' };
  process.stdout.write(JSON.stringify(out) + '\n');
}

main();
