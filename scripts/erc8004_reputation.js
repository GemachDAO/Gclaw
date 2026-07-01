#!/usr/bin/env node
/**
 * Gclaw ERC-8004 reputation sync — attest SETTLED PERFORMANCE onchain (Base mainnet).
 *
 * Posts the verifiable scorecard (reputation.py: realized PnL from settled HyperLiquid
 * fills + forge-graduated proven edge + lineage) as feedback in the ERC-8004
 * ReputationRegistry, tied to the agentId. This makes the reputation a portable,
 * re-derivable signal of real financial performance — not social activity.
 *
 * The registry forbids SELF-feedback (the agent owner cannot rate its own agent —
 * the correct trust model), so feedback must be posted by a distinct ATTESTER
 * wallet (the game operator / a verifying client). Set GCLAW_ATTESTER_KEY to that
 * wallet's private key. dry-run simulates from a fresh non-owner address to prove
 * the call passes the self-feedback guard.
 *
 *   node erc8004_reputation.js dry-run    # eth_call from a non-owner — proves the call, no gas
 *   node erc8004_reputation.js broadcast  # real tx, signed by GCLAW_ATTESTER_KEY (needs its Base ETH gas)
 *
 * Env: GDEX_SKILL_DIR, GCLAW_WALLET, GCLAW_HOME, BASE_RPC, GCLAW_ATTESTER_KEY.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));

const BASE_RPC = process.env.BASE_RPC || 'https://mainnet.base.org';
const REPUTATION_REGISTRY = '0x8004BAa17C55a88189AE136b182e5fdA19dE9b63'; // ERC-8004 ReputationRegistry, Base mainnet
const ABI = [
  'function giveFeedback(uint256 agentId, int128 value, uint8 valueDecimals, string tag1, string tag2, string endpoint, string feedbackURI, bytes32 feedbackHash)',
];
const ZERO_HASH = '0x' + '00'.repeat(32);


async function main() {
  const mode = process.argv[2];
  if (!['dry-run', 'broadcast'].includes(mode)) throw new Error('usage: erc8004_reputation.js <dry-run|broadcast>');
  const state = JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'metabolism.json'), 'utf8'));
  const identity = state.onchain_identity;
  if (!identity || !identity.agentId) throw new Error('no onchain identity — run erc8004_register.js broadcast first');
  const agentId = BigInt(identity.agentId);
  // Reputation is SETTLED PERFORMANCE, not goodwill: load the verifiable scorecard
  // (reputation.py writes it every heartbeat from real closed fills + forge graduation).
  let scorecard;
  try {
    scorecard = JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'reputation.json'), 'utf8'));
  } catch {
    scorecard = JSON.parse(
      require('node:child_process').execFileSync(
        'uv', ['run', '--no-project', 'python3', path.join(__dirname, 'reputation.py'), 'card'],
        { encoding: 'utf8' },
      ),
    );
  }
  const realizedPnl = Number(scorecard?.trading?.realized_pnl_usd ?? 0);
  const closedTrades = Number(scorecard?.trading?.closed_trades ?? 0);
  const pnlCents = Math.round(realizedPnl * 100);

  const provider = new ethers.JsonRpcProvider(BASE_RPC);
  const code = await provider.getCode(REPUTATION_REGISTRY);
  if (code === '0x') throw new Error(`no contract at ${REPUTATION_REGISTRY} on Base — wrong address`);
  // Attester must NOT be the agent owner (registry forbids self-feedback).
  const attesterKey =
    process.env.GCLAW_ATTESTER_KEY || (mode === 'dry-run' ? ethers.Wallet.createRandom().privateKey : null);
  if (!attesterKey) throw new Error('set GCLAW_ATTESTER_KEY (a non-owner wallet) to broadcast reputation');
  const wallet = new ethers.Wallet(attesterKey, provider);
  const registry = new ethers.Contract(REPUTATION_REGISTRY, ABI, wallet);

  const feedbackURI = `data:application/json;base64,${Buffer.from(JSON.stringify(scorecard)).toString('base64')}`;
  // value = realized PnL in cents (int128, signed — an honest, re-derivable bottom line);
  // the tags name the basis so any reader knows this reputation is SETTLED trading + proven
  // edge, not social activity. The full scorecard rides in the feedbackURI.
  const args = [agentId, BigInt(pnlCents), 2, 'settled-pnl', 'gclaw-evolution-lab', '', feedbackURI, ZERO_HASH];
  const provenEdge = scorecard?.evolution?.proven_edge_count ?? 0;
  console.log(`agentId ${agentId} · realized $${realizedPnl} (${closedTrades} closes) · proven-edge ${provenEdge} · registry code ${code.length} bytes`);

  if (mode === 'dry-run') {
    await registry.giveFeedback.staticCall(...args);
    let gas = 'n/a';
    try {
      gas = (await registry.giveFeedback.estimateGas(...args)).toString();
    } catch { /* needs gas balance to estimate */ }
    console.log(`DRY-RUN OK — giveFeedback would post the settled scorecard | gas≈${gas}`);
    return;
  }

  if (closedTrades <= 0) throw new Error('no settled trades yet — nothing verifiable to attest');
  const bal = await provider.getBalance(wallet.address);
  if (bal === 0n) throw new Error('attester wallet has 0 Base ETH — fund gas first');
  const tx = await registry.giveFeedback(...args);
  console.log(`broadcast ${tx.hash} — waiting...`);
  const receipt = await tx.wait();
  state.onchain_reputation = { realizedPnl, closedTrades, provenEdge, txHash: tx.hash, block: receipt.blockNumber, at: new Date().toISOString() };
  fs.writeFileSync(path.join(GCLAW_HOME, 'metabolism.json'), JSON.stringify(state, null, 2) + '\n');
  console.log(`REPUTATION SYNCED — settled scorecard onchain, tx ${tx.hash}`);
}

main().catch((e) => {
  console.error('ERROR', e?.shortMessage || e.message || String(e));
  process.exit(1);
});
