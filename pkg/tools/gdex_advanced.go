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

// ─── gdex_hl_deposit ────────────────────────────────────────────────────────

type GDEXHLDepositTool struct{}

func (t *GDEXHLDepositTool) Name() string { return "gdex_hl_deposit" }

func (t *GDEXHLDepositTool) Description() string {
	return "Deposit USDC to HyperLiquid perpetuals via the GDEX /v1/hl/deposit endpoint. Requires Arbitrum (chain_id 42161) and the control wallet credentials. Minimum 10 USDC. Amount is human-readable USDC, for example '10' to deposit 10 USDC. If Arbitrum USDC is short but the managed wallet has ETH on Arbitrum, the helper can auto-swap ETH into USDC before depositing."
}

func (t *GDEXHLDepositTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"amount": map[string]any{
				"type":        "string",
				"description": "Human-readable USDC amount, for example '10' to deposit 10 USDC",
			},
			"chain_id": map[string]any{
				"type":        "number",
				"description": "Chain ID for deposit (default: 42161 for Arbitrum — only Arbitrum is supported)",
			},
			"token_address": map[string]any{
				"type":        "string",
				"description": "USDC token address (default: 0xaf88d065e77c8cC2239327C5EDb3A432268e5831 on Arbitrum)",
			},
			"auto_fund_from_native": map[string]any{
				"type":        "boolean",
				"description": "When true (default), auto-swap Arbitrum ETH into USDC before the deposit if the wallet is short on USDC",
			},
			"prefund_slippage": map[string]any{
				"type":        "number",
				"description": "Slippage percent for the ETH->USDC top-up swap when auto-funding is used (default: 1)",
			},
			"prefund_buffer_percent": map[string]any{
				"type":        "number",
				"description": "Extra ETH buffer percent to buy slightly more USDC than the requested deposit (default: 3)",
			},
			"prefund_wait_seconds": map[string]any{
				"type":        "number",
				"description": "How long to wait for the ETH->USDC auto-funding swap to settle before giving up (default: 90 seconds)",
			},
		},
		"required": []string{"amount"},
	}
}

func (t *GDEXHLDepositTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	amount, _ := args["amount"].(string)
	if amount == "" {
		return ErrorResult("amount is required")
	}

	params := map[string]any{"amount": amount}
	if v, ok := args["chain_id"]; ok {
		params["chain_id"] = v
	}
	if v, ok := args["token_address"]; ok {
		params["token_address"] = v
	}
	if v, ok := args["auto_fund_from_native"]; ok {
		params["auto_fund_from_native"] = v
	}
	if v, ok := args["prefund_slippage"]; ok {
		params["prefund_slippage"] = v
	}
	if v, ok := args["prefund_buffer_percent"]; ok {
		params["prefund_buffer_percent"] = v
	}
	if v, ok := args["prefund_wait_seconds"]; ok {
		params["prefund_wait_seconds"] = v
	}

	logger.InfoCF("tool", "gdex_hl_deposit executing", map[string]any{"amount": amount})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "hl_deposit",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_hl_deposit failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_hl_deposit failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_hl_withdraw ───────────────────────────────────────────────────────

type GDEXHLWithdrawTool struct{}

func (t *GDEXHLWithdrawTool) Name() string { return "gdex_hl_withdraw" }

func (t *GDEXHLWithdrawTool) Description() string {
	return "Withdraw USDC from HyperLiquid back to the managed Arbitrum wallet via the GDEX /v1/hl/withdraw endpoint. Amount is human-readable USDC and the backend rounds to 0.1. Practical rule: withdraw more than 1 USDC and leave about 1 USDC fee buffer; for example '5.0' is a safe test amount."
}

func (t *GDEXHLWithdrawTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"amount": map[string]any{
				"type":        "string",
				"description": "Human-readable USDC amount to withdraw from HyperLiquid (e.g. '5.0'). Values at or below 1 USDC and near-full-balance withdrawals can fail because the backend rounds to 0.1 and currently applies about a 1 USDC fee.",
			},
		},
		"required": []string{"amount"},
	}
}

