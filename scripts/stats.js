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
const crypto = require('node:crypto');

const GCLAW_HOME = process.env.GCLAW_HOME || path.join(os.homedir(), '.gclaw');
const STATS_DIR = path.join(GCLAW_HOME, 'stats');
const IMAGE_PATH = path.join(GCLAW_HOME, 'identity_image.json');
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

// A technique is LIVE-PROVEN at >= 3 real closes with positive expectancy — the same
// gate reputation.py/_proven_edge and evolve.py.proven_edge_techniques enforce. Kept in
// sync deliberately: the manifest is the published mirror of the reputation scorecard.
const PROVEN_MIN_TRADES = 3;
const REPLICATE_MIN_EDGE = Number(process.env.GCLAW_REPLICATE_MIN_EDGE) || 2;

function provenEdgeTechniques(adopted) {
  return adopted
    .filter((a) => Number(a.trades || 0) >= PROVEN_MIN_TRADES && Number(a.e || 0) > 0)
    .map((a) => ({ id: a.id, e: round(a.e), trades: Number(a.trades || 0) }));
}

// Adopted techniques THIS agent authored (technique.json author == its id) — its real
// self-modifications, mirroring evolve.py.self_authored_adopted.
function authoredCount(adopted, agentId) {
  let n = 0;
  for (const a of adopted) {
    const tech = readJson(path.join(GCLAW_HOME, 'forge', 'techniques', String(a.id), 'technique.json'), {});
    if (String(tech.author) === String(agentId)) n += 1;
  }
  return n;
}

