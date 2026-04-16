package replication

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/bus"
	"github.com/GemachDAO/Gclaw/pkg/config"
)

// --- Replicator ---

func newTestReplicationConfig(tmpDir string) ReplicationConfig {
	return ReplicationConfig{
		Enabled:           true,
		MaxChildren:       3,
		GMACSharePercent:  50,
		MutatePrompt:      true,
		InheritSkills:     false,
		InheritMemory:     false,
		ChildWorkspaceDir: filepath.Join(tmpDir, "children"),
	}
}

func newMinimalConfig() *config.Config {
	cfg := config.DefaultConfig()
	cfg.Gateway.Port = 8080
	return cfg
}

func TestNewReplicator_Defaults(t *testing.T) {
	r := NewReplicator("parent-1", ReplicationConfig{})
	if r.config.MaxChildren != 3 {
		t.Errorf("expected MaxChildren=3, got %d", r.config.MaxChildren)
	}
	if r.config.GMACSharePercent != 50 {
		t.Errorf("expected GMACSharePercent=50, got %.1f", r.config.GMACSharePercent)
	}
	if r.parentID != "parent-1" {
		t.Errorf("unexpected parentID: %s", r.parentID)
	}
}

func TestCanReplicate(t *testing.T) {
	r := NewReplicator("parent", ReplicationConfig{})
	if !r.CanReplicate(100, 50) {
		t.Error("expected CanReplicate=true when goodwill >= threshold")
	}
	if r.CanReplicate(49, 50) {
		t.Error("expected CanReplicate=false when goodwill < threshold")
	}
	if !r.CanReplicate(50, 50) {
		t.Error("expected CanReplicate=true when goodwill == threshold")
	}
}

func TestReplicate_Disabled(t *testing.T) {
	r := NewReplicator("parent", ReplicationConfig{Enabled: false})
	gmac := 100.0
	_, err := r.Replicate(newMinimalConfig(), "/tmp/workspace", &gmac, nil)
	if err == nil {
		t.Error("expected error when replication is disabled")
	}
}

func TestReplicate_MaxChildren(t *testing.T) {
	dir := t.TempDir()
	cfg := newTestReplicationConfig(dir)
	cfg.MaxChildren = 1

	r := NewReplicator("parent", cfg)
	parentCfg := newMinimalConfig()
	gmac := 100.0
	workspace := dir

	_, err := r.Replicate(parentCfg, workspace, &gmac, nil)
	if err != nil {
		t.Fatalf("first replicate failed: %v", err)
	}

	gmac = 100.0
	_, err = r.Replicate(parentCfg, workspace, &gmac, nil)
	if err == nil {
		t.Error("expected error when max children reached")
	}
}

func TestReplicate_Success(t *testing.T) {
	dir := t.TempDir()
	cfg := newTestReplicationConfig(dir)

	r := NewReplicator("parent", cfg)
	parentCfg := newMinimalConfig()
	gmac := 200.0
	workspace := dir

	child, err := r.Replicate(parentCfg, workspace, &gmac, &ReplicateOptions{
		Name:         "solana scout",
		StrategyHint: "Focus on Solana momentum and bridge profits back to GMAC",
	})
	if err != nil {
		t.Fatalf("Replicate failed: %v", err)
	}

	if child.ParentID != "parent" {
		t.Errorf("unexpected ParentID: %s", child.ParentID)
	}
	if child.Status != "provisioned" {
		t.Errorf("expected status 'provisioned', got %q", child.Status)
	}
	if child.GMACBalance != 100.0 {
		t.Errorf("expected child GMAC=100, got %.2f", child.GMACBalance)
	}
	if gmac != 100.0 {
		t.Errorf("expected parent GMAC reduced to 100, got %.2f", gmac)
	}
	if child.ConfigPath == "" {
		t.Error("expected non-empty config path")
	}
	if child.Profile.Style == "" || len(child.Profile.PreferredChains) == 0 {
		t.Fatalf("expected non-empty child profile, got %+v", child.Profile)
	}
	if child.Profile.Role == "" {
		t.Fatalf("expected derived child role, got %+v", child.Profile)
	}
	if child.Profile.StrategyHint == "" {
		t.Fatalf("expected strategy hint to persist, got %+v", child.Profile)
	}

	// Verify config file was created
	if _, statErr := os.Stat(child.ConfigPath); os.IsNotExist(statErr) {
		t.Error("expected child config file to exist")
	}
	profile, err := LoadChildStrategyProfile(child.WorkspacePath)
	if err != nil {
		t.Fatalf("LoadChildStrategyProfile failed: %v", err)
	}
	if profile == nil || profile.Style != child.Profile.Style {
		t.Fatalf("expected saved profile to match child profile, got %+v", profile)
	}
}

