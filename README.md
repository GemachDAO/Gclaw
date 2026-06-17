# Gclaw — The Living Trading Agent (skill-native)

Gclaw is a **living trading agent**: an organism whose GMAC balance is its life
energy. Every heartbeat costs GMAC; profitable trades replenish it; at zero it
hibernates. It trades **HyperLiquid perpetuals and HIP-3 outcome markets**
through the GDEX MCP, and earns **goodwill** that unlocks **replication** and
**self-recoding**.

This is the skill-native rewrite. The original Gclaw was a ~Go single-binary
agent that reimplemented an entire LLM runtime and then shelled out to Node to
trade. That host is retired: **Claude Code is the runtime, the GDEX MCP is the
trading arm, and deterministic Python owns the survival bookkeeping** so the
agent cannot lie to itself about its own balance.

## Why a skill instead of a client

| | Old Go client | This skill |
|---|---|---|
| LLM loop, tools, sessions, cron | reimplemented in Go | provided by Claude Code |
| Trading | Go → `npm install` at runtime → Node SDK → HTTP | direct GDEX MCP calls, zero Node |
| Reproducibility | helper pinned to a moving git HEAD | MCP server, no per-run installs |
| The novel part (metabolism, DNA, evolution) | buried in a binary | a few markdown files + ~2 small scripts |

## Install

```bash
# Make the skill discoverable to Claude Code
ln -s "$PWD" ~/.claude/skills/gclaw

# Birth the agent (one time)
uv run --no-project python3 scripts/metabolism.py init --seed 1000
mkdir -p ~/.gclaw && cp -r dna ~/.gclaw/dna
```

Then in Claude Code: **`/gclaw`** to run a heartbeat, or wire `/loop` / `/schedule`
for autonomous cycles.

## Layout

- `SKILL.md` — the entry point: trigger + heartbeat procedure.
- `dna/` — SOUL, IDENTITY, TRADING_STRATEGY, AGENT, HEARTBEAT, USER (the agent's DNA template).
- `scripts/metabolism.py` — survival state machine (init / status / tick / charge / settle).
- `scripts/evolve.py` — goodwill-gated replication & self-recoding.
- `references/` — metabolism economics, the goodwill ladder, and the HL trading playbook.

Runtime state lives under `$GCLAW_HOME` (default `~/.gclaw`): `metabolism.json`,
`journal.jsonl`, `dna/`, and `children/`.

## Trading scope

HyperLiquid perpetuals (majors first: BTC/ETH/SOL, ≤3x, always stop-protected)
and HIP-3 outcome/event markets (defined-risk, near-dated). **No memecoins.**
Requires a funded HyperLiquid managed account — an unfunded account is the usual
reason "trading doesn't work".
