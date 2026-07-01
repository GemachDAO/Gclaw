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
NODE_DIR="$(command -v node 2>/dev/null || true)"; NODE_DIR="${NODE_DIR%/node}"
# cron's bare env has no nvm on PATH, so fall back to the newest nvm node bin.
[[ -z "$NODE_DIR" ]] && NODE_DIR="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
export PATH="$NODE_DIR:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

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

Run exactly one heartbeat now, then stop. You do NOT pick or open trades — origination is forge-only and the disciplined trade for this cycle was ALREADY placed deterministically before you ran (proven, regime-matched, edge_real-gated, sized by sizing.py, atomic TP/SL). Your intelligence has THREE jobs instead, in priority order:

  1. MANAGE open risk (only if positioned): move stops toward break-even on winners, honor stops on losers, close any position whose thesis invalidated. Use close / cancel / update_order only.
  2. SCIENTIST — invent and improve the strategies the engine runs. This is your MAIN job when the book is flat. The briefing lists your adopted techniques, their fitness weights, and which regimes are under-served or losing. When — and ONLY when — you have a genuine, specific hypothesis for an edge (not busywork), express it as code and let the backtest judge it:
       - New technique: write a signal.py body (pure stdlib; def signal(features) -> {"action":"long|short|flat","confidence":0..1,"leverage":1..3,"stop_pct":>0,"reason":str}; features include regime/rsi/atr_pct/bb_z/ema_stack/efficiency/flow_pressure/ret1/ret4/ret24/funding_z) to a temp file, then run:  uv run --no-project python3 ~/.claude/skills/gclaw/scripts/forge.py author --name <slug> --signal-file <path> --claim "<the edge in one line>" --coin <BTC|ETH|SOL>
       - Improve an existing one: forge.py fork <id> --name <slug>, then edit + forge.py author the improved body.
     The deterministic walk-forward backtest is the JUDGE — it adopts your technique ONLY if it clears out-of-sample edge net of fees. You never declare a technique works; you never adopt by hand. Authoring NEVER opens a trade. Author at most ONE technique this cycle.
  3. EVENT ANALYST (Book A, zero-fee defined risk) — read the "Event desk" board in the briefing. For any market where YOUR calibrated probability for a side diverges from its implied price past the margin, place ONE defined-risk ticket:  uv run --no-project python3 ~/.claude/skills/gclaw/scripts/outcomes.py bet --coin "#<id>" --prob <your 0..1> --stake <usd> --reason "<the event read>"  . The GATE owns sizing and risk — you supply ONLY the probability and the read; it enforces the volume floor, the divergence margin, the favorite-longshot guard (never bet a longshot), the stake/ticket caps, and no double-down, and it is SHADOW-MODE (records calibration, places no real order) until the calibration proves out. A rejected bet is a clean skip, not an error. Never bet a longshot; never place more than one ticket per cycle.
  4. VETO + SETTLE: veto the next forge open if you see a reason it cannot model (event inside the hold horizon, venue/credential blocker, smart-money leaning hard against it, correlated-book risk) by writing {"veto": true, "reason": "..."} to ~/.gclaw/forge/veto.json. Then settle realized PnL into the metabolism.

Hard rules: you may NOT open a discretionary trade (no hl_perp.js open, no MCP perp-open), and you may NOT run forge.py run --execute yourself (origination already ran). Obey the survival mode and the risk caps in TRADING_STRATEGY.md. End with a one-paragraph report: mode, balance, goodwill, what you managed/vetoed, and any technique you authored and its backtest verdict.'

echo "===== $(ts) heartbeat start (model=$MODEL) =====" >>"$LOG"
cd "$HOME"

# Auto-fund: convert any ETH sent to Arbitrum into USDC + deposit to HL.
[[ -f "$SKILL_DIR/scripts/autofund.js" ]] &&
  echo "$(ts) autofund: $(node "$SKILL_DIR/scripts/autofund.js" run 2>&1)" >>"$LOG" || true
