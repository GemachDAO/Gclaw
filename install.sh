#!/usr/bin/env bash
# Gclaw — one-command install. Clone the repo, run this, follow two prompts.
#
#   ./install.sh
#
# It links the skill, checks prerequisites, makes you a wallet, and tells you
# exactly what to fund. Then: `gclaw fund` to confirm, `gclaw start` to go live.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GCLAW_HOME="${GCLAW_HOME:-$HOME/.gclaw}"
GCLAW="$SKILL_DIR/bin/gclaw"
b(){ printf '\n\033[1m%s\033[0m\n' "$1"; }
ok(){ printf '  \033[32m✓\033[0m %s\n' "$1"; }
arrow(){ printf '  \033[33m→\033[0m %s\n' "$1"; }

b "🜃 Installing Gclaw — the living trading agent"

# 1) Prerequisites
command -v node >/dev/null || { echo "Need Node 22+. Install it, then re-run."; exit 1; }
command -v python3 >/dev/null || { echo "Need python3. Install it, then re-run."; exit 1; }
ok "node $(node -v) · python3 $(python3 -V 2>&1 | awk '{print $2}')"

# 2) GDEX SDK (the trading engine). Not on npm — needs the GemachDAO/gdex-skill clone.
GDEX_DIR="${GDEX_SKILL_DIR:-$HOME/gdex-skill}"
if [ ! -d "$GDEX_DIR/dist" ]; then
  arrow "GDEX SDK not found at $GDEX_DIR"
  arrow "Clone it:  git clone https://github.com/GemachDAO/gdex-skill ~/gdex-skill && (cd ~/gdex-skill && npm i && npm run build)"
  arrow "Or set GDEX_SKILL_DIR to your copy, then re-run ./install.sh"
  exit 1
fi
ok "GDEX SDK at $GDEX_DIR"

# 3) Link the skill + put gclaw on PATH
ln -sfn "$SKILL_DIR" "$HOME/.claude/skills/gclaw"
chmod +x "$GCLAW" "$SKILL_DIR"/scripts/*.py "$SKILL_DIR"/scripts/*.js 2>/dev/null || true
mkdir -p "$HOME/.local/bin" && ln -sfn "$GCLAW" "$HOME/.local/bin/gclaw"
ok "skill linked + 'gclaw' command installed (~/.local/bin)"

# 4) Wallet
if [ -f "$GCLAW_HOME/wallet.json" ] || [ -f "$HOME/gdex-test-wallet.json" ]; then
  ok "wallet already present"
else
  b "Creating your wallet…"
  node "$SKILL_DIR/scripts/new_wallet.js"
fi

b "✅ Installed. Next:"
arrow "1. Fund the addresses shown above (USDC for trading, a little Base ETH for identity gas)"
arrow "2. gclaw fund     — confirm your money landed"
arrow "3. gclaw start    — bring your creature to life (births it + hourly heartbeat)"
arrow "4. gclaw dashboard — watch it live  ·  gclaw talk Gclaw — say hello"
echo
arrow "If ~/.local/bin isn't on PATH yet:  export PATH=\"\$HOME/.local/bin:\$PATH\""
