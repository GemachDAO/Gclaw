// Vitest config for the Gclaw node scripts (CommonJS). Tests live in tests/node/,
// mirroring scripts/, as *.test.js. No globals — import { test, expect } explicitly.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/node/**/*.test.js'],
    // Node env; these are pure-logic unit tests, no DOM.
    environment: 'node',
    // Fast and deterministic: no real network (scripts' https calls are mocked at the
    // boundary), no real clock unless a test opts in with vi.useFakeTimers().
    testTimeout: 5000,
    // Each test file gets a clean module registry so a script's top-level state
    // (and our require.main guard) behaves identically across files.
    isolate: true,
    restoreMocks: true,
    clearMocks: true,
  },
});
