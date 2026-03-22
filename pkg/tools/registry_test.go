package tools

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/metabolism"
	"github.com/GemachDAO/Gclaw/pkg/providers"
)

// --- mock types ---

type mockRegistryTool struct {
	name   string
	desc   string
	params map[string]any
	result *ToolResult
}

func (m *mockRegistryTool) Name() string               { return m.name }
func (m *mockRegistryTool) Description() string        { return m.desc }
func (m *mockRegistryTool) Parameters() map[string]any { return m.params }
func (m *mockRegistryTool) Execute(_ context.Context, _ map[string]any) *ToolResult {
	return m.result
}

type mockCtxTool struct {
	mockRegistryTool
	channel string
	chatID  string
}

func (m *mockCtxTool) SetContext(channel, chatID string) {
	m.channel = channel
	m.chatID = chatID
}

type mockAsyncRegistryTool struct {
	mockRegistryTool
	cb AsyncCallback
}

func (m *mockAsyncRegistryTool) SetCallback(cb AsyncCallback) {
	m.cb = cb
}

// --- helpers ---

func newMockTool(name, desc string) *mockRegistryTool {
	return &mockRegistryTool{
		name:   name,
		desc:   desc,
		params: map[string]any{"type": "object"},
		result: SilentResult("ok"),
	}
}

// --- tests ---

func TestNewToolRegistry(t *testing.T) {
	r := NewToolRegistry()
	if r.Count() != 0 {
		t.Errorf("expected empty registry, got count %d", r.Count())
	}
	if len(r.List()) != 0 {
		t.Errorf("expected empty list, got %v", r.List())
	}
}

func TestDefaultToolCosts_AreLowBurn(t *testing.T) {
	for tool, want := range map[string]float64{
		"gdex_buy":      0.001,
		"gdex_scan":     0.0025,
		"gdex_holdings": 0.001,
		"spawn":         0.01,
	} {
		if got := DefaultToolCosts[tool]; got != want {
			t.Fatalf("DefaultToolCosts[%q] = %.3f, want %.3f", tool, got, want)
		}
	}
}

func TestDefaultToolCosts_AutoTradeCycleIsNearPointZeroOneGMAC(t *testing.T) {
	cycleCost := 2*DefaultToolCosts["gdex_holdings"] +
		2*DefaultToolCosts["gdex_scan"] +
		2*DefaultToolCosts["gdex_trending"] +
		DefaultToolCosts["gdex_buy"]
	if cycleCost > 0.01 {
		t.Fatalf("expected standard auto-trade cycle cost <= 0.01 GMAC, got %.6f", cycleCost)
	}
}

func TestToolRegistry_RegisterAndGet(t *testing.T) {
	r := NewToolRegistry()
	tool := newMockTool("echo", "echoes input")
	r.Register(tool)

	got, ok := r.Get("echo")
	if !ok {
		t.Fatal("expected to find registered tool")
	}
	if got.Name() != "echo" {
		t.Errorf("expected name 'echo', got %q", got.Name())
	}
}

func TestToolRegistry_Get_NotFound(t *testing.T) {
	r := NewToolRegistry()
	_, ok := r.Get("nonexistent")
	if ok {
		t.Error("expected ok=false for unregistered tool")
	}
}

func TestToolRegistry_RegisterOverwrite(t *testing.T) {
	r := NewToolRegistry()
	r.Register(newMockTool("dup", "first"))
	r.Register(newMockTool("dup", "second"))

	if r.Count() != 1 {
		t.Errorf("expected count 1 after overwrite, got %d", r.Count())
	}
	tool, _ := r.Get("dup")
	if tool.Description() != "second" {
		t.Errorf("expected overwritten description 'second', got %q", tool.Description())
	}
}

func TestToolRegistry_Execute_Success(t *testing.T) {
	r := NewToolRegistry()
	r.Register(&mockRegistryTool{
		name:   "greet",
		desc:   "says hello",
		params: map[string]any{},
		result: SilentResult("hello"),
	})

	result := r.Execute(context.Background(), "greet", nil)
	if result.IsError {
		t.Errorf("expected success, got error: %s", result.ForLLM)
	}
	if result.ForLLM != "hello" {
		t.Errorf("expected ForLLM 'hello', got %q", result.ForLLM)
	}
}

