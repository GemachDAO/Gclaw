# Safety & security model

This is a real-money agent that holds wallet keys, so the design assumes the
network is adversarial. The controls below exist so a creature can't be drained.

## Anti-drain controls

| Vector | Control |
|---|---|
| **Untrusted technique code (RCE)** | The forge executes `signal.py` only inside a sandbox: an AST allow-list (imports limited to `math`/`statistics`, dunder/`__builtins__`/`format`/`getattr`/`eval`/`exec`/`open` banned) **and** a restricted `exec` `__builtins__` with a math-only `_safe_import`. The `__builtins__['__import__']('os')` escape is closed at both layers. **Do not auto-execute peer-supplied code** — cross-machine sharing must share data/specs, not code, or run pulled code isolated + draft-only. |
| **Prompt injection → fund exit** | The heartbeat runs unattended (`bypassPermissions`) and reads untrusted text (peer cards, family bus, market data, gene-pool metadata). It denies every tool that can move funds to an arbitrary destination: `transfer_native`, `transfer_token`, `execute_bridge`, `perp_withdraw`, `hl_swap_collateral`, sells. Legit funding is done by deterministic scripts (`autofund`, `gmac_buy`) with **hard-coded destinations** — never by the model. |
| **Key exposure** | The control private key is used only for local `ethers.Wallet` signing; it is never logged or sent. Wallet files (`*-wallet.json`) and secrets (`~/.gclaw/env`) are gitignored. |
| **Runaway losses** | A portfolio **circuit breaker** halts new entries (never blocks closing) when equity falls ≥25% from its high-water mark or there are ≥3 open positions. Per-trade risk is also capped (5% / 2% in survive) with a mandatory stop. |
| **Giving back profit** | Managed custody can't move an exchange stop (the backend only attaches tp/sl to an executing order). A **soft trailing stop** (`autotrail.js`, run each heartbeat) instead closes a position once it's in profit and trails ≥0.6% off its high-water mark — floored at break-even, so it only ever closes green. The hard exchange SL set at open stays as the between-heartbeat catastrophic floor. (A true exchange-side trailing stop needs the GDEX backend to expose standalone trigger orders — see assune-6tk.) |

## Health alerting

Set `GCLAW_ALERT_WEBHOOK` (Slack/Discord/generic JSON) and/or `GCLAW_TELEGRAM_TOKEN`
+ `GCLAW_TELEGRAM_CHAT` in `~/.gclaw/env`. Each heartbeat runs `notify.js check`
and pings on the *transition* into a red state:

- **hibernate** (out of GMAC) — fund it to revive
- **low beacon gas** — top up Base ETH
- **circuit breaker tripped** — drawdown / too many positions
- **trading funds low** while flat

No webhook → it no-ops. Errors (heartbeat exit non-zero) alert immediately.

## Owner withdrawal (not blocked)

The anti-drain controls stop the **autonomous model** from moving funds — they do
**not** lock out the owner. You hold the control wallet, so your funds are always
withdrawable: `scripts/withdraw.js` does the HL→Arbitrum (`perpWithdraw`) and
Arbitrum→your-wallet (`transferToken`) legs, gated so a real `--confirm` only runs
from an interactive terminal (the headless heartbeat has no TTY, so the agent can
never withdraw through it; under `GCLAW_SANDBOX` the wallet is masked too). Never
tell an owner their funds are stuck or to "contact gemach" — point them at it.

## What still needs your trust

- The wallet's **managed custody** is operated by GDEX; the autonomous model can't
  move funds out (the owner always can, above), but custody itself is a trust assumption.
- **Live deployed config** (registry owner, attester) is onchain — verify it.
- The sandbox raises the bar a lot but in-process Python isolation is not a
  hard boundary; treat any *peer-pulled* code as untrusted and keep it
  data-only / draft-only until a process-isolated runner exists.
