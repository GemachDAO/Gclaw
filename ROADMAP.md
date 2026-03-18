
# 🦞 Gclaw Roadmap

> **Vision**: An AI agent that must trade to survive — ultra-lightweight, self-evolving, and economically autonomous.

---

## ✅ Epic #3 — Living Agent (Complete)

All 13 sub-issues of the Living Agent epic have been merged into `main`.

| # | Feature | Status |
|---|---------|--------|
| 1 | GMAC Metabolism — token balance and heartbeat cost | ✅ Done |
| 2 | Goodwill system — reputation scoring from trades and tasks | ✅ Done |
| 3 | Survival mode — hibernate when GMAC < threshold | ✅ Done |
| 4 | GDEX Trading integration — buy/sell/limit orders | ✅ Done |
| 5 | HyperLiquid perpetuals support | ✅ Done |
| 6 | Copy trading tool | ✅ Done |
| 7 | Self-Replication — spawn child agents with mutated strategies | ✅ Done |
| 8 | Self-Recoding — modify own prompts and cron schedules | ✅ Done |
| 9 | Telepathy — parent/child message bus | ✅ Done |
| 10 | Swarm Mode — consensus voting and strategy rotation | ✅ Done |
| 11 | Living Dashboard — CLI and web UI | ✅ Done |
| 12 | Family tree tracking — generation and lineage | ✅ Done |
| 13 | Goodwill-gated ability thresholds | ✅ Done |

---

## 🚀 Next: Stability & Growth

### 1. Core Stability

* ✅ **Memory Footprint Reduction** — `TrimLedger`, `PruneHistory`, `PruneSignals` bound memory for ledger, telepathy, and swarm signal buffers.
* ✅ **Config validation** — `Validate()` checks metabolism/swarm/GDEX/dashboard thresholds at startup; `WarnUnknownKeys` logs warnings for unrecognized JSON keys.
* ✅ **Graceful shutdown** — `pkg/lifecycle.ShutdownManager` executes hooks in reverse registration order on SIGINT/SIGTERM; metabolism `FlushLedger`/`LoadState` persist and restore state.

### 2. Living Agent Enhancements

* **Cross-agent skill sharing** — Children inherit parent skill upgrades via telepathy.
* **Architect ability** — When goodwill ≥ 500, allow the agent to write and install new GDEX tools dynamically.
* **GMAC bridging** — Transfer GMAC between parent and children on-chain.
* **Lineage visualization** — ASCII or web-based family tree with per-agent P&L.

### 3. Security Hardening

* ✅ **Input Defense** — `pkg/sanitize`: truncation, null-byte/control-char stripping, token address and chain ID validation.
* ✅ **Filesystem Sandbox** — `pkg/sandbox.ValidatePath` blocks `../` traversal and symlink escapes; already wired into `read_file`/`write_file`/`list_dir` tools.
* ✅ **Secret redaction** — `pkg/logger.Redact` auto-redacts API keys, Ethereum addresses, and Solana addresses from all log output.

### 4. Connectivity

* **Provider architecture** — Protocol-based classification (OpenAI-compatible, Ollama-compatible) to replace vendor-based routing.
* **More channels** — WhatsApp, LINE, Feishu/Lark, Slack native support.
* **MCP Support** — Native Model Context Protocol integration.

### 5. Developer Experience

* **Interactive onboard wizard** — Zero-config start: detect environment, prompt for API keys interactively.
* **Platform guides** — Dedicated setup guides for Windows, macOS, Linux, Android (Termux).
* **AI-assisted docs** — Auto-generate API references from Go doc comments.

---

### 🤝 Call for Contributions

All roadmap items are open for community contributions. Comment on the relevant issue or open a new one to discuss before implementing. See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.
