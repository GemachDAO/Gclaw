package tools

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/logger"
	"github.com/GemachDAO/Gclaw/pkg/metabolism"
	"github.com/GemachDAO/Gclaw/pkg/providers"
)

// DefaultToolCosts maps tool names to their GMAC cost per execution.
var DefaultToolCosts = map[string]float64{
	"gdex_buy":        2.0,
	"gdex_sell":       2.0,
	"gdex_limit_buy":  3.0,
	"gdex_limit_sell": 3.0,
	"gdex_trending":   1.0,
	"gdex_search":     1.0,
	"gdex_price":      0.5,
	"gdex_holdings":   0.5,
	"gdex_scan":       5.0,
	"gdex_copy_trade": 10.0,
	"web_search":      1.0,
	"web_fetch":       0.5,
	"exec":            1.5,
	"spawn":           5.0,
}

type ToolRegistry struct {
	tools      map[string]Tool
	metabolism *metabolism.Metabolism // optional, nil if metabolism disabled
	toolCosts  map[string]float64    // tool name -> GMAC cost
	mu         sync.RWMutex
}

// SetMetabolism attaches a Metabolism instance to the registry for cost gating.
func (r *ToolRegistry) SetMetabolism(m *metabolism.Metabolism) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.metabolism = m
}

// GetMetabolism returns the configured Metabolism instance, or nil if not set.
func (r *ToolRegistry) GetMetabolism() *metabolism.Metabolism {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.metabolism
}

// SetToolCost sets the GMAC cost for a specific tool.
func (r *ToolRegistry) SetToolCost(toolName string, cost float64) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.toolCosts == nil {
		r.toolCosts = make(map[string]float64)
	}
	r.toolCosts[toolName] = cost
}

func NewToolRegistry() *ToolRegistry {
	return &ToolRegistry{
		tools:     make(map[string]Tool),
		toolCosts: make(map[string]float64),
	}
}

func (r *ToolRegistry) Register(tool Tool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.tools[tool.Name()] = tool
}

func (r *ToolRegistry) Get(name string) (Tool, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	tool, ok := r.tools[name]
	return tool, ok
}

func (r *ToolRegistry) Execute(ctx context.Context, name string, args map[string]any) *ToolResult {
	return r.ExecuteWithContext(ctx, name, args, "", "", nil)
}

// ExecuteWithContext executes a tool with channel/chatID context and optional async callback.
// If the tool implements AsyncTool and a non-nil callback is provided,
// the callback will be set on the tool before execution.
// If a Metabolism is configured and the tool has a cost, the cost is checked and
// debited before execution. Execution is blocked if the balance is insufficient.
func (r *ToolRegistry) ExecuteWithContext(
	ctx context.Context,
	name string,
	args map[string]any,
	channel, chatID string,
	asyncCallback AsyncCallback,
) *ToolResult {
	logger.InfoCF("tool", "Tool execution started",
		map[string]any{
			"tool": name,
			"args": args,
		})

	tool, ok := r.Get(name)
	if !ok {
		logger.ErrorCF("tool", "Tool not found",
			map[string]any{
				"tool": name,
			})
		return ErrorResult(fmt.Sprintf("tool %q not found", name)).WithError(fmt.Errorf("tool not found"))
	}

	// Metabolism gating: check and debit GMAC cost if configured
	r.mu.RLock()
	met := r.metabolism
	cost, hasCost := r.toolCosts[name]
	r.mu.RUnlock()

	if met != nil && hasCost && cost > 0 {
		if !met.CanAfford(cost) {
			balance := met.GetBalance()
			msg := fmt.Sprintf(
				"Insufficient GMAC balance to execute tool. Current balance: %.4f, Cost: %.4f. Agent entering survival mode.",
				balance, cost,
			)
			logger.WarnCF("tool", "Metabolism gate: insufficient GMAC",
				map[string]any{"tool": name, "balance": balance, "cost": cost})
			return ErrorResult(msg)
		}
		if err := met.Debit(cost, "tool_exec", name); err != nil {
			return ErrorResult(fmt.Sprintf("GMAC debit failed: %v", err))
		}
	}

	// If tool implements ContextualTool, set context
	if contextualTool, ok := tool.(ContextualTool); ok && channel != "" && chatID != "" {
		contextualTool.SetContext(channel, chatID)
	}

	// If tool implements AsyncTool and callback is provided, set callback
	if asyncTool, ok := tool.(AsyncTool); ok && asyncCallback != nil {
		asyncTool.SetCallback(asyncCallback)
		logger.DebugCF("tool", "Async callback injected",
			map[string]any{
				"tool": name,
			})
	}

	start := time.Now()
	result := tool.Execute(ctx, args)
	duration := time.Since(start)

	// Log based on result type
	if result.IsError {
		logger.ErrorCF("tool", "Tool execution failed",
			map[string]any{
				"tool":     name,
				"duration": duration.Milliseconds(),
				"error":    result.ForLLM,
			})
	} else if result.Async {
		logger.InfoCF("tool", "Tool started (async)",
			map[string]any{
				"tool":     name,
				"duration": duration.Milliseconds(),
			})
	} else {
		logger.InfoCF("tool", "Tool execution completed",
			map[string]any{
				"tool":          name,
				"duration_ms":   duration.Milliseconds(),
				"result_length": len(result.ForLLM),
			})
	}

	return result
}

func (r *ToolRegistry) GetDefinitions() []map[string]any {
	r.mu.RLock()
	defer r.mu.RUnlock()

	definitions := make([]map[string]any, 0, len(r.tools))
	for _, tool := range r.tools {
		definitions = append(definitions, ToolToSchema(tool))
	}
	return definitions
}

// ToProviderDefs converts tool definitions to provider-compatible format.
// This is the format expected by LLM provider APIs.
func (r *ToolRegistry) ToProviderDefs() []providers.ToolDefinition {
	r.mu.RLock()
	defer r.mu.RUnlock()

	definitions := make([]providers.ToolDefinition, 0, len(r.tools))
	for _, tool := range r.tools {
		schema := ToolToSchema(tool)

		// Safely extract nested values with type checks
		fn, ok := schema["function"].(map[string]any)
		if !ok {
			continue
		}

		name, _ := fn["name"].(string)
		desc, _ := fn["description"].(string)
		params, _ := fn["parameters"].(map[string]any)

		definitions = append(definitions, providers.ToolDefinition{
			Type: "function",
			Function: providers.ToolFunctionDefinition{
				Name:        name,
				Description: desc,
				Parameters:  params,
			},
		})
	}
	return definitions
}

// List returns a list of all registered tool names.
func (r *ToolRegistry) List() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	names := make([]string, 0, len(r.tools))
	for name := range r.tools {
		names = append(names, name)
	}
	return names
}

// Count returns the number of registered tools.
func (r *ToolRegistry) Count() int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return len(r.tools)
}

// GetSummaries returns human-readable summaries of all registered tools.
// Returns a slice of "name - description" strings.
func (r *ToolRegistry) GetSummaries() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	summaries := make([]string, 0, len(r.tools))
	for _, tool := range r.tools {
		summaries = append(summaries, fmt.Sprintf("- `%s` - %s", tool.Name(), tool.Description()))
	}
	return summaries
}
