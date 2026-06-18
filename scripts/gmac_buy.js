#!/usr/bin/env node
/**
 * Gclaw GMAC buy-back — convert earmarked profit into the real Gemach token.
 *
 * The metabolism sets aside 10% of every realized USD profit into a buy-back
 * treasury (gmac_treasury_usd). When it crosses a threshold the agent buys real
 * GMAC on Ethereum Uniswap through the GDEX managed flow, then records the buy
 * with `metabolism.py gmac --spend ... --tokens ...`.
 *
 *   node gmac_buy.js plan                 # gasless: verify GMAC routing + show the buy plan
 *   node gmac_buy.js buy --usd 5          # real managed buy on Ethereum (needs ETH/USDC + gas)
 *
 * GMAC (Ethereum): 0xd96e84ddbc7cbe1d73c55b6fe8c64f3a6550deea — Uniswap/SushiSwap, 0 tax, LP locked.
 * Env: GDEX_SKILL_DIR, GCLAW_WALLET, GCLAW_HOME, GDEX_API_KEY.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

const ETH_CHAIN = 1;
const GMAC = '0xd96e84ddbc7cbe1d73c55b6fe8c64f3a6550deea';
const SLIPPAGE = 3;

function state() {
  return JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'metabolism.json'), 'utf8'));
}

async function tokenInfo(skill) {
  const t = await skill.getTokenDetails({ tokenAddress: GMAC, chain: ETH_CHAIN });
  return {
    symbol: t.symbol,
    priceUsd: t.priceUsd ?? t.tokenPrice,
    liquidityUsd: t.liquidityUsd,
    dex: (t.dexes && t.dexes[0]) || t.dexId || 'Uniswap',
    honeypot: !!(t.honeyPot && t.honeyPot.isHoneyPot),
    buyTax: t.honeyPot?.buyTax ?? 0,
  };
}

async function signIn(skill, wallet) {
  const apiKey = process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY;
  const kp = SDK.generateGdexSessionKeyPair();
  const nonce = SDK.generateGdexNonce().toString();
  const sig = (
    await new ethers.Wallet(wallet.control.privateKey).signMessage(
      SDK.buildGdexSignInMessage(wallet.control.address, nonce, kp.sessionKey),
    )
  ).replace(/^0x/, '');
  const payload = SDK.buildGdexSignInComputedData({
    apiKey,
    userId: wallet.control.address,
    sessionKey: kp.sessionKey,
    nonce,
    signature: sig,
  });
  await skill.signInWithComputedData({ computedData: payload.computedData, chainId: ETH_CHAIN });
  return { apiKey, walletAddress: wallet.control.address, sessionPrivateKey: kp.sessionPrivateKey };
}

async function main() {
  const mode = process.argv[2];
  const usdArg = process.argv.includes('--usd') ? Number(process.argv[process.argv.indexOf('--usd') + 1]) : null;
  const wallet = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY);

  const info = await tokenInfo(skill);
  const treasury = state().gmac_treasury_usd ?? 0;
  const usd = usdArg ?? treasury;
  const expectedTokens = info.priceUsd ? usd / info.priceUsd : 0;
  const plan = {
    token: `${info.symbol} @ $${info.priceUsd} on ${info.dex} (Ethereum)`,
    liquidityUsd: info.liquidityUsd,
    safe: !info.honeypot && info.buyTax === 0,
    treasuryUsd: treasury,
    spendUsd: usd,
    expectedTokens: Math.round(expectedTokens),
    minOutAtSlippage: Math.round(expectedTokens * (1 - SLIPPAGE / 100)),
  };

  if (mode === 'plan') {
    console.log(JSON.stringify({ ok: true, mode: 'plan', ...plan }, null, 2));
    console.log(plan.safe ? 'ROUTE OK — GMAC is tradeable and safe to buy.' : 'WARN — token failed safety gate.');
    return;
  }
  if (mode === 'buy') {
    if (!plan.safe) throw new Error('refusing to buy: token failed safety gate');
    if (usd <= 0) throw new Error('nothing to spend (treasury empty; --usd 0)');
    // GMAC liquidity is the Ethereum GMAC/WETH pool, so the managed buy spends
    // native ETH. Convert the USD budget to an ETH amount; buyToken routes EVM +
    // sessionPrivateKey through the session-signed purchase_v2 flow.
    const ethPrice = await skill.getHlMarkPrice('ETH').catch(() => 0);
    if (!ethPrice) throw new Error('could not fetch ETH price for USD→ETH conversion');
    const ethAmount = (usd / ethPrice).toFixed(8);
    const creds = await signIn(skill, wallet);
    const res = await skill.buyToken({
      chain: ETH_CHAIN,
      tokenAddress: GMAC,
      amount: ethAmount,
      slippage: SLIPPAGE,
      dex: info.dex,
      ...creds,
    });
    console.log(JSON.stringify({ ok: res?.isSuccess !== false, spendEth: ethAmount, ethPrice, result: res, ...plan }));
    return;
  }
  throw new Error('usage: gmac_buy.js <plan|buy> [--usd N]');
}

main().catch((e) => {
  console.error('ERROR', e?.responseBody ? JSON.stringify(e.responseBody) : e.message || String(e));
  process.exit(1);
});
