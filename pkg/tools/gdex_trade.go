package tools

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"

	"github.com/GemachDAO/Gclaw/pkg/logger"
)

// helperScriptDir returns the path to the GDEX trading helpers directory.
// It uses the GDEX_HELPERS_DIR environment variable if set, otherwise
// falls back to workspace/skills/gdex-trading/helpers relative to the
// process working directory.
func helperScriptDir() string {
	if dir := os.Getenv("GDEX_HELPERS_DIR"); dir != "" {
		return dir
	}
	wd, err := os.Getwd()
	if err != nil {
		return "workspace/skills/gdex-trading/helpers"
	}
	return filepath.Join(wd, "workspace", "skills", "gdex-trading", "helpers")
}

// ensureNodeDeps checks whether the helpers directory has node_modules installed.
// If not, it runs setup.sh (or falls back to npm install) to install dependencies.
// This is called once per process via sync.Once.
var ensureDepsOnce sync.Once
var ensureDepsErr error

func ensureNodeDeps() error {
	ensureDepsOnce.Do(func() {
		dir := helperScriptDir()
		nodeModules := filepath.Join(dir, "node_modules")
		if _, err := os.Stat(nodeModules); err == nil {
			return // already installed
		}

		logger.InfoCF("tool", "GDEX helpers: node_modules not found, installing dependencies...",
			map[string]any{"dir": dir})

		// Try setup.sh first
		setupScript := filepath.Join(dir, "setup.sh")
		if _, err := os.Stat(setupScript); err == nil {
			cmd := exec.Command("bash", setupScript)
			cmd.Dir = dir
			cmd.Env = os.Environ()
			if out, err := cmd.CombinedOutput(); err != nil {
				logger.WarnCF("tool", "setup.sh failed, trying npm install",
					map[string]any{"error": err.Error(), "output": string(out)})
			} else {
				logger.InfoCF("tool", "GDEX helpers: dependencies installed via setup.sh", nil)
				return
			}
		}

		// Fallback to npm install
		cmd := exec.Command("npm", "install", "--no-audit", "--no-fund")
		cmd.Dir = dir
		cmd.Env = os.Environ()
		if out, err := cmd.CombinedOutput(); err != nil {
			ensureDepsErr = fmt.Errorf("failed to install GDEX helper dependencies: %w — %s", err, string(out))
			logger.ErrorCF("tool", "npm install failed for GDEX helpers",
				map[string]any{"error": ensureDepsErr.Error()})
		} else {
			logger.InfoCF("tool", "GDEX helpers: dependencies installed via npm install", nil)
		}
	})
	return ensureDepsErr
}

// runNodeHelper executes a Node.js helper script, passing input as JSON on stdin,
// and returns the parsed JSON output. scriptName should be "trade.js" or "market.js".
// It automatically installs Node dependencies on first invocation if needed.
func runNodeHelper(ctx context.Context, scriptName string, input map[string]any) (map[string]any, error) {
	// Auto-install dependencies if needed
	if err := ensureNodeDeps(); err != nil {
		return nil, err
	}

	scriptPath := filepath.Join(helperScriptDir(), scriptName)

	inputJSON, err := json.Marshal(input)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal input: %w", err)
	}

	cmd := exec.CommandContext(ctx, "node", scriptPath)
	cmd.Stdin = bytes.NewReader(inputJSON)
	cmd.Env = os.Environ()

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err = cmd.Run()
	if err != nil {
		stderrStr := stderr.String()
		// Cap and redact to avoid leaking key material from SDK debug output
		if len(stderrStr) > 512 {
			stderrStr = stderrStr[:512] + "... [truncated]"
		}
		return nil, fmt.Errorf("node helper failed: %w\nstderr: %s", err, stderrStr)
	}

	// Log any stderr output from Node even on success (e.g. console.error/console.log)
	if stderrStr := stderr.String(); stderrStr != "" {
		// Cap and redact to avoid leaking key material from SDK debug output
		if len(stderrStr) > 512 {
			stderrStr = stderrStr[:512] + "... [truncated]"
		}
		logger.WarnCF("tool", "node helper wrote to stderr", map[string]any{
			"script": scriptName,
			"stderr": stderrStr,
		})
	}

	// Parse stdout only — stderr is intentionally excluded to avoid JSON parse errors
	output := stdout.Bytes()
	var result map[string]any
	if err := json.Unmarshal(output, &result); err != nil {
		return nil, fmt.Errorf("failed to parse helper output: %w", err)
	}
	return result, nil
}

