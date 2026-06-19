#!/usr/bin/env bash
# Telegram poll for the Call it game — invoked by cron every 2 min for near-real-time
# call capture. Sources runtime secrets (token); cron has a minimal PATH so resolve node.
#
# Install:   cp scripts/predict_bot.sh "$HOME/.gclaw/predict_bot.sh" && chmod +x "$_"
#            ( crontab -l 2>/dev/null; echo "*/2 * * * * \$HOME/.gclaw/predict_bot.sh >> \$HOME/.gclaw/predict_bot.log 2>&1" ) | crontab -
set -euo pipefail
GCLAW_HOME="${GCLAW_HOME:-$HOME/.gclaw}"
SKILL_DIR="${GCLAW_SKILL_DIR:-$HOME/.claude/skills/gclaw}"
NODE_DIR="$(command -v node 2>/dev/null || true)"; NODE_DIR="${NODE_DIR%/node}"
# cron's bare env has no nvm on PATH, so fall back to the newest nvm node bin.
[[ -z "$NODE_DIR" ]] && NODE_DIR="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
export PATH="$NODE_DIR:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
[[ -f "$GCLAW_HOME/env" ]] && { set -a; . "$GCLAW_HOME/env"; set +a; }
exec node "$SKILL_DIR/scripts/predict_bot.js" poll
