#!/usr/bin/env node
/**
 * Gclaw venture deploy — compile and deploy a venture's GmacBuyAndBurn engine.
 *
 *   node venture_deploy.js plan   --name <venture>              # compile + show params (no gas)
 *   node venture_deploy.js deploy --name <venture> [--chain ethereum|base]
 *
 * `deploy` is gated on the Venture Architect tier (goodwill >= 5000) and needs gas
 * on the target chain. The GMAC buy-and-burn is permissionless once live.
 *
 * Env: GDEX_SKILL_DIR (ethers), GCLAW_WALLET, GCLAW_HOME, ETH_RPC / BASE_RPC.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || path.join(os.homedir(), 'gdex-test-wallet.json');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));

const VENTURE_THRESHOLD = 5000;
const CHAINS = {
  ethereum: { id: 1, rpc: process.env.ETH_RPC || 'https://eth.llamarpc.com' },
  base: { id: 8453, rpc: process.env.BASE_RPC || 'https://mainnet.base.org' },
};
const SOURCE = path.join(__dirname, '..', 'contracts', 'GmacBuyAndBurn.sol');

function compile() {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'gmacbuild-'));
  execFileSync('solc', ['--optimize', '--bin', '--abi', '--overwrite', '-o', out, SOURCE], { stdio: 'pipe' });
  const bytecode = '0x' + fs.readFileSync(path.join(out, 'GmacBuyAndBurn.bin'), 'utf8').trim();
  const abi = JSON.parse(fs.readFileSync(path.join(out, 'GmacBuyAndBurn.abi'), 'utf8'));
  return { abi, bytecode };
}

function loadVenture(name) {
  const file = path.join(GCLAW_HOME, 'ventures', name, 'manifest.json');
  if (!fs.existsSync(file)) throw new Error(`no venture '${name}' (run venture.py launch first)`);
  return { file, manifest: JSON.parse(fs.readFileSync(file, 'utf8')) };
}

async function main() {
  const mode = process.argv[2];
  const name = process.argv.includes('--name') ? process.argv[process.argv.indexOf('--name') + 1] : null;
  const chainKey = process.argv.includes('--chain') ? process.argv[process.argv.indexOf('--chain') + 1] : 'ethereum';
  if (!['plan', 'deploy'].includes(mode) || !name) throw new Error('usage: venture_deploy.js <plan|deploy> --name <venture> [--chain ethereum|base]');
  const chain = CHAINS[chainKey];
  if (!chain) throw new Error(`unknown chain '${chainKey}'`);

  const { file, manifest } = loadVenture(name);
  const { abi, bytecode } = compile();
  const args = [manifest.constructor.router, manifest.constructor.gmac];
  console.log(`venture ${name} · ${chainKey} · router ${args[0].slice(0, 10)}… · gmac ${args[1].slice(0, 10)}…`);
  console.log(`bytecode: ${(bytecode.length - 2) / 2} bytes · routes ${manifest.route_pct}% of revenue → GMAC burn`);

  if (mode === 'plan') {
    console.log('PLAN OK — compiled; ready to deploy (needs gas + Venture Architect tier).');
    return;
  }

  const state = JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'metabolism.json'), 'utf8'));
  if ((state.goodwill || 0) < VENTURE_THRESHOLD) throw new Error(`goodwill ${state.goodwill || 0} < ${VENTURE_THRESHOLD}: venture deploy locked`);
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const provider = new ethers.JsonRpcProvider(chain.rpc);
  const wallet = new ethers.Wallet(w.control.privateKey, provider);
  const bal = await provider.getBalance(wallet.address);
  if (bal === 0n) throw new Error(`control wallet has 0 gas on ${chainKey}`);

  const factory = new ethers.ContractFactory(abi, bytecode, wallet);
  const contract = await factory.deploy(...args);
  await contract.waitForDeployment();
  const address = await contract.getAddress();
  manifest.deployed_address = address;
  manifest.deploy_state = 'deployed';
  manifest.deploy_chain = `${chainKey}:${chain.id}`;
  fs.writeFileSync(file, JSON.stringify(manifest, null, 2) + '\n');
  console.log(`DEPLOYED GmacBuyAndBurn → ${address} on ${chainKey}. Buy-and-burn is now live and permissionless.`);
}

main().catch((e) => {
  console.error('ERROR', e?.shortMessage || e.message || String(e));
  process.exit(1);
});
