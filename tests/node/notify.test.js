// The health-alert dedup (scripts/notify.js check()): a critical, trading-blocking
// condition must NOT alert once and then go silent for days — that's exactly how a
// falsely-tripped breaker sat unnoticed. check() should:
//   - fire when a condition first appears,
//   - stay quiet while it persists within the re-remind window,
//   - re-alert a persistent CRITICAL condition once the window elapses,
//   - re-alert immediately when the message escalates (e.g. a deeper drawdown),
//   - clear a resolved condition so its later return fires again.
// deliver() no-ops without a webhook/telegram, so check() drives with no network.

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';
import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const os = require('node:os');
const fs = require('node:fs');

let tmp;
let savedEnv;
beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-notify-'));
  savedEnv = { ...process.env };
  process.env.GCLAW_HOME = tmp;
  // Guarantee no real delivery during the test, whatever the shell exported.
  delete process.env.GCLAW_ALERT_WEBHOOK;
  delete process.env.GCLAW_TELEGRAM_TOKEN;
  delete process.env.GCLAW_TELEGRAM_CHAT;
});
afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
  process.env = savedEnv;
});

function setBreaker(reason) {
  fs.writeFileSync(path.join(tmp, 'breaker.json'), JSON.stringify({ tripped: true, reason }));
}
function clearBreaker() {
  fs.writeFileSync(path.join(tmp, 'breaker.json'), JSON.stringify({ tripped: false }));
}
const alerts = () => JSON.parse(fs.readFileSync(path.join(tmp, 'alerts.json'), 'utf8'));

describe('check() — persistent critical conditions re-remind, they do not go silent', () => {
  test('first appearance fires; persistence within the window stays quiet', async () => {
    process.env.GCLAW_ALERT_REMIND_H = '24';
    const notify = loadScript('notify.js');
    setBreaker('drawdown 26%');
    expect((await notify.check()).fired).toContain('breaker');
    // still tripped, same message, within 24h → no repeat alert (no spam)
    expect((await notify.check()).fired).not.toContain('breaker');
  });

  test('a persistent critical condition re-alerts once the re-remind window elapses', async () => {
    process.env.GCLAW_ALERT_REMIND_H = '24';
    const notify = loadScript('notify.js');
    setBreaker('drawdown 26%');
    await notify.check(); // first fire
    // backdate lastFired beyond the window to simulate a day passing
    const st = alerts();
    st.breaker.lastFired = Date.now() - 25 * 3600 * 1000;
    fs.writeFileSync(path.join(tmp, 'alerts.json'), JSON.stringify(st));
    expect((await notify.check()).fired).toContain('breaker'); // re-reminded
  });

  test('an escalating message re-alerts immediately, even within the window', async () => {
    process.env.GCLAW_ALERT_REMIND_H = '24';
    const notify = loadScript('notify.js');
    setBreaker('drawdown 26%');
    await notify.check();
    setBreaker('drawdown 41%'); // got worse
    expect((await notify.check()).fired).toContain('breaker');
  });

  test('a resolved condition clears, and its later return fires again', async () => {
    const notify = loadScript('notify.js');
    setBreaker('drawdown 26%');
    await notify.check();
    clearBreaker();
    await notify.check();
    expect(alerts().breaker).toBeUndefined(); // cleared from the baseline
    setBreaker('drawdown 30%');
    expect((await notify.check()).fired).toContain('breaker'); // returns → fires
  });
});
