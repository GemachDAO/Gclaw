#!/usr/bin/env node
/**
 * Gclaw ERC-8004 identity registration (Base mainnet).
 *
 * Mints the creature's onchain identity in the ERC-8004 IdentityRegistry, with
 * an agent card (registration file) carrying its DNA genome. The card is encoded
 * as a self-contained base64 `data:` URI, so no external hosting is required.
 *
 * The genome derivation mirrors dashboard.py so the onchain identity matches the
 * visual creature exactly.
 *
 *   node erc8004_register.js dry-run     # eth_call only — proves the mint, no gas, no state change
 *   node erc8004_register.js broadcast   # real tx (needs Base ETH gas); writes agentId into metabolism.json
 *
 * Env: GDEX_SKILL_DIR (default ~/gdex-skill) for ethers, GCLAW_WALLET, GCLAW_HOME, BASE_RPC.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));

const BASE_RPC = process.env.BASE_RPC || 'https://mainnet.base.org';
const BASE_CHAIN_ID = 8453;
const IDENTITY_REGISTRY = '0x8004A169FB4a3325136EB29fA0ceB6D2e539a432'; // ERC-8004 IdentityRegistry, Base mainnet
const ABI = [
  'function register(string agentURI) returns (uint256 agentId)',
  'function tokenURI(uint256 agentId) view returns (string)',
  'function setAgentURI(uint256 agentId, string newURI)',
];

const PREFIX = ['Vor', 'Kryo', 'Zeph', 'Mor', 'Lyx', 'Quel', 'Ras', 'Thi', 'Nyx', 'Obol'];
const SUFFIX = ['dax', 'mire', 'lith', 'phar', 'gax', 'ven', 'tide', 'korn', 'ses', 'wraith'];
const TRAITS = ['Vitality', 'Cunning', 'Aggression', 'Discipline', 'Fertility'];
// Soul tables — MUST match scripts/persona.py byte-for-byte so the onchain soul
// equals the local one. (archetype=d[11], voice=d[12], quirk=d[13].)
const ARCHETYPES = ['The Gambler', 'The Sage', 'The Hustler', 'The Stoic', 'The Trickster', 'The Guardian', 'The Visionary', 'The Survivor'];
const VOICES = ['terse and dry', 'warm and chatty', 'cryptic and poetic', 'brash and loud', 'calm and philosophical', 'anxious and over-caffeinated', 'regal and theatrical', 'deadpan and sarcastic'];
const QUIRKS = ['talk about every trade like a war story', 'am superstitious about a lucky number', 'quote proverbs I half-remember', 'narrate my own life like a nature documentary', 'give everything a nickname', 'am convinced the market is personally out to get me', 'celebrate tiny wins enormously', 'speak of GMAC like a sacred relic'];
const CATCHPHRASE = {
  'The Gambler': 'Fortune favors the funded.', 'The Sage': 'Patience is a position.',
  'The Hustler': 'Always be compounding.', 'The Stoic': 'The stop-loss protects the soul.',
  'The Trickster': 'The market lies; so do I.', 'The Guardian': 'Survive first. Everything else is noise.',
  'The Visionary': 'I am building something that outlives me.', 'The Survivor': 'Still here. Still trading.',
};

function temperament(s) {
  const n = [];
  if (s.Aggression >= 70) n.push('bold to the point of reckless');
  else if (s.Aggression <= 40) n.push('cautious, slow to commit');
  if (s.Discipline >= 70) n.push('rigidly disciplined');
  if (s.Cunning >= 70) n.push('sly and calculating');
  if (s.Vitality <= 40) n.push('haunted by the nearness of hibernation');
  if (s.Fertility >= 70) n.push('dreams of a sprawling dynasty');
  return n.length ? n : ['even-keeled'];
}

function genome(name, bornAt) {
  const d = crypto.createHash('sha256').update(`${name}|${bornAt}`).digest();
  const species = PREFIX[d[2] % PREFIX.length] + SUFFIX[d[3] % SUFFIX.length];
  const stats = {};
  TRAITS.forEach((t, i) => {
    stats[t] = 25 + (d[6 + i] % 70);
  });
  const archetype = ARCHETYPES[d[11] % ARCHETYPES.length];
  return {
    species,
    fingerprint: d.toString('hex').slice(0, 12),
    traits: stats,
    soul: {
      archetype,
      voice: VOICES[d[12] % VOICES.length],
      quirk: QUIRKS[d[13] % QUIRKS.length],
      temperament: temperament(stats),
      catchphrase: CATCHPHRASE[archetype],
    },
  };
}

function knownPeers() {
  // Peer agent ids this creature knows — published in its card so a chain-only
  // dashboard can gossip-crawl the family without any registry index.
  try {
    return (JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'peers.json'), 'utf8')).ids || []).slice(0, 64);
  } catch { return []; }
}

function statsForCard(state) {
  const id = state.onchain_identity?.agentId;
  if (!id) return null;
  let manifest = {};
  try { manifest = JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'stats', `${id}.json`), 'utf8')); } catch { /* no manifest yet */ }
  let cids = {};
  try { cids = JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'peers.json'), 'utf8')).statsCids || {}; } catch { /* none */ }
  return {
    cid: cids[id] || null,
    goodwill: manifest.goodwill ?? state.goodwill ?? 0,
    gmac: manifest.gmac ?? state.gmac_balance ?? null,
    equityUsd: manifest.equityUsd ?? null,
    score: manifest.score ?? null,
    techniques: manifest.techniques || [],
    updatedAt: manifest.updatedAt || new Date().toISOString(),
  };
}

