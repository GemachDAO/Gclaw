package tools

import (
	"context"
	"fmt"

	"github.com/GemachDAO/Gclaw/pkg/logger"
)

// ─── gdex_copy_trade ────────────────────────────────────────────────────────

type GDEXCopyTradeTool struct{}

func (t *GDEXCopyTradeTool) Name() string { return "gdex_copy_trade" }

func (t *GDEXCopyTradeTool) Description() string {
	return "Set up copy trading on GDEX to mirror another wallet's trades automatically."
}

func (t *GDEXCopyTradeTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"target_address": map[string]any{
				"type":        "string",
				"description": "The wallet address to copy trades from",
			},
			"name": map[string]any{
				"type":        "string",
				"description": "A label for this copy-trade configuration",
			},
			"amount": map[string]any{
				"type":        "string",
				"description": "Amount to allocate per copied trade in smallest unit",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID (default: 622112261 for Solana). Base=8453, Arbitrum=42161",
			},
		},
		"required": []string{"target_address", "name", "amount"},
	}
}

func (t *GDEXCopyTradeTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	targetAddress, _ := args["target_address"].(string)
	name, _ := args["name"].(string)
	amount, _ := args["amount"].(string)
	if targetAddress == "" || name == "" || amount == "" {
		return ErrorResult("target_address, name, and amount are required")
	}

	params := map[string]any{
		"target_address": targetAddress,
		"name":           name,
		"amount":         amount,
	}
	if chainID, ok := args["chain_id"]; ok {
		params["chain_id"] = chainID
	}

	logger.InfoCF("tool", "gdex_copy_trade executing", map[string]any{
		"target_address": targetAddress,
		"name":           name,
	})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "copy_trade",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_copy_trade failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_copy_trade failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_hl_balance ────────────────────────────────────────────────────────

type GDEXHLBalanceTool struct{}

func (t *GDEXHLBalanceTool) Name() string { return "gdex_hl_balance" }

func (t *GDEXHLBalanceTool) Description() string {
	return "Check the HyperLiquid USDC balance for the authenticated wallet."
}

func (t *GDEXHLBalanceTool) Parameters() map[string]any {
	return map[string]any{
		"type":       "object",
		"properties": map[string]any{},
	}
}

func (t *GDEXHLBalanceTool) Execute(ctx context.Context, _ map[string]any) *ToolResult {
	logger.InfoCF("tool", "gdex_hl_balance executing", map[string]any{})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "hl_balance",
		"params": map[string]any{},
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_hl_balance failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_hl_balance failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_hl_positions ──────────────────────────────────────────────────────

type GDEXHLPositionsTool struct{}

func (t *GDEXHLPositionsTool) Name() string { return "gdex_hl_positions" }

func (t *GDEXHLPositionsTool) Description() string {
	return "Get open HyperLiquid perpetual positions for the authenticated wallet."
}

func (t *GDEXHLPositionsTool) Parameters() map[string]any {
	return map[string]any{
		"type":       "object",
		"properties": map[string]any{},
	}
}

func (t *GDEXHLPositionsTool) Execute(ctx context.Context, _ map[string]any) *ToolResult {
	logger.InfoCF("tool", "gdex_hl_positions executing", map[string]any{})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "hl_positions",
		"params": map[string]any{},
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_hl_positions failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_hl_positions failed: %v", err))
	}
	return gdexResultToToolResult(result)
}