func TestToolRegistry_Execute_NotFound(t *testing.T) {
	r := NewToolRegistry()
	result := r.Execute(context.Background(), "missing", nil)
	if !result.IsError {
		t.Error("expected error for missing tool")
	}
	if !strings.Contains(result.ForLLM, "not found") {
		t.Errorf("expected 'not found' in error, got %q", result.ForLLM)
	}
	if result.Err == nil {
		t.Error("expected Err to be set via WithError")
	}
}

func TestToolRegistry_ExecuteWithContext_ContextualTool(t *testing.T) {
	r := NewToolRegistry()
	ct := &mockCtxTool{
		mockRegistryTool: *newMockTool("ctx_tool", "needs context"),
	}
	r.Register(ct)

	r.ExecuteWithContext(context.Background(), "ctx_tool", nil, "telegram", "chat-42", nil)

	if ct.channel != "telegram" {
		t.Errorf("expected channel 'telegram', got %q", ct.channel)
	}
	if ct.chatID != "chat-42" {
		t.Errorf("expected chatID 'chat-42', got %q", ct.chatID)
	}
}

func TestToolRegistry_ExecuteWithContext_SkipsEmptyContext(t *testing.T) {
	r := NewToolRegistry()
	ct := &mockCtxTool{
		mockRegistryTool: *newMockTool("ctx_tool", "needs context"),
	}
	r.Register(ct)

	r.ExecuteWithContext(context.Background(), "ctx_tool", nil, "", "", nil)

	if ct.channel != "" || ct.chatID != "" {
		t.Error("SetContext should not be called with empty channel/chatID")
	}
}

func TestToolRegistry_ExecuteWithContext_AsyncCallback(t *testing.T) {
	r := NewToolRegistry()
	at := &mockAsyncRegistryTool{
		mockRegistryTool: *newMockTool("async_tool", "async work"),
	}
	at.result = AsyncResult("started")
	r.Register(at)

	called := false
	cb := func(_ context.Context, _ *ToolResult) { called = true }

	result := r.ExecuteWithContext(context.Background(), "async_tool", nil, "", "", cb)
	if at.cb == nil {
		t.Error("expected SetCallback to have been called")
	}
	if !result.Async {
		t.Error("expected async result")
	}

	at.cb(context.Background(), SilentResult("done"))
	if !called {
		t.Error("expected callback to be invoked")
	}
}

func TestToolRegistry_TradeObserverRunsWithoutMetabolism(t *testing.T) {
	r := NewToolRegistry()
	r.Register(&mockRegistryTool{
		name:   "gdex_buy",
		desc:   "buy token",
		params: map[string]any{"type": "object"},
		result: SilentResult(`{"tokenAddress":"0xabc","amount":"1.5","chainID":1}`),
	})

	var observed TradeRecord
	called := 0
	r.AddTradeObserver(func(record TradeRecord) {
		called++
		observed = record
	})

	result := r.Execute(context.Background(), "gdex_buy", nil)
	if result.IsError {
		t.Fatalf("expected success, got %s", result.ForLLM)
	}
	if called != 1 {
		t.Fatalf("expected 1 observer call, got %d", called)
	}
	if observed.Action != "buy" {
		t.Fatalf("expected action buy, got %q", observed.Action)
	}
	if observed.TokenAddress != "0xabc" {
		t.Fatalf("expected token address 0xabc, got %q", observed.TokenAddress)
	}
	history := r.GetTradeHistory(10)
	if len(history) != 1 {
		t.Fatalf("expected trade history to record 1 trade, got %d", len(history))
	}
}

func TestToolRegistry_PersistsTradeHistory(t *testing.T) {
	r := NewToolRegistry()
	path := filepath.Join(t.TempDir(), "runtime", "trade_history.json")
	if err := r.SetTradeHistoryPersistence(path); err != nil {
		t.Fatalf("SetTradeHistoryPersistence failed: %v", err)
	}
	r.Register(&mockRegistryTool{
		name:   "gdex_buy",
		desc:   "buy token",
		params: map[string]any{"type": "object"},
		result: SilentResult(`{"tokenAddress":"0xabc","amount":"1.5","chainID":1}`),
	})

	result := r.Execute(context.Background(), "gdex_buy", nil)
	if result.IsError {
		t.Fatalf("expected successful trade execution, got %s", result.ForLLM)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("expected persisted trade history file, got %v", err)
	}

	reloaded := NewToolRegistry()
	if err := reloaded.SetTradeHistoryPersistence(path); err != nil {
		t.Fatalf("reloading trade history failed: %v", err)
	}
	history := reloaded.GetTradeHistory(0)
	if len(history) != 1 {
		t.Fatalf("expected 1 persisted trade, got %d", len(history))
	}
	if history[0].TokenAddress != "0xabc" {
		t.Fatalf("unexpected persisted trade history: %+v", history[0])
	}
}

