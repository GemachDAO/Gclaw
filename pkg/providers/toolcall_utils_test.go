package providers

import (
	"testing"
)

func TestNormalizeToolCall_NameFromFunction(t *testing.T) {
	tc := ToolCall{
		Function: &FunctionCall{
			Name:      "my_tool",
			Arguments: `{"key":"value"}`,
		},
	}
	result := NormalizeToolCall(tc)
	if result.Name != "my_tool" {
		t.Errorf("expected Name 'my_tool', got %q", result.Name)
	}
	if result.Arguments["key"] != "value" {
		t.Errorf("expected key='value', got %v", result.Arguments["key"])
	}
}

func TestNormalizeToolCall_NilArguments(t *testing.T) {
	tc := ToolCall{
		Name:      "tool",
		Arguments: nil,
	}
	result := NormalizeToolCall(tc)
	if result.Arguments == nil {
		t.Error("expected non-nil Arguments after normalization")
	}
}

func TestNormalizeToolCall_EmptyArguments(t *testing.T) {
	tc := ToolCall{
		Name:      "tool",
		Arguments: map[string]any{},
		Function: &FunctionCall{
			Name:      "tool",
			Arguments: `{"x":1}`,
		},
	}
	result := NormalizeToolCall(tc)
	if result.Arguments["x"] == nil {
		t.Error("expected Arguments to be parsed from Function.Arguments")
	}
}

func TestNormalizeToolCall_NoFunction(t *testing.T) {
	tc := ToolCall{
		Name: "my_func",
		Arguments: map[string]any{
			"param": "val",
		},
	}
	result := NormalizeToolCall(tc)
	if result.Function == nil {
		t.Fatal("expected Function to be created")
	}
	if result.Function.Name != "my_func" {
		t.Errorf("expected Function.Name 'my_func', got %q", result.Function.Name)
	}
}

func TestNormalizeToolCall_EmptyFunctionArguments(t *testing.T) {
	tc := ToolCall{
		Name: "tool",
		Arguments: map[string]any{
			"k": "v",
		},
		Function: &FunctionCall{
			Name:      "tool",
			Arguments: "",
		},
	}
	result := NormalizeToolCall(tc)
	if result.Function.Arguments == "" {
		t.Error("expected Function.Arguments to be populated")
	}
}

func TestNormalizeToolCall_FunctionNameEmpty(t *testing.T) {
	tc := ToolCall{
		Name: "toolname",
		Function: &FunctionCall{
			Name:      "",
			Arguments: `{}`,
		},
	}
	result := NormalizeToolCall(tc)
	if result.Function.Name != "toolname" {
		t.Errorf("expected Function.Name 'toolname', got %q", result.Function.Name)
	}
}