func TestListChildren(t *testing.T) {
	dir := t.TempDir()
	cfg := newTestReplicationConfig(dir)
	r := NewReplicator("parent", cfg)
	parentCfg := newMinimalConfig()

	gmac := 200.0
	_, _ = r.Replicate(parentCfg, dir, &gmac, nil)
	gmac = 200.0
	_, _ = r.Replicate(parentCfg, dir, &gmac, nil)

	children := r.ListChildren()
	if len(children) != 2 {
		t.Errorf("expected 2 children, got %d", len(children))
	}
}

func TestGetChild(t *testing.T) {
	dir := t.TempDir()
	cfg := newTestReplicationConfig(dir)
	r := NewReplicator("parent", cfg)

	gmac := 200.0
	child, _ := r.Replicate(newMinimalConfig(), dir, &gmac, nil)

	got, ok := r.GetChild(child.ID)
	if !ok {
		t.Fatal("expected to find child")
	}
	if got.ID != child.ID {
		t.Errorf("unexpected child ID: %s", got.ID)
	}

	_, ok = r.GetChild("nonexistent")
	if ok {
		t.Error("expected not found for nonexistent child")
	}
}

func TestStopChild(t *testing.T) {
	dir := t.TempDir()
	cfg := newTestReplicationConfig(dir)
	r := NewReplicator("parent", cfg)

	gmac := 200.0
	child, _ := r.Replicate(newMinimalConfig(), dir, &gmac, nil)

	err := r.StopChild(child.ID)
	if err != nil {
		t.Fatalf("StopChild failed: %v", err)
	}

	got, _ := r.GetChild(child.ID)
	if got.Status != "stopped" {
		t.Errorf("expected status 'stopped', got %q", got.Status)
	}
}

func TestStopChild_NotFound(t *testing.T) {
	r := NewReplicator("parent", ReplicationConfig{})
	err := r.StopChild("nonexistent")
	if err == nil {
		t.Error("expected error for nonexistent child")
	}
}

// --- Persistence ---

func TestSaveAndLoadChildren(t *testing.T) {
	dir := t.TempDir()
	cfg := newTestReplicationConfig(dir)
	r := NewReplicator("parent", cfg)

	gmac := 200.0
	_, _ = r.Replicate(newMinimalConfig(), dir, &gmac, nil)

	err := r.SaveChildren(dir)
	if err != nil {
		t.Fatalf("SaveChildren failed: %v", err)
	}

	r2 := NewReplicator("parent", cfg)
	err = r2.LoadChildren(dir)
	if err != nil {
		t.Fatalf("LoadChildren failed: %v", err)
	}

	if len(r2.children) != 1 {
		t.Errorf("expected 1 child after load, got %d", len(r2.children))
	}
}

func TestLoadChildren_MissingFile(t *testing.T) {
	r := NewReplicator("parent", ReplicationConfig{})
	err := r.LoadChildren("/nonexistent/workspace")
	if err != nil {
		t.Errorf("expected no error for missing file, got: %v", err)
	}
}

// --- Mutation ---

func TestMutateSystemPrompt_EmptyParent(t *testing.T) {
	result := mutateSystemPrompt("")
	if result == "" {
		t.Error("expected non-empty mutation for empty parent")
	}
}

func TestMutateSystemPrompt_WithParent(t *testing.T) {
	result := mutateSystemPrompt("You are a helpful assistant.")
	if len(result) == 0 {
		t.Error("expected non-empty result")
	}
	if result == "You are a helpful assistant." {
		t.Error("expected result to contain mutation")
	}
}

func TestMutationPool_NotEmpty(t *testing.T) {
	if len(mutationPool) == 0 {
		t.Error("expected non-empty mutation pool")
	}
}

// --- TelepathyBus ---