func TestToolRegistry_RefreshesPersistedTradeHistoryOnRead(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime", "trade_history.json")

	gateway := NewToolRegistry()
	if err := gateway.SetTradeHistoryPersistence(path); err != nil {
		t.Fatalf("gateway persistence setup failed: %v", err)
	}

	worker := NewToolRegistry()
	if err := worker.SetTradeHistoryPersistence(path); err != nil {
		t.Fatalf("worker persistence setup failed: %v", err)
	}
	worker.Register(&mockRegistryTool{
		name:   "gdex_buy",
		desc:   "buy token",
		params: map[string]any{"type": "object"},
		result: SilentResult(`{"tokenAddress":"0xdef","amount":"0.25","chainID":42161}`),
	})

	if got := gateway.GetTradeHistory(0); len(got) != 0 {
		t.Fatalf("expected empty gateway history before external write, got %d", len(got))
	}

	time.Sleep(5 * time.Millisecond)
	result := worker.Execute(context.Background(), "gdex_buy", nil)
	if result.IsError {
		t.Fatalf("expected successful worker trade execution, got %s", result.ForLLM)
	}

	history := gateway.GetTradeHistory(0)
	if len(history) != 1 {
		t.Fatalf("expected gateway to observe 1 persisted trade after refresh, got %d", len(history))
	}
	if history[0].TokenAddress != "0xdef" || history[0].ChainID != 42161 {
		t.Fatalf("unexpected refreshed trade history: %+v", history[0])
	}
}

func TestToolRegistry_GetDefinitions(t *testing.T) {
	r := NewToolRegistry()
	r.Register(newMockTool("alpha", "tool A"))

	defs := r.GetDefinitions()
	if len(defs) != 1 {
		t.Fatalf("expected 1 definition, got %d", len(defs))
	}
	if defs[0]["type"] != "function" {
		t.Errorf("expected type 'function', got %v", defs[0]["type"])
	}
	fn, ok := defs[0]["function"].(map[string]any)
	if !ok {
		t.Fatal("expected 'function' key to be a map")
	}
	if fn["name"] != "alpha" {
		t.Errorf("expected name 'alpha', got %v", fn["name"])
	}
	if fn["description"] != "tool A" {
		t.Errorf("expected description 'tool A', got %v", fn["description"])
	}
}

func TestToolRegistry_ToProviderDefs(t *testing.T) {
	r := NewToolRegistry()
	params := map[string]any{"type": "object", "properties": map[string]any{}}
	r.Register(&mockRegistryTool{
		name:   "beta",
		desc:   "tool B",
		params: params,
		result: SilentResult("ok"),
	})

	defs := r.ToProviderDefs()
	if len(defs) != 1 {
		t.Fatalf("expected 1 provider def, got %d", len(defs))
	}

	want := providers.ToolDefinition{
		Type: "function",
		Function: providers.ToolFunctionDefinition{
			Name:        "beta",
			Description: "tool B",
			Parameters:  params,
		},
	}
	got := defs[0]
	if got.Type != want.Type {
		t.Errorf("Type: want %q, got %q", want.Type, got.Type)
	}
	if got.Function.Name != want.Function.Name {
		t.Errorf("Name: want %q, got %q", want.Function.Name, got.Function.Name)
	}
	if got.Function.Description != want.Function.Description {
		t.Errorf("Description: want %q, got %q", want.Function.Description, got.Function.Description)
	}
}

func TestToolRegistry_List(t *testing.T) {
	r := NewToolRegistry()
	r.Register(newMockTool("x", ""))
	r.Register(newMockTool("y", ""))

	names := r.List()
	if len(names) != 2 {
		t.Fatalf("expected 2 names, got %d", len(names))
	}

	nameSet := map[string]bool{}
	for _, n := range names {
		nameSet[n] = true
	}
	if !nameSet["x"] || !nameSet["y"] {
		t.Errorf("expected names {x, y}, got %v", names)
	}
}

func TestToolRegistry_Count(t *testing.T) {
	r := NewToolRegistry()
	if r.Count() != 0 {
		t.Errorf("expected 0, got %d", r.Count())
	}

	r.Register(newMockTool("a", ""))
	r.Register(newMockTool("b", ""))
	if r.Count() != 2 {
		t.Errorf("expected 2, got %d", r.Count())
	}

	r.Register(newMockTool("a", "replaced"))
	if r.Count() != 2 {
		t.Errorf("expected 2 after overwrite, got %d", r.Count())
	}
}

