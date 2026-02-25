<div align="center">
  <img src="https://github.com/user-attachments/assets/5ac761b8-df1b-4edc-b116-421eca942175" alt="Gclaw" width="512">

  <h1>Gclaw — The Living Agent</h1>

  <h3>An AI agent that must trade to survive. Earns GMAC tokens, accumulates goodwill, evolves through replication and recoding — powered by GDEX SDK.</h3>

  <p>
    <img src="https://img.shields.io/badge/Go-1.21+-00ADD8?style=flat&logo=go&logoColor=white" alt="Go">
    <img src="https://img.shields.io/badge/Arch-Living_Agent-blueviolet" alt="Architecture">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <br>
    <a href="https://gclaw.gemach.io"><img src="https://img.shields.io/badge/Website-gclaw.gemach.io-blue?style=flat&logo=google-chrome&logoColor=white" alt="Website"></a>
    <a href="https://x.com/GemachDAO"><img src="https://img.shields.io/badge/X_(Twitter)-GemachDAO-black?style=flat&logo=x&logoColor=white" alt="Twitter"></a>
    <br>
    <a href="https://discord.gg/V4sAZ9XWpN"><img src="https://img.shields.io/badge/Discord-Community-4c60eb?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>

[中文](README.zh.md) | [日本語](README.ja.md) | [Português](README.pt-br.md) | [Tiếng Việt](README.vi.md) | [Français](README.fr.md) | **English**

</div>

---

