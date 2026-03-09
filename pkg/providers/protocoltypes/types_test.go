package protocoltypes

import "testing"

func TestToolCall_Fields(t *testing.T) {
	tc := ToolCall{
		ID:   "call-1",
		Type: "function",
		Name: "my_tool",
		Arguments: map[string]any{
			"param1": "value1",
		},
		Function: &FunctionCall{
			Name:      "my_tool",
			Arguments: `{"param1":"value1"}`,
		},
	}
	if tc.ID != "call-1" {
		t.Errorf("expected ID 'call-1', got %q", tc.ID)
	}
	if tc.Type != "function" {
		t.Errorf("expected Type 'function', got %q", tc.Type)
	}
	if tc.Name != "my_tool" {
		t.Errorf("expected Name 'my_tool', got %q", tc.Name)
	}
	if tc.Arguments["param1"] != "value1" {
		t.Errorf("expected param1='value1', got %v", tc.Arguments["param1"])
	}
	if tc.Function == nil || tc.Function.Name != "my_tool" {
		t.Errorf("expected Function.Name 'my_tool'")
	}
}

func TestFunctionCall_Fields(t *testing.T) {
	fc := FunctionCall{
		Name:      "search",
		Arguments: `{"query":"test"}`,
	}
	if fc.Name != "search" {
		t.Errorf("expected Name 'search', got %q", fc.Name)
	}
	if fc.Arguments != `{"query":"test"}` {
		t.Errorf("expected Arguments, got %q", fc.Arguments)
	}
}

func TestLLMResponse_Fields(t *testing.T) {
	resp := LLMResponse{
		Content:          "Hello!",
		ReasoningContent: "Let me think...",
		ToolCalls: []ToolCall{
			{ID: "tc1", Name: "tool1"},
		},
	}
	if resp.Content != "Hello!" {
		t.Errorf("expected content 'Hello!', got %q", resp.Content)
	}
	if resp.ReasoningContent != "Let me think..." {
		t.Errorf("expected reasoning content, got %q", resp.ReasoningContent)
	}
	if len(resp.ToolCalls) != 1 {
		t.Errorf("expected 1 tool call, got %d", len(resp.ToolCalls))
	}
}

func TestExtraContent_Fields(t *testing.T) {
	ec := ExtraContent{
		Google: &GoogleExtra{
			ThoughtSignature: "sig123",
		},
	}
	if ec.Google.ThoughtSignature != "sig123" {
		t.Errorf("expected sig123, got %q", ec.Google.ThoughtSignature)
	}
}