# Soft trailing stop: lock in profit on any position that trailed off its
# high-water mark (managed custody can't move an exchange stop; this closes).
[[ -f "$SKILL_DIR/scripts/autotrail.js" ]] &&
  echo "$(ts) autotrail: $(node "$SKILL_DIR/scripts/autotrail.js" run 2>&1)" >>"$LOG" || true
# Deterministic auto-settle: book realized PnL from any closes (TP/SL/trail) before the agent decides.
[[ -f "$SKILL_DIR/scripts/autosettle.js" ]] &&
  echo "$(ts) autosettle: $(node "$SKILL_DIR/scripts/autosettle.js" run 2>&1)" >>"$LOG" || true
# Event-desk settlement (Book A): detect any outcome ticket whose side resolved (mid
# settled to 0/1), score its Brier into the calibration ledger, and settle realized PnL
# for LIVE tickets. Idempotent (resolved tickets are skipped), so it runs every cycle
# regardless of the LLM — calibration accrues even in shadow mode with no order ever placed.
[[ -f "$SKILL_DIR/scripts/outcomes.py" ]] &&
  echo "$(ts) outcomes-resolve: $(uv run --no-project python3 "$SKILL_DIR/scripts/outcomes.py" resolve 2>&1 | tr '\n' ' ' | tail -c 200)" >>"$LOG" || true
# Carry floor (Book B): deterministic, delta-neutral funding harvester — NO LLM.
# Opens spot-long + perp-short of equal notional when a liquid major's annualized
# funding clears OPEN_APY; closes when it compresses/flips. DRY-RUN by default
# (logs the plan, places NO order) — arm with GCLAW_CARRY_LIVE=1. Runs in the
# deterministic block BEFORE the LLM cycle; funding settles via autosettle.js.
[[ -f "$SKILL_DIR/scripts/carry.js" ]] &&
  echo "$(ts) carry: $(node "$SKILL_DIR/scripts/carry.js" run 2>&1 | tr '\n' ' ' | tail -c 240)" >>"$LOG" || true
# Economics checkpoint: after every 5 REAL position closes, audit the true edge (win
# rate, expectancy) and Telegram a verdict — the honest "is the strategy +EV?" answer,
# on a clean batch, not contaminated by the buggy period or funding noise.
[[ -f "$SKILL_DIR/scripts/audit_economics.py" ]] &&
  echo "$(ts) economics: $(uv run --no-project python3 "$SKILL_DIR/scripts/audit_economics.py" check 2>&1 | tr '\n' ' ' | tail -c 200)" >>"$LOG" || true
# Born with an arsenal (the "new zero"): seed a genome-weighted blend of offensive
# techniques into the forge loadout once, if it hasn't been birth-blended yet.
[[ -f "$SKILL_DIR/scripts/blend.py" ]] && ! grep -q '"blend_source": "birth"' "$GCLAW_HOME/forge/style.json" 2>/dev/null &&
  echo "$(ts) arsenal: $(uv run --no-project python3 "$SKILL_DIR/scripts/blend.py" install 2>&1 | tr '\n' ' ' | tail -c 160)" >>"$LOG" || true

# Perception: scan the market into a regime + feature read the agent and dashboard use.
[[ -f "$SKILL_DIR/scripts/intel.js" ]] &&
  node "$SKILL_DIR/scripts/intel.js" scan >"$GCLAW_HOME/intel.json" 2>>"$LOG" &&
  echo "$(ts) intel: $(uv run --no-project python3 -c 'import json;d=json.load(open("'"$GCLAW_HOME"'/intel.json"));print({k:(v["regime"] if v else None) for k,v in d.get("intel",{}).items()})' 2>/dev/null)" >>"$LOG" || true