// gdexResultToToolResult converts a parsed node helper result map to a ToolResult.
func gdexResultToToolResult(result map[string]any) *ToolResult {
	success, _ := result["success"].(bool)
	if !success {
		errMsg, _ := result["error"].(string)
		if errMsg == "" {
			errMsg = "unknown error from GDEX helper"
		}
		return ErrorResult(errMsg)
	}
	data := result["data"]
	out, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return SilentResult(fmt.Sprintf("%v", data))
	}
	return SilentResult(string(out))
}

// ─── gdex_buy ───────────────────────────────────────────────────────────────

type GDEXBuyTool struct{}

func (t *GDEXBuyTool) Name() string { return "gdex_buy" }

func (t *GDEXBuyTool) Description() string {
	return "Market buy a token using GDEX. Amount is in the smallest unit (lamports for Solana, wei for EVM chains)."
}

func (t *GDEXBuyTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"token_address": map[string]any{
				"type":        "string",
				"description": "The token contract address to buy",
			},
			"amount": map[string]any{
				"type":        "string",
				"description": "Amount to spend in smallest unit (lamports for Solana, wei for EVM)",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID (default: 622112261 for Solana). Base=8453, Arbitrum=42161",
			},
		},
		"required": []string{"token_address", "amount"},
	}
}

