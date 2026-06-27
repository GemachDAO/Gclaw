// sandbox_cycle.sh masks the money secrets from a wrapped command. Skipped where bwrap
// is unavailable (the CI node job installs vitest only), so it validates locally where
// bubblewrap is present.

import { describe, expect, test } from 'vitest';
import { execFileSync, execSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.join(dir, '..', '..', 'scripts', 'sandbox_cycle.sh');

const hasBwrap = (() => {
  try {
    execSync('command -v bwrap', { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
})();

const run = (env, ...cmd) =>
  execFileSync(SCRIPT, cmd, { encoding: 'utf8', env: { ...process.env, ...env } }).trim();

describe.skipIf(!hasBwrap)('sandbox_cycle.sh', () => {
  const tmp = mkdtempSync(path.join(tmpdir(), 'gclaw-sbx-'));
  const wallet = path.join(tmp, 'wallet.json');
  writeFileSync(wallet, JSON.stringify({ control: { privateKey: '0xDEADBEEF_SECRET' } }));

  test('masks the wallet file — the control key is unreadable inside', () => {
    const outside = execSync(`cat ${wallet}`, { encoding: 'utf8' });
    expect(outside).toContain('0xDEADBEEF_SECRET');
    const inside = run({ GCLAW_WALLET: wallet }, 'sh', '-c', `cat ${wallet} 2>/dev/null || true`);
    expect(inside).toBe(''); // bound to /dev/null — reads empty
  });

  test('strips secret env vars but keeps GCLAW_SESSION (the trade cred)', () => {
    const out = run(
      { GCLAW_WALLET: wallet, PINATA_JWT: 'jwt-secret', GCLAW_SESSION: 'sess-token' },
      'sh',
      '-c',
      'echo "jwt=[$PINATA_JWT] sess=[$GCLAW_SESSION]"',
    );
    expect(out).toBe('jwt=[] sess=[sess-token]');
  });

  test('non-secret files and interpreters still work inside', () => {
    expect(run({ GCLAW_WALLET: wallet }, 'node', '-e', 'console.log(40+2)')).toBe('42');
  });
});