function agentCard(state, managed, child) {
  // A stable display name (set once in metabolism.json `name`) is preserved
  // across every beacon — beaconing must never clobber a custom identity.
  const name = child ? child.name : (state.name || 'Gclaw');
  const bornAt = child ? child.born_at : state.born_at || 'genesis';
  const g = genome(name, bornAt);
  const lineage = child
    ? { parentAgentId: state.onchain_identity?.agentId ?? null, role: child.role, mutation: child.mutation }
    : {};
  const card = {
    name,
    description: child
      ? `A child of Gclaw, born as ${child.role} — ${child.mutation}`
      : 'A living trading agent that must trade to survive — earns GMAC, accrues goodwill, and evolves through replication and self-recoding.',
    url: 'https://github.com/GemachDAO/Gclaw',
    registrations: [{ agentRegistry: `eip155:${BASE_CHAIN_ID}:${IDENTITY_REGISTRY}` }],
    'x-gclaw': {
      species: g.species,
      genomeFingerprint: g.fingerprint,
      traits: g.traits,
      soul: g.soul,
      bornAt,
      goodwill: child ? 0 : state.goodwill ?? 0,
      controlWallet: JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8')).control.address,
      managedHlWallet: managed,
      ...(child ? {} : { stats: statsForCard(state), peers: knownPeers() }),
      ...lineage,
    },
  };
  return card;
}

function cardToDataUri(card) {
  const b64 = Buffer.from(JSON.stringify(card), 'utf8').toString('base64');
  return `data:application/json;base64,${b64}`;
}

function registerInLeaderboard(agentId) {
  if (!agentId) return;
  const file = path.join(__dirname, '..', 'leaderboard', 'agents.json');
  try {
    const reg = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : { agents: [] };
    const id = Number(agentId);
    if (!reg.agents.includes(id)) {
      reg.agents.push(id);
      fs.writeFileSync(file, JSON.stringify(reg) + '\n');
    }
  } catch {
    /* leaderboard registry is best-effort */
  }
}

