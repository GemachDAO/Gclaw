package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/x402"
)

// X402FetchTool makes HTTP requests with automatic x402 payment support.
// When the target server responds with HTTP 402 (Payment Required), the tool
// signs a USDC payment via EIP-3009 and retries the request with the payment
// header, enabling the autonomous agent to access paid APIs and resources.
type X402FetchTool struct {
	client *x402.Client
}

// NewX402FetchTool creates a new x402 fetch tool with the given client.
func NewX402FetchTool(client *x402.Client) *X402FetchTool {
	return &X402FetchTool{client: client}
}

func (t *X402FetchTool) Name() string { return "x402_fetch" }

func (t *X402FetchTool) Description() string {
	return "Fetch a URL with automatic x402 payment support. " +
		"If the server requires payment (HTTP 402), this tool signs a USDC payment " +
		"using EIP-3009 and retries the request. Supports Base and Ethereum networks. " +
		"Use this for accessing paid APIs, premium content, or agent-to-agent services " +
		"that use the x402 payment protocol (ERC-8004)."
}

func (t *X402FetchTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"url": map[string]any{
				"type":        "string",
				"description": "The URL to fetch. Must be http or https.",
			},
			"method": map[string]any{
				"type":        "string",
				"description": "HTTP method (GET, POST, PUT, DELETE). Defaults to GET.",
				"enum":        []string{"GET", "POST", "PUT", "DELETE"},
			},
			"headers": map[string]any{
				"type":        "object",
				"description": "Optional HTTP headers as key-value pairs.",
			},
			"body": map[string]any{
				"type":        "string",
				"description": "Optional request body (for POST/PUT).",
			},
		},
		"required": []string{"url"},
	}
}

func (t *X402FetchTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	urlStr, _ := args["url"].(string)
	if urlStr == "" {
		return ErrorResult("url is required")
	}

	if !strings.HasPrefix(urlStr, "http://") && !strings.HasPrefix(urlStr, "https://") {
		return ErrorResult("only http/https URLs are allowed")
	}

	method := "GET"
	if m, ok := args["method"].(string); ok && m != "" {
		method = strings.ToUpper(m)
	}

	var headers map[string]string
	if h, ok := args["headers"].(map[string]any); ok {
		headers = make(map[string]string, len(h))
		for k, v := range h {
			if vs, ok := v.(string); ok {
				headers[k] = vs
			}
		}
	}

	var body []byte
	if b, ok := args["body"].(string); ok && b != "" {
		body = []byte(b)
	}

	result, err := t.client.Fetch(ctx, method, urlStr, headers, body)
	if err != nil {
		return ErrorResult(fmt.Sprintf("x402_fetch failed: %v", err))
	}

	// Format the response.
	var text string
	if strings.Contains(result.ContentType, "application/json") {
		var jsonData any
		if err := json.Unmarshal(result.Body, &jsonData); err == nil {
			formatted, _ := json.MarshalIndent(jsonData, "", "  ")
			text = string(formatted)
		} else {
			text = string(result.Body)
		}
	} else {
		text = string(result.Body)
	}

	// Truncate very long responses.
	const maxLen = 50000
	truncated := len(text) > maxLen
	if truncated {
		text = text[:maxLen]
	}

	output := map[string]any{
		"url":        urlStr,
		"status":     result.StatusCode,
		"truncated":  truncated,
		"length":     len(text),
		"text":       text,
	}

	if result.PaidAmount != "" {
		output["paid_amount"] = result.PaidAmount
		output["payment_network"] = result.Network
	}

	outputJSON, _ := json.MarshalIndent(output, "", "  ")

	llmMsg := fmt.Sprintf("Fetched %s (status: %d, %d bytes", urlStr, result.StatusCode, len(text))
	if result.PaidAmount != "" {
		llmMsg += fmt.Sprintf(", paid %s on %s", result.PaidAmount, result.Network)
	}
	llmMsg += ")"

	return &ToolResult{
		ForLLM:  llmMsg,
		ForUser: string(outputJSON),
	}
}
