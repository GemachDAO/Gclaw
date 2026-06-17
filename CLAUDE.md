# Gclaw skill — developer guide

A Claude Code **skill** that runs a living trading agent on the GDEX MCP. The
agent burns GMAC each heartbeat and earns it back trading HyperLiquid perps +
HIP-3 outcome markets. This repo is the skill; runtime state lives under
`$GCLAW_HOME` (default `~/.gclaw`).

## Architecture (one line)

`SKILL.md` drives a heartbeat loop → deterministic Python (`metabolism.py`,
`evolve.py`) owns survival/evolution bookkeeping → the gdex MCP executes trades,
with `gdex_sign.js` providing the one local signature managed custody can't delegate.

## Layout

| path | role |
|------|------|
| `SKILL.md` | entry point — trigger + heartbeat procedure |
| `dna/` | the agent's DNA template (copied to `~/.gclaw/dna` on first run) |
| `scripts/metabolism.py` | survival state machine — `init/status/tick/charge/settle` |
| `scripts/evolve.py` | goodwill-gated `replicate/recode/capabilities` |
| `scripts/gdex_sign.js` | instant local sign-in signer (pure crypto) |
| `scripts/hl_perp.js` | SDK fallback executor (`status/open/close`) |
| `references/` | `mcp-trading.md` (primary), `trading.md`, `metabolism.md`, `evolution.md` |

## Build / test / lint

Python (3.13, stdlib only — no deps):
```bash
uv run --no-project ruff check scripts/        # lint (must pass clean)
uv run --no-project python3 scripts/metabolism.py status
```
Node helpers resolve `ethers` + the SDK from `~/gdex-skill` (`$GDEX_SKILL_DIR`):
```bash
node --check scripts/gdex_sign.js scripts/hl_perp.js   # syntax
node scripts/gdex_sign.js                              # instant, prints a signed session
```
**Run Python via `uv run --no-project python3`** (a box hook blocks bare `python3`).

## Trading invariants (do not regress)

- HL funds/positions are under the **managed** Arbitrum/HL address, never the control wallet.
- Every perp entry carries a stop. The $11 HL min notional is enforced.
- The GMAC balance changes ONLY through `metabolism.py`; PnL is settled ONLY from real closed positions.
- Majors first (BTC/ETH/SOL), low size, conservative leverage. No memecoins.

## Issue tracking — beads

This repo uses **bd (beads)**, shared box-wide (`assune` prefix). Filter this
project's work with the `gclaw` label:
```bash
bd list --label gclaw      # the backlog
bd ready                   # available work
bd show <id>               # details
bd update <id> --claim     # start
bd close <id>              # finish
```
File new follow-ups with `--label gclaw`. Do NOT use TodoWrite or markdown TODO lists.

## Conventions

- ≤100 lines/function, absolute imports, Google-style docstrings on public APIs.
- Replace, don't deprecate — no shims or dead code.
- Commit subjects imperative, ≤72 chars; one logical change per commit; never push to a shared branch directly.