func TestNewTelepathyBus(t *testing.T) {
	mb := bus.NewMessageBus()
	tb := NewTelepathyBus(mb, "family-1", "agent-1")
	if tb == nil {
		t.Fatal("expected non-nil TelepathyBus")
	}
	if tb.familyID != "family-1" {
		t.Errorf("unexpected familyID: %s", tb.familyID)
	}
}

func TestSubscribeAndBroadcast(t *testing.T) {
	tb := NewTelepathyBus(nil, "fam", "agent-1")

	ch := tb.Subscribe("agent-2")
	tb.Broadcast(TelepathyMessage{
		FromAgentID: "agent-1",
		Type:        "trade_signal",
		Content:     "buy token-abc",
		Priority:    1,
	})

	select {
	case msg := <-ch:
		if msg.Content != "buy token-abc" {
			t.Errorf("expected 'buy token-abc', got %q", msg.Content)
		}
		if msg.ToAgentID != "*" {
			t.Errorf("expected ToAgentID='*', got %q", msg.ToAgentID)
		}
	case <-time.After(time.Second):
		t.Error("timeout waiting for message")
	}
}

func TestTelepathyBus_EnableFilePersistence_ReplaysHistoryToSubscriber(t *testing.T) {
	dir := t.TempDir()
	msg := TelepathyMessage{
		FromAgentID: "parent",
		ToAgentID:   "*",
		Type:        "strategy_update",
		Content:     "rotate to bridge route",
		Timestamp:   time.Now().UnixMilli(),
	}
	if err := WriteMessage(dir, msg); err != nil {
		t.Fatalf("WriteMessage failed: %v", err)
	}

	tb := NewTelepathyBus(nil, "fam", "agent-1")
	if err := tb.EnableFilePersistence(dir); err != nil {
		t.Fatalf("EnableFilePersistence failed: %v", err)
	}
	ch := tb.Subscribe("agent-2")

	select {
	case replayed := <-ch:
		if replayed.Content != msg.Content {
			t.Fatalf("expected replayed content %q, got %q", msg.Content, replayed.Content)
		}
	case <-time.After(time.Second):
		t.Fatal("timeout waiting for replayed telepathy message")
	}
}

func TestSendTo(t *testing.T) {
	tb := NewTelepathyBus(nil, "fam", "agent-1")

	ch := tb.Subscribe("agent-2")
	tb.SendTo("agent-2", TelepathyMessage{
		FromAgentID: "agent-1",
		Type:        "strategy_update",
		Content:     "switch to momentum",
	})

	select {
	case msg := <-ch:
		if msg.Content != "switch to momentum" {
			t.Errorf("unexpected content: %q", msg.Content)
		}
		if msg.ToAgentID != "agent-2" {
			t.Errorf("expected ToAgentID='agent-2', got %q", msg.ToAgentID)
		}
	case <-time.After(time.Second):
		t.Error("timeout waiting for message")
	}
}

func TestSendTo_NoSubscriber(t *testing.T) {
	tb := NewTelepathyBus(nil, "fam", "agent-1")
	// Should not panic when target is not subscribed
	tb.SendTo("nobody", TelepathyMessage{Content: "test"})
}

func TestUnsubscribe(t *testing.T) {
	tb := NewTelepathyBus(nil, "fam", "agent-1")
	tb.Subscribe("agent-2")
	tb.Unsubscribe("agent-2")

	// Channel should be closed; verify subscriber is removed
	tb.mu.RLock()
	_, exists := tb.subscribers["agent-2"]
	tb.mu.RUnlock()
	if exists {
		t.Error("expected subscriber to be removed after unsubscribe")
	}
}

func TestGetHistory(t *testing.T) {
	tb := NewTelepathyBus(nil, "fam", "agent-1")

	for i := 0; i < 5; i++ {
		tb.Broadcast(TelepathyMessage{FromAgentID: "agent-1", Content: "msg"})
	}

	history := tb.GetHistory(3)
	if len(history) != 3 {
		t.Errorf("expected 3 history entries, got %d", len(history))
	}

	history = tb.GetHistory(0)
	if len(history) != 5 {
		t.Errorf("expected all 5 history entries, got %d", len(history))
	}
}