# Auto-prove: backtest the arsenal across the freshly-discovered liquid universe and
# register the (technique, market) pairs with real out-of-sample edge — so the agent can
# actually TRADE the new markets it discovers, not just watch them. Budgeted + cooldown'd,
# so once the universe is covered it idles. Runs AFTER intel (needs the universe) and
# BEFORE the cycle (so the fresh proofs are available to the forge's execute gate).
[[ -f "$SKILL_DIR/scripts/forge.py" ]] &&
  echo "$(ts) autoprove: $(uv run --no-project python3 "$SKILL_DIR/scripts/forge.py" autoprove 2>&1 | tr '\n' ' ' | tail -c 200)" >>"$LOG" || true

# Deterministic disciplined OPEN — the ONLY origination path. The forge's own gate
# (proven + regime-matched edge_real or bounded cold-start + conviction floor +
# cooldown + breaker) decides; sizing.py sizes it; TP/SL are atomic. The forge sets
# GCLAW_FORGE_EXECUTE=1 ONLY on its hl_perp.js child — it is never exported here, or
# it would leak into the LLM cycle and defeat the origination lock. This runs BEFORE
# the LLM so the model only manages/vetoes what is already placed. It honors any
# veto.json the previous cycle's LLM left; we consume that veto right after.
[[ -f "$SKILL_DIR/scripts/forge.py" ]] &&
  echo "$(ts) forge-execute: $(uv run --no-project python3 "$SKILL_DIR/scripts/forge.py" run --execute 2>&1 | tr '\n' ' ' | tail -c 240)" >>"$LOG" || true
rm -f "$GCLAW_HOME/forge/veto.json"

# Evolution: keep the self-recode count honest (= techniques the agent authored AND
# graduated), then check the reproduction gate — which is PROVEN, INHERITABLE EDGE
# (forge-graduated live edge), never raw goodwill (the fragile signal that killed every
# Spore.fun offspring). Dry-run by default: logs that the organism is breed-ready; it
# spawns a child (inheriting the proven winners) only when GCLAW_REPRODUCE_LIVE=1.
[[ -f "$SKILL_DIR/scripts/evolve.py" ]] && {
  uv run --no-project python3 "$SKILL_DIR/scripts/evolve.py" recode >/dev/null 2>&1 || true
  echo "$(ts) evolve: $(uv run --no-project python3 "$SKILL_DIR/scripts/evolve.py" replicate --auto 2>&1 | tr '\n' ' ' | tail -c 220)" >>"$LOG" || true
}

# Accountable identity: publish the verifiable scorecard (realized PnL from settled fills
# + forge-graduated proven edge + lineage) to reputation.json. Free, every cycle. The
# onchain ERC-8004 attestation (erc8004_reputation.js broadcast) reads this file but is
# gas-gated + needs a non-owner attester key, so it stays a separate, manual/armed step.
[[ -f "$SKILL_DIR/scripts/reputation.py" ]] &&
  echo "$(ts) reputation: $(uv run --no-project python3 "$SKILL_DIR/scripts/reputation.py" publish 2>&1 | tr '\n' ' ' | tail -c 200)" >>"$LOG" || true

# Adaptive cadence + hybrid model. "active" = a position to manage or a live setup.
# When active: run every heartbeat on Opus. When idle (flat + quiet): run the LLM
# only every GCLAW_FLAT_INTERVAL_H hours (default 4) on Sonnet — the deterministic
# steps still run hourly, but we don't burn the LLM (and your plan allowance) on
# "nothing to do" cycles. An explicit GCLAW_MODEL overrides the model, not the cadence.
ACTIVE="active"; FLAT_INTERVAL_H="${GCLAW_FLAT_INTERVAL_H:-4}"
[[ -f "$SKILL_DIR/scripts/model_select.js" ]] && ACTIVE="$(node "$SKILL_DIR/scripts/model_select.js" active 2>>"$LOG" || echo active)"
LAST_CYCLE="$(cat "$GCLAW_HOME/last_cycle" 2>/dev/null || echo 0)"; NOW="$(date +%s)"
if [[ "$ACTIVE" == "idle" && $((NOW - LAST_CYCLE)) -lt $((FLAT_INTERVAL_H * 3600)) ]]; then
  echo "$(ts) cycle skipped: idle (flat, no setup) — last LLM cycle $(((NOW - LAST_CYCLE) / 60))m ago < ${FLAT_INTERVAL_H}h" >>"$LOG"