func (t *GDEXHLWithdrawTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	amount, _ := args["amount"].(string)
	if amount == "" {
		return ErrorResult("amount is required")
	}

	logger.InfoCF("tool", "gdex_hl_withdraw executing", map[string]any{"amount": amount})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "hl_withdraw",
		"params": map[string]any{
			"amount": amount,
		},
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_hl_withdraw failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_hl_withdraw failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_bridge_estimate ───────────────────────────────────────────────────

type GDEXBridgeEstimateTool struct{}

func (t *GDEXBridgeEstimateTool) Name() string { return "gdex_bridge_estimate" }

func (t *GDEXBridgeEstimateTool) Description() string {
	return "Get a GDEX native-token bridge quote between supported chains. Amount must be in raw native units such as wei or lamports."
}

func (t *GDEXBridgeEstimateTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"from_chain_id": map[string]any{
				"type":        "number",
				"description": "Source chain ID, for example 1 for Ethereum or 42161 for Arbitrum",
			},
			"to_chain_id": map[string]any{
				"type":        "number",
				"description": "Destination chain ID, for example 8453 for Base or 622112261 for Solana",
			},
			"amount": map[string]any{
				"type":        "string",
				"description": "Amount in raw native units, for example wei on EVM chains or lamports on Solana",
			},
		},
		"required": []string{"from_chain_id", "to_chain_id", "amount"},
	}
}

func (t *GDEXBridgeEstimateTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	if _, ok := args["from_chain_id"]; !ok {
		return ErrorResult("from_chain_id is required")
	}
	if _, ok := args["to_chain_id"]; !ok {
		return ErrorResult("to_chain_id is required")
	}
	amount, _ := args["amount"].(string)
	if amount == "" {
		return ErrorResult("amount is required")
	}

	logger.InfoCF("tool", "gdex_bridge_estimate executing", map[string]any{
		"from_chain_id": args["from_chain_id"],
		"to_chain_id":   args["to_chain_id"],
		"amount":        amount,
	})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "bridge_estimate",
		"params": map[string]any{
			"from_chain_id": args["from_chain_id"],
			"to_chain_id":   args["to_chain_id"],
			"amount":        amount,
		},
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_bridge_estimate failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_bridge_estimate failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_bridge_request ────────────────────────────────────────────────────

type GDEXBridgeRequestTool struct{}

func (t *GDEXBridgeRequestTool) Name() string { return "gdex_bridge_request" }

func (t *GDEXBridgeRequestTool) Description() string {
	return "Execute a GDEX native-token bridge between supported chains. Requires control wallet credentials and uses managed-custody auth."
}

func (t *GDEXBridgeRequestTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"from_chain_id": map[string]any{
				"type":        "number",
				"description": "Source chain ID",
			},
			"to_chain_id": map[string]any{
				"type":        "number",
				"description": "Destination chain ID",
			},
			"amount": map[string]any{
				"type":        "string",
				"description": "Amount in raw native units, for example wei or lamports",
			},
		},
		"required": []string{"from_chain_id", "to_chain_id", "amount"},
	}
}

func (t *GDEXBridgeRequestTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	if _, ok := args["from_chain_id"]; !ok {
		return ErrorResult("from_chain_id is required")
	}
	if _, ok := args["to_chain_id"]; !ok {
		return ErrorResult("to_chain_id is required")
	}
	amount, _ := args["amount"].(string)
	if amount == "" {
		return ErrorResult("amount is required")
	}

	logger.InfoCF("tool", "gdex_bridge_request executing", map[string]any{
		"from_chain_id": args["from_chain_id"],
		"to_chain_id":   args["to_chain_id"],
		"amount":        amount,
	})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "bridge_request",
		"params": map[string]any{
			"from_chain_id": args["from_chain_id"],
			"to_chain_id":   args["to_chain_id"],
			"amount":        amount,
		},
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_bridge_request failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_bridge_request failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_bridge_orders ─────────────────────────────────────────────────────

type GDEXBridgeOrdersTool struct{}

func (t *GDEXBridgeOrdersTool) Name() string { return "gdex_bridge_orders" }

func (t *GDEXBridgeOrdersTool) Description() string {
	return "List recent GDEX bridge orders for the authenticated control wallet."
}

func (t *GDEXBridgeOrdersTool) Parameters() map[string]any {
	return map[string]any{
		"type":       "object",
		"properties": map[string]any{},
	}
}

func (t *GDEXBridgeOrdersTool) Execute(ctx context.Context, _ map[string]any) *ToolResult {
	logger.InfoCF("tool", "gdex_bridge_orders executing", map[string]any{})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "bridge_orders",
		"params": map[string]any{},
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_bridge_orders failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_bridge_orders failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_hl_create_order ───────────────────────────────────────────────────

type GDEXHLCreateOrderTool struct{}

func (t *GDEXHLCreateOrderTool) Name() string { return "gdex_hl_create_order" }

func (t *GDEXHLCreateOrderTool) Description() string {
	return "Open a leveraged perpetual position on HyperLiquid via the GDEX /v1/hl/create_order REST endpoint. Minimum order value: price × size ≥ $11. Use is_market=false for limit orders (safe testing). Example: ETH long limit at 50% below market."
}

func (t *GDEXHLCreateOrderTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"coin": map[string]any{
				"type":        "string",
				"description": "Perpetual asset symbol (e.g. 'ETH', 'BTC', 'SOL')",
			},
			"is_long": map[string]any{
				"type":        "boolean",
				"description": "true for long (buy), false for short (sell)",
			},
			"price": map[string]any{
				"type":        "string",
				"description": "Limit price as a string (e.g. '1500.0'). Required for limit orders.",
			},
			"size": map[string]any{
				"type":        "string",
				"description": "Position size in asset units (e.g. '0.013' for 0.013 ETH)",
			},
			"reduce_only": map[string]any{
				"type":        "boolean",
				"description": "If true, only reduces an existing position. Default false.",
			},
			"tp_price": map[string]any{
				"type":        "string",
				"description": "Take-profit price (default '0' = disabled)",
			},
			"sl_price": map[string]any{
				"type":        "string",
				"description": "Stop-loss price (default '0' = disabled)",
			},
			"is_market": map[string]any{
				"type":        "boolean",
				"description": "true for market order, false for limit order. Default false.",
			},
		},
		"required": []string{"coin", "price", "size"},
	}
}

func (t *GDEXHLCreateOrderTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	coin, _ := args["coin"].(string)
	price, _ := args["price"].(string)
	size, _ := args["size"].(string)
	if coin == "" || price == "" || size == "" {
		return ErrorResult("coin, price, and size are required")
	}

	params := map[string]any{
		"coin":  coin,
		"price": price,
		"size":  size,
	}
	if v, ok := args["is_long"]; ok {
		params["is_long"] = v
	}
	if v, ok := args["reduce_only"]; ok {
		params["reduce_only"] = v
	}
	if v, ok := args["tp_price"]; ok {
		params["tp_price"] = v
	}
	if v, ok := args["sl_price"]; ok {
		params["sl_price"] = v
	}
	if v, ok := args["is_market"]; ok {
		params["is_market"] = v
	}

	logger.InfoCF("tool", "gdex_hl_create_order executing", map[string]any{
		"coin": coin, "price": price, "size": size,
	})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "hl_create_order",
		"params": params,
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_hl_create_order failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_hl_create_order failed: %v", err))
	}
	return gdexResultToToolResult(result)
}

// ─── gdex_hl_cancel_order ───────────────────────────────────────────────────

type GDEXHLCancelOrderTool struct{}

func (t *GDEXHLCancelOrderTool) Name() string { return "gdex_hl_cancel_order" }

func (t *GDEXHLCancelOrderTool) Description() string {
	return "Cancel a HyperLiquid perpetual order via the GDEX /v1/hl/cancel_order REST endpoint."
}

func (t *GDEXHLCancelOrderTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"coin": map[string]any{
				"type":        "string",
				"description": "Perpetual asset symbol (e.g. 'ETH', 'BTC')",
			},
			"order_id": map[string]any{
				"type":        "string",
				"description": "The order ID (oid) to cancel, as returned by gdex_hl_create_order",
			},
		},
		"required": []string{"coin", "order_id"},
	}
}

func (t *GDEXHLCancelOrderTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	coin, _ := args["coin"].(string)
	orderID, _ := args["order_id"].(string)
	if coin == "" || orderID == "" {
		return ErrorResult("coin and order_id are required")
	}

	logger.InfoCF("tool", "gdex_hl_cancel_order executing", map[string]any{
		"coin": coin, "order_id": orderID,
	})

	result, err := runNodeHelper(ctx, "market.js", map[string]any{
		"action": "hl_cancel_order",
		"params": map[string]any{
			"coin":     coin,
			"order_id": orderID,
		},
	})
	if err != nil {
		logger.ErrorCF("tool", "gdex_hl_cancel_order failed", map[string]any{"error": err.Error()})
		return ErrorResult(fmt.Sprintf("gdex_hl_cancel_order failed: %v", err))
	}
	return gdexResultToToolResult(result)
}