func TestGetHistory_LimitGreaterThanHistory(t *testing.T) {
	tb := NewTelepathyBus(nil, "fam", "agent-1")
	tb.Broadcast(TelepathyMessage{Content: "only"})

	history := tb.GetHistory(100)
	if len(history) != 1 {
		t.Errorf("expected 1 entry, got %d", len(history))
	}
}

func TestBroadcastTradeSignal(t *testing.T) {
	tb := NewTelepathyBus(nil, "fam", "agent-1")
	ch := tb.Subscribe("agent-2")

	signal := TradeSignal{
		Action:       "buy",
		TokenAddress: "0xabc",
		ChainID:      1,
		Confidence:   0.85,
		Reasoning:    "strong momentum",
	}
	tb.BroadcastTradeSignal(signal)

	select {
	case msg := <-ch:
		if msg.Type != "trade_signal" {
			t.Errorf("expected type 'trade_signal', got %q", msg.Type)
		}
	case <-time.After(time.Second):
		t.Error("timeout")
	}
}

func TestBroadcast_AutoTimestamp(t *testing.T) {
	tb := NewTelepathyBus(nil, "fam", "agent-1")
	ch := tb.Subscribe("agent-2")

	tb.Broadcast(TelepathyMessage{FromAgentID: "agent-1", Content: "test"})

	select {
	case msg := <-ch:
		if msg.Timestamp == 0 {
			t.Error("expected non-zero timestamp")
		}
	case <-time.After(time.Second):
		t.Error("timeout")
	}
}

// --- TelepathyFile ---

func TestWriteMessage(t *testing.T) {
	dir := t.TempDir()
	msg := TelepathyMessage{
		FromAgentID: "agent-1",
		ToAgentID:   "*",
		Type:        "trade_signal",
		Content:     "buy SOL",
		Timestamp:   time.Now().UnixMilli(),
	}

	err := WriteMessage(dir, msg)
	if err != nil {
		t.Fatalf("WriteMessage failed: %v", err)
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("ReadDir failed: %v", err)
	}
	if len(entries) != 1 {
		t.Errorf("expected 1 file, got %d", len(entries))
	}
}

func TestWriteMessage_AutoTimestamp(t *testing.T) {
	dir := t.TempDir()
	msg := TelepathyMessage{
		FromAgentID: "agent-1",
		Content:     "test",
	}

	err := WriteMessage(dir, msg)
	if err != nil {
		t.Fatalf("WriteMessage failed: %v", err)
	}

	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 {
		t.Fatalf("expected 1 file, got %d", len(entries))
	}
}

func TestTelepathyDir(t *testing.T) {
	got := TelepathyDir("/workspace", "family-abc")
	expected := "/workspace/replication/telepathy/family-abc"
	if got != expected {
		t.Errorf("expected %q, got %q", expected, got)
	}
}

func TestStartFileWatcher(t *testing.T) {
	dir := t.TempDir()
	done := make(chan struct{})
	received := make(chan TelepathyMessage, 1)

	go StartFileWatcher(dir, 50*time.Millisecond, time.Hour, func(msg TelepathyMessage) {
		received <- msg
	}, done)

	// Write a message file
	msg := TelepathyMessage{
		FromAgentID: "agent-1",
		Content:     "hello from watcher",
		Timestamp:   time.Now().UnixMilli(),
	}
	if err := WriteMessage(dir, msg); err != nil {
		t.Fatalf("WriteMessage failed: %v", err)
	}

	select {
	case got := <-received:
		if got.Content != "hello from watcher" {
			t.Errorf("unexpected content: %q", got.Content)
		}
	case <-time.After(2 * time.Second):
		t.Error("timeout waiting for watcher callback")
	}

	close(done)
}

func TestSanitizeID(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"agent-1", "agent-1"},
		{"path/to/agent", "path_to_agent"},
		{"agent:1", "agent_1"},
		{"agent*name", "agent_name"},
		{"normal", "normal"},
	}

	for _, tt := range tests {
		got := sanitizeID(tt.input)
		if got != tt.expected {
			t.Errorf("sanitizeID(%q) = %q, want %q", tt.input, got, tt.expected)
		}
	}
}

func TestFormatFloat(t *testing.T) {
	got := formatFloat(0.85)
	if got != "0.85" {
		t.Errorf("formatFloat(0.85) = %q, want '0.85'", got)
	}
}
