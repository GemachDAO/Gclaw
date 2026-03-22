package tools

import "testing"

func TestParseNodeHelperOutput(t *testing.T) {
	result, err := parseNodeHelperOutput([]byte(`{"success":false,"error":"insufficient funds for fee"}`))
	if err != nil {
		t.Fatalf("parseNodeHelperOutput returned error: %v", err)
	}
	success, ok := result["success"].(bool)
	if !ok {
		t.Fatalf("expected boolean success field, got %T", result["success"])
	}
	if success {
		t.Fatal("expected success=false")
	}
	if got := result["error"]; got != "insufficient funds for fee" {
		t.Fatalf("expected helper error to survive parse, got %v", got)
	}
}

func TestGDEXResultToToolResult_ReturnsHelperError(t *testing.T) {
	toolResult := gdexResultToToolResult(map[string]any{
		"success": false,
		"error":   "insufficient funds for fee",
	})
	if toolResult == nil {
		t.Fatal("expected tool result")
	}
	if !toolResult.IsError {
		t.Fatal("expected error tool result")
	}
	if toolResult.ForLLM != "insufficient funds for fee" {
		t.Fatalf("expected helper error output, got %q", toolResult.ForLLM)
	}
}