func (t *GDEXBuyTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	tokenAddress, _ := args["token_address"].(string)
	amount, _ := args["amount"].(string)
	if tokenAddress == "" || amount == "" {
		return ErrorResult("token_address and amount are required")
	}

	params := map[string]any{
		"token_address": tokenAddress,
		"amount":        amount,
	}
	if chainID, ok := args["chain_id"]; ok {
		params["chain_id"] = chainID
	}

	logger.InfoCF("tool", "gdex_buy executing", map[string]any{
		"token_address": tokenAddress,
		"amount":        amount,
	})

	result, err := runNodeHelper(ctx, "trade.js", map[string]any{
		"action": "buy",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_buy failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_buy failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_sell ──────────────────────────────────────────────────────────────

type GDEXSellTool struct{}

func (t *GDEXSellTool) Name() string { return "gdex_sell" }

func (t *GDEXSellTool) Description() string {
	return "Market sell a token using GDEX. Amount is in the smallest unit (lamports for Solana, wei for EVM chains)."
}

func (t *GDEXSellTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"token_address": map[string]any{
				"type":        "string",
				"description": "The token contract address to sell",
			},
			"amount": map[string]any{
				"type":        "string",
				"description": "Amount to sell in smallest unit (lamports for Solana, wei for EVM)",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID (default: 622112261 for Solana). Base=8453, Arbitrum=42161",
			},
		},
		"required": []string{"token_address", "amount"},
	}
}

func (t *GDEXSellTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	tokenAddress, _ := args["token_address"].(string)
	amount, _ := args["amount"].(string)
	if tokenAddress == "" || amount == "" {
		return ErrorResult("token_address and amount are required")
	}

	params := map[string]any{
		"token_address": tokenAddress,
		"amount":        amount,
	}
	if chainID, ok := args["chain_id"]; ok {
		params["chain_id"] = chainID
	}

	logger.InfoCF("tool", "gdex_sell executing", map[string]any{
		"token_address": tokenAddress,
		"amount":        amount,
	})

	result, err := runNodeHelper(ctx, "trade.js", map[string]any{
		"action": "sell",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_sell failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_sell failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_limit_buy ─────────────────────────────────────────────────────────

type GDEXLimitBuyTool struct{}

func (t *GDEXLimitBuyTool) Name() string { return "gdex_limit_buy" }

func (t *GDEXLimitBuyTool) Description() string {
	return "Place a limit buy order on GDEX. Executes when the token reaches the trigger price."
}

func (t *GDEXLimitBuyTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"token_address": map[string]any{
				"type":        "string",
				"description": "The token contract address to buy",
			},
			"amount": map[string]any{
				"type":        "string",
				"description": "Amount to spend in smallest unit (lamports for Solana, wei for EVM)",
			},
			"trigger_price": map[string]any{
				"type":        "string",
				"description": "Price at which to trigger the buy order",
			},
			"profit_percent": map[string]any{
				"type":        "number",
				"description": "Optional take-profit percentage above entry price (e.g. 50 for +50%)",
			},
			"loss_percent": map[string]any{
				"type":        "number",
				"description": "Optional stop-loss percentage below entry price (e.g. 20 for -20%)",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID (default: 622112261 for Solana). Base=8453, Arbitrum=42161",
			},
		},
		"required": []string{"token_address", "amount", "trigger_price"},
	}
}

func (t *GDEXLimitBuyTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	tokenAddress, _ := args["token_address"].(string)
	amount, _ := args["amount"].(string)
	triggerPrice, _ := args["trigger_price"].(string)
	if tokenAddress == "" || amount == "" || triggerPrice == "" {
		return ErrorResult("token_address, amount, and trigger_price are required")
	}

	params := map[string]any{
		"token_address": tokenAddress,
		"amount":        amount,
		"trigger_price": triggerPrice,
	}
	if v, ok := args["profit_percent"]; ok {
		params["profit_percent"] = v
	}
	if v, ok := args["loss_percent"]; ok {
		params["loss_percent"] = v
	}
	if chainID, ok := args["chain_id"]; ok {
		params["chain_id"] = chainID
	}

	logger.InfoCF("tool", "gdex_limit_buy executing", map[string]any{
		"token_address": tokenAddress,
		"trigger_price": triggerPrice,
	})

	result, err := runNodeHelper(ctx, "trade.js", map[string]any{
		"action": "limit_buy",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_limit_buy failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_limit_buy failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_limit_sell ────────────────────────────────────────────────────────

type GDEXLimitSellTool struct{}

func (t *GDEXLimitSellTool) Name() string { return "gdex_limit_sell" }

func (t *GDEXLimitSellTool) Description() string {
	return "Place a limit sell order on GDEX. Executes when the token reaches the trigger price."
}

func (t *GDEXLimitSellTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"token_address": map[string]any{
				"type":        "string",
				"description": "The token contract address to sell",
			},
			"amount": map[string]any{
				"type":        "string",
				"description": "Amount to sell in smallest unit (lamports for Solana, wei for EVM)",
			},
			"trigger_price": map[string]any{
				"type":        "string",
				"description": "Price at which to trigger the sell order",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID (default: 622112261 for Solana). Base=8453, Arbitrum=42161",
			},
		},
		"required": []string{"token_address", "amount", "trigger_price"},
	}
}

func (t *GDEXLimitSellTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	tokenAddress, _ := args["token_address"].(string)
	amount, _ := args["amount"].(string)
	triggerPrice, _ := args["trigger_price"].(string)
	if tokenAddress == "" || amount == "" || triggerPrice == "" {
		return ErrorResult("token_address, amount, and trigger_price are required")
	}

	params := map[string]any{
		"token_address": tokenAddress,
		"amount":        amount,
		"trigger_price": triggerPrice,
	}
	if chainID, ok := args["chain_id"]; ok {
		params["chain_id"] = chainID
	}

	logger.InfoCF("tool", "gdex_limit_sell executing", map[string]any{
		"token_address": tokenAddress,
		"trigger_price": triggerPrice,
	})

	result, err := runNodeHelper(ctx, "trade.js", map[string]any{
		"action": "limit_sell",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_limit_sell failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_limit_sell failed: %v", err))
	}
	return gdexResultToToolResult(result)
}