function buildManifest() {
  const meta = readJson(path.join(GCLAW_HOME, 'metabolism.json'), {});
  const id = Number(meta.onchain_identity?.agentId);
  const roster = readJson(path.join(GCLAW_HOME, 'peers_roster.json'), { roster: [] });
  const me = (roster.roster || []).find((a) => a.id === id) || {};
  const status = nodeRun('hl_perp.js', ['status']) || {};
  const loadout = readJson(path.join(GCLAW_HOME, 'forge', 'style.json'), {});
  const adopted = loadout.adopted || [];
  const techniques = adopted.map((a) => `${a.id}@${a.coin}`);
  const img = readJson(IMAGE_PATH, {});

  // Proven edge = fitness (FITNESS.md). Read the settled scorecard reputation.py writes.
  const rep = readJson(path.join(GCLAW_HOME, 'reputation.json'), {});
  const trade = rep.trading || {};
  const calib = rep.event_calibration || {};
  const provenTechniques = provenEdgeTechniques(adopted);
  const provenEdge = provenTechniques.length;
  const authored = authoredCount(adopted, id);
  const realizedPnl = round(trade.realized_pnl_usd);
  // Breed-ready mirrors evolve.py.replication_gate: >= REPLICATE_MIN_EDGE proven-edge
  // techniques AND at least one NEW proven technique since the last birth (anti-storm).
  const lastEdge = Number(meta.last_replicate_edge_count || 0);
  const breedReady =
    provenEdge >= REPLICATE_MIN_EDGE &&
    provenEdge > lastEdge &&
    (meta.children || []).length < 8;

  return {
    agentId: id,
    name: me.name || meta.onchain_identity?.name || 'Gclaw',
    owner: me.owner || null,
    image: img.ipfs || me.image || null,
    mode: meta.mode || 'unknown',
    gmac: round(meta.gmac_balance),
    goodwill: meta.goodwill || 0,
    heartbeats: meta.heartbeats || 0,
    equityUsd: round(status.equity),
    techniques,
    // --- schema 2: PROVEN EDGE is the fitness signal, not equity/goodwill ---
    provenEdge,
    provenTechniques,
    authored,
    breedReady,
    realizedPnl,
    closedTrades: Number(trade.closed_trades || 0),
    winRate: trade.win_rate == null ? null : Number(trade.win_rate),
    calibrationBrier: calib.brier == null ? null : Number(calib.brier),
    // Rank key: proven edge dominates; breed-ready is a large step; self-authoring is a
    // tiebreak; honest realized PnL only ever breaks ties among equally-proven creatures
    // and NEVER lets equity/bankroll set the rank. max(0, pnl) so a loss can't sink a
    // proven scientist below an unproven one.
    score:
      provenEdge * 1e6 +
      (breedReady ? 2e5 : 0) +
      authored * 1e3 +
      Math.max(0, realizedPnl),
    updatedAt: new Date().toISOString(),
    schema: 2,
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

// Pin the agent's deterministic DNA image to IPFS once (idempotent by content
// hash) so its onchain-style identity has a real, decentralized avatar.
async function cmdPinImage() {
  const svgPath = path.join(GCLAW_HOME, 'identity.svg');
  if (!fs.existsSync(svgPath)) return { ok: false, error: 'no identity.svg (render the dashboard first)' };
  const svg = fs.readFileSync(svgPath);
  const fingerprint = crypto.createHash('sha256').update(svg).digest('hex').slice(0, 16);
  const cached = readJson(IMAGE_PATH, null);
  if (cached && cached.fingerprint === fingerprint && cached.cid) return { ok: true, ...cached, cached: true };
  const jwt = process.env.PINATA_JWT;
  if (!jwt) return { ok: false, error: 'PINATA_JWT not set' };
  const form = new FormData();
  form.append('file', new Blob([svg], { type: 'image/svg+xml' }), 'identity.svg');
  const res = await fetch('https://api.pinata.cloud/pinning/pinFileToIPFS', {
    method: 'POST', headers: { authorization: `Bearer ${jwt}` }, body: form,
  });
  if (!res.ok) return { ok: false, error: `pin failed: ${res.status} ${(await res.text()).slice(0, 120)}` };
  const cid = (await res.json()).IpfsHash;
  const out = { cid, ipfs: `ipfs://${cid}`, gateway: GATEWAY + cid, fingerprint };
  fs.writeFileSync(IMAGE_PATH, JSON.stringify(out, null, 2) + '\n');
  return { ok: true, ...out };
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
    // Prefer a fully-fetched IPFS manifest; otherwise use the onchain beacon the
    // peer wrote into its card (read by peers.js) — no manual CID exchange needed.
    const local = readJson(path.join(STATS_DIR, `${a.id}.json`), null);
    const src = local || (a.stats && a.stats.score != null ? { agentId: a.id, name: a.name, ...a.stats } : null);
    if (src && src.score != null) {
      // Carry the schema-2 fitness fields when present; schema-1 peers simply omit them
      // (rendered undefined downstream, sorted below by their lower score).
      ranked.push({
        agentId: a.id, name: a.name || src.name, goodwill: src.goodwill, gmac: src.gmac,
        equityUsd: src.equityUsd, score: src.score, image: a.image || src.image,
        provenEdge: src.provenEdge, provenTechniques: src.provenTechniques, authored: src.authored,
        breedReady: src.breedReady, realizedPnl: src.realizedPnl, closedTrades: src.closedTrades,
        winRate: src.winRate, calibrationBrier: src.calibrationBrier, schema: src.schema || 1,
        source: local ? 'ipfs' : 'onchain', self: a.id === selfId,
      });
    } else {
      pending.push({ agentId: a.id, name: a.name, self: a.id === selfId });
    }
  }
  ranked.sort((x, y) => y.score - x.score);
  ranked.forEach((e, i) => { e.rank = i + 1; });
  return { ok: true, ranked, pending, updatedAt: new Date().toISOString() };
}

async function main() {
  const cmd = process.argv[2] || 'leaderboard';
  let out;
  if (cmd === 'publish') out = await cmdPublish();
  else if (cmd === 'pin-image') out = await cmdPinImage();
  else if (cmd === 'fetch') out = await cmdFetch();
  else if (cmd === 'leaderboard') out = cmdLeaderboard();
  else out = { ok: false, error: `unknown command '${cmd}'. Use: publish | pin-image | fetch | leaderboard` };
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: e.message }) + '\n'); process.exit(1); });
