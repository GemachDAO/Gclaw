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
| `dna/` | the agent's DNA template (copied to `~/.gclaw/dna` on first run); `TRADING_STRATEGY.md` is the trading brain |
| `scripts/heartbeat.sh` | the unattended cron loop — sequences every deterministic step around the LLM cycle |
| `scripts/metabolism.py` | survival state machine — `init/status/tick/charge/settle/gmac` (atomic writes) |
| `scripts/evolve.py` | goodwill-gated `replicate/recode/capabilities` |
| **Perception & risk** | |
| `scripts/intel.js` | perception + **regime** engine (EMA/RSI/ATR/Bollinger-z/funding-z/BTC-corr → trend/range/chop) |
| `scripts/sizing.py` | vol-targeted + fractional-Kelly position sizing (sample-shrunk) |
| `scripts/memory.py` | trade-memory — regime-conditional expectancy w/ bootstrap CI; `swarm` pools the family |
| `scripts/riskguard.js` | **deterministic** per-trade/portfolio risk cap + naked-flatten + drawdown breaker (enforces, not advises) |
| `scripts/model_select.js` | hybrid model + adaptive cadence — Opus only when active, else Sonnet |
| **Execution & settlement** | |
| `scripts/gdex_sign.js` | instant local sign-in signer (pure crypto) |
| `scripts/hl_perp.js` | SDK executor (`status [--cache] / open / close [--size]`) |
| `scripts/autofund.js` · `autotrail.js` · `autosettle.js` · `gmac_buy.js` | deterministic funding, trailing stops, settlement (atomic/idempotent), GMAC buy-back |
| `scripts/forge.py` + `scripts/forge_data.js` | technique forge — author/prove/adopt/run self-made skills (AST-sandboxed) |
| **Identity, social & UI** | |
| `scripts/erc8004_register.js` · `peers.js` · `stats.js` | onchain ERC-8004 card/beacon, family discovery, IPFS leaderboard |
| `scripts/predict.js` + `predict_bot.js` | the "Call it" prediction game engine + Telegram input |
| `scripts/notify.js` | health alerts + in-voice win/milestone texts (webhook + Telegram) |
| `scripts/dashboard.py` | the tabbed living dashboard (vitals, P&L sparkline, regime, predictions) |
| `leaderboard/leaderboard.html` | the decentralized, unhosted leaderboard (reads the chain directly) |
| `references/` | `mcp-trading.md` (primary), `trading.md`, `metabolism.md`, `evolution.md`, `safety.md`, `family.md` |

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
- **Safety is deterministic, never advisory.** Risk caps (`riskguard.js`), settlement
  (`autosettle.js`), GMAC spend (`gmac_buy.js`), and the drawdown breaker run as code the
  model can't skip — that's the lesson from every audit. Don't "fix" a safety gap by adding
  a model instruction; enforce it in a script.
- **No drain surface.** The heartbeat denies every fund-moving / arbitrary-token / copy-trade
  MCP tool; the forge sandbox blocks introspection-attribute escapes. Re-check both when
  touching `heartbeat.sh` deny-list or `forge.py` validators.
- The agent trades on the **regime** (`intel.js`): no entries in `chop`; size via `sizing.py`;
  open only on memory-proven, regime-matched edge.

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
