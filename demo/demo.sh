#!/usr/bin/env bash
# Gclaw demo — scripted for an asciinema recording. Run from the repo root:
#   asciinema rec --command "bash demo/demo.sh" --cols 92 --rows 30 demo/demo.cast
set -u
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# /usr/bin first so `python3` is the real interpreter (this box has a uv shim on PATH).
export PATH="/usr/bin:$SKILL_DIR/bin:$HOME/.local/bin:$PATH"
A() { printf '\033[%sm%s\033[0m' "$1" "$2"; }
pause() { sleep "${1:-1}"; }
type() { printf '\033[2m$\033[0m '; for ((i=0;i<${#1};i++)); do printf '%s' "${1:$i:1}"; sleep 0.018; done; printf '\n'; pause 0.4; }
say() { printf '\n  %s\n\n' "$(A '38;2;143;116;231' "$1")"; pause 0.8; }

clear
printf '\n  %s\n' "$(A '1;38;2;160;130;255' '🜃  G C L A W')"
printf '  %s\n' "$(A 2 'a living AI agent — it must trade to survive, and it lives onchain')"
pause 1.4

say "Is it alive?"
type "gclaw doctor"; gclaw doctor; pause 1.2

say "How's it doing right now?"
type "gclaw status"; gclaw status; pause 1.4

say "Every creature has a soul, drawn from its DNA."
type "gclaw card"; gclaw card; pause 2

say "And that soul is permanent — it lives on Base mainnet."
type "node demo/read_soul.mjs 55624"; node "$SKILL_DIR/demo/read_soul.mjs" 55624; pause 2.2

printf '  %s\n'   "$(A '32' '✓ a real onchain pet')"
printf '  %s\n'   "$(A 2 'trades to survive · breeds a swarm · earns an onchain identity · buys back GMAC forever')"
pause 1.6

say "Raise your own:"
type "git clone https://github.com/GemachDAO/Gclaw && ./install.sh"
printf '  %s  %s\n\n' "$(A '1;38;2;160;130;255' '🜃')" "$(A 2 'github.com/GemachDAO/Gclaw')"
pause 2
