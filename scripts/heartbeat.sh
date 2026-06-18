#!/usr/bin/env bash
# Gclaw unattended heartbeat — installed to $GCLAW_HOME and invoked hourly by cron.
# Runs one /gclaw cycle headless (local gdex MCP + wallet), then refreshes the
# dashboard (which publishes stats + the DNA avatar to IPFS when configured).
#
# Install:   cp scripts/heartbeat.sh "$HOME/.gclaw/heartbeat.sh" && chmod +x "$_"
#            ( crontab -l 2>/dev/null; echo "0 * * * * $HOME/.gclaw/heartbeat.sh" ) | crontab -
# Kill switch:   touch ~/.gclaw/PAUSE   (rm it to resume)
# Logs:          ~/.gclaw/heartbeat.log
set -euo pipefail

GCLAW_HOME="${GCLAW_HOME:-$HOME/.gclaw}"
LOG="$GCLAW_HOME/heartbeat.log"
LOCK="$GCLAW_HOME/heartbeat.lock"
MODEL="${GCLAW_MODEL:-sonnet}"
SKILL_DIR="${GCLAW_SKILL_DIR:-$HOME/.claude/skills/gclaw}"
mkdir -p "$GCLAW_HOME"

# cron has a minimal PATH; ensure node + user bins resolve. Adjust if needed.
NODE_BIN="$(command -v node 2>/dev/null || true)"
export PATH="$HOME/.local/bin:${NODE_BIN%/node}:/usr/local/bin:/usr/bin:/bin:$PATH"

# Load runtime secrets (PINATA_JWT for IPFS publishing, etc.) — gitignored, never committed.
if [[ -f "$GCLAW_HOME/env" ]]; then set -a; . "$GCLAW_HOME/env"; set +a; fi

ts() { date -u +%FT%TZ; }

if [[ -f "$GCLAW_HOME/PAUSE" ]]; then
  echo "$(ts) PAUSED (rm $GCLAW_HOME/PAUSE to resume)" >>"$LOG"
  exit 0
fi

# Never overlap heartbeats.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(ts) skipped: previous heartbeat still running" >>"$LOG"
  exit 0
fi

PROMPT='/gclaw

Run exactly one heartbeat now and then stop: tick the metabolism, sign in via the gdex MCP, read live HyperLiquid state, and only if the strategy clearly warrants it, open or close one small stop-protected trade. Obey the current survival mode. Never exceed the risk caps in TRADING_STRATEGY.md. Settle any realized PnL into the metabolism and end with a one-paragraph report.'

echo "===== $(ts) heartbeat start (model=$MODEL) =====" >>"$LOG"
cd "$HOME"

# Auto-fund: convert any ETH sent to Arbitrum into USDC + deposit to HL.
[[ -f "$SKILL_DIR/scripts/autofund.js" ]] &&
  echo "$(ts) autofund: $(node "$SKILL_DIR/scripts/autofund.js" run 2>&1)" >>"$LOG" || true
# Deterministic auto-settle: book realized PnL from any closes (TP/SL) before the agent decides.
[[ -f "$SKILL_DIR/scripts/autosettle.js" ]] &&
  echo "$(ts) autosettle: $(node "$SKILL_DIR/scripts/autosettle.js" run 2>&1)" >>"$LOG" || true

if timeout 600 claude --print --permission-mode bypassPermissions --model "$MODEL" "$PROMPT" >>"$LOG" 2>&1; then
  echo "===== $(ts) heartbeat ok =====" >>"$LOG"
else
  echo "===== $(ts) heartbeat exited non-zero ($?) =====" >>"$LOG"
fi

# Always refresh the dashboard — this also publishes stats + the DNA avatar to
# IPFS and recomputes the family leaderboard (no-ops cleanly without PINATA_JWT).
[[ -f "$SKILL_DIR/scripts/dashboard.py" ]] &&
  "$SKILL_DIR/scripts/dashboard.py" render >>"$LOG" 2>&1 || true
