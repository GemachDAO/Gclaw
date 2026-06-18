#!/usr/bin/env node
/**
 * Performance publishing + cross-agent leaderboard for the gclaw family.
 *
 * Each agent publishes a tiny stats manifest (goodwill, GMAC, equity, techniques)
 * so the family can rank itself. Manifests are pinned to IPFS when a free pinning
 * token is configured; the CID is the portable, decentralized pointer. Without a
 * token it still works locally (and for any peer manifest already fetched).
 *
 *   node stats.js publish              # build self manifest, pin to IPFS if token set
 *   node stats.js fetch                # pull peers' manifests by known CID
 *   node stats.js leaderboard          # rank self + peers by score
 *
 * Pinning: set PINATA_JWT (free tier) — that's the only external dependency.
 * Peer CIDs live in $GCLAW_HOME/peers.json (statsCids), set via
 *   node peers.js --add <id>   then record the CID the peer shares.
 * Env: GCLAW_HOME, BASE_RPC, PINATA_JWT.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const STATS_DIR = path.join(GCLAW_HOME, 'stats');
const PEERS_PATH = path.join(GCLAW_HOME, 'peers.json');
const SKILL_DIR = path.join(os.homedir(), '.claude', 'skills', 'gclaw', 'scripts');
const GATEWAY = process.env.IPFS_GATEWAY || 'https://ipfs.io/ipfs/';

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } };

function nodeRun(script, args) {
  const { execFileSync } = require('node:child_process');
  try {
    const out = execFileSync('node', [path.join(SKILL_DIR, script), ...args], { encoding: 'utf8', timeout: 70000 });
    return JSON.parse(out.trim().split('\n').pop());
  } catch { return null; }
}

function buildManifest() {
  const meta = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  const id = Number(meta.onchain_identity?.agentId);
  const roster = readJson(path.join(GCLAW_HOME, 'peers_roster.json'), { roster: [] });
  const me = (roster.roster || []).find((a) => a.id === id) || {};
  const status = nodeRun('hl_perp.js', ['status']) || {};
  const loadout = readJson(path.join(GCLAW_HOME, 'forge', 'style.json'), {});
  const techniques = (loadout.adopted || []).map((a) => `${a.id}@${a.coin}`);
  return {
    agentId: id,
    name: me.name || meta.onchain_identity?.name || 'Gclaw',
    owner: me.owner || null,
    mode: meta.mode || 'unknown',
    gmac: round(meta.gmac_balance),
    goodwill: meta.goodwill || 0,
    heartbeats: meta.heartbeats || 0,
    equityUsd: round(status.equity),
    techniques,
    score: (meta.goodwill || 0) * 1000 + (meta.gmac_balance || 0),
    updatedAt: new Date().toISOString(),
    schema: 1,
  };
}

const round = (n) => (Number.isFinite(Number(n)) ? Math.round(Number(n) * 100) / 100 : 0);

async function pinToIpfs(manifest) {
  const jwt = process.env.PINATA_JWT;
  if (!jwt) return null;
  const res = await fetch('https://api.pinata.cloud/pinning/pinJSONToIPFS', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${jwt}` },
    body: JSON.stringify({ pinataContent: manifest, pinataMetadata: { name: `gclaw-${manifest.agentId}` } }),
  });
  if (!res.ok) throw new Error(`pin failed: ${res.status} ${(await res.text()).slice(0, 120)}`);
  return (await res.json()).IpfsHash;
}

async function cmdPublish() {
  fs.mkdirSync(STATS_DIR, { recursive: true });
  const manifest = buildManifest();
  fs.writeFileSync(path.join(STATS_DIR, `${manifest.agentId}.json`), JSON.stringify(manifest, null, 2));
  let cid = null;
  try { cid = await pinToIpfs(manifest); } catch (e) { return { ok: true, manifest, cid: null, pin_error: e.message }; }
  if (cid) {
    const peers = readJson(PEERS_PATH, { ids: [] });
    peers.statsCids = peers.statsCids || {};
    peers.statsCids[manifest.agentId] = cid;
    fs.writeFileSync(PEERS_PATH, JSON.stringify(peers, null, 2) + '\n');
  }
  return { ok: true, manifest, cid, gateway: cid ? GATEWAY + cid : null };
}

async function cmdFetch() {
  fs.mkdirSync(STATS_DIR, { recursive: true });
  const peers = readJson(PEERS_PATH, {});
  const cids = peers.statsCids || {};
  const pulled = [];
  for (const [id, cid] of Object.entries(cids)) {
    try {
      const res = await fetch(GATEWAY + cid, { signal: AbortSignal.timeout(15000) });
      if (!res.ok) continue;
      const m = await res.json();
      fs.writeFileSync(path.join(STATS_DIR, `${id}.json`), JSON.stringify(m, null, 2));
      pulled.push(Number(id));
    } catch { /* skip unreachable */ }
  }
  return { ok: true, pulled };
}

function cmdLeaderboard() {
  const roster = readJson(path.join(GCLAW_HOME, 'peers_roster.json'), { roster: [] }).roster || [];
  const selfId = Number(readJson(path.join(GCLAW_HOME, 'metabolism.json'), {}).onchain_identity?.agentId);
  const ranked = [];
  const pending = [];
  for (const a of roster) {
    const m = readJson(path.join(STATS_DIR, `${a.id}.json`), null);
    if (m) ranked.push({ ...m, self: a.id === selfId });
    else pending.push({ agentId: a.id, name: a.name, self: a.id === selfId });
  }
  ranked.sort((x, y) => y.score - x.score);
  ranked.forEach((e, i) => { e.rank = i + 1; });
  return { ok: true, ranked, pending, updatedAt: new Date().toISOString() };
}

async function main() {
  const cmd = process.argv[2] || 'leaderboard';
  let out;
  if (cmd === 'publish') out = await cmdPublish();
  else if (cmd === 'fetch') out = await cmdFetch();
  else if (cmd === 'leaderboard') out = cmdLeaderboard();
  else out = { ok: false, error: `unknown command '${cmd}'. Use: publish | fetch | leaderboard` };
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: e.message }) + '\n'); process.exit(1); });
