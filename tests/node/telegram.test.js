// Guards for scripts/telegram.js — the three-plane command-and-control router.
//
// What these lock (each maps to a non-negotiable invariant of the design):
//   1. AUTH BOUNDARY — a control command from a NON-owner (or a group) is denied,
//      audited, and changes NO state. A stranger never owns the kill switch.
//   2. update_id DEDUPE — a redelivered update never double-acts (the Jane St bug).
//   3. SAFETY INVARIANT — a control command flips only the ENV FLAG / PAUSE / veto
//      and NEVER shells a fund primitive (no hl_perp open, no outcomes bet, no
//      carry live legs). Asserted by intercepting execFileSync.
//   4. /confirm NONCE FLOW — arming money needs a typed two-step confirm.
//   5. HONEST RENDERING — a read failure renders an explicit error, not "$0/flat";
//      n=0 renders "warming", never a fake 0.0.
//
// The Telegram API is mocked (https.request captured) — no real network, no real
// action. Source scripts are stubbed via an execFileSync spy so no trade can fire.

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const fs = require('node:fs');
const os = require('node:os');
const https = require('node:https');
const child_process = require('node:child_process');

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.resolve(HERE, '..', '..', 'scripts', 'telegram.js');

let tmp;
let savedEnv;
let sent; // captured Telegram sendMessage payloads
let realRequest;
let realExecFileSync;
let execCalls; // every execFileSync invocation (to assert no fund primitive)

// Intercept https.request so getUpdates returns queued updates and sendMessage is
// captured. The queue is set per-test via `queueUpdates`.
let updatesQueue;
function installHttpsMock() {
  realRequest = https.request;
  https.request = (url, _opts, cb) => {
    const u = String(url);
    let respObj = { ok: true, result: [] };
    if (u.includes('/getUpdates')) { respObj = { ok: true, result: updatesQueue.shift() || [] }; }
    else if (u.includes('/sendMessage')) { respObj = { ok: true }; }
    const body = JSON.stringify(respObj);
    const res = {
      on(event, handler) {
        if (event === 'data') handler(body);
        if (event === 'end') handler();
        return res;
      },
    };
    queueMicrotask(() => cb(res));
    return {
      on() { return this; },
      write(payload) {
        if (u.includes('/sendMessage')) { try { sent.push(JSON.parse(payload)); } catch { /* ignore */ } }
        return this;
      },
      end() {}, destroy() {},
    };
  };
}
function restoreHttpsMock() { https.request = realRequest; }

// Intercept execFileSync so NO real script runs and we can assert what was shelled.
// `execBehavior` is a per-test hook (bin,argsStr)->string|throw so a test can make a
// specific read fail. Default returns benign JSON so renderers don't crash; a fund
// primitive would show up in execCalls and fail the safety test.
let execBehavior;
function installExecMock() {
  realExecFileSync = child_process.execFileSync;
  execBehavior = () => '{"ok":true}';
  child_process.execFileSync = (bin, args) => {
    const argsStr = (args || []).join(' ');
    execCalls.push({ bin, args: argsStr });
    return execBehavior(bin, argsStr);
  };
}
function restoreExecMock() { child_process.execFileSync = realExecFileSync; }

function loadFresh() {
  delete require.cache[SCRIPT];
  return require(SCRIPT);
}
function msg(from, text, chatOverride) {
  return { message_id: 1, from, chat: { id: chatOverride ?? from.id }, text };
}
function readAudit() {
  const p = path.join(tmp, 'telegram', 'audit.jsonl');
  try { return fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)); } catch { return []; }
}

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-tg-'));
  savedEnv = { ...process.env };
  process.env.GCLAW_HOME = tmp;
  process.env.GCLAW_TELEGRAM_TOKEN = 'test-token';
  process.env.GCLAW_TELEGRAM_OWNER = '111'; // sole owner
  delete process.env.GCLAW_TELEGRAM_CHAT;
  sent = [];
  execCalls = [];
  updatesQueue = [];
  installHttpsMock();
  installExecMock();
});
afterEach(() => {
  restoreHttpsMock();
  restoreExecMock();
  fs.rmSync(tmp, { recursive: true, force: true });
  process.env = savedEnv;
  vi.restoreAllMocks();
});

// ── 1. AUTH BOUNDARY ─────────────────────────────────────────────────────────
describe('auth boundary — a non-owner control command is denied, audited, no state change', () => {
  test('non-owner /pause: no PAUSE file, denied+audited, no reply leaking the verb', async () => {
    const tg = loadFresh();
    await tg.handleMessage(msg({ id: 999, username: 'stranger' }, '/pause'));
    expect(fs.existsSync(tg.PAUSE_PATH)).toBe(false); // state untouched
    expect(sent.length).toBe(0); // never confirms the verb exists
    const audit = readAudit();
    expect(audit.some((a) => a.phase === 'authz_deny')).toBe(true);
  });

  test('owner /pause in a GROUP chat is hard-rejected (control is DM-only)', async () => {
    const tg = loadFresh();
    await tg.handleMessage(msg({ id: 111 }, '/pause', -100777)); // negative chat = group
    expect(fs.existsSync(tg.PAUSE_PATH)).toBe(false);
    const audit = readAudit();
    expect(audit.some((a) => a.phase === 'authz_deny' && a.reason === 'group chat')).toBe(true);
  });

  test('owner /pause in a DM works (the allow-list positive case)', async () => {
    const tg = loadFresh();
    await tg.handleMessage(msg({ id: 111 }, '/pause'));
    expect(fs.existsSync(tg.PAUSE_PATH)).toBe(true);
    expect(sent.some((s) => /Paused/.test(s.text))).toBe(true);
  });
});

