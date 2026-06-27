#!/usr/bin/env bash
# Run a command under a rootless bubblewrap namespace with Gclaw's wallet and secret
# files masked and secret env vars stripped — so a prompt-injection in the agentic cycle
# can't read the control private key or API tokens even via arbitrary shell. The
# deterministic steps that NEED those secrets (sign-in, funding, settlement) run OUTSIDE
# this wrapper; the cycle trades only through the ephemeral GCLAW_SESSION injected by the
# heartbeat. Used only when GCLAW_SANDBOX=1.
#
# Scope: this masks the money secrets. It does NOT yet isolate network egress, so it is
# defense-in-depth (key containment), not full exfiltration prevention. See bd assune-367.
#
#   sandbox_cycle.sh <cmd> [args...]
set -euo pipefail

command -v bwrap >/dev/null 2>&1 || {
  echo "sandbox_cycle: bwrap not found — install bubblewrap or unset GCLAW_SANDBOX" >&2
  exit 127
}

WALLET="${GCLAW_WALLET:-$HOME/gdex-test-wallet.json}"
HOME_DIR="${GCLAW_HOME:-$HOME/.gclaw}"

args=(--dev-bind / / --proc /proc --tmpfs /tmp --die-with-parent)
# Mask each secret FILE that exists by binding /dev/null over it (reads return empty).
for f in "$WALLET" "$HOME_DIR/wallet.json" "$HOME_DIR/env"; do
  [[ -e "$f" ]] && args+=(--ro-bind /dev/null "$f")
done
# Strip secret ENV VARS the heartbeat sourced into its own environment upstream
# (GCLAW_SESSION is intentionally kept — it is how the cycle trades).
for v in PINATA_JWT GCLAW_TELEGRAM_TOKEN GCLAW_TELEGRAM_CHAT GDEX_API_KEY GCLAW_ATTESTER_KEY; do
  args+=(--unsetenv "$v")
done

exec bwrap "${args[@]}" -- "$@"
