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

async function ethCall(data) {
  const res = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_call', params: [{ to: REGISTRY, data }, 'latest'] }),
  });
  const j = await res.json();
  if (j.error) throw new Error(j.error.message);
  return j.result;
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
