package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/tempo"
)

// TempoPayTool makes HTTP requests with automatic Tempo MPP payment support.
// When the target server responds with HTTP 402 (Payment Required), the tool
// signs a payment credential via the Machine Payments Protocol and retries
// the request, enabling the autonomous agent to access paid APIs and services
// on the Tempo blockchain.
type TempoPayTool struct {
	client *tempo.Client
}

// NewTempoPayTool creates a new Tempo MPP payment tool with the given client.
func NewTempoPayTool(client *tempo.Client) *TempoPayTool {
	return &TempoPayTool{client: client}
}

func (t *TempoPayTool) Name() string { return "tempo_pay" }

func (t *TempoPayTool) Description() string {
	return "Fetch a URL with automatic Tempo MPP (Machine Payments Protocol) payment support. " +
		"If the server requires payment (HTTP 402), this tool signs a payment credential " +
		"on the Tempo blockchain and retries the request. " +
		"Use this for accessing paid APIs, premium content, agent-to-agent services, " +
		"or any MPP-compatible service listed in the payments directory at mpp.dev/services."
}

func (t *TempoPayTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"url": map[string]any{
				"type":        "string",
				"description": "The URL to fetch. Must be http or https.",
			},
			"method": map[string]any{
				"type":        "string",
				"description": "HTTP method (e.g., GET, POST, PUT, DELETE). Defaults to GET.",
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

func (t *TempoPayTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
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
		return ErrorResult(fmt.Sprintf("tempo_pay failed: %v", err))
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
		"url":       urlStr,
		"status":    result.StatusCode,
		"truncated": truncated,
		"length":    len(text),
		"text":      text,
	}

	if result.PaidAmount != "" {
		output["paid_amount"] = result.PaidAmount
		output["payment_currency"] = result.Currency
	}

	outputJSON, _ := json.MarshalIndent(output, "", "  ")

	llmMsg := fmt.Sprintf("Fetched %s (status: %d, %d bytes", urlStr, result.StatusCode, len(text))
	if result.PaidAmount != "" {
		llmMsg += fmt.Sprintf(", paid %s on Tempo", result.PaidAmount)
	}
	llmMsg += ")"

	return &ToolResult{
		ForLLM:  llmMsg,
		ForUser: string(outputJSON),
	}
}