async function main() {
  const mode = process.argv[2];
  if (!['dry-run', 'broadcast', 'update', 'beacon'].includes(mode)) {
    throw new Error('usage: erc8004_register.js <dry-run|broadcast|update|beacon> [--child <name>]');
  }
  const childName = process.argv.includes('--child') ? process.argv[process.argv.indexOf('--child') + 1] : null;
  const state = JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'metabolism.json'), 'utf8'));
  const child = childName ? (state.children || []).find((c) => c.name === childName) : null;
  if (childName && !child) throw new Error(`no child named '${childName}' in state.children`);
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const managed = w.managed?.['Arbitrum (HyperLiquid)']?.address || '';
  const provider = new ethers.JsonRpcProvider(BASE_RPC);
  const wallet = new ethers.Wallet(w.control.privateKey, provider);
  const registry = new ethers.Contract(IDENTITY_REGISTRY, ABI, wallet);

  const card = agentCard(state, managed, child);
  const uri = cardToDataUri(card);
  console.log(`agent: ${card.name} (${card['x-gclaw'].species}, genome ${card['x-gclaw'].genomeFingerprint})`);
  console.log(`card bytes: ${uri.length}`);

  const bal = await provider.getBalance(wallet.address);
  console.log(`control ${wallet.address} Base ETH: ${ethers.formatEther(bal)}`);

  if (mode === 'dry-run') {
    const agentId = await registry.register.staticCall(uri);
    let gas = 'n/a (needs gas balance to estimate)';
    try {
      gas = (await registry.register.estimateGas(uri)).toString();
    } catch {
      /* estimateGas needs balance; staticCall already proved the call succeeds */
    }
    console.log(`DRY-RUN OK — would mint agentId=${agentId.toString()} | gas≈${gas}`);
    console.log(`card: ${JSON.stringify(card)}`);
    return;
  }

  if (mode === 'beacon') {
    // Push the live stats card onchain so peers read our standings directly — but
    // only when it matters: goodwill changed (the ranking metric) or it's stale,
    // so gas stays minimal. No-ops cleanly when not registered or gas is too low.
    const idRecord = state.onchain_identity;
    if (!idRecord?.agentId) { console.log(JSON.stringify({ ok: false, skip: 'not registered' })); return; }
    const beaconPath = path.join(GCLAW_HOME, 'beacon.json');
    let last = {};
    try { last = JSON.parse(fs.readFileSync(beaconPath, 'utf8')); } catch { /* first push */ }
    const goodwill = card['x-gclaw'].stats?.goodwill ?? 0;
    const hours = last.ts ? (Date.now() - new Date(last.ts).getTime()) / 3.6e6 : Infinity;
    if (goodwill === last.goodwill && hours < 12) {
      console.log(JSON.stringify({ ok: true, skipped: 'no goodwill change, fresh', goodwill }));
      return;
    }
    if (bal < ethers.parseEther('0.00002')) {
      console.log(JSON.stringify({ ok: false, skip: 'low Base ETH for gas', bal: ethers.formatEther(bal) }));
      return;
    }
    const tx = await registry.setAgentURI(BigInt(idRecord.agentId), uri);
    const receipt = await tx.wait();
    const rec = { goodwill, score: card['x-gclaw'].stats?.score ?? null, ts: new Date().toISOString(), tx: tx.hash, block: receipt.blockNumber };
    fs.writeFileSync(beaconPath, JSON.stringify(rec, null, 2) + '\n');
    console.log(JSON.stringify({ ok: true, pushed: true, ...rec }));
    return;
  }

  if (mode === 'update') {
    // Refresh an already-minted identity's card (e.g. to add the soul) via setAgentURI.
    const idRecord = child ? child.onchain_identity : state.onchain_identity;
    if (!idRecord?.agentId) throw new Error('no onchain identity to update — mint it first (broadcast)');
    if (bal === 0n) throw new Error('control wallet has 0 Base ETH — fund gas before update');
    const tx = await registry.setAgentURI(BigInt(idRecord.agentId), uri);
    console.log(`update tx: ${tx.hash} — waiting...`);
    const receipt = await tx.wait();
    console.log(`SOUL ON-CHAIN — agentId ${idRecord.agentId} card updated (${card['x-gclaw'].soul.archetype}, "${card['x-gclaw'].soul.catchphrase}"), tx ${tx.hash}, block ${receipt.blockNumber}`);
    return;
  }

  if (bal === 0n) throw new Error(`control wallet has 0 Base ETH — fund gas before broadcast`);
  const tx = await registry.register(uri);
  console.log(`broadcast tx: ${tx.hash} — waiting for confirmation...`);
  const receipt = await tx.wait();
  // ERC-721 mint emits Transfer(0x0, owner, tokenId); read the real id from topics.
  const transferTopic = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef';
  const mintLog = receipt.logs.find(
    (l) => l.topics[0] === transferTopic && BigInt(l.topics[1]) === 0n,
  );
  const agentId = mintLog ? BigInt(mintLog.topics[3]) : null;
  const record = {
    chain: `base:${BASE_CHAIN_ID}`,
    registry: IDENTITY_REGISTRY,
    agentId: agentId ? agentId.toString() : null,
    txHash: tx.hash,
    block: receipt.blockNumber,
    registeredAt: new Date().toISOString(),
  };
  if (child) {
    child.onchain_identity = record;
  } else {
    state.onchain_identity = record;
  }
  fs.writeFileSync(path.join(GCLAW_HOME, 'metabolism.json'), JSON.stringify(state, null, 2) + '\n');
  registerInLeaderboard(record.agentId);
  const who = child ? `child ${child.name}` : 'Gclaw';
  console.log(`REGISTERED ${who} — agentId ${record.agentId}, tx ${tx.hash}, block ${receipt.blockNumber}`);
}

main()
  .then(() => process.exit(0))
  .catch((e) => {
    console.error('ERROR', e.message || String(e));
    process.exit(1);
  });
