// Owner withdrawal (scripts/withdraw.js). The load-bearing safety property is the
// anti-drain guard: a real (--confirm) withdrawal must be refused unless run from an
// interactive terminal, so the headless autonomous heartbeat can never move funds
// through it. Unit-tested here without the GDEX SDK (requireOwner touches neither).

import { afterEach, describe, expect, test, vi } from 'vitest';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const w = require('../../scripts/withdraw.js');

describe('withdraw.js', () => {
  afterEach(() => vi.restoreAllMocks());

  test('parseArgs reads flags, values, and boolean switches', () => {
    expect(w.parseArgs(['--to', '0xabc', '--amount', '50', '--confirm'])).toEqual({
      to: '0xabc',
      amount: '50',
      confirm: true,
    });
  });

  test('requireOwner refuses when stdin is not a TTY (the headless agent case)', () => {
    const exit = vi.spyOn(process, 'exit').mockImplementation((c) => {
      throw new Error(`exit:${c}`);
    });
    const out = vi.spyOn(process.stdout, 'write').mockImplementation(() => true);
    const orig = Object.getOwnPropertyDescriptor(process.stdin, 'isTTY');
    Object.defineProperty(process.stdin, 'isTTY', { value: false, configurable: true });

    expect(() => w.requireOwner()).toThrow('exit:1');
    expect(out).toHaveBeenCalledWith(expect.stringContaining('interactive terminal'));

    if (orig) Object.defineProperty(process.stdin, 'isTTY', orig);
  });

  test('requireOwner allows an interactive terminal (the owner)', () => {
    const orig = Object.getOwnPropertyDescriptor(process.stdin, 'isTTY');
    Object.defineProperty(process.stdin, 'isTTY', { value: true, configurable: true });
    expect(() => w.requireOwner()).not.toThrow();
    if (orig) Object.defineProperty(process.stdin, 'isTTY', orig);
  });
});
