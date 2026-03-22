package agent

import (
	"context"
	"strings"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/tools"
)

type contextTestTool struct{}

func (contextTestTool) Name() string { return "dashboard" }

func (contextTestTool) Description() string { return "test dashboard tool" }

func (contextTestTool) Parameters() map[string]any {
	return map[string]any{"type": "object"}
}

func (contextTestTool) Execute(context.Context, map[string]any) *tools.ToolResult {
	return tools.SilentResult("ok")
}

func TestBuildToolsSection_IncludesRuntimeGuidance(t *testing.T) {
	cb := NewContextBuilder(t.TempDir())
	registry := tools.NewToolRegistry()
	registry.Register(contextTestTool{})
	cb.SetToolsRegistry(registry)

	section := cb.buildToolsSection()

	for _, want := range []string{
		"Never invent tool names",
		"call `dashboard` with section `funding`",
		"call `dashboard` with section `registration`",
		"- `dashboard` - test dashboard tool",
	} {
		if !strings.Contains(section, want) {
			t.Fatalf("expected tools section to contain %q", want)
		}
	}
}
