// Regression guards for the "Call it" Telegram input parser (scripts/predict_bot.js).
//
// THE BUG THIS LOCKS: an earlier parsePick matched the substring 'up'/'win'/'tp'
// anywhere in a message, so ordinary chat ("what is up", "i'm down", "stop it")
// got logged as a prediction. The fix requires the WHOLE message to be the pick
// (optionally a 'call' verb and/or a coin) — nothing else counts. We exhaustively
// assert real chat is rejected and only genuine calls are accepted.

import { describe, expect, test } from 'vitest';
import { loadScript } from './helpers.js';

const { parsePick, identity } = loadScript('predict_bot.js');

describe('parsePick — only a message that IS a call is logged', () => {
  // ACCEPT: the whole message is the pick (with optional verb / coin / punctuation).
  const tp = ['TP', 'tp', ' TP ', 'TP!', 'take profit', 'TakeProfit', 'call TP',
    'i call tp', 'TP SOL', 'tp btc', '📈', '📈 ETH'];
  for (const msg of tp) {
    test(`accepts "${msg}" as TP`, () => expect(parsePick(msg)).toBe('TP'));
  }
  const sl = ['SL', 'sl', 'SL.', 'stop loss', 'StopLoss', 'call SL', 'SL ETH', '📉'];
  for (const msg of sl) {
    test(`accepts "${msg}" as SL`, () => expect(parsePick(msg)).toBe('SL'));
  }

  // REJECT: ordinary chat that merely CONTAINS a trigger token must NOT be a call.
  const chat = [
    'what is up', "i'm down", 'stop it', 'wakey wakey', 'the price went up',
    'gg wp', 'tip', 'i won', 'profit looks good', 'take profit when you can lol',
    'tp or sl?', 'should i tp', 'TP and then SL', 'why did you sl', 'slap',
    'tpot', 'how do i call it', 'call', 'TP BTC ETH', '', '   ', 'help', 'board',
  ];
  for (const msg of chat) {
    test(`rejects chat "${msg}"`, () => expect(parsePick(msg)).toBeNull());
  }

  test('null/undefined/non-string never throws and returns null', () => {
    expect(parsePick(null)).toBeNull();
    expect(parsePick(undefined)).toBeNull();
    expect(parsePick(42)).toBeNull();
  });
});

describe('identity — stable handle across calls + creatures', () => {
  test('prefers @username', () => expect(identity({ username: 'alice', id: 7 })).toBe('@alice'));
  test('falls back to tg:<id> with no username', () => expect(identity({ id: 7 })).toBe('tg:7'));
  test('null from yields a defined, stable string', () => expect(identity(null)).toBe('tg:null'));
});
