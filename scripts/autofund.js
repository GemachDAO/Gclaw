#!/usr/bin/env node
/**
 * Gclaw auto-fund — turn "just send ETH" into tradeable USDC on HyperLiquid.
 *
 * HL only accepts USDC deposits (min $10) and deposits cost gas. So a player can
 * simply send ETH to their managed Arbitrum wallet, and this swaps the surplus
 * (keeping a gas reserve) into USDC and deposits it to HL — fully automated.
 *
 *   node autofund.js plan      # show ETH found + what it would convert (no spend)
 *   node autofund.js run       # swap ETH->USDC on Arbitrum, deposit to HL
 *
 * Env: GDEX_SKILL_DIR, GCLAW_WALLET, ARB_RPC, GDEX_API_KEY.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
const ARB_RPC = process.env.ARB_RPC || 'https://arb1.arbitrum.io/rpc';
const ARB_CHAIN = 42161;
const ARB_USDC = '0xaf88d065e77c8cC2239327C5EDb3A432268e5831';
const GAS_RESERVE_ETH = 0.0003; // keep enough Arbitrum ETH for the swap + deposit tx
const MIN_SWAP_ETH = 0.006; // ~$10 at current ETH; below this a swap can't clear the HL min — skip dust
const MIN_DEPOSIT_USDC = 10; // HyperLiquid minimum
const SLIPPAGE = 2;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function loadWallet() {
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const managed = w.managed?.['Arbitrum (HyperLiquid)']?.address;
  if (!managed) throw new Error('wallet missing managed Arbitrum address');
  return { control: w.control.address, pk: w.control.privateKey, managed };
}

async function arbProvider() {
  return new ethers.JsonRpcProvider(ARB_RPC);
}

async function usdcBalance(provider, addr) {
  const erc20 = new ethers.Contract(ARB_USDC, ['function balanceOf(address) view returns (uint256)'], provider);
  return Number(ethers.formatUnits(await erc20.balanceOf(addr), 6));
}

async function signIn(skill, wallet) {
  const apiKey = process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY;
  const kp = SDK.generateGdexSessionKeyPair();
  const nonce = SDK.generateGdexNonce().toString();
  const sig = (await new ethers.Wallet(wallet.pk).signMessage(SDK.buildGdexSignInMessage(wallet.control, nonce, kp.sessionKey))).replace(/^0x/, '');
  const payload = SDK.buildGdexSignInComputedData({ apiKey, userId: wallet.control, sessionKey: kp.sessionKey, nonce, signature: sig });
  await skill.signInWithComputedData({ computedData: payload.computedData, chainId: ARB_CHAIN });
  return { apiKey, walletAddress: wallet.control, sessionPrivateKey: kp.sessionPrivateKey };
}

async function main() {
  const mode = process.argv[2] || 'plan';
  const wallet = loadWallet();
  const provider = await arbProvider();
  const ethBal = Number(ethers.formatEther(await provider.getBalance(wallet.managed)));
  const swapEth = Math.max(0, ethBal - GAS_RESERVE_ETH);
  const summary = { ok: true, mode, arbitrumEth: ethBal, gasReserve: GAS_RESERVE_ETH, swapEth: Number(swapEth.toFixed(6)) };

  if (swapEth < MIN_SWAP_ETH) {
    summary.action = swapEth <= 0
      ? 'nothing to convert (ETH at or below gas reserve)'
      : `holding ${swapEth.toFixed(6)} ETH dust (below ${MIN_SWAP_ETH} min swap — would not clear the HL deposit min)`;
    console.log(JSON.stringify(summary, null, 2));
    return;
  }
  if (mode === 'plan') {
    summary.action = `would swap ${swapEth.toFixed(6)} ETH → USDC on Arbitrum, then deposit to HL (if ≥ $${MIN_DEPOSIT_USDC})`;
    console.log(JSON.stringify(summary, null, 2));
    return;
  }

  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY);
  const creds = await signIn(skill, wallet);

  const before = await usdcBalance(provider, wallet.managed);
  const swap = await skill.buyToken({ chain: ARB_CHAIN, tokenAddress: ARB_USDC, amount: String(swapEth), slippage: SLIPPAGE, ...creds });
  if (swap && swap.isSuccess === false) throw new Error(`swap rejected: ${JSON.stringify(swap)}`);
  summary.swap = 'submitted';

  let after = before;
  for (let i = 0; i < 12 && after <= before + 0.01; i += 1) {
    await sleep(5000);
    after = await usdcBalance(provider, wallet.managed);
  }
  const gained = Number((after - before).toFixed(6));
  summary.usdcReceived = gained;

  if (after >= MIN_DEPOSIT_USDC) {
    const dep = await skill.perpDeposit({ amount: String(Math.floor(after)), tokenAddress: ARB_USDC, chainId: ARB_CHAIN, ...creds });
    if (dep && dep.isSuccess === false) throw new Error(`deposit rejected: ${JSON.stringify(dep)}`);
    summary.deposited = `${Math.floor(after)} USDC → HyperLiquid`;
    summary.action = 'swapped + deposited — ready to trade';
  } else {
    summary.action = `swapped to $${after.toFixed(2)} USDC; holding on Arbitrum (below $${MIN_DEPOSIT_USDC} HL min — add more ETH)`;
  }
  console.log(JSON.stringify(summary, null, 2));
}

main()
  .then(() => process.exit(0))
  .catch((e) => {
    console.log(JSON.stringify({ ok: false, error: e?.responseBody ? JSON.stringify(e.responseBody) : e.message || String(e) }));
    process.exit(1);
  });
