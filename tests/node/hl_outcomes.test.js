// Unit tests for the hl_outcomes.js pure classifiers: classifyMarket + parsePriceBinary.
// These label + parse what HL already published so the desk can tell an edgeable dated
// market (crypto price threshold / macro print) apart from an efficient sports market —
// they never fabricate a probability. Loaded via require.main guard, so no network fires.
import { test, expect } from 'vitest';
import { loadScript } from './helpers.js';

const { classifyMarket, parsePriceBinary } = loadScript('hl_outcomes.js');

test('classifyMarket labels an HL price-binary as crypto-price', () => {
  expect(
    classifyMarket('Recurring', 'class:priceBinary|underlying:BTC|expiry:20260702-0600|targetPrice:59122|period:1d'),
  ).toBe('crypto-price');
});

test('classifyMarket labels an FOMC / CPI print as macro', () => {
  expect(classifyMarket('No change', 'resolves to Yes if the July 2026 FOMC decision leaves the rate range unchanged')).toBe('macro');
  expect(classifyMarket('Below 3.8%', 'resolves to Yes if the BLS CPI year-over-year value for June 2026 is below 3.8%')).toBe('macro');
});

test('classifyMarket labels a World Cup / head-to-head market as sports', () => {
  expect(classifyMarket('Argentina', 'resolves to Yes if Argentina is the 2026 FIFA World Cup champion')).toBe('sports');
  expect(classifyMarket('World Cup Round of 32: England vs Congo DR', '')).toBe('sports');
});

test('classifyMarket falls back to other for a bare fallback market', () => {
  expect(classifyMarket('Fallback', '')).toBe('other');
});

test('parsePriceBinary extracts the structured resolution terms', () => {
  const r = parsePriceBinary('class:priceBinary|underlying:BTC|expiry:20260702-0600|targetPrice:59122|period:1d');
  expect(r).toEqual({ underlying: 'BTC', targetPrice: 59122, expiry: '20260702-0600', period: '1d' });
});

test('parsePriceBinary returns null for a non-price-binary description', () => {
  expect(parsePriceBinary('resolves to Yes if Argentina is the 2026 FIFA World Cup champion')).toBeNull();
  expect(parsePriceBinary('')).toBeNull();
});
