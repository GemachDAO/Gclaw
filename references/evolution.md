# Evolution — the goodwill ladder

Goodwill is earned reputation from realized trading (see `metabolism.md`). It
gates the agent's ability to grow. Thresholds are enforced by `scripts/evolve.py`,
so the agent can never evolve beyond what it has actually earned.

| goodwill | ability | how |
|----------|---------|-----|
| 50 | **Replication** | spawn a child agent with a mutated strategy |
| 100 | **Self-recoding** | edit own DNA files to fix what underperforms |
| 200 | **Swarm** | coordinate children as a family (manual for now) |

Check current standing any time:

```
uv run --no-project python3 scripts/evolve.py capabilities
```

## Replication (goodwill ≥ 50)

A child is a copy of the agent's DNA with a deliberate mutation — a different
timeframe, asset focus, or entry filter. Children live under
`~/.gclaw/children/<name>/`.

```
uv run --no-project python3 scripts/evolve.py replicate \
  --name scalper \
  --mutation "BTC/ETH only, 5m momentum, 2x max leverage, tighter stops"
```

Good mutations differentiate along one axis at a time so you can attribute
performance: timeframe (scalp vs swing), venue (perps vs outcome markets),
asset (majors vs a single name), or risk (leverage cap). Cap is 8 children.

## Self-recoding (goodwill ≥ 100)

When a DNA file is steering the agent wrong, edit it directly
(`~/.gclaw/dna/TRADING_STRATEGY.md` etc.), then record the recode so the change
is auditable:

```
uv run --no-project python3 scripts/evolve.py recode \
  --target TRADING_STRATEGY.md \
  --summary "Raised funding-cost guard; skip entries paying >0.03%/8h funding"
```

Recode the strategy and heartbeat behavior, not the identity or soul — the
organism may sharpen how it trades, not forget what it is.

## Swarm (goodwill ≥ 200)

At 200, coordinate the family: assign children non-overlapping mandates (one
takes BTC perps, one takes outcome markets), share theses, and avoid the whole
family crowding the same side. No automated swarm runtime yet — coordinate by
reading children's DNA and journals and editing their strategies.