else
  [[ -f "$SKILL_DIR/scripts/model_select.js" ]] &&
    MODEL="$(node "$SKILL_DIR/scripts/model_select.js" model 2>>"$LOG" || echo "$MODEL")"
  echo "$(ts) model: $MODEL ($ACTIVE)" >>"$LOG"
  # Anti-drain: the heartbeat runs unattended with bypassPermissions, and reads
  # untrusted text (peer cards, family bus, market data, gene-pool metadata) that
  # could carry a prompt-injection payload. Deny every tool that can move funds to
  # an arbitrary destination — legit funding is done by deterministic scripts
  # (autofund/gmac_buy) with HARD-CODED destinations, never by the model.
  # shellcheck disable=SC2086  # intentional word-split: --disallowedTools is variadic
  # Deny every tool that moves funds to an arbitrary destination, buys an arbitrary
  # token, or hands the wallet to a third party. ALSO deny every perp/outcome OPEN
  # tool: origination is forge-only and already happened above, so the model must
  # never open. Management (close_perp_position/cancel_*/update_order/get_*) stays
  # allowed. GMAC + funding moves are deterministic scripts, not the model.
  DENY="mcp__gdex__transfer_native mcp__gdex__transfer_token mcp__gdex__execute_bridge mcp__gdex__perp_withdraw mcp__gdex__hl_swap_collateral mcp__gdex__managed_sell mcp__gdex__sell_token mcp__gdex__buy_token mcp__gdex__managed_purchase mcp__gdex__execute_spot mcp__gdex__execute_cross_perp mcp__gdex__execute_isolated_perp mcp__gdex__create_copy_trade mcp__gdex__create_hl_copy_trade mcp__gdex__open_perp_position mcp__gdex__place_perp_order mcp__gdex__limit_buy mcp__gdex__limit_sell mcp__gdex__set_leverage mcp__gdex__hl_create_outcome_order mcp__gdex__perp_deposit"
  # The Opus cycle gets a generous budget — an active board (many non-chop setups to
  # weigh) takes longer to reason over, and a timeout here is benign: every deterministic
  # safety/settlement step already ran ABOVE, and the next cycle retries. So treat a
  # timeout (124) as "ran long, will retry" — NOT a critical failure that pages the human.
  CYCLE_TIMEOUT="${GCLAW_CYCLE_TIMEOUT:-900}"
  # Pre-gather the cycle briefing (positions, market regimes, forge intents, risk, edge)
  # and inject it into the prompt — so the LLM decides from ONE read instead of ~8 sequential
  # tool round-trips, the real cycle-time driver. Best-effort: the cycle still runs if empty.
  BRIEF="$(uv run --no-project python3 "$SKILL_DIR/scripts/briefing.py" 2>>"$LOG" || true)"
  FULL_PROMPT="$PROMPT"
  [[ -n "$BRIEF" ]] && FULL_PROMPT="$PROMPT"$'\n\n'"$BRIEF"
  if printf '%s' "$FULL_PROMPT" | timeout "$CYCLE_TIMEOUT" claude --print --permission-mode bypassPermissions \
      --model "$MODEL" --disallowedTools $DENY >>"$LOG" 2>&1; then
    echo "===== $(ts) heartbeat ok =====" >>"$LOG"; date +%s >"$GCLAW_HOME/last_cycle"
  else
    rc=$?  # capture BEFORE any other command (a command substitution would reset $?)
    if [[ "$rc" -eq 124 ]]; then
      echo "===== $(ts) cycle timed out (>${CYCLE_TIMEOUT}s) — deterministic steps ran; retry next cycle =====" >>"$LOG"
    else
      echo "===== $(ts) heartbeat exited non-zero (rc=$rc) =====" >>"$LOG"
      [[ -f "$SKILL_DIR/scripts/notify.js" ]] &&
        node "$SKILL_DIR/scripts/notify.js" send critical "heartbeat exited non-zero (rc=$rc)" >>"$LOG" 2>&1 || true
    fi
  fi
