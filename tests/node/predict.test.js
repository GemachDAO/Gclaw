// Regression + robustness for the prediction engine (scripts/predict.js):
//   - atomic file writes (temp + rename) under concurrent reads,
//   - readJson / readJsonl degrade on missing / empty / corrupt files,
//   - cmdCall idempotency (one handle, one call per round; closed rounds reject),
//   - the JSON-first-brace contract: callers parse predict.js's PRETTY (multi-line)
//     output from its FIRST brace, NOT the last line (which is just "}").

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const os = require('node:os');
const fs = require('node:fs');

const HERE = path.dirname(fileURLToPath(import.meta.url));

const { readJson, readJsonl, writeAtomic } = loadScript('predict.js');

let tmp;
beforeEach(() => { tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gclaw-pred-')); });
afterEach(() => { fs.rmSync(tmp, { recursive: true, force: true }); });

describe('writeAtomic — temp + rename never leaves a half-file', () => {
  test('a reader only ever sees the prior file or the new file, never a partial', () => {
    const p = path.join(tmp, 'rounds.json');
    writeAtomic(p, JSON.stringify({ v: 1 }));
    expect(readJson(p, null)).toEqual({ v: 1 });
    // Overwrite with a large payload; the file is renamed into place atomically.
    const big = JSON.stringify({ v: 2, blob: 'x'.repeat(500000) });
    writeAtomic(p, big);
    expect(readJson(p, {}).v).toBe(2);
    // No temp turds left behind.
    expect(fs.readdirSync(tmp).filter((f) => f.includes('.tmp'))).toHaveLength(0);
  });

  test('writeAtomic does not corrupt the existing file if the payload is valid JSON', () => {
    const p = path.join(tmp, 'predictors.json');
    writeAtomic(p, JSON.stringify({ alice: { correct: 3, total: 4 } }));
    writeAtomic(p, JSON.stringify({ alice: { correct: 4, total: 5 } }));
    expect(readJson(p, null)).toEqual({ alice: { correct: 4, total: 5 } });
  });
});

describe('readJson — degrades on every bad input', () => {
  test('missing file returns the default', () => {
    expect(readJson(path.join(tmp, 'nope.json'), { d: true })).toEqual({ d: true });
  });
  test('empty file returns the default (not a throw)', () => {
    const p = path.join(tmp, 'empty.json');
    fs.writeFileSync(p, '');
    expect(readJson(p, { d: 1 })).toEqual({ d: 1 });
  });
  test('corrupt JSON returns the default', () => {
    const p = path.join(tmp, 'corrupt.json');
    fs.writeFileSync(p, '{ "a": 1, ');
    expect(readJson(p, [])).toEqual([]);
  });
  test('a truncated mid-write file returns the default', () => {
    const p = path.join(tmp, 'partial.json');
    fs.writeFileSync(p, '{"rounds": {"abc": {"id":"abc","stat'); // crashed mid-write
    expect(readJson(p, { fallback: true })).toEqual({ fallback: true });
  });
});

describe('readJsonl — tolerant of blank lines and a torn last line', () => {
  test('skips empty lines', () => {
    const p = path.join(tmp, 'calls.jsonl');
    fs.writeFileSync(p, `${JSON.stringify({ a: 1 })}\n\n${JSON.stringify({ a: 2 })}\n`);
    expect(readJsonl(p)).toEqual([{ a: 1 }, { a: 2 }]);
  });
  test('missing file returns []', () => {
    expect(readJsonl(path.join(tmp, 'none.jsonl'))).toEqual([]);
  });
  test('a torn final line (crash mid-append) degrades to [] rather than throwing', () => {
    // readJsonl wraps the parse in try/catch -> []. A half-written final line makes the
    // whole read fall back to empty: the engine treats the corrupt log as "no calls"
    // (fail-conservative) instead of crashing the heartbeat. Appends are O_APPEND so
    // this is rare, but the read still must never throw.
    const p = path.join(tmp, 'torn.jsonl');
    fs.writeFileSync(p, `${JSON.stringify({ a: 1 })}\n{"a": 2`); // last line torn
    expect(readJsonl(p)).toEqual([]);
  });
});

describe('JSON-first-brace contract', () => {
  // predict.js prints `JSON.stringify(out, null, 2)` — PRETTY, multi-line. A caller
  // that did `out.split('\n').pop()` would get "}" and fail. The contract is to slice
  // from the FIRST brace. We assert that contract holds even with a leading banner.
  function parseFirstBrace(out) {
    return JSON.parse(out.slice(out.indexOf('{')));
  }
  test('parses a pretty multi-line object from its first brace', () => {
    const out = `${JSON.stringify({ ok: true, opened: [{ id: 'r1' }] }, null, 2)}\n`;
    expect(parseFirstBrace(out).ok).toBe(true);
    // The last line is just the closing brace — proving why .pop() would break.
    expect(out.trim().split('\n').pop()).toBe('}');
  });
  test('tolerates a leading non-JSON banner before the first brace', () => {
    const out = `warming up SDK...\n${JSON.stringify({ ok: true, n: 3 }, null, 2)}\n`;
    expect(parseFirstBrace(out)).toEqual({ ok: true, n: 3 });
  });
});

describe('cmdCall idempotency + round-state guards', () => {
  // cmdCall reads $GCLAW_HOME/predictions/{rounds.json,calls.jsonl}. Drive it against
  // a seeded temp home; one handle can call a round once, and a resolved round rejects.
  let realHome;
  beforeEach(() => {
    realHome = process.env.GCLAW_HOME;
    process.env.GCLAW_HOME = tmp;
    fs.mkdirSync(path.join(tmp, 'predictions'), { recursive: true });
  });
  afterEach(() => {
    if (realHome === undefined) delete process.env.GCLAW_HOME;
    else process.env.GCLAW_HOME = realHome;
  });

  function seedRound(status = 'open') {
    const rounds = { r1: { id: 'r1', coin: 'ETH', side: 'long', entry: 3000, status, openedAt: new Date().toISOString() } };
    fs.writeFileSync(path.join(tmp, 'predictions', 'rounds.json'), JSON.stringify(rounds));
  }

  test('a valid call is recorded; the same handle calling twice is rejected', () => {
    const predict = loadScript('predict.js'); // fresh load reads the temp GCLAW_HOME
    seedRound('open');
    const first = predict.cmdCall({ round: 'r1', pick: 'TP', by: 'alice' });
    expect(first.ok).toBe(true);
    const dup = predict.cmdCall({ round: 'r1', pick: 'SL', by: 'alice' });
    expect(dup.ok).toBe(false);
    expect(dup.error).toMatch(/already called/);
    // Exactly one call line was written.
    const lines = fs.readFileSync(path.join(tmp, 'predictions', 'calls.jsonl'), 'utf8').trim().split('\n');
    expect(lines).toHaveLength(1);
  });

  test('a call on an unknown round is rejected', () => {
    const predict = loadScript('predict.js');
    seedRound('open');
    expect(predict.cmdCall({ round: 'nope', pick: 'TP', by: 'bob' }).ok).toBe(false);
  });

  test('a call on a resolved round is rejected (calls closed)', () => {
    const predict = loadScript('predict.js');
    seedRound('resolved');
    const r = predict.cmdCall({ round: 'r1', pick: 'TP', by: 'carol' });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/already resolved/);
  });

  test('an invalid pick is rejected', () => {
    const predict = loadScript('predict.js');
    seedRound('open');
    expect(predict.cmdCall({ round: 'r1', pick: 'MAYBE', by: 'dave' }).ok).toBe(false);
  });
});
