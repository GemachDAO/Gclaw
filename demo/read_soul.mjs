#!/usr/bin/env node
// Read a Gclaw creature's soul straight from the ERC-8004 IdentityRegistry on Base.
// No SDK, no key — just a public RPC. Proof the pet is real and onchain.
const REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432";
const SEL = "0xc87b56dd"; // tokenURI(uint256)
const id = process.argv[2] || "55624";
const pad = (n) => BigInt(n).toString(16).padStart(64, "0");
const call = async (data) => (await (await fetch("https://mainnet.base.org", {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_call", params: [{ to: REGISTRY, data }, "latest"] }),
})).json()).result;
const dec = (h) => { h = h.replace(/^0x/, ""); const len = parseInt(h.slice(64, 128), 16); const b = h.slice(128, 128 + len * 2); let s = ""; for (let i = 0; i < b.length; i += 2) s += String.fromCharCode(parseInt(b.substr(i, 2), 16)); return s; };
const A = (c, s) => `\x1b[${c}m${s}\x1b[0m`;
const card = JSON.parse(Buffer.from(dec(await call(SEL + pad(id))).split(",")[1], "base64").toString());
const g = card["x-gclaw"], soul = g.soul;
console.log(A("2", `\n  reading agentId ${id} from Base mainnet (IdentityRegistry ${REGISTRY.slice(0,10)}…)`));
console.log(A("32", "  ✓ on-chain, verifiable by anyone:\n"));
console.log("  " + A("1", card.name) + A("2", `  ${g.species} · ${soul.archetype}`));
console.log("  " + A("38;2;143;116;231", `"${soul.catchphrase}"`));
console.log(A("2", `  voice: ${soul.voice} · ${soul.temperament.join(", ")}`));
console.log(A("2", `  genome ${g.genomeFingerprint} · traits ${JSON.stringify(g.traits)}\n`));
