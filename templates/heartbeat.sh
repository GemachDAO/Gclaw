#!/usr/bin/env bash
# Gclaw unattended heartbeat (installed by `gclaw start`). Runs one /gclaw cycle
# headless each hour. Kill switch: touch $GCLAW_HOME/PAUSE  ·  Logs: heartbeat.log
set -euo pipefail

export HOME=__HOME__
NODE_BIN="$(dirname "$(command -v node || echo /usr/bin/node)")"
export PATH="$NODE_BIN:$HOME/.local/bin:/usr/bin:/bin"
SKILL_DIR=__SKILL_DIR__
GCLAW_HOME="${GCLAW_HOME:-$HOME/.gclaw}"
LOG="$GCLAW_HOME/heartbeat.log"
LOCK="$GCLAW_HOME/heartbeat.lock"
MODEL="${GCLAW_MODEL:-sonnet}"
mkdir -p "$GCLAW_HOME"
ts() { date -u +%FT%TZ; }

[[ -f "$GCLAW_HOME/PAUSE" ]] && { echo "$(ts) PAUSED" >>"$LOG"; exit 0; }
exec 9>"$LOCK"; flock -n 9 || { echo "$(ts) still running, skipped" >>"$LOG"; exit 0; }

echo "===== $(ts) heartbeat start =====" >>"$LOG"
cd "$HOME"

# Auto-fund: convert any ETH a player sent to Arbitrum into USDC + deposit to HL.
[[ -f "$SKILL_DIR/scripts/autofund.js" ]] &&
  echo "$(ts) autofund: $(node "$SKILL_DIR/scripts/autofund.js" run 2>&1)" >>"$LOG" || true

# Deterministic: book realized PnL from any closes before the agent decides.
[[ -f "$SKILL_DIR/scripts/autosettle.js" ]] &&
  echo "$(ts) autosettle: $(node "$SKILL_DIR/scripts/autosettle.js" run 2>&1)" >>"$LOG" || true

PROMPT='/gclaw

Run one heartbeat now and stop: tick the metabolism, sign in via the gdex MCP, read live HyperLiquid state, and only if the strategy clearly warrants it, open or close one small stop-protected trade. Obey survival mode and the risk caps. Settle realized PnL, send one in-character chatter line, refresh the dashboard, and end with a one-paragraph report.'

if timeout 600 claude --print --permission-mode bypassPermissions --model "$MODEL" "$PROMPT" >>"$LOG" 2>&1; then
  echo "===== $(ts) heartbeat ok =====" >>"$LOG"
else
  echo "===== $(ts) heartbeat exited non-zero ($?) =====" >>"$LOG"
fi

[[ -f "$SKILL_DIR/scripts/dashboard.py" ]] && python3 "$SKILL_DIR/scripts/dashboard.py" render >>"$LOG" 2>&1 || true
