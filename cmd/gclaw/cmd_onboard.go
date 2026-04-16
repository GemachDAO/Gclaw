// Gclaw - Ultra-lightweight personal AI agent
// License: MIT

package main

import (
	"bufio"
	"embed"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/config"
)

//go:generate cp -r ../../workspace .
//go:embed workspace
var embeddedFiles embed.FS

// providerOption describes a selectable LLM provider during onboarding.
type providerOption struct {
	label     string // display name shown in the menu
	modelName string // key used in model_list and agents.defaults.model_name
	keyURL    string // URL where the user can obtain an API key (empty = no key needed)
	isLocal   bool   // true for local providers that need no API key
}

// onboardProviders is the ordered list of providers shown during interactive setup.
var onboardProviders = []providerOption{
	{
		label:     "OpenRouter  (100+ models — recommended for beginners)",
		modelName: "openrouter-auto",
		keyURL:    "https://openrouter.ai/keys",
	},
	{
		label:     "OpenAI      (GPT-4o, o1, …)",
		modelName: "gpt-5.2",
		keyURL:    "https://platform.openai.com/api-keys",
	},
	{
		label:     "Anthropic   (Claude Sonnet / Opus)",
		modelName: "claude-sonnet-4.6",
		keyURL:    "https://console.anthropic.com/settings/keys",
	},
	{
		label:     "DeepSeek    (deepseek-chat)",
		modelName: "deepseek-chat",
		keyURL:    "https://platform.deepseek.com/",
	},
	{
		label:     "Google      (Gemini 2.0 Flash)",
		modelName: "gemini-2.0-flash",
		keyURL:    "https://aistudio.google.com/app/apikey",
	},
	{
		label:     "Groq        (Llama 3 — fast & free tier)",
		modelName: "llama-3.3-70b",
		keyURL:    "https://console.groq.com/keys",
	},
	{
		label:     "Ollama      (local, runs on your machine — no API key needed)",
		modelName: "llama3",
		isLocal:   true,
	},
	{
		label:     "Skip        (I'll configure manually)",
		modelName: "",
	},
}

