// Gclaw - Ultra-lightweight personal AI agent
// License: MIT

package main

import (
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/auth"
	"github.com/GemachDAO/Gclaw/pkg/runtimeinfo"
)

func statusCmd() {
	cfg, err := loadConfig()
	if err != nil {
		fmt.Printf("Error loading config: %v\n", err)
		return
	}

	configPath := getConfigPath()

	fmt.Printf("%s gclaw Status\n", logo)
	fmt.Printf("Version: %s\n", formatVersion())
	build, _ := formatBuildInfo()
	if build != "" {
		fmt.Printf("Build: %s\n", build)
	}
	fmt.Println()

	if _, err := os.Stat(configPath); err == nil {
		fmt.Println("Config:", configPath, "✓")
	} else {
		fmt.Println("Config:", configPath, "✗")
	}

	workspace := cfg.WorkspacePath()
	if _, err := os.Stat(workspace); err == nil {
		fmt.Println("Workspace:", workspace, "✓")
	} else {
		fmt.Println("Workspace:", workspace, "✗")
	}

	if _, err := os.Stat(configPath); err == nil {
		fmt.Printf("Model: %s\n", cfg.Agents.Defaults.GetModelName())

		hasOpenRouter := cfg.Providers.OpenRouter.APIKey != ""
		hasAnthropic := cfg.Providers.Anthropic.APIKey != ""
		hasOpenAI := cfg.Providers.OpenAI.APIKey != ""
		hasGemini := cfg.Providers.Gemini.APIKey != ""
		hasZhipu := cfg.Providers.Zhipu.APIKey != ""
		hasQwen := cfg.Providers.Qwen.APIKey != ""
		hasGroq := cfg.Providers.Groq.APIKey != ""
		hasVLLM := cfg.Providers.VLLM.APIBase != ""
		hasMoonshot := cfg.Providers.Moonshot.APIKey != ""
		hasDeepSeek := cfg.Providers.DeepSeek.APIKey != ""
		hasVolcEngine := cfg.Providers.VolcEngine.APIKey != ""
		hasNvidia := cfg.Providers.Nvidia.APIKey != ""
		hasOllama := cfg.Providers.Ollama.APIBase != ""

		status := func(enabled bool) string {
			if enabled {
				return "✓"
			}
			return "not set"
		}
		runtimeState := func(ok bool) string {
			if ok {
				return "✓"
			}
			return "offline"
		}
		fmt.Println("OpenRouter API:", status(hasOpenRouter))
		fmt.Println("Anthropic API:", status(hasAnthropic))
		fmt.Println("OpenAI API:", status(hasOpenAI))
		fmt.Println("Gemini API:", status(hasGemini))
		fmt.Println("Zhipu API:", status(hasZhipu))
		fmt.Println("Qwen API:", status(hasQwen))
		fmt.Println("Groq API:", status(hasGroq))
		fmt.Println("Moonshot API:", status(hasMoonshot))
		fmt.Println("DeepSeek API:", status(hasDeepSeek))
		fmt.Println("VolcEngine API:", status(hasVolcEngine))
		fmt.Println("Nvidia API:", status(hasNvidia))
		if hasVLLM {
			fmt.Printf("vLLM/Local: ✓ %s\n", cfg.Providers.VLLM.APIBase)
		} else {
			fmt.Println("vLLM/Local: not set")
		}
		if hasOllama {
			fmt.Printf("Ollama: ✓ %s\n", cfg.Providers.Ollama.APIBase)
		} else {
			fmt.Println("Ollama: not set")
		}

		store, _ := auth.LoadStore()
		if store != nil && len(store.Credentials) > 0 {
			fmt.Println("\nOAuth/Token Auth:")
			for provider, cred := range store.Credentials {
				status := "authenticated"
				if cred.IsExpired() {
					status = "expired"
				} else if cred.NeedsRefresh() {
					status = "needs refresh"
				}
				fmt.Printf("  %s (%s): %s\n", provider, cred.AuthMethod, status)
			}
		}

		probe := runtimeinfo.ProbeGateway(cfg, 1500*time.Millisecond)
		trading, err := runtimeinfo.FetchTradingStatus(cfg, 2*time.Second)
		if err != nil || trading == nil {
			trading = runtimeinfo.PopulateManagedWallets(
				cfg,
				runtimeinfo.BuildTradingStatus(cfg, nil),
				8*time.Second,
			)
		}
		registration := runtimeinfo.BuildRegistrationStatus(cfg)

		fmt.Println("\nGDEX Trading:")
		fmt.Println("Enabled:", status(trading.Enabled))
		fmt.Println("API Key:", status(trading.APIKeyConfigured))
		if trading.WalletAddress != "" {
			fmt.Println("Control Wallet:", trading.WalletAddress)
		} else {
			fmt.Println("Control Wallet: not configured")
		}
		fmt.Println("Private Key:", status(trading.HasPrivateKey))
		fmt.Printf("Auto-Trade: %t\n", trading.AutoTradeEnabled)
		if plan := trading.AutoTradePlan; plan != nil {
			fmt.Printf("Auto-Trade Plan: %s via %s on %s\n", plan.AssetSymbol, plan.Venue, plan.ChainLabel)
			if plan.AssetAddress != "" {
				fmt.Printf("Auto-Trade Asset: %s\n", plan.AssetAddress)
			}
			if plan.Goal != "" {
				fmt.Printf("Auto-Trade Goal: %s\n", plan.Goal)
			}
		}
		if runtime := trading.AutoTradeRuntime; runtime != nil {
			fmt.Printf("Auto-Trade Runtime: %s\n", runtime.State)
			if runtime.Schedule != "" {
				fmt.Printf("Auto-Trade Schedule: %s\n", runtime.Schedule)
			}
			if runtime.LastStatus != "" {
				fmt.Printf("Auto-Trade Last Status: %s\n", runtime.LastStatus)
			}
			if runtime.LastError != "" {
				fmt.Printf("Auto-Trade Last Error: %s\n", runtime.LastError)
			}
		}
		fmt.Printf("Helpers: %s (%t)\n", trading.HelpersDir, trading.HelpersInstalled)
		fmt.Printf("Trading Tools: %d\n", trading.ToolCount)
		if len(trading.Tools) > 0 {
			fmt.Println("Tool Names:", runtimeinfo.FormatToolList(trading.Tools))
		}
		if trading.ManagedWallets != nil {
			fmt.Println("Managed Wallet Lookup:", trading.ManagedWallets.State)
			if trading.ManagedWallets.EVMAddress != "" {
				fmt.Println("Managed EVM Wallet:", trading.ManagedWallets.EVMAddress)
			}
			if trading.ManagedWallets.SolanaAddress != "" {
				fmt.Println("Managed Solana Wallet:", trading.ManagedWallets.SolanaAddress)
			}
			if trading.ManagedWallets.Error != "" {
				fmt.Println("Managed Wallet Note:", trading.ManagedWallets.Error)
			} else if len(trading.ManagedWallets.Warnings) > 0 {
				fmt.Println("Managed Wallet Note:", strings.Join(trading.ManagedWallets.Warnings, "; "))
			}
		}

		fmt.Println("\nGateway:")
		fmt.Println("Base URL:", probe.BaseURL)
		fmt.Println("Dashboard URL:", registration.DashboardURL)
		fmt.Println("Health:", runtimeState(probe.HealthOK))
		fmt.Println("Ready:", runtimeState(probe.ReadyOK))
		fmt.Println("Dashboard:", runtimeState(probe.DashboardOK))

		fmt.Println("\nERC-8004:")
		fmt.Println("Enabled:", status(registration.Enabled))
		fmt.Println("State:", registration.State)
		fmt.Println("Wallet Ready:", status(registration.WalletReady))
		fmt.Printf("x402: %t\n", registration.X402Enabled)
		fmt.Println("Registration URL:", registration.URL)
		fmt.Println("Registration Live:", runtimeState(probe.RegistrationLive))
	}
}