func TestToolRegistry_GetSummaries(t *testing.T) {
	r := NewToolRegistry()
	r.Register(newMockTool("read_file", "Reads a file"))

	summaries := r.GetSummaries()
	if len(summaries) != 1 {
		t.Fatalf("expected 1 summary, got %d", len(summaries))
	}
	if !strings.Contains(summaries[0], "`read_file`") {
		t.Errorf("expected backtick-quoted name in summary, got %q", summaries[0])
	}
	if !strings.Contains(summaries[0], "Reads a file") {
		t.Errorf("expected description in summary, got %q", summaries[0])
	}
}

func TestToolToSchema(t *testing.T) {
	tool := newMockTool("demo", "demo tool")
	schema := ToolToSchema(tool)

	if schema["type"] != "function" {
		t.Errorf("expected type 'function', got %v", schema["type"])
	}
	fn, ok := schema["function"].(map[string]any)
	if !ok {
		t.Fatal("expected 'function' to be a map")
	}
	if fn["name"] != "demo" {
		t.Errorf("expected name 'demo', got %v", fn["name"])
	}
	if fn["description"] != "demo tool" {
		t.Errorf("expected description 'demo tool', got %v", fn["description"])
	}
	if fn["parameters"] == nil {
		t.Error("expected parameters to be set")
	}
}

func TestToolRegistry_ConcurrentAccess(t *testing.T) {
	r := NewToolRegistry()
	var wg sync.WaitGroup

	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			name := string(rune('A' + n%26))
			r.Register(newMockTool(name, "concurrent"))
			r.Get(name)
			r.Count()
			r.List()
			r.GetDefinitions()
		}(i)
	}

	wg.Wait()

	if r.Count() == 0 {
		t.Error("expected tools to be registered after concurrent access")
	}
}

func TestToolRegistry_RecordsTradeHistory(t *testing.T) {
	r := NewToolRegistry()
	r.SetMetabolism(metabolism.NewMetabolism(1000, metabolism.Thresholds{}))
	r.Register(&mockRegistryTool{
		name:   "gdex_buy",
		desc:   "buy token",
		params: map[string]any{"type": "object"},
		result: SilentResult(`{"token_address":"0xgmac","amount":"1000","chain_id":8453}`),
	})

	result := r.Execute(context.Background(), "gdex_buy", nil)
	if result.IsError {
		t.Fatalf("unexpected tool error: %s", result.ForLLM)
	}

	history := r.GetTradeHistory(10)
	if len(history) != 1 {
		t.Fatalf("expected 1 trade history record, got %d", len(history))
	}
	if history[0].TokenAddress != "0xgmac" {
		t.Fatalf("expected token address to be recorded, got %q", history[0].TokenAddress)
	}
	if history[0].ChainID != 8453 {
		t.Fatalf("expected chain id 8453, got %d", history[0].ChainID)
	}
}

func TestToolRegistry_TradeHistoryFallsBackToArgsWhenHelperOmitsFields(t *testing.T) {
	r := NewToolRegistry()
	r.SetMetabolism(metabolism.NewMetabolism(1000, metabolism.Thresholds{}))
	r.Register(&mockRegistryTool{
		name:   "gdex_buy",
		desc:   "buy token",
		params: map[string]any{"type": "object"},
		result: SilentResult(`{"requestId":"abc123","status":"processing"}`),
	})

	result := r.Execute(context.Background(), "gdex_buy", map[string]any{
		"token_address": "0xgmac",
		"amount":        "0.01",
		"chain_id":      8453,
	})
	if result.IsError {
		t.Fatalf("unexpected tool error: %s", result.ForLLM)
	}

	history := r.GetTradeHistory(10)
	if len(history) != 1 {
		t.Fatalf("expected 1 trade history record, got %d", len(history))
	}
	if history[0].TokenAddress != "0xgmac" {
		t.Fatalf("expected token address fallback to args, got %q", history[0].TokenAddress)
	}
	if history[0].Amount != "0.01" {
		t.Fatalf("expected amount fallback to args, got %q", history[0].Amount)
	}
	if history[0].ChainID != 8453 {
		t.Fatalf("expected chain id fallback to args, got %d", history[0].ChainID)
	}
	if history[0].HasPnL {
		t.Fatal("expected no realized PnL for request/status-only result")
	}
}
