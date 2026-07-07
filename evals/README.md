# gclaw harness evals

A small suite of instruments that **gauge the trading harness** so refining it is
measured, not guesswork. Each eval drives the *real* code (imports `forge`, reads the
live GDEX MCP source) rather than re-implementing it, so a passing eval reflects the
actual behaviour, and several double as regression guards for a specific fix.

```bash
uv run --no-project python3 evals/run.py           # full scorecard
uv run --no-project python3 evals/run.py --quick   # skip the slow judge_power
uv run --no-project python3 evals/judge_power.py    # or run one directly
```

Each eval exits `0` on PASS, non-zero on FAIL.

| eval | question it answers | guards |
|------|---------------------|--------|
| `judge_power` | Does the backtest JUDGE certify signals with **no real edge**? Feeds structured signals through the real `_backtest_with` gate on block-bootstrapped **surrogate** data and measures the noise-certification rate. | JUDGE significance gate |
| `cost_truth` | Does the JUDGE + ledger charge the **true** round-trip cost? Recomputes fee + builderFee from real fills and re-nets every `proven_markets` pair. | builderFee in cost model |
| `feature_parity` | Does the backtest reconstruct features the way **live** `intel.js` sees them? Compares `_intel_features_at` to intel.js's exact definition across bars. | 120-bar window + sample stdev |
| `tool_budget` | Are the GDEX MCP read tools **economical with context**? Checks `trade_history` bounding, compact JSON, `isError`, and quantifies the token saving. | MCP ergonomics fixes |

## Fixtures

`fixtures/` holds cached candle series and a real fills export so the evals are
reproducible offline. It is gitignored (regenerable market data + personal fill
history). `judge_power`/`feature_parity` fetch and cache candles on first run;
`cost_truth`/`tool_budget` need `fixtures/fills.json` (fetch via the
`get_hl_trade_history` MCP tool and save it there).

## Baselines captured during the 2026-07-07 red-team

| eval | before fix | after fix |
|------|-----------|-----------|
| `judge_power` | 22.2% surrogate-FPR | 1.1% |
| `cost_truth` | modeled 15bp vs true 25bp (FAIL) | 25bp = 25bp (PASS) |
| `feature_parity` | realized_vol diverged 19/89 bars (FAIL) | all features 0.0000 (PASS) |
| `tool_budget` | trade_history ~19k tok, no isError (FAIL) | ~1.9k tok, isError (PASS) |
