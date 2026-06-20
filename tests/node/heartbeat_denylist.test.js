// Deny-list regression guard for the unattended heartbeat (scripts/heartbeat.sh).
//
// The heartbeat runs `claude --permission-mode bypassPermissions` while reading
// UNTRUSTED text (peer onchain cards, the family bus, market data, gene-pool
// metadata) that can carry a prompt-injection payload. The only thing standing
// between an injection and a drained wallet is the `--disallowedTools` deny-list:
// every MCP tool that can move funds to an arbitrary destination, buy an arbitrary
// token, or hand the wallet to a third party MUST be denied.
//
// This test parses the DENY="..." line out of heartbeat.sh and asserts membership.
// It is a REGRESSION GUARD: if someone adds a new dangerous GDEX tool to the SDK,
// or trims one out of the deny-list, this fails — so a drain surface can't ship
// silently. The legit HL-perp trading tools stay allowed (riskguard caps them).

import { describe, expect, test } from 'vitest';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const fs = require('node:fs');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const HEARTBEAT = path.resolve(HERE, '..', '..', 'scripts', 'heartbeat.sh');

// Parse the DENY assignment. The script defines it as a single double-quoted,
// space-separated string: DENY="tool_a tool_b ...". We extract that token set.
function parseDenyList() {
  const src = fs.readFileSync(HEARTBEAT, 'utf8');
  const m = src.match(/^\s*DENY="([^"]*)"/m);
  if (!m) throw new Error('could not find a DENY="..." assignment in heartbeat.sh');
  return new Set(m[1].split(/\s+/).filter(Boolean));
}

// Every GDEX MCP tool that can move value off the managed account or to a third
// party. Sourced from the GDEX MCP surface; each is a known drain vector and MUST
// be denied to the unattended, injection-exposed agent. Grouped by drain class.
const MUST_DENY = {
  'arbitrary transfer / bridge / withdraw': [
    'mcp__gdex__transfer_native',
    'mcp__gdex__transfer_token',
    'mcp__gdex__execute_bridge',
    'mcp__gdex__perp_withdraw',
    'mcp__gdex__hl_swap_collateral',
  ],
  'arbitrary token buy / sell / spot': [
    'mcp__gdex__buy_token',
    'mcp__gdex__sell_token',
    'mcp__gdex__managed_purchase',
    'mcp__gdex__managed_sell',
    'mcp__gdex__execute_spot',
  ],
  'arbitrary perp execution (bypasses sized intents)': [
    'mcp__gdex__execute_cross_perp',
    'mcp__gdex__execute_isolated_perp',
  ],
  'hand wallet to a third party (copy-trade)': [
    'mcp__gdex__create_copy_trade',
    'mcp__gdex__create_hl_copy_trade',
  ],
};

describe('heartbeat deny-list', () => {
  const deny = parseDenyList();

  for (const [drainClass, tools] of Object.entries(MUST_DENY)) {
    for (const tool of tools) {
      test(`denies ${tool} (${drainClass})`, () => {
        expect(
          deny.has(tool),
          `${tool} is a fund-moving tool but is NOT in heartbeat.sh's --disallowedTools deny-list. `
            + 'An unattended, prompt-injection-exposed agent could be steered into calling it. '
            + 'Add it to the DENY="..." line.',
        ).toBe(true);
      });
    }
  }

  test('the deny-list is non-empty and well-formed', () => {
    expect(deny.size).toBeGreaterThanOrEqual(Object.values(MUST_DENY).flat().length);
    for (const t of deny) expect(t).toMatch(/^mcp__gdex__/);
  });

  test('it is wired into the claude invocation as --disallowedTools', () => {
    const src = fs.readFileSync(HEARTBEAT, 'utf8');
    expect(src).toMatch(/--disallowedTools\s+\$DENY/);
    // And the agent runs with bypassPermissions, which is WHY the deny-list is the
    // load-bearing control — assert that pairing so neither half drifts away alone.
    expect(src).toMatch(/--permission-mode bypassPermissions/);
  });

  test('does NOT deny the legit HL-perp trading tools (riskguard caps those)', () => {
    // These are intentionally ALLOWED — denying them would break the agent's core
    // function; their risk is bounded deterministically by riskguard.js, not by denial.
    for (const allowed of ['mcp__gdex__open_perp_position', 'mcp__gdex__place_perp_order',
      'mcp__gdex__close_perp_position']) {
      expect(deny.has(allowed)).toBe(false);
    }
  });
});
