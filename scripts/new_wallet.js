#!/usr/bin/env node
/**
 * Gclaw wallet creation — make a fresh managed-custody wallet for a new player.
 *
 * Generates an EVM control keypair, signs in on each chain to resolve the managed
 * deposit addresses, and writes everything to ~/.gclaw/wallet.json (chmod 600,
 * outside any git repo). Prints exactly which address to fund with what.
 *
 *   node new_wallet.js              # create (refuses to overwrite)
 *   node new_wallet.js --force      # regenerate (DANGER: abandons the old wallet)
 *
 * Env: GDEX_SKILL_DIR, GCLAW_HOME, GDEX_API_KEY.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

const WALLET_PATH = path.join(GCLAW_HOME, 'wallet.json');
const CHAINS = [
  { name: 'Solana', chainId: 622112261, fund: 'SOL + SPL tokens (Solana spot)' },
  { name: 'Arbitrum (HyperLiquid)', chainId: 42161, fund: 'USDC — your trading capital for perps + outcomes' },
  { name: 'Base', chainId: 8453, fund: 'a little ETH — gas for onchain identity' },
];

async function main() {
  if (fs.existsSync(WALLET_PATH) && !process.argv.includes('--force')) {
    console.log(`Wallet already exists at ${WALLET_PATH}. Use --force to regenerate (abandons it).`);
    return;
  }
  const apiKey = process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY;
  const w = SDK.generateEvmWallet();
  const wallet = new ethers.Wallet(w.privateKey);
  const skill = new SDK.GdexSkill({ timeout: 45000, maxRetries: 1 });
  skill.loginWithApiKey(apiKey);

  const managed = {};
  for (const c of CHAINS) {
    const kp = SDK.generateGdexSessionKeyPair();
    const nonce = SDK.generateGdexNonce().toString();
    const sig = (await wallet.signMessage(SDK.buildGdexSignInMessage(w.address, nonce, kp.sessionKey))).replace(/^0x/, '');
    const payload = SDK.buildGdexSignInComputedData({ apiKey, userId: w.address, sessionKey: kp.sessionKey, nonce, signature: sig });
    try {
      const resp = await skill.signInWithComputedData({ computedData: payload.computedData, chainId: c.chainId });
      managed[c.name] = { chainId: c.chainId, address: resp.address || resp.walletAddress || null, fund: c.fund };
    } catch (e) {
      managed[c.name] = { chainId: c.chainId, address: null, error: e.message, fund: c.fund };
    }
  }

  fs.mkdirSync(GCLAW_HOME, { recursive: true });
  fs.writeFileSync(
    WALLET_PATH,
    JSON.stringify({ createdAt: new Date().toISOString(), control: { address: w.address, privateKey: w.privateKey, mnemonic: w.mnemonic || null }, managed }, null, 2),
  );
  fs.chmodSync(WALLET_PATH, 0o600);

  console.log(`\n🔑 Wallet created → ${WALLET_PATH} (chmod 600, never commit it)`);
  console.log(`   control / identity: ${w.address}`);
  console.log('\n💰 Fund these to come alive:');
  const hl = managed['Arbitrum (HyperLiquid)'];
  if (hl?.address) {
    console.log(`   • Trading capital → send USDC **or just ETH** on Arbitrum to:\n       ${hl.address}`);
    console.log('       (ETH is auto-swapped to USDC + deposited — run: gclaw autofund)');
  }
  console.log(`   • Gas for onchain identity → send ~0.001 ETH on Base to:\n       ${w.address}`);
  console.log('\n   Then run:  gclaw fund   ·   gclaw autofund   ·   gclaw start');
}

main()
  .then(() => process.exit(0))
  .catch((e) => {
    console.error('ERROR', e?.message || String(e));
    process.exit(1);
  });
