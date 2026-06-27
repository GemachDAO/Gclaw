// GCLAW_SESSION injection — the sandboxed-cycle path of hl_perp.js. When the heartbeat
// runs the cycle under bwrap (GCLAW_SANDBOX=1), the wallet file is masked and the
// control-key sign-in already ran outside. hl_perp.js must then trade from the injected
// ephemeral session WITHOUT reading the wallet or holding the control private key.

import { afterEach, describe, expect, test } from 'vitest';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const hl = require('../../scripts/hl_perp.js');

// apiKey must be UUID-format — loginWithApiKey validates the shape synchronously (no network).
const SESSION = { apiKey: '00000000-0000-0000-0000-000000000000', walletAddress: '0xControl', sessionPrivateKey: '0xsess', managed: '0xManaged' };

describe('GCLAW_SESSION injection (sandboxed cycle)', () => {
  afterEach(() => {
    delete process.env.GCLAW_SESSION;
    delete process.env.GCLAW_WALLET;
  });

  test('loadWallet uses the injected session and never reads the wallet file', () => {
    process.env.GCLAW_WALLET = '/nonexistent/wallet.json'; // would throw if it were read
    process.env.GCLAW_SESSION = JSON.stringify(SESSION);
    const w = hl.loadWallet();
    expect(w).toEqual({ control: '0xControl', managed: '0xManaged' });
    expect(w.pk).toBeUndefined(); // the control private key never enters this process
  });

  test('signedSkill builds a skill from the session creds, no control key, no re-sign', async () => {
    process.env.GCLAW_SESSION = JSON.stringify(SESSION);
    let res;
    try {
      res = await hl.signedSkill({});
    } catch (e) {
      if (/Cannot find module/.test(e.message)) return; // GDEX SDK absent (CI installs vitest only) — skip
      throw e;
    }
    expect(res.creds).toEqual({ apiKey: SESSION.apiKey, walletAddress: '0xControl', sessionPrivateKey: '0xsess' });
    expect(res.skill).toBeDefined();
  });
});
