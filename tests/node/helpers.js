// Test helpers for the Gclaw CommonJS node scripts.
//
// This file is ESM (vitest 4 test files must be ESM — you cannot `require('vitest')`).
// The SCRIPTS, however, are CommonJS. We bridge with createRequire: load a CJS
// script's module.exports from an ESM test.
//
// THE PROBLEM these solve: every script in scripts/*.js calls `main()` at the
// bottom of the file and, by default, exports nothing. A naive load would fire
// real network calls and return {}.
//
// THE PATTERN (do this once per script you want to unit-test):
//   1. Guard the auto-run so it only fires as a CLI, not on require:
//        if (require.main === module) {
//          main().catch((e) => { ...; process.exit(1); });
//        }
//   2. Export the pure functions you want to test:
//        module.exports = { rsi, atrPct, classifyRegime, efficiencyRatio };
//   Then `loadScript('intel.js')` returns those exports with NO main() side effects.
//
// The https boundary: intel.js (and peers) POST to api.hyperliquid.xyz via
// node:https. Pure indicator functions don't touch it, so unit tests of those
// need no mock. For the rare test that drives a function which fetches, use
// `withHttpsMock(payloads, fn)` to replay recorded responses instead of network.

import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS_DIR = path.resolve(HERE, '..', '..', 'scripts');
const FIXTURES_DIR = path.resolve(HERE, '..', 'fixtures');

const require = createRequire(import.meta.url);

/**
 * Require a script from scripts/ and return its module.exports.
 * Requires the script to guard main() with `require.main === module` and to
 * export the functions under test. Throws a clear error if it exports nothing —
 * that's the signal to add the export line + guard.
 *
 * @param {string} file e.g. 'intel.js'
 * @returns {Record<string, unknown>}
 */
function loadScript(file) {
  const full = path.join(SCRIPTS_DIR, file);
  delete require.cache[full]; // fresh top-level state every load
  const mod = require(full);
  if (!mod || (typeof mod === 'object' && Object.keys(mod).length === 0)) {
    throw new Error(
      `${file} exports nothing. Add \`module.exports = { ...pureFns }\` and guard ` +
        '`main()` with `if (require.main === module)` so it is unit-testable.',
    );
  }
  return mod;
}

/**
 * Load a recorded HyperLiquid payload from tests/fixtures/<name>.json.
 * @param {string} name e.g. 'candles_btc_1h'
 * @returns {unknown}
 */
function hlFixture(name) {
  return require(path.join(FIXTURES_DIR, `${name}.json`));
}

/**
 * Replace node:https' request with a stub that resolves each call to the next
 * queued payload, runs `fn`, then restores the real https. The scripts' `info()`
 * helper only reads the JSON body, so we emulate just enough of the request/
 * response event API. Use ONLY for tests that must exercise a fetching function;
 * prefer testing the pure math directly.
 *
 * @param {unknown[]} payloads responses to replay, in call order
 * @param {() => unknown | Promise<unknown>} fn
 */
async function withHttpsMock(payloads, fn) {
  const https = require('node:https');
  const realRequest = https.request;
  const queue = [...payloads];
  https.request = (_url, _opts, cb) => {
    const body = JSON.stringify(queue.shift() ?? null);
    const res = {
      on(event, handler) {
        if (event === 'data') handler(body);
        if (event === 'end') handler();
        return res;
      },
    };
    queueMicrotask(() => cb(res));
    return { on() {}, write() {}, end() {}, destroy() {} };
  };
  try {
    return await fn();
  } finally {
    https.request = realRequest;
  }
}

export { loadScript, hlFixture, withHttpsMock, SCRIPTS_DIR, FIXTURES_DIR };