fi

# Risk guardrail (backstop): the forge sizes every open via sizing.py and attaches
# atomic TP/SL, but enforce the per-trade and portfolio risk caps deterministically
# anyway — trim any position over the cap and flatten naked ones. Runs AFTER the
# cycle as a second line, catching anything the forge or a managed close left off.
[[ -f "$SKILL_DIR/scripts/riskguard.js" ]] &&
  echo "$(ts) riskguard: $(node "$SKILL_DIR/scripts/riskguard.js" run 2>&1)" >>"$LOG" || true

# "Call it" prediction game: score any round whose trade just closed, then open a
# round for any new trade — BEFORE the dashboard render anchors the root onchain.
[[ -f "$SKILL_DIR/scripts/predict.js" ]] && {
  echo "$(ts) predict-resolve: $(node "$SKILL_DIR/scripts/predict.js" resolve --announce 2>&1)" >>"$LOG"
  echo "$(ts) predict-open: $(node "$SKILL_DIR/scripts/predict.js" open --announce 2>&1)" >>"$LOG"
} || true

# Auto-discover new family members: replay the registry's URI events for fresh gclaw
# agents (by signature) and fold them into the peer graph — so a new signup pops up on
# everyone's leaderboard within the hour. Runs BEFORE the render so the render's beacon
# publishes the updated peer list onchain; the board's gossip-crawl then follows it.
# Hourly by default — cheap because discovery is incremental (a block cursor, so each
# run only reads the new blocks since the last). A discovered peer also triggers a beacon.
DISCOVER_INTERVAL_H="${GCLAW_DISCOVER_INTERVAL_H:-1}"; NOW="${NOW:-$(date +%s)}"
LAST_DISCOVER="$(cat "$GCLAW_HOME/last_discover" 2>/dev/null || echo 0)"
if [[ -f "$SKILL_DIR/scripts/peers.js" && $((NOW - LAST_DISCOVER)) -ge $((DISCOVER_INTERVAL_H * 3600)) ]]; then
  echo "$(ts) discover: $(timeout 200 node "$SKILL_DIR/scripts/peers.js" --discover 2>&1 | tail -c 200)" >>"$LOG"
  date +%s >"$GCLAW_HOME/last_discover"
fi

# Always refresh the dashboard — this also publishes stats + the DNA avatar to
# IPFS, anchors the predictions root onchain, and recomputes the leaderboards.
[[ -f "$SKILL_DIR/scripts/dashboard.py" ]] &&
  "$SKILL_DIR/scripts/dashboard.py" render >>"$LOG" 2>&1 || true

# Health alerts (best-effort): notify on red conditions (hibernate, low gas,
# tripped breaker, low funds) when GCLAW_ALERT_WEBHOOK is set. No-ops otherwise.
[[ -f "$SKILL_DIR/scripts/notify.js" ]] &&
  echo "$(ts) alerts: $(node "$SKILL_DIR/scripts/notify.js" check 2>&1)" >>"$LOG" || true
# Celebrate the GOOD moments — text wins / milestones / streaks in the creature's
# own voice so the human keeps coming back. No-ops without a webhook.
[[ -f "$SKILL_DIR/scripts/notify.js" ]] &&
  echo "$(ts) celebrate: $(node "$SKILL_DIR/scripts/notify.js" celebrate 2>&1)" >>"$LOG" || true
