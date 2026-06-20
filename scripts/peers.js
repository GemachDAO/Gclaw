#!/usr/bin/env node
/**
 * Onchain peer discovery for the gclaw family.
 *
 * Agents register their identity in the shared ERC-8004 registry on Base, but
 * the gene pool / leaderboard is local file state — so agents on different
 * machines never see each other. This reads peer identities straight from the
 * registry so the roster reflects who is actually live onchain.
 *
 *   node peers.js                 # show the roster (self + known peers)
 *   node peers.js --add 55671     # remember a peer agent id, then show roster
 *   node peers.js --scan 55600-55700   # best-effort discovery by gclaw signature
 *
 * Known peers persist in $GCLAW_HOME/peers.json. Env: GCLAW_HOME, BASE_RPC.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const PEERS_PATH = path.join(GCLAW_HOME, 'peers.json');
const REGISTRY = '0x8004a169fb4a3325136eb29fa0ceb6d2e539a432';
const RPC = process.env.BASE_RPC || 'https://mainnet.base.org';
const SIGNATURE = 'trade to survive'; // shared gclaw description marker
const pad = (n) => BigInt(n).toString(16).padStart(64, '0');

async function rpc(method, params) {
  const res = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  const j = await res.json();
  if (j.error) throw new Error(j.error.message);
  return j.result;
}
const ethCall = (data) => rpc('eth_call', [{ to: REGISTRY, data }, 'latest']);

// The registry emits this event on register AND setAgentURI, with the agentId indexed
// in topic1 and the full agent URI in the log data. So we discover EVERY gclaw agent
// from the event stream by the shared description signature — regardless of where its
// token id lands in the shared registry — instead of guessing an id window.
const REGISTER_TOPIC = '0xca52e62c367d81bb2e328eb795f7c7ba24afb478408a26c0e201d155c449bc4a';
const GENESIS_BLOCK = Number(process.env.GCLAW_GENESIS_BLOCK) || 47435383; // first gclaw mint
const LOG_CHUNK = 10000; // public Base RPC caps eth_getLogs at a 10k block range

function isGclawUri(uri) {
  if (!uri) return false;
  if (uri.includes('base64,')) {
    try {
      const card = JSON.parse(Buffer.from(uri.split('base64,')[1], 'base64').toString('utf8'));
      return typeof card.description === 'string' && card.description.includes(SIGNATURE);
    } catch { return false; }
  }
  return uri.includes(SIGNATURE);
}

// Event-sourced discovery: replay the registry's URI events from the gclaw genesis
// block (or the saved cursor) forward, keep the ones whose card carries the signature,
// and fold them into peers.json. Incremental via peers.lastBlock — steady state only
// reads the handful of new blocks since the last run.
async function discover(peers, self) {
  const latest = parseInt(await rpc('eth_blockNumber', []), 16);
  const start = peers.lastBlock ? peers.lastBlock + 1 : GENESIS_BLOCK;
  const added = [];
  for (let lo = start; lo <= latest; lo += LOG_CHUNK) {
    const hi = Math.min(lo + LOG_CHUNK - 1, latest);
    const logs = await rpc('eth_getLogs', [{
      address: REGISTRY, topics: [REGISTER_TOPIC],
      fromBlock: '0x' + lo.toString(16), toBlock: '0x' + hi.toString(16),
    }]).catch(() => []);
    for (const log of logs || []) {
      const id = Number(BigInt(log.topics[1]));
      if (id === self || peers.ids.includes(id)) continue;
      if (isGclawUri(decodeString(log.data))) { peers.ids.push(id); added.push(id); }
    }
  }
  peers.lastBlock = latest;
  savePeers(peers);
  return { ok: true, from: start, to: latest, added, knownPeers: peers.ids.length };
}

function decodeString(hex) {
  if (!hex || hex === '0x') return null;
  const b = hex.slice(2);
  const off = parseInt(b.slice(0, 64), 16) * 2;
  const len = parseInt(b.slice(off, off + 64), 16) * 2;
  return Buffer.from(b.slice(off + 64, off + 64 + len), 'hex').toString('utf8');
}

async function readAgent(id) {
  const [uriRaw, ownerRaw] = await Promise.all([
    ethCall('0xc87b56dd' + pad(id)).catch(() => null), // tokenURI(uint256)
    ethCall('0x6352211e' + pad(id)).catch(() => null), // ownerOf(uint256)
  ]);
  const uri = decodeString(uriRaw);
  let meta = {};
  if (uri && uri.includes('base64,')) {
    try { meta = JSON.parse(Buffer.from(uri.split('base64,')[1], 'base64').toString('utf8')); } catch { meta = {}; }
  }
  const owner = ownerRaw && ownerRaw !== '0x' ? '0x' + ownerRaw.slice(-40) : null;
  return { id: Number(id), name: meta.name || null, owner, image: meta.image || null,
    stats: meta['x-gclaw']?.stats || null,  // live standings beacon, read straight from chain
    predictors: meta['x-gclaw']?.predictors || [],  // who called this creature's trades right — for the global ladder
    edges: meta['x-gclaw']?.edges || [],  // proven technique x regime edges — for the collective swarm graph
    published: meta['x-gclaw']?.published || [],  // proven techniques advertised for discovery
    isGclaw: typeof meta.description === 'string' && meta.description.includes(SIGNATURE) };
}

function loadPeers() {
  try { return JSON.parse(fs.readFileSync(PEERS_PATH, 'utf8')); } catch { return { ids: [] }; }
}

function savePeers(p) {
  fs.writeFileSync(PEERS_PATH, JSON.stringify(p, null, 2) + '\n');
}

function selfId() {
  try { return Number(JSON.parse(fs.readFileSync(path.join(GCLAW_HOME, 'metabolism.json'), 'utf8')).onchain_identity.agentId); } catch { return null; }
}

async function main() {
  const argv = process.argv.slice(2);
  const peers = loadPeers();
  const self = selfId();

  // Discover the whole family from the registry's event log — every gclaw agent that
  // ever registered or beaconed, by signature, regardless of token id. Run by the
  // heartbeat so a new signup is pulled into the peer graph automatically; the next
  // beacon publishes the updated peers, and the leaderboard's crawl surfaces it.
  if (argv.includes('--discover')) {
    const out = await discover(peers, self).catch((e) => ({ ok: false, error: e.message }));
    process.stdout.write(JSON.stringify(out) + '\n');
    return;
  }

  const addIdx = argv.indexOf('--add');
  if (addIdx !== -1 && argv[addIdx + 1]) {
    const id = Number(argv[addIdx + 1]);
    if (!peers.ids.includes(id)) peers.ids.push(id);
    savePeers(peers);
  }

  const scanIdx = argv.indexOf('--scan');
  if (scanIdx !== -1 && argv[scanIdx + 1]) {
    const [start, end] = argv[scanIdx + 1].split('-').map(Number);
    for (let id = start; id <= end; id += 1) {
      const a = await readAgent(id).catch(() => null);
      if (a && a.isGclaw && !peers.ids.includes(id) && id !== self) peers.ids.push(id);
    }
    savePeers(peers);
  }

  const ids = [...new Set([self, ...peers.ids].filter((x) => x != null))].sort((a, b) => a - b);
  const roster = [];
  for (const id of ids) {
    const a = await readAgent(id).catch(() => ({ id: Number(id), name: null, owner: null, error: true }));
    roster.push({ ...a, self: id === self });
  }
  process.stdout.write(JSON.stringify({ ok: true, registry: REGISTRY, chain: 'base:8453', count: roster.length, roster }, null, 2) + '\n');
}

main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: e.message }) + '\n'); process.exit(1); });