func onboard() {
	reader := bufio.NewReader(os.Stdin)
	configPath := getConfigPath()

	// ── Welcome banner ────────────────────────────────────────────────────────
	fmt.Printf("\n%s  Welcome to gclaw — The Living Agent!\n", logo)
	fmt.Println("   Let's get you set up in under a minute.")
	fmt.Println()

	// ── Overwrite check ───────────────────────────────────────────────────────
	if _, err := os.Stat(configPath); err == nil {
		fmt.Printf("A config already exists at %s\n", configPath)
		fmt.Print("Overwrite it? (y/N): ")
		answer, _ := reader.ReadString('\n')
		answer = strings.TrimSpace(strings.ToLower(answer))
		if answer != "y" {
			fmt.Println("Aborted — your existing config was not changed.")
			return
		}
		fmt.Println()
	}

	// ── Provider selection ────────────────────────────────────────────────────
	fmt.Println("Which LLM provider would you like to use?")
	fmt.Println()
	for i, p := range onboardProviders {
		fmt.Printf("  %d) %s\n", i+1, p.label)
	}
	fmt.Println()

	var choiceIdx int
	for {
		fmt.Printf("Enter a number (1–%d): ", len(onboardProviders))
		var n int
		_, err := fmt.Fscan(reader, &n)
		// consume rest of line
		reader.ReadString('\n') //nolint:errcheck
		if err == nil && n >= 1 && n <= len(onboardProviders) {
			choiceIdx = n - 1
			break
		}
		fmt.Printf("  Please enter a number between 1 and %d.\n", len(onboardProviders))
	}

	selected := onboardProviders[choiceIdx]

	// ── API key prompt ────────────────────────────────────────────────────────
	var apiKey string
	if selected.modelName != "" && !selected.isLocal {
		fmt.Println()
		fmt.Println("  This prompt is for your LLM provider key.")
		fmt.Println("  GDEX trading access is configured separately and does not replace this key.")
		fmt.Println()
		if selected.keyURL != "" {
			fmt.Printf("  Get your free API key at: %s\n\n", selected.keyURL)
		}
		fmt.Print("  Paste your API key (or press Enter to skip): ")
		apiKey, _ = reader.ReadString('\n')
		apiKey = strings.TrimSpace(apiKey)
	}

	// ── Build config ──────────────────────────────────────────────────────────
	cfg := config.DefaultConfig()

	if selected.modelName != "" {
		// Set the default model
		cfg.Agents.Defaults.ModelName = selected.modelName

		// Inject the API key into the matching entry in model_list
		if apiKey != "" {
			for i, m := range cfg.ModelList {
				if m.ModelName == selected.modelName {
					cfg.ModelList[i].APIKey = apiKey
					break
				}
			}
		}
	}

	// ── Persist ───────────────────────────────────────────────────────────────
	if err := config.SaveConfig(configPath, cfg); err != nil {
		fmt.Printf("Error saving config: %v\n", err)
		os.Exit(1)
	}

	workspace := cfg.WorkspacePath()
	createWorkspaceTemplates(workspace)
	if err := repairLegacyWorkspaceFiles(workspace); err != nil {
		fmt.Printf("Warning: could not repair legacy workspace skills: %v\n", err)
	}

	walletAddress, walletGenerated, walletErr := ensureGDEXWallet(cfg)

	// ── Success message ───────────────────────────────────────────────────────
	fmt.Printf("\n%s  gclaw is ready!\n", logo)
	fmt.Println()
	fmt.Println("  Config:    ", configPath)
	fmt.Println("  Workspace: ", workspace)
	if walletAddress != "" {
		fmt.Println("  GDEX Control Wallet:", walletAddress)
	}
	fmt.Println()
	if walletGenerated {
		fmt.Println("  A GDEX control wallet was generated automatically.")
		fmt.Println("  It is used to authenticate GDEX and for EVM-side agent payments.")
		fmt.Println("  The managed Solana and managed EVM trading wallets appear after gateway sign-in.")
		fmt.Println("  Back up the private key stored in your config before funding it.")
		fmt.Println()
	} else if walletErr != nil {
		fmt.Printf("  Wallet setup warning: %v\n\n", walletErr)
	}
	fmt.Println("Next steps:")

	if selected.modelName == "" || (!selected.isLocal && apiKey == "") {
		fmt.Println("  1. Open your config and add an API key:")
		fmt.Println("       " + configPath)
		fmt.Println()
		fmt.Println("     Recommended providers:")
		fmt.Println("       OpenRouter — https://openrouter.ai/keys  (100+ models, free tier)")
		fmt.Println("       Ollama     — https://ollama.com           (local, fully free)")
		fmt.Println()
		fmt.Println("  2. Bring the living agent online:  gclaw gateway")
		fmt.Println("     Dashboard:  http://127.0.0.1:18790/dashboard")
		fmt.Println()
		fmt.Println("  3. Talk to it directly anytime:  gclaw agent")
	} else if selected.isLocal {
		fmt.Println("  1. Make sure Ollama is running:")
		fmt.Println("       ollama serve")
		fmt.Println()
		fmt.Println("  2. Pull the default model (first run only):")
		fmt.Println("       ollama pull llama3")
		fmt.Println()
		fmt.Println("  3. Bring the living agent online:  gclaw gateway")
		fmt.Println("     Dashboard:  http://127.0.0.1:18790/dashboard")
		fmt.Println()
		fmt.Println("  4. Talk to it directly anytime:  gclaw agent")
	} else {
		fmt.Println("  1. Bring the living agent online:  gclaw gateway")
		fmt.Println("     Dashboard:  http://127.0.0.1:18790/dashboard")
		fmt.Println()
		fmt.Println("  Living Agent features are active by default:")
		fmt.Println(
			"    GMAC Metabolism: 1000 seeded internal GMAC starting balance" +
				" (meant to be earned back with real GMAC over time)",
		)
		fmt.Println("    Auto-Trade Loop: heartbeat-driven, small and conservative")
		fmt.Println("    Swarm Mode:      ready when goodwill >= 200")
		fmt.Println()
		fmt.Println("  2. Talk to it directly anytime:  gclaw agent")
		fmt.Println()
		fmt.Println("  To replace the shared GDEX key with your own, edit:")
		fmt.Println("       " + configPath)
	}
	fmt.Println()
}

func copyEmbeddedToTarget(targetDir string) error {
	// Ensure target directory exists
	if err := os.MkdirAll(targetDir, 0o755); err != nil {
		return fmt.Errorf("Failed to create target directory: %w", err)
	}

	// Walk through all files in embed.FS
	err := fs.WalkDir(embeddedFiles, "workspace", func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		// Skip directories
		if d.IsDir() {
			return nil
		}

		// Read embedded file
		data, err := embeddedFiles.ReadFile(path)
		if err != nil {
			return fmt.Errorf("Failed to read embedded file %s: %w", path, err)
		}

		new_path, err := filepath.Rel("workspace", path)
		if err != nil {
			return fmt.Errorf("Failed to get relative path for %s: %v\n", path, err)
		}

		// Build target file path
		targetPath := filepath.Join(targetDir, new_path)

		// Ensure target file's directory exists
		if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
			return fmt.Errorf("Failed to create directory %s: %w", filepath.Dir(targetPath), err)
		}

		// Write file
		if err := os.WriteFile(targetPath, data, 0o644); err != nil {
			return fmt.Errorf("Failed to write file %s: %w", targetPath, err)
		}

		return nil
	})

	return err
}

func createWorkspaceTemplates(workspace string) {
	err := copyEmbeddedToTarget(workspace)
	if err != nil {
		fmt.Printf("Error copying workspace templates: %v\n", err)
	}
}
