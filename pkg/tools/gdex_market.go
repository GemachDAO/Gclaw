package tools

import (
	"context"
	"fmt"

	"github.com/GemachDAO/Gclaw/pkg/logger"
)

// ─── gdex_trending ──────────────────────────────────────────────────────────

type GDEXTrendingTool struct{}

func (t *GDEXTrendingTool) Name() string { return "gdex_trending" }

func (t *GDEXTrendingTool) Description() string {
	return "Get trending tokens from GDEX across supported chains."
}

func (t *GDEXTrendingTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"limit": map[string]any{
				"type":        "number",
				"description": "Number of trending tokens to return (default: 10)",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Filter by chain ID (optional). 622112261=Solana, 8453=Base, 42161=Arbitrum",
			},
		},
	}
}

func (t *GDEXTrendingTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	params := map[string]any{}
	if v, ok := args["limit"]; ok {
		params["limit"] = v
	}
	if v, ok := args["chain_id"]; ok {
		params["chain_id"] = v
	}

	logger.InfoCF("tool", "gdex_trending executing", map[string]any{"params": params})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "trending",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_trending failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_trending failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_search ────────────────────────────────────────────────────────────

type GDEXSearchTool struct{}

func (t *GDEXSearchTool) Name() string { return "gdex_search" }

func (t *GDEXSearchTool) Description() string {
	return "Search for tokens by name or symbol on GDEX."
}

func (t *GDEXSearchTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"query": map[string]any{
				"type":        "string",
				"description": "Token name or symbol to search for",
			},
			"limit": map[string]any{
				"type":        "number",
				"description": "Maximum number of results to return (default: 10)",
			},
		},
		"required": []string{"query"},
	}
}

func (t *GDEXSearchTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	query, _ := args["query"].(string)
	if query == "" {
		return ErrorResult("query is required")
	}

	params := map[string]any{"query": query}
	if v, ok := args["limit"]; ok {
		params["limit"] = v
	}

	logger.InfoCF("tool", "gdex_search executing", map[string]any{"query": query})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "search",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_search failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_search failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_price ─────────────────────────────────────────────────────────────

type GDEXPriceTool struct{}

func (t *GDEXPriceTool) Name() string { return "gdex_price" }

func (t *GDEXPriceTool) Description() string {
	return "Get the current price of a token on GDEX."
}

func (t *GDEXPriceTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"token_address": map[string]any{
				"type":        "string",
				"description": "The token contract address",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID. 622112261=Solana, 8453=Base, 42161=Arbitrum",
			},
		},
		"required": []string{"token_address", "chain_id"},
	}
}

func (t *GDEXPriceTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	tokenAddress, _ := args["token_address"].(string)
	chainID := args["chain_id"]
	if tokenAddress == "" {
		return ErrorResult("token_address is required")
	}
	if chainID == nil {
		return ErrorResult("chain_id is required")
	}

	params := map[string]any{
		"token_address": tokenAddress,
		"chain_id":      chainID,
	}

	logger.InfoCF("tool", "gdex_price executing", map[string]any{"token_address": tokenAddress})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "price",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_price failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_price failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_holdings ──────────────────────────────────────────────────────────

type GDEXHoldingsTool struct{}

func (t *GDEXHoldingsTool) Name() string { return "gdex_holdings" }

func (t *GDEXHoldingsTool) Description() string {
	return "Check portfolio holdings for the authenticated wallet on GDEX."
}

func (t *GDEXHoldingsTool) Parameters() map[string]any {
	return map[string]any{
		"type":       "object",
		"properties": map[string]any{},
	}
}

func (t *GDEXHoldingsTool) Execute(ctx context.Context, _ map[string]any) *ToolResult {
	logger.InfoCF("tool", "gdex_holdings executing", map[string]any{})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "holdings",
		"params": map[string]any{},
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_holdings failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_holdings failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_scan ──────────────────────────────────────────────────────────────

type GDEXScanTool struct{}

func (t *GDEXScanTool) Name() string { return "gdex_scan" }

func (t *GDEXScanTool) Description() string {
	return "Get the newest tokens listed on a chain via GDEX."
}

func (t *GDEXScanTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID to scan (default: 622112261 for Solana). Base=8453, Arbitrum=42161",
			},
			"limit": map[string]any{
				"type":        "number",
				"description": "Number of newest tokens to return (default: 20)",
			},
		},
	}
}

func (t *GDEXScanTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	params := map[string]any{}
	if v, ok := args["chain_id"]; ok {
		params["chain_id"] = v
	}
	if v, ok := args["limit"]; ok {
		params["limit"] = v
	}

	logger.InfoCF("tool", "gdex_scan executing", map[string]any{"params": params})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "scan",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_scan failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_scan failed: %v", err))
	}
	return gdexResultToToolResult(result)
}
