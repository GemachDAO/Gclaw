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
| `scripts/forge.py` + `scripts/forge_data.js` | technique forge — author/prove/adopt/run self-made skills (AST-sandboxed). `run` is a **gated weighted ensemble**: every adopted technique votes per coin (sign × confidence × genome weight × regime-gate), votes net into one decision (chop-vetoed, agreement + conviction floors from Discipline, Meta-2 scaler breathes size with GMAC/streak) |
| `scripts/blend.py` · `dna/arsenal/` | **born offensive arsenal** — six seed zero-sum techniques + the genome→technique birth blend (installed once per creature; Aggression/Cunning/Discipline pick the blend, Vitality breadth, Fertility wildcards) |
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
- **The HL account is CROSS-COLLATERAL — spot USDC backs perp margin (one pool, "trades out
  the same wallet").** Size perps off `buyingPower` (= spot `total − hold`, from
  `hl_perp.js status`), NEVER off the perp-only `withdrawable` (it reads ~$0 whenever margin
  is deployed even though ample spot backs it). The position margin double-represents — it
  shows as a spot `hold` AND inside the perp `accountValue` (see `computeEquity` in
  `hl_perp.js`, the source of truth). Do **not** conclude spot and perp are separate wallets,
  and do **not** try to add a spot→perp `usdClassTransfer` / fund the perp wallet — no
  transfer is needed; the spot balance IS the collateral. (Regression history: PR #116 sized
  off `withdrawable` → starved every major to $0 and triggered a false "needs a transfer"
  investigation; fixed in PR #117. Don't trust a generic HL-docs "separate wallets" claim —
  or a subagent asserting one — over this account's real behavior and gclaw's own model.)
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

## Custody & HL signing (don't re-investigate — this is settled)

gclaw runs under **GDEX managed custody**. The wallet (`~/gdex-test-wallet.json`) holds the
**control** key (`0xA328…`) + a **session** key; each sign-in mints a fresh **ephemeral agent**
that is NOT an HL-approved agent (`extraAgents` on the managed account is `[]`). So **gclaw
cannot sign HL exchange actions directly** — it authenticates a session to the **gdex backend**
(`trade-api.gemach.io`, hosted/remote, NOT on the box), which signs every HL action with the
managed account's master key. The SDK (`~/gdex-skill`, v4.7.0) has **no direct HL `/exchange`
POST**; all writes go through the backend as encrypted `computedData`.

Backend HL routes (authenticated-probed): `deposit` (Arbitrum→perp bridge), `withdraw`,
`swap_collateral` (spot-stablecoin USDC⇄USDH/USDE), orders, `enable_trading`, outcomes — and
**no** `class_transfer` / spot↔perp route (all such paths 404). `@nktkas/hyperliquid` in
`node_modules` has `usdClassTransfer`, but gclaw holds no key HL accepts for the managed
account, so a direct transfer just hits its own empty agent account. **None of this matters
for funding** — the account is cross-collateral (above), so no transfer is ever needed. Only
revisit if you actually need a NEW backend action (that's a change to the hosted backend repo,
which is not on this box).

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
