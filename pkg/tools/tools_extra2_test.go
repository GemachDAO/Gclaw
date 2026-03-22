package tools

import (
	"context"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/cron"
	"github.com/GemachDAO/Gclaw/pkg/dashboard"
	"github.com/GemachDAO/Gclaw/pkg/recode"
	"github.com/GemachDAO/Gclaw/pkg/replication"
	"github.com/GemachDAO/Gclaw/pkg/swarm"
)

// --- GDEX Tools: Name/Description/Parameters ---

func TestGDEXTrendingTool(t *testing.T) {
	tool := &GDEXTrendingTool{}
	if tool.Name() != "gdex_trending" {
		t.Errorf("expected 'gdex_trending', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestGDEXSearchTool(t *testing.T) {
	tool := &GDEXSearchTool{}
	if tool.Name() != "gdex_search" {
		t.Errorf("expected 'gdex_search', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestGDEXPriceTool(t *testing.T) {
	tool := &GDEXPriceTool{}
	if tool.Name() != "gdex_price" {
		t.Errorf("expected 'gdex_price', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestGDEXHoldingsTool(t *testing.T) {
	tool := &GDEXHoldingsTool{}
	if tool.Name() == "" {
		t.Error("expected non-empty name for holdings tool")
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
}

func TestGDEXScanTool(t *testing.T) {
	tool := &GDEXScanTool{}
	if tool.Name() == "" {
		t.Error("expected non-empty name for scan tool")
	}
}

// --- GDEX Advanced Tools ---

func TestGDEXCopyTradeTool(t *testing.T) {
	tool := &GDEXCopyTradeTool{}
	if tool.Name() == "" {
		t.Error("expected non-empty name for copy trade tool")
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestGDEXHLBalanceTool(t *testing.T) {
	tool := &GDEXHLBalanceTool{}
	if tool.Name() == "" {
		t.Error("expected non-empty name")
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
}

func TestGDEXHLDepositTool(t *testing.T) {
	tool := &GDEXHLDepositTool{}
	if tool.Name() != "gdex_hl_deposit" {
		t.Errorf("expected 'gdex_hl_deposit', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
	properties, _ := tool.Parameters()["properties"].(map[string]any)
	if _, ok := properties["auto_fund_from_native"]; !ok {
		t.Fatal("expected auto_fund_from_native parameter")
	}
	// Missing required amount
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when amount is missing")
	}
}

func TestGDEXHLWithdrawTool(t *testing.T) {
	tool := &GDEXHLWithdrawTool{}
	if tool.Name() != "gdex_hl_withdraw" {
		t.Errorf("expected 'gdex_hl_withdraw', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when amount is missing")
	}
}

func TestGDEXBridgeEstimateTool(t *testing.T) {
	tool := &GDEXBridgeEstimateTool{}
	if tool.Name() != "gdex_bridge_estimate" {
		t.Errorf("expected 'gdex_bridge_estimate', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when bridge params are missing")
	}
}

func TestGDEXBridgeRequestTool(t *testing.T) {
	tool := &GDEXBridgeRequestTool{}
	if tool.Name() != "gdex_bridge_request" {
		t.Errorf("expected 'gdex_bridge_request', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when bridge params are missing")
	}
}

func TestGDEXBridgeOrdersTool(t *testing.T) {
	tool := &GDEXBridgeOrdersTool{}
	if tool.Name() != "gdex_bridge_orders" {
		t.Errorf("expected 'gdex_bridge_orders', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestGDEXHLCreateOrderTool(t *testing.T) {
	tool := &GDEXHLCreateOrderTool{}
	if tool.Name() != "gdex_hl_create_order" {
		t.Errorf("expected 'gdex_hl_create_order', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
	// Missing required fields
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when coin/price/size are missing")
	}
}

func TestGDEXHLCancelOrderTool(t *testing.T) {
	tool := &GDEXHLCancelOrderTool{}
	if tool.Name() != "gdex_hl_cancel_order" {
		t.Errorf("expected 'gdex_hl_cancel_order', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
	// Missing required fields
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when coin/order_id are missing")
	}
}

// --- GDEX Trade Tool ---

func TestGDEXBuyTool(t *testing.T) {
	tool := &GDEXBuyTool{}
	if tool.Name() == "" {
		t.Error("expected non-empty name")
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestGDEXSellTool(t *testing.T) {
	tool := &GDEXSellTool{}
	if tool.Name() == "" {
		t.Error("expected non-empty name")
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
}

// --- CronTool: Name/Description/Parameters/SetContext ---

func TestCronTool_NameDescriptionParams(t *testing.T) {
	storePath := t.TempDir() + "/cron/jobs.json"
	cronSvc := cron.NewCronService(storePath, nil)
	tool := NewCronTool(cronSvc, nil, nil, t.TempDir(), false, 0, nil)

	if tool.Name() != "cron" {
		t.Errorf("expected 'cron', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestCronTool_SetContext(t *testing.T) {
	storePath := t.TempDir() + "/cron/jobs.json"
	cronSvc := cron.NewCronService(storePath, nil)
	tool := NewCronTool(cronSvc, nil, nil, t.TempDir(), false, 0, nil)

	tool.SetContext("telegram", "12345")

	tool.mu.RLock()
	ch := tool.channel
	cid := tool.chatID
	tool.mu.RUnlock()

	if ch != "telegram" {
		t.Errorf("expected channel 'telegram', got %q", ch)
	}
	if cid != "12345" {
		t.Errorf("expected chatID '12345', got %q", cid)
	}
}

func TestCronTool_Execute_InvalidAction(t *testing.T) {
	storePath := t.TempDir() + "/cron/jobs.json"
	cronSvc := cron.NewCronService(storePath, nil)
	tool := NewCronTool(cronSvc, nil, nil, t.TempDir(), false, 0, nil)

	result := tool.Execute(context.Background(), map[string]any{
		"action": "invalid",
	})
	if !result.IsError {
		t.Error("expected error for invalid action")
	}
}

func TestCronTool_Execute_MissingAction(t *testing.T) {
	storePath := t.TempDir() + "/cron/jobs.json"
	cronSvc := cron.NewCronService(storePath, nil)
	tool := NewCronTool(cronSvc, nil, nil, t.TempDir(), false, 0, nil)

	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error when action is missing")
	}
}

func TestCronTool_Execute_List(t *testing.T) {
	storePath := t.TempDir() + "/cron/jobs.json"
	cronSvc := cron.NewCronService(storePath, nil)
	tool := NewCronTool(cronSvc, nil, nil, t.TempDir(), false, 0, nil)

	result := tool.Execute(context.Background(), map[string]any{
		"action": "list",
	})
	if result.IsError {
		t.Errorf("expected no error for list, got: %s", result.ForLLM)
	}
}

func TestCronTool_Execute_Remove_Missing(t *testing.T) {
	storePath := t.TempDir() + "/cron/jobs.json"
	cronSvc := cron.NewCronService(storePath, nil)
	tool := NewCronTool(cronSvc, nil, nil, t.TempDir(), false, 0, nil)

	result := tool.Execute(context.Background(), map[string]any{
		"action": "remove",
		// no job_id
	})
	if !result.IsError {
		t.Error("expected error when job_id is missing for remove")
	}
}

func TestCronTool_Execute_Enable(t *testing.T) {
	storePath := t.TempDir() + "/cron/jobs.json"
	cronSvc := cron.NewCronService(storePath, nil)
	tool := NewCronTool(cronSvc, nil, nil, t.TempDir(), false, 0, nil)

	result := tool.Execute(context.Background(), map[string]any{
		"action": "enable",
		"job_id": "nonexistent",
	})
	// Should return error or not found result
	_ = result
}

// --- DashboardTool: execute sections with data ---

func TestDashboardTool_Execute_Metabolism(t *testing.T) {
	dash := dashboard.NewDashboard(dashboard.DashboardOptions{
		AgentID: "test",
		GetMetabolism: func() *dashboard.MetabolismSnapshot {
			return &dashboard.MetabolismSnapshot{Balance: 100}
		},
	})
	tool := NewDashboardTool(dash)
	result := tool.Execute(context.Background(), map[string]any{"section": "metabolism"})
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	if result.IsError {
		t.Errorf("unexpected error: %s", result.ForLLM)
	}
}

// --- ReplicateTool: Name/Description/Parameters/Execute ---

func TestReplicateTool_NameDescriptionParams(t *testing.T) {
	r := replication.NewReplicator("parent", replication.ReplicationConfig{})
	tool := NewReplicateTool(r, nil, t.TempDir(), nil, func() int { return 0 }, 100)
	if tool.Name() != "replicate" {
		t.Errorf("expected 'replicate', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestReplicateTool_Execute_InsufficientGoodwill(t *testing.T) {
	r := replication.NewReplicator("parent", replication.ReplicationConfig{})
	tool := NewReplicateTool(r, nil, t.TempDir(), nil, func() int { return 50 }, 100)
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error for insufficient goodwill")
	}
}

// --- SwarmTool: Name/Description/Parameters ---

func TestSwarmTool_NameDescriptionParams(t *testing.T) {
	sc := swarm.NewSwarmCoordinator("leader", swarm.SwarmConfig{}, nil)
	tool := NewSwarmTool(sc, func() int { return 0 }, 200)
	if tool.Name() != "swarm" {
		t.Errorf("expected 'swarm', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestSwarmTool_Execute_InsufficientGoodwill(t *testing.T) {
	sc := swarm.NewSwarmCoordinator("leader", swarm.SwarmConfig{}, nil)
	tool := NewSwarmTool(sc, func() int { return 50 }, 200)
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error for insufficient goodwill")
	}
}

func TestSwarmTool_SubmitSignalDefaultsAgentIDAndPersists(t *testing.T) {
	sc := swarm.NewSwarmCoordinator("leader", swarm.SwarmConfig{}, nil)
	tool := NewSwarmTool(sc, func() int { return 500 }, 200)
	dir := t.TempDir()
	tool.SetRuntimeContext("leader", func() error {
		return swarm.SaveSwarmState(dir, sc)
	})

	result := tool.Execute(context.Background(), map[string]any{
		"action":        "submit_signal",
		"token_address": "0xabc",
		"action_signal": "buy",
	})
	if result.IsError {
		t.Fatalf("expected signal submission to succeed, got %s", result.ForLLM)
	}

	signals := sc.GetSignals("0xabc")
	if len(signals) != 1 {
		t.Fatalf("expected 1 signal, got %d", len(signals))
	}
	if signals[0].AgentID != "leader" {
		t.Fatalf("expected default agent_id leader, got %q", signals[0].AgentID)
	}

	loaded, err := swarm.LoadSwarmState(dir)
	if err != nil {
		t.Fatalf("LoadSwarmState failed: %v", err)
	}
	if got := len(loaded.GetSignals("0xabc")); got != 1 {
		t.Fatalf("expected persisted signal count 1, got %d", got)
	}
}

// --- TelepathyTool: Name/Description/Parameters ---

func TestTelepathyTool_NameDescriptionParams(t *testing.T) {
	tb := replication.NewTelepathyBus(nil, "fam", "agent-1")
	tool := NewTelepathyTool(tb, "agent-1")
	if tool.Name() != "telepathy" {
		t.Errorf("expected 'telepathy', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestTelepathyTool_Execute_MissingContent(t *testing.T) {
	tb := replication.NewTelepathyBus(nil, "fam", "agent-1")
	tool := NewTelepathyTool(tb, "agent-1")
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error for missing content")
	}
}

func TestTelepathyTool_Execute_Success(t *testing.T) {
	tb := replication.NewTelepathyBus(nil, "fam", "agent-1")
	tool := NewTelepathyTool(tb, "agent-1")
	result := tool.Execute(context.Background(), map[string]any{
		"content": "test message",
		"type":    "market_insight",
		"to":      "*",
	})
	if result.IsError {
		t.Errorf("unexpected error: %s", result.ForLLM)
	}
}

// --- RecodeTool ---

func TestRecodeTool_NameDescriptionParams(t *testing.T) {
	rc := recode.NewRecoder(t.TempDir()+"/config.json", t.TempDir())
	tool := NewRecodeTool(rc, func() int { return 200 }, 100)
	if tool.Name() != "self_recode" {
		t.Errorf("expected 'self_recode', got %q", tool.Name())
	}
	if tool.Description() == "" {
		t.Error("expected non-empty description")
	}
	if tool.Parameters() == nil {
		t.Error("expected non-nil parameters")
	}
}

func TestRecodeTool_Execute_NilRecoder(t *testing.T) {
	tool := NewRecodeTool(nil, nil, 0)
	result := tool.Execute(context.Background(), map[string]any{
		"action": "modify_prompt",
		"value":  "test",
	})
	if !result.IsError {
		t.Error("expected error for nil recoder")
	}
}

func TestRecodeTool_Execute_InsufficientGoodwill(t *testing.T) {
	rc := recode.NewRecoder(t.TempDir()+"/config.json", t.TempDir())
	tool := NewRecodeTool(rc, func() int { return 50 }, 100)
	result := tool.Execute(context.Background(), map[string]any{
		"action": "modify_prompt",
		"value":  "test",
	})
	if !result.IsError {
		t.Error("expected error for insufficient goodwill")
	}
}

func TestRecodeTool_Execute_MissingAction(t *testing.T) {
	rc := recode.NewRecoder(t.TempDir()+"/config.json", t.TempDir())
	tool := NewRecodeTool(rc, func() int { return 200 }, 100)
	result := tool.Execute(context.Background(), map[string]any{})
	if !result.IsError {
		t.Error("expected error for missing action")
	}
}