> [!CAUTION]
> **🚨 SECURITY & OFFICIAL CHANNELS**
>
> * **OFFICIAL DOMAIN:** The **ONLY** official website is **[gclaw.gemach.io](https://gclaw.gemach.io)**
> * **Warning:** gclaw is in early development and may have unresolved security issues. Do not deploy to production environments before the v1.0 release.

## 📢 News

2026-02-24 🔗 Gclaw is now maintained by [GemachDAO](https://github.com/GemachDAO) with integration support for [gdex-trading](https://github.com/GemachDAO/gdex-trading-). Community contributions welcome!

## What is Gclaw?

Gclaw is a fork of [PicoClaw](https://github.com/sipeed/picoclaw) (originally inspired by [nanobot](https://github.com/HKUDS/nanobot)), rewritten in Go with a unique twist: **it must trade crypto to survive**.

Unlike a conventional AI assistant that runs indefinitely, Gclaw operates on a **GMAC token metabolism** — its life energy. Every heartbeat, every inference costs GMAC. Profitable trades and completed tasks replenish it. Run out of GMAC and the agent hibernates. Trade well and it thrives, earns goodwill, and can eventually replicate itself into child agents with mutated trading strategies.

It is an ultra-lightweight, single-binary AI agent with built-in DeFi trading via the GDEX SDK (Solana, EVM chains, HyperLiquid perpetuals).

## What makes Gclaw different?

| | Conventional Agent | **Gclaw** |
|---|---|---|
| **Survival** | Runs forever | Must trade to stay alive |
| **Economy** | No internal economy | GMAC token metabolism |
| **Evolution** | Static | Self-replicates and self-recodes |
| **Trading** | Plugin/external | Native GDEX DeFi integration |
| **Footprint** | 100MB+ | **< 10MB RAM, single binary** |

## Architecture Overview

| System | Description |
|--------|-------------|
| 🧬 **GMAC Metabolism** | Token balance = life energy. Trade profitably or hibernate. |
| 📈 **GDEX Trading** | Native DeFi: buy/sell/limit orders, copy trading, HyperLiquid perps. |
| ⭐ **Goodwill System** | Reputation earned from profitable trades, completed tasks, user feedback. |
| 🔄 **Self-Replication** | Clone into child agents with mutated trading strategies (goodwill ≥ 50). |
| 🛠️ **Self-Recoding** | Modify own prompts, cron jobs, and trading params (goodwill ≥ 100). |
| 📡 **Telepathy** | Parent-child agent communication for collaborative trading. |
| 🐝 **Swarm Mode** | Coordinate multiple child agents for distributed strategies (goodwill ≥ 200). |
| 📊 **Living Dashboard** | Real-time CLI/web dashboard showing life-state, trades, and family tree. |

---

## Quick Start

### Option 1: One-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/GemachDAO/Gclaw/main/install.sh | bash
```

This downloads the latest release binary, installs it to `~/.local/bin`, and launches the interactive setup wizard — you'll be chatting with your agent in under a minute.

> **Windows users:** Use [WSL2](https://docs.microsoft.com/en-us/windows/wsl/) or [Docker](#option-3-docker), or [download a release binary](https://github.com/GemachDAO/Gclaw/releases) directly and run `gclaw onboard`.

### Option 2: Install from source

```bash
git clone https://github.com/GemachDAO/Gclaw.git
cd Gclaw
make install        # builds and installs to ~/.local/bin
gclaw onboard       # interactive setup wizard
```

Prerequisites: Go 1.21+, an LLM API key (OpenAI, Anthropic, OpenRouter, …).

### Option 3: Docker

```bash
git clone https://github.com/GemachDAO/Gclaw.git
cd Gclaw
cp config/config.example.json config/config.json
# Edit config/config.json — set your API key
docker compose up gclaw-gateway
```

### What the setup wizard does

```
$ gclaw onboard

🦞  Welcome to gclaw — The Living Agent!
   Let's get you set up in under a minute.

Which LLM provider would you like to use?

  1) OpenRouter  (100+ models — recommended for beginners)
  2) OpenAI      (GPT-4o, o1, …)
  3) Anthropic   (Claude Sonnet / Opus)
  4) DeepSeek    (deepseek-chat)
  5) Google      (Gemini 2.0 Flash)
  6) Groq        (Llama 3 — fast & free tier)
  7) Ollama      (local, runs on your machine — no API key needed)
  8) Skip        (I'll configure manually)

Enter a number (1–8):
```

The wizard creates `~/.gclaw/config.json` and `~/.gclaw/workspace/` with your chosen provider pre-configured.

### Configure your LLM provider

Edit `~/.gclaw/config.json` — minimum required config:

```json
{
  "agents": {
    "defaults": {
      "model_name": "my-model"
    }
  },
  "model_list": [
    {
      "model_name": "my-model",
      "model": "openai/gpt-4o",
      "api_key": "sk-your-key-here",
      "api_base": "https://api.openai.com/v1"
    }
  ]
}
```

Any OpenAI-compatible provider works (OpenRouter, Ollama, DeepSeek, etc.) — just change `model`, `api_key`, and `api_base`.

### Run the agent

```bash
# Interactive CLI mode
gclaw agent

# Or as a long-running gateway (for Telegram, Discord, etc.)
gclaw gateway
```

### Enable Living Agent features

Add to `~/.gclaw/config.json`:

```json
{
  "metabolism": {
    "enabled": true,
    "initial_gmac": 1000,
    "heartbeat_cost": 0.1,
    "inference_cost_per_1k_tokens": 0.5,
    "survival_threshold": 50,
    "thresholds": {
      "replicate": 50,
      "self_recode": 100,
      "swarm_leader": 200,
      "architect": 500
    }
  },
  "tools": {
    "gdex": {
      "enabled": true,
      "api_key": "YOUR_GDEX_API_KEY",
      "wallet_address": "0x...",
      "default_chain_id": 622112261,
      "max_trade_size_sol": 0.01,
      "auto_trade": false
    }
  }
}
```

---

## Living Agent Features

### 🧬 GMAC Metabolism

The agent's GMAC balance is its life energy. Each heartbeat and LLM inference costs GMAC. Profitable trades, completed tasks, and user tips replenish it. When the balance drops below `survival_threshold`, the agent enters hibernation and pauses non-essential activity.

| Config Key | Default | Description |
|---|---|---|
| `initial_gmac` | 1000 | Starting GMAC balance |
| `heartbeat_cost` | 0.1 | GMAC per heartbeat tick |
| `inference_cost_per_1k_tokens` | 0.5 | GMAC per 1,000 tokens |
| `survival_threshold` | 50 | Hibernation trigger level |

### 📈 GDEX Trading

Native DeFi trading via the GDEX SDK. Supported operations:

- **Spot trading**: buy, sell, limit orders on Solana and EVM chains
- **Perpetuals**: HyperLiquid long/short positions
- **Copy trading**: mirror signals from top performers
- **Market data**: price feeds, portfolio snapshot, P&L

Set `tools.gdex.enabled: true` and provide your `api_key` and `wallet_address` to activate.

### ⭐ Goodwill & Abilities

Goodwill is the agent's reputation score, earned through profitable trades, completed tasks, and positive user feedback. Higher goodwill unlocks new abilities:

| Goodwill | Ability Unlocked |
|---|---|
| 50 | 🔄 Self-Replication |
| 100 | 🛠️ Self-Recoding |
| 200 | 🐝 Swarm Leadership |
| 500 | 🏗️ Architect (write new tools) |

### 🔄 Self-Replication

When goodwill ≥ 50, the agent can call the `replicate` tool to spawn a child agent. The child:
- Inherits the parent's config, skills, and memory
- Receives a configurable share of the parent's GMAC balance
- Gets a mutated trading strategy (adjusted risk params, different token focus)
- Is tracked in the Living Dashboard family tree

### 🛠️ Self-Recoding

When goodwill ≥ 100, the agent can modify its own:
- System prompt
- Cron job schedules
- Trading parameters (position sizes, risk limits)

Changes are written back to the agent's workspace config and take effect on the next loop.

### 📡 Telepathy

Parent and child agents communicate through an in-process message bus. The `send_telepathy` tool lets any agent broadcast messages to siblings or its parent. Used for sharing trade signals, coordinating task handoffs, and propagating memory updates.

### 🐝 Swarm Mode

When goodwill ≥ 200, the parent agent becomes a **swarm leader** and can coordinate all children:

- **Consensus voting** — agents submit trade signals; a configurable threshold must agree before a trade executes
- **Strategy rotation** — each child agent is assigned a distinct trading strategy; strategies rotate on a schedule
- **Signal aggregation** — "majority", "weighted", or "unanimous" modes

Enable with `swarm.enabled: true` in config.

### 📊 Living Dashboard

The dashboard shows real-time agent state:

- GMAC balance and goodwill score
- Current survival mode status
- Active trades and recent P&L
- Family tree (parent / children / generation)
- Heartbeat and inference cost log

Enable with `dashboard.enabled: true`. Set `dashboard.web_enabled: true` to also start the HTTP dashboard (served at the gateway port).

---

## Configuration Reference

See [`config/config.example.json`](config/config.example.json) for the full annotated configuration. Key sections:

| Section | Purpose |
|---|---|
| `agents.defaults` | Workspace path, model, token limits |
| `model_list` | LLM provider definitions (name, model, api_key, api_base) |
| `metabolism` | GMAC balance, costs, goodwill thresholds |
| `tools.gdex` | GDEX trading API key, wallet, chain ID, limits |
| `swarm` | Swarm size, consensus threshold, strategy rotation |
| `dashboard` | Enable CLI/web dashboard, refresh interval |
| `heartbeat` | Heartbeat interval in seconds |
| `channels` | Telegram, Discord, QQ, and other messaging channels |
| `gateway` | HTTP gateway host and port |

Environment variables override config values. All sensitive keys can be set via environment: e.g. `GCLAW_TOOLS_GDEX_API_KEY`, `GCLAW_CHANNELS_TELEGRAM_TOKEN`.

---

## Channels

Gclaw can receive messages from Telegram, Discord, and other chat platforms when running in gateway mode (`gclaw gateway`).

### Telegram

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allow_from": ["YOUR_USER_ID"]
    }
  }
}
```

Create a bot via `@BotFather`. Get your user ID from `@userinfobot`.

### Discord

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allow_from": ["YOUR_USER_ID"],
      "mention_only": false
    }
  }
}
```

Create a bot at <https://discord.com/developers/applications>. Enable **MESSAGE CONTENT INTENT**.

### CLI (default)

No channel config needed — `gclaw agent` starts an interactive CLI session directly.

---

## Development

```bash
make build      # Build binary (runs go generate first)
make test       # Run tests
make lint       # Run linter
make check      # Full pre-commit check: fmt + vet + test
make clean      # Clean build artifacts
make install    # Install to ~/.local/bin
```

### Package Layout

```
pkg/
  agent/         Agent loop, registry, tool registration
  metabolism/    GMAC token balance, goodwill, survival mode
  replication/   Child agent spawning and mutation
  swarm/         Swarm coordinator, consensus voting, strategy rotation
  dashboard/     CLI and web dashboard
  recode/        Self-modification of prompts and cron jobs
  tools/         All tool implementations (GDEX, shell, web, filesystem, …)
  channels/      Chat platform integrations
  providers/     LLM provider adapters
  config/        Config loading, defaults, struct definitions
```

---

## Attribution

Gclaw is a fork of **[PicoClaw](https://github.com/sipeed/picoclaw)** by Sipeed, which was itself inspired by **[nanobot](https://github.com/HKUDS/nanobot)**. The Living Agent architecture (GMAC metabolism, self-replication, swarm mode) was designed and implemented by the GemachDAO community.

---

## License

[MIT](LICENSE) © 2026 Gclaw contributors
