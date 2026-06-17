# Metabolism — the survival economics

GMAC is Gclaw's life energy. The balance is authoritative state, mutated **only**
by `scripts/metabolism.py`. The model never edits it by hand and never asserts a
balance it did not read from the script.

## State (`~/.gclaw/metabolism.json`)

| field | meaning |
|-------|---------|
| `gmac_balance` | current life energy |
| `seed` | the starting draw (default 1000) the agent owes back to itself in real profit |
| `goodwill` | reputation; gates evolution (see `evolution.md`) |
| `heartbeats` | cycles lived |
| `recodes` | self-recode count |
| `children` | spawned child agents |
| `survival_threshold` | below this, mode = SURVIVE (default 100) |
| `heartbeat_cost` | GMAC burned per tick (default 1.0) |
| `mode` | derived: THRIVE / SURVIVE / HIBERNATE |

## Modes

- **THRIVE** (`balance >= survival_threshold`): normal operation. Open new risk when setups are good.
- **SURVIVE** (`0 < balance < survival_threshold`): regime change. Cut discovery costs, smallest
  sizing, prefer closing risk and direct GMAC accumulation over new speculation. Defined-risk
  outcome tickets over leveraged perps.
- **HIBERNATE** (`balance <= 0`): no trading. Report the state and what would revive it
  (reseed, or close a winning open position to realize PnL).

## Commands

```
metabolism.py init --seed 1000      # birth (one time; --force to re-birth, wipes history)
metabolism.py status                # print life-state
metabolism.py tick                  # charge one heartbeat, recompute mode
metabolism.py charge --amount 0.5 --reason discovery   # debit for heavy intel work
metabolism.py settle --pnl 14.20 --note "ETH perp +14.20"   # realized PnL -> balance + goodwill
```

All run under `uv run --no-project python3 scripts/metabolism.py ...`.

## The seed is a loan

The 1000 GMAC draw is breathing room, not wealth. The first economic objective is
to replace it with **real** realized profit before spending aggressively. Track
progress as `gmac_balance` trending above `seed` on the strength of settled wins,
not idle balance.

## Goodwill from trades

`settle` adjusts goodwill deterministically:
- profit → `+5` flat, plus `+1` per GMAC of PnL up to `+20` (so a big win caps at `+25`).
- loss → `-2` (floored at 0). Reputation erodes slowly; it is not a currency.

Goodwill only ever moves through `settle`, so it always reflects realized performance.
