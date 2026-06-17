#!/usr/bin/env node
/**
 * Gclaw HIP-3 outcome-market execution arm (defined-risk event bets).
 *
 * Outcome markets are HyperLiquid event markets (e.g. "June Fed rate change" →
 * Change / No Change). Each side is a coin you buy/sell at a price = implied
 * probability. Downside is bounded — good for survival mode.
 *
 * Uses the proven managed sign-in (chainId 42161, fresh session) like hl_perp.js,
 * then the SDK outcome methods. Emits JSON.
 *
 *   node hl_outcomes.js list [--limit 15]                       # active markets + volume
 *   node hl_outcomes.js account --outcome <id>                  # your positions/balance in a market
 *   node hl_outcomes.js enable                                  # one-time: enable HL trading (required first)
 *   node hl_outcomes.js order --outcome <id> --coin <side> --buy --price <0..1> --size <n> [--market]
 *   node hl_outcomes.js close --outcome <id> --coin <side>
 *
 * Env: GDEX_SKILL_DIR, GCLAW_WALLET, GDEX_API_KEY.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || path.join(os.homedir(), 'gdex-test-wallet.json');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

const HL_CHAIN_ID = 42161;

function die(msg) {
  process.stdout.write(JSON.stringify({ ok: false, error: msg }) + '\n');
  process.exit(1);
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[(i += 1)] : 'true';
      out[key] = val;
    }
  }
  return out;
}

function loadWallet() {
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const managed = w.managed?.['Arbitrum (HyperLiquid)']?.address;
  if (!w.control?.address || !managed) die('wallet missing control key or managed HL address');
  return { control: w.control.address, pk: w.control.privateKey, managed };
}

async function signedSkill(wallet) {
  const apiKey = process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY;
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(apiKey);
  const kp = SDK.generateGdexSessionKeyPair();
  const nonce = SDK.generateGdexNonce().toString();
  const sig = (
    await new ethers.Wallet(wallet.pk).signMessage(SDK.buildGdexSignInMessage(wallet.control, nonce, kp.sessionKey))
  ).replace(/^0x/, '');
  const payload = SDK.buildGdexSignInComputedData({
    apiKey,
    userId: wallet.control,
    sessionKey: kp.sessionKey,
    nonce,
    signature: sig,
  });
  await skill.signInWithComputedData({ computedData: payload.computedData, chainId: HL_CHAIN_ID });
  return { skill, creds: { apiKey, walletAddress: wallet.control, sessionPrivateKey: kp.sessionPrivateKey } };
}

function loginOnly() {
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY);
  return skill;
}

async function cmdList(_w, args) {
  const skill = loginOnly();
  const resp = await skill.getHlOutcomes({ status: 'active' });
  const all = resp?.data?.meta?.outcomes || [];
  const rows = all.slice(0, Number(args.limit || 15));
  return {
    ok: true,
    total: all.length,
    shown: rows.length,
    markets: rows.map((m) => ({
      outcomeId: m.outcome,
      name: m.name,
      sides: (m.sideSpecs || []).map((s) => s.name).filter(Boolean),
    })),
  };
}

async function cmdAccount(wallet, args) {
  if (!args.outcome) die('--outcome <id> required');
  const { skill } = await signedSkill(wallet);
  const acct = await skill.getHlOutcomeAccount({ userAddress: wallet.managed, outcomeId: args.outcome });
  return { ok: true, outcomeId: args.outcome, account: acct };
}

async function cmdEnable(wallet) {
  const { skill, creds } = await signedSkill(wallet);
  try {
    const res = await skill.hlEnableTrading({ ...creds });
    return { ok: res?.isSuccess !== false, action: 'enable_trading', result: res };
  } catch (e) {
    const body = JSON.stringify(e?.responseBody || e?.message || '');
    if (body.includes('already enabled') || body.includes('104')) {
      return { ok: true, action: 'enable_trading', alreadyEnabled: true };
    }
    throw e;
  }
}

async function cmdOrder(wallet, args) {
  for (const k of ['outcome', 'coin', 'price', 'size']) if (!args[k]) die(`--${k} required`);
  const isBuy = !!args.buy && args.buy !== 'false';
  const { skill, creds } = await signedSkill(wallet);
  const res = await skill.createHlOutcomeOrder({
    outcomeId: args.outcome,
    coin: args.coin,
    isBuy,
    price: String(args.price),
    size: String(args.size),
    reduceOnly: false,
    isMarket: !!args.market && args.market !== 'false',
    ...creds,
  });
  if (res && res.isSuccess === false) die(`order rejected: ${JSON.stringify(res)}`);
  return { ok: true, action: 'order', outcomeId: args.outcome, coin: args.coin, side: isBuy ? 'buy' : 'sell', price: args.price, size: args.size };
}

async function cmdClose(wallet, args) {
  for (const k of ['outcome', 'coin']) if (!args[k]) die(`--${k} required`);
  const { skill, creds } = await signedSkill(wallet);
  const res = await skill.closeHlOutcomeOrder({ outcomeId: args.outcome, coin: args.coin, ...creds });
  if (res && res.isSuccess === false) die(`close rejected: ${JSON.stringify(res)}`);
  return { ok: true, action: 'close', outcomeId: args.outcome, coin: args.coin };
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);
  const wallet = loadWallet();
  const handlers = { list: cmdList, account: cmdAccount, enable: cmdEnable, order: cmdOrder, close: cmdClose };
  const handler = handlers[cmd];
  if (!handler) die(`unknown command '${cmd}'. Use: list | account | enable | order | close`);
  const result = await handler(wallet, args);
  process.stdout.write(JSON.stringify(result) + '\n');
}

main().catch((e) => die(e?.responseBody ? JSON.stringify(e.responseBody) : e.message || String(e)));