// ── 2. update_id DEDUPE ──────────────────────────────────────────────────────
describe('update_id dedupe — a redelivered update never double-acts', () => {
  test('the same update_id delivered twice is processed once', async () => {
    const tg = loadFresh();
    const upd = { update_id: 42, message: msg({ id: 111 }, '/status') };
    updatesQueue = [[upd], [upd]]; // Telegram redelivers the identical update
    await tg.poll(0);
    const firstReplies = sent.length;
    expect(firstReplies).toBeGreaterThan(0);
    await tg.poll(0); // redelivery
    expect(sent.length).toBe(firstReplies); // no second reply → no double-act
  });
});

// ── 3. SAFETY INVARIANT ──────────────────────────────────────────────────────
describe('safety invariant — control flips env/PAUSE/veto, never a fund primitive', () => {
  const FUND_PRIMITIVES = ['hl_perp.js', 'outcomes.py', 'carry.js'];
  function assertNoFundMove() {
    for (const c of execCalls) {
      const isFundScript = FUND_PRIMITIVES.some((p) => c.args.includes(p));
      const isOpenOrBet = /\b(open|bet)\b/.test(c.args) || /--stake/.test(c.args) || c.args.includes('carry.js run');
      expect(isFundScript && isOpenOrBet).toBe(false);
    }
  }

  test('/arm outcomes → confirm flips ONLY the env flag, shells no fund primitive', async () => {
    const tg = loadFresh();
    await tg.handleMessage(msg({ id: 111 }, '/arm outcomes'));
    // a nonce was issued; env NOT yet armed (two-step)
    expect(tg.readEnvFlags().GCLAW_OUTCOMES_LIVE).toBeUndefined();
    const nonceMsg = sent.find((s) => /\/confirm/.test(s.text));
    expect(nonceMsg).toBeTruthy();
    const nonce = nonceMsg.text.match(/\/confirm (\w+)/)[1];
    await tg.handleMessage(msg({ id: 111 }, `/confirm ${nonce}`));
    expect(tg.readEnvFlags().GCLAW_OUTCOMES_LIVE).toBe('1'); // flag armed
    assertNoFundMove(); // and NOTHING moved money
  });

  test('/veto writes veto.json and shells no fund primitive', async () => {
    const tg = loadFresh();
    await tg.handleMessage(msg({ id: 111 }, '/veto no fundable margin'));
    const veto = JSON.parse(fs.readFileSync(tg.VETO_PATH, 'utf8'));
    expect(veto.veto).toBe(true);
    expect(veto.reason).toContain('no fundable margin');
    assertNoFundMove();
  });
});

// ── 4. /confirm NONCE FLOW ───────────────────────────────────────────────────
describe('/confirm nonce flow — arming money needs the typed two-step', () => {
  test('a wrong nonce does not arm; the right one does', async () => {
    const tg = loadFresh();
    await tg.handleMessage(msg({ id: 111 }, '/arm carry'));
    await tg.handleMessage(msg({ id: 111 }, '/confirm WRONG'));
    expect(tg.readEnvFlags().GCLAW_CARRY_LIVE).toBeUndefined();
    const nonce = sent.find((s) => /\/confirm/.test(s.text)).text.match(/\/confirm (\w+)/)[1];
    await tg.handleMessage(msg({ id: 111 }, `/confirm ${nonce}`));
    expect(tg.readEnvFlags().GCLAW_CARRY_LIVE).toBe('1');
  });

  test('a non-owner cannot spend a pending nonce', async () => {
    const tg = loadFresh();
    await tg.handleMessage(msg({ id: 111 }, '/arm carry'));
    const nonce = sent.find((s) => /\/confirm/.test(s.text)).text.match(/\/confirm (\w+)/)[1];
    await tg.handleMessage(msg({ id: 999, username: 'stranger' }, `/confirm ${nonce}`));
    expect(tg.readEnvFlags().GCLAW_CARRY_LIVE).toBeUndefined();
  });

  test('/pause needs NO confirm (kill switch is friction-free)', async () => {
    const tg = loadFresh();
    await tg.handleMessage(msg({ id: 111 }, '/pause'));
    expect(fs.existsSync(tg.PAUSE_PATH)).toBe(true); // took effect immediately
  });
});

// ── 5. HONEST RENDERING ──────────────────────────────────────────────────────
describe('honest rendering — a read failure is an error string, not $0/flat; n=0 → warming', () => {
  test('honest(null) is "warming", never a fake zero', () => {
    const tg = loadFresh();
    expect(tg.honest(null)).toBe('warming');
    expect(tg.honest(undefined)).toBe('warming');
    expect(tg.money(NaN)).toBe('warming');
  });

  test('a positions read failure renders the failure line, never a fake $0/flat book', () => {
    execBehavior = () => { throw new Error('SDK read failed'); };
    const tg = loadFresh();
    const out = tg.renderPositions();
    expect(out).toContain("couldn't read");
    expect(out).not.toMatch(/\$0\.00/); // never a fabricated zero equity
    expect(out).not.toMatch(/0 open/); // never a fabricated flat book
  });

  test('an hl_perp {ok:false} (venue error) renders the failure line, not a flat book', () => {
    execBehavior = () => JSON.stringify({ ok: false, error: 'venue unreachable' });
    const tg = loadFresh();
    const out = tg.renderPositions();
    expect(out).toContain("couldn't read");
    expect(out).not.toMatch(/0 open|\$0\.00/);
  });

  test('calibration with n=0 renders "warming", not "0.0"', () => {
    execBehavior = () => JSON.stringify({ ok: true, aggregates: { n: 0, n_resolved: 0, brier_mean: null } });
    const tg = loadFresh();
    const out = tg.renderCalibration();
    expect(out).toMatch(/warming/);
    expect(out).not.toMatch(/0\.0/);
  });
});
