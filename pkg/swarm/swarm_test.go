package swarm

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/replication"
)

func newTestCoordinator(leaderID string) *SwarmCoordinator {
	return NewSwarmCoordinator(leaderID, SwarmConfig{}, nil)
}

// --- NewSwarmCoordinator ---

func TestNewSwarmCoordinator_Defaults(t *testing.T) {
	sc := NewSwarmCoordinator("leader-1", SwarmConfig{}, nil)
	if sc == nil {
		t.Fatal("expected non-nil SwarmCoordinator")
	}
	if sc.config.MaxSwarmSize != 5 {
		t.Errorf("expected MaxSwarmSize=5, got %d", sc.config.MaxSwarmSize)
	}
	if sc.config.ConsensusThreshold != 0.6 {
		t.Errorf("expected ConsensusThreshold=0.6, got %.2f", sc.config.ConsensusThreshold)
	}
	if sc.config.SignalAggregation != "majority" {
		t.Errorf("expected SignalAggregation='majority', got %q", sc.config.SignalAggregation)
	}
	if sc.config.RebalanceInterval != 60 {
		t.Errorf("expected RebalanceInterval=60, got %d", sc.config.RebalanceInterval)
	}
}

func TestGetLeaderID(t *testing.T) {
	sc := newTestCoordinator("leader-abc")
	if sc.GetLeaderID() != "leader-abc" {
		t.Errorf("unexpected leader ID: %s", sc.GetLeaderID())
	}
}

func TestGetConfig(t *testing.T) {
	cfg := SwarmConfig{MaxSwarmSize: 10, ConsensusThreshold: 0.75}
	sc := NewSwarmCoordinator("leader", cfg, nil)
	got := sc.GetConfig()
	if got.MaxSwarmSize != 10 {
		t.Errorf("expected MaxSwarmSize=10, got %d", got.MaxSwarmSize)
	}
}

// --- AddMember ---

func TestAddMember(t *testing.T) {
	sc := newTestCoordinator("leader")

	err := sc.AddMember("agent-1", RoleScout, "momentum_scalper")
	if err != nil {
		t.Fatalf("AddMember failed: %v", err)
	}

	members := sc.GetMembers()
	if len(members) != 1 {
		t.Fatalf("expected 1 member, got %d", len(members))
	}
	if members[0].AgentID != "agent-1" {
		t.Errorf("unexpected agent ID: %s", members[0].AgentID)
	}
	if members[0].Status != "active" {
		t.Errorf("expected status 'active', got %q", members[0].Status)
	}
}

func TestAddMember_Duplicate(t *testing.T) {
	sc := newTestCoordinator("leader")
	_ = sc.AddMember("agent-1", RoleScout, "strategy")
	err := sc.AddMember("agent-1", RoleAnalyst, "other")
	if err == nil {
		t.Error("expected error for duplicate agent")
	}
}

func TestAddMember_MaxSize(t *testing.T) {
	sc := NewSwarmCoordinator("leader", SwarmConfig{MaxSwarmSize: 2}, nil)
	_ = sc.AddMember("a1", RoleScout, "s1")
	_ = sc.AddMember("a2", RoleAnalyst, "s2")
	err := sc.AddMember("a3", RoleExecutor, "s3")
	if err == nil {
		t.Error("expected error when swarm is full")
	}
}

// --- RemoveMember ---

func TestRemoveMember(t *testing.T) {
	sc := newTestCoordinator("leader")
	_ = sc.AddMember("agent-1", RoleScout, "strategy")

	err := sc.RemoveMember("agent-1")
	if err != nil {
		t.Fatalf("RemoveMember failed: %v", err)
	}

	if len(sc.GetMembers()) != 0 {
		t.Error("expected 0 members after removal")
	}
}

func TestRemoveMember_NotFound(t *testing.T) {
	sc := newTestCoordinator("leader")
	err := sc.RemoveMember("nonexistent")
	if err == nil {
		t.Error("expected error for nonexistent member")
	}
}

// --- GetMember ---

func TestGetMember(t *testing.T) {
	sc := newTestCoordinator("leader")
	_ = sc.AddMember("agent-1", RoleLeader, "strategy")

	m, ok := sc.GetMember("agent-1")
	if !ok {
		t.Fatal("expected to find member")
	}
	if m.Role != RoleLeader {
		t.Errorf("expected role %q, got %q", RoleLeader, m.Role)
	}

	_, ok = sc.GetMember("nonexistent")
	if ok {
		t.Error("expected not found")
	}
}

// --- SubmitSignal ---

func TestSubmitSignal(t *testing.T) {
	sc := newTestCoordinator("leader")
	_ = sc.AddMember("agent-1", RoleScout, "strategy")

	signal := SwarmSignal{
		AgentID:      "agent-1",
		Action:       "buy",
		TokenAddress: "0xtoken",
		ChainID:      1,
		Confidence:   0.9,
		Reasoning:    "strong momentum",
		Timestamp:    time.Now().UnixMilli(),
	}

	err := sc.SubmitSignal(signal)
	if err != nil {
		t.Fatalf("SubmitSignal failed: %v", err)
	}

	sigs := sc.GetSignals("0xtoken")
	if len(sigs) != 1 {
		t.Fatalf("expected 1 signal, got %d", len(sigs))
	}
}

func TestSubmitSignal_MissingAgentID(t *testing.T) {
	sc := newTestCoordinator("leader")
	err := sc.SubmitSignal(SwarmSignal{TokenAddress: "0xtoken"})
	if err == nil {
		t.Error("expected error for missing agent_id")
	}
}

func TestSubmitSignal_MissingTokenAddress(t *testing.T) {
	sc := newTestCoordinator("leader")
	err := sc.SubmitSignal(SwarmSignal{AgentID: "agent-1"})
	if err == nil {
		t.Error("expected error for missing token_address")
	}
}

func TestSubmitSignal_AutoTimestamp(t *testing.T) {
	sc := newTestCoordinator("leader")
	err := sc.SubmitSignal(SwarmSignal{AgentID: "agent-1", TokenAddress: "0xabc"})
	if err != nil {
		t.Fatalf("SubmitSignal failed: %v", err)
	}
	sigs := sc.GetSignals("0xabc")
	if sigs[0].Timestamp == 0 {
		t.Error("expected auto-set timestamp")
	}
}

func TestSubmitSignal_UpdatesMemberStats(t *testing.T) {
	sc := newTestCoordinator("leader")
	_ = sc.AddMember("agent-1", RoleScout, "strategy")

	_ = sc.SubmitSignal(SwarmSignal{AgentID: "agent-1", TokenAddress: "0xabc", Timestamp: 123})

	m, _ := sc.GetMember("agent-1")
	if m.SignalCount != 1 {
		t.Errorf("expected SignalCount=1, got %d", m.SignalCount)
	}
}

// --- RunConsensus ---

func TestRunConsensus_NoSignals(t *testing.T) {
	sc := newTestCoordinator("leader")
	_, err := sc.RunConsensus("0xtoken", 1)
	if err == nil {
		t.Error("expected error when no signals")
	}
}

func TestRunConsensus_Majority(t *testing.T) {
	sc := NewSwarmCoordinator("leader", SwarmConfig{ConsensusThreshold: 0.5}, nil)
	_ = sc.AddMember("leader", RoleLeader, "profit_to_gmach")
	_ = sc.AddMember("executor-1", RoleExecutor, "liquid_executor")

	// 3 buy, 1 sell -> majority = buy
	for i := 0; i < 3; i++ {
		_ = sc.SubmitSignal(
			SwarmSignal{AgentID: "agent", Action: "buy", TokenAddress: "0xabc", Confidence: 0.8, Reasoning: "reason"},
		)
	}
	_ = sc.SubmitSignal(SwarmSignal{AgentID: "agent2", Action: "sell", TokenAddress: "0xabc", Confidence: 0.5})

	result, err := sc.RunConsensus("0xabc", 1)
	if err != nil {
		t.Fatalf("RunConsensus failed: %v", err)
	}
	if result.Action != "buy" {
		t.Errorf("expected action 'buy', got %q", result.Action)
	}
	if !result.Approved {
		t.Error("expected consensus to be approved")
	}
	if decision := sc.GetLastDecision(); decision == nil || decision.ExecutorID == "" {
		t.Fatalf("expected execution decision to be created, got %+v", decision)
	}
}

func TestRunConsensus_Unanimous_Agreed(t *testing.T) {
	sc := NewSwarmCoordinator("leader", SwarmConfig{SignalAggregation: "unanimous"}, nil)

	for i := 0; i < 3; i++ {
		_ = sc.SubmitSignal(SwarmSignal{AgentID: "a", Action: "buy", TokenAddress: "0xunanimous", Confidence: 0.9})
	}

	result, err := sc.RunConsensus("0xunanimous", 1)
	if err != nil {
		t.Fatalf("RunConsensus failed: %v", err)
	}
	if !result.Approved {
		t.Error("expected unanimous consensus to be approved")
	}
}

func TestRunConsensus_Unanimous_Disagreed(t *testing.T) {
	sc := NewSwarmCoordinator("leader", SwarmConfig{SignalAggregation: "unanimous"}, nil)

	_ = sc.SubmitSignal(SwarmSignal{AgentID: "a1", Action: "buy", TokenAddress: "0xdisagree", Confidence: 0.9})
	_ = sc.SubmitSignal(SwarmSignal{AgentID: "a2", Action: "sell", TokenAddress: "0xdisagree", Confidence: 0.4})

	result, err := sc.RunConsensus("0xdisagree", 1)
	if err != nil {
		t.Fatalf("RunConsensus failed: %v", err)
	}
	if result.Approved {
		t.Error("expected unanimous consensus to fail when agents disagree")
	}
}

func TestRunConsensus_Weighted(t *testing.T) {
	sc := NewSwarmCoordinator("leader", SwarmConfig{SignalAggregation: "weighted", ConsensusThreshold: 0.5}, nil)

	// High confidence buy signals
	_ = sc.SubmitSignal(SwarmSignal{AgentID: "a1", Action: "buy", TokenAddress: "0xweighted", Confidence: 0.95})
	_ = sc.SubmitSignal(SwarmSignal{AgentID: "a2", Action: "buy", TokenAddress: "0xweighted", Confidence: 0.85})
	_ = sc.SubmitSignal(SwarmSignal{AgentID: "a3", Action: "sell", TokenAddress: "0xweighted", Confidence: 0.2})

	result, err := sc.RunConsensus("0xweighted", 1)
	if err != nil {
		t.Fatalf("RunConsensus failed: %v", err)
	}
	if result.Action != "buy" {
		t.Errorf("expected weighted action 'buy', got %q", result.Action)
	}
}

func TestRunConsensus_WithBusBroadcastsNarrativeMessages(t *testing.T) {
	tb := replication.NewTelepathyBus(nil, "family", "leader")
	sc := NewSwarmCoordinator("leader", SwarmConfig{ConsensusThreshold: 0.5}, tb)
	_ = sc.AddMember("leader", RoleLeader, "profit_to_gmach")
	_ = sc.AddMember("executor-1", RoleExecutor, "liquid_executor")

	_ = sc.SubmitSignal(
		SwarmSignal{
			AgentID:      "leader",
			Action:       "buy",
			TokenAddress: "0xabc",
			Confidence:   0.9,
			Reasoning:    "momentum held",
		},
	)
	_ = sc.SubmitSignal(
		SwarmSignal{
			AgentID:      "executor-1",
			Action:       "buy",
			TokenAddress: "0xabc",
			Confidence:   0.8,
			Reasoning:    "liquidity confirmed",
		},
	)

	result, err := sc.RunConsensus("0xabc", 1)
	if err != nil {
		t.Fatalf("RunConsensus failed: %v", err)
	}
	if !result.Approved {
		t.Fatalf("expected approved consensus, got %+v", result)
	}

	messages := tb.GetHistory(0)
	types := make(map[string]string, len(messages))
	for _, msg := range messages {
		types[msg.Type] = msg.Content
	}
	if !strings.Contains(types["market_insight"], "Votes: buy=2") {
		t.Fatalf("expected market insight vote summary, got %q", types["market_insight"])
	}
	if types["swarm_execution_plan"] != "buy 0xabc" {
		t.Fatalf("expected execution plan broadcast, got %q", types["swarm_execution_plan"])
	}
	if !strings.Contains(types["strategy_update"], "Consensus approved a small liquid entry") {
		t.Fatalf("expected strategy update to describe assigned decision, got %q", types["strategy_update"])
	}
}

func TestRunConsensus_RejectedBroadcastsWarning(t *testing.T) {
	tb := replication.NewTelepathyBus(nil, "family", "leader")
	sc := NewSwarmCoordinator("leader", SwarmConfig{ConsensusThreshold: 0.75}, tb)
	ch := tb.Subscribe("observer")

	_ = sc.SubmitSignal(
		SwarmSignal{AgentID: "a1", Action: "buy", TokenAddress: "0xdef", Confidence: 0.9, Reasoning: "breakout"},
	)
	_ = sc.SubmitSignal(
		SwarmSignal{AgentID: "a2", Action: "sell", TokenAddress: "0xdef", Confidence: 0.8, Reasoning: "mean reversion"},
	)

	result, err := sc.RunConsensus("0xdef", 1)
	if err != nil {
		t.Fatalf("RunConsensus failed: %v", err)
	}
	if result.Approved {
		t.Fatalf("expected rejected consensus, got %+v", result)
	}

	select {
	case msg := <-ch:
		if msg.Type != "warning" {
			t.Fatalf("expected warning message, got %+v", msg)
		}
		if !strings.Contains(msg.Content, "Threshold 0.75 was not met") {
			t.Fatalf("expected threshold detail in warning, got %q", msg.Content)
		}
	case <-time.After(time.Second):
		t.Fatal("timeout waiting for warning broadcast")
	}
}

// --- ClearSignals ---

func TestClearSignals(t *testing.T) {
	sc := newTestCoordinator("leader")
	_ = sc.SubmitSignal(SwarmSignal{AgentID: "a", Action: "buy", TokenAddress: "0xclear"})
	sc.ClearSignals("0xclear")

	sigs := sc.GetSignals("0xclear")
	if len(sigs) != 0 {
		t.Errorf("expected 0 signals after clear, got %d", len(sigs))
	}
}

// --- BroadcastStrategy ---

func TestBroadcastStrategy_NilBus(t *testing.T) {
	sc := newTestCoordinator("leader")
	// Should not panic when bus is nil
	sc.BroadcastStrategy("momentum")
}

func TestBroadcastStrategy_WithBus(t *testing.T) {
	tb := replication.NewTelepathyBus(nil, "fam", "leader")
	sc := NewSwarmCoordinator("leader", SwarmConfig{}, tb)

	ch := tb.Subscribe("agent-1")
	sc.BroadcastStrategy("dip_buyer")

	select {
	case msg := <-ch:
		if msg.Content != "dip_buyer" {
			t.Errorf("expected 'dip_buyer', got %q", msg.Content)
		}
	case <-time.After(time.Second):
		t.Error("timeout waiting for broadcast")
	}
}

// --- UpdateMemberPerformance ---

func TestUpdateMemberPerformance(t *testing.T) {
	sc := newTestCoordinator("leader")
	_ = sc.AddMember("agent-1", RoleExecutor, "strategy")

	sc.UpdateMemberPerformance("agent-1", 15.5)
	sc.UpdateMemberPerformance("agent-1", -5.0)

	m, _ := sc.GetMember("agent-1")
	if m.Performance != 10.5 {
		t.Errorf("expected performance 10.5, got %.2f", m.Performance)
	}
}

func TestSaveAndLoadSwarmState_PersistsDecision(t *testing.T) {
	dir := t.TempDir()
	sc := NewSwarmCoordinator("leader-1", SwarmConfig{ConsensusThreshold: 0.5}, nil)
	_ = sc.AddMember("leader-1", RoleLeader, "profit_to_gmach")
	_ = sc.AddMember("exec-1", RoleExecutor, "liquid_executor")
	_ = sc.SubmitSignal(SwarmSignal{AgentID: "exec-1", Action: "buy", TokenAddress: "0xabc", Confidence: 0.9})

	result, err := sc.RunConsensus("0xabc", 1)
	if err != nil {
		t.Fatalf("RunConsensus failed: %v", err)
	}
	if !result.Approved {
		t.Fatalf("expected approved consensus, got %+v", result)
	}
	if saveErr := SaveSwarmState(dir, sc); saveErr != nil {
		t.Fatalf("SaveSwarmState failed: %v", saveErr)
	}

	loaded, err := LoadSwarmState(dir)
	if err != nil {
		t.Fatalf("LoadSwarmState failed: %v", err)
	}
	if loaded.GetLastConsensus() == nil {
		t.Fatal("expected last consensus to persist")
	}
	if loaded.GetLastDecision() == nil || loaded.GetLastDecision().ExecutorID == "" {
		t.Fatalf("expected decision to persist, got %+v", loaded.GetLastDecision())
	}
}

func TestUpdateMemberPerformance_NotFound(t *testing.T) {
	sc := newTestCoordinator("leader")
	// Should not panic for nonexistent member
	sc.UpdateMemberPerformance("nobody", 10.0)
}

// --- MajorityAction ---

func TestMajorityAction(t *testing.T) {
	counts := map[string]int{"buy": 3, "sell": 1, "hold": 2}
	got := majorityAction(counts)
	if got != "buy" {
		t.Errorf("expected 'buy', got %q", got)
	}
}

// --- Roles ---

func TestGetRolePromptAddition(t *testing.T) {
	desc := GetRolePromptAddition(RoleLeader)
	if desc == "" {
		t.Error("expected non-empty description for leader role")
	}

	desc = GetRolePromptAddition("unknown_role")
	if desc != "" {
		t.Errorf("expected empty description for unknown role, got %q", desc)
	}
}

func TestRoleConstants(t *testing.T) {
	roles := []string{RoleLeader, RoleScout, RoleExecutor, RoleAnalyst}
	for _, role := range roles {
		if _, ok := RoleDescriptions[role]; !ok {
			t.Errorf("missing description for role %q", role)
		}
	}
}

// --- Strategies ---

func TestAssignStrategies(t *testing.T) {
	members := []*SwarmMember{
		{AgentID: "a1"},
		{AgentID: "a2"},
		{AgentID: "a3"},
	}
	assignments := AssignStrategies(members)
	if len(assignments) != 3 {
		t.Fatalf("expected 3 assignments, got %d", len(assignments))
	}
	for _, m := range members {
		if assignments[m.AgentID] == "" {
			t.Errorf("expected non-empty strategy for %s", m.AgentID)
		}
	}
}

func TestAssignStrategies_MoreMembersThanStrategies(t *testing.T) {
	members := make([]*SwarmMember, len(StrategyPool)+2)
	for i := range members {
		members[i] = &SwarmMember{AgentID: "a"}
	}
	members[0].AgentID = "unique-a"
	members[1].AgentID = "unique-b"
	assignments := AssignStrategies(members)
	// Should wrap around without panic
	if len(assignments) == 0 {
		t.Error("expected assignments")
	}
}

func TestRotateStrategies_SingleMember(t *testing.T) {
	members := []*SwarmMember{{AgentID: "a1", Performance: 10}}
	current := map[string]string{"a1": "momentum"}
	result := RotateStrategies(members, current)
	if result["a1"] != "momentum" {
		t.Errorf("expected unchanged strategy for single member")
	}
}

func TestRotateStrategies_MultiMember(t *testing.T) {
	members := []*SwarmMember{
		{AgentID: "best", Performance: 100},
		{AgentID: "worst", Performance: -50},
	}
	current := map[string]string{"best": "momentum_scalper", "worst": "dip_buyer"}
	result := RotateStrategies(members, current)
	if result["worst"] != "momentum_scalper" {
		t.Errorf("expected worst to receive best's strategy, got %q", result["worst"])
	}
}

func TestRotateStrategies_SamePerformance(t *testing.T) {
	members := []*SwarmMember{
		{AgentID: "a1", Performance: 50},
		{AgentID: "a2", Performance: 50},
	}
	current := map[string]string{"a1": "strategy1", "a2": "strategy2"}
	// Should not panic; best == worst so no rotation
	result := RotateStrategies(members, current)
	if result["a1"] != "strategy1" && result["a2"] != "strategy2" {
		t.Error("expected no rotation when all same performance")
	}
}

// --- Persistence ---

func TestSaveAndLoadSwarmState(t *testing.T) {
	dir := t.TempDir()

	sc := NewSwarmCoordinator("leader-1", SwarmConfig{MaxSwarmSize: 10}, nil)
	_ = sc.AddMember("agent-1", RoleScout, "momentum")
	_ = sc.AddMember("agent-2", RoleExecutor, "dip_buyer")
	_ = sc.SubmitSignal(SwarmSignal{AgentID: "agent-1", Action: "buy", TokenAddress: "0xabc", Confidence: 0.9})

	err := SaveSwarmState(dir, sc)
	if err != nil {
		t.Fatalf("SaveSwarmState failed: %v", err)
	}

	// Verify file exists
	path := filepath.Join(dir, "swarm", "state.json")
	if _, statErr := os.Stat(path); os.IsNotExist(statErr) {
		t.Fatal("expected swarm state file to exist")
	}

	loaded, err := LoadSwarmState(dir)
	if err != nil {
		t.Fatalf("LoadSwarmState failed: %v", err)
	}
	if loaded == nil {
		t.Fatal("expected non-nil coordinator")
	}
	if loaded.GetLeaderID() != "leader-1" {
		t.Errorf("unexpected leader ID: %s", loaded.GetLeaderID())
	}
	if len(loaded.GetMembers()) != 2 {
		t.Errorf("expected 2 members, got %d", len(loaded.GetMembers()))
	}
	if len(loaded.GetSignals("0xabc")) != 1 {
		t.Fatalf("expected 1 persisted signal, got %d", len(loaded.GetSignals("0xabc")))
	}
}

func TestLoadSwarmState_MissingFile(t *testing.T) {
	sc, err := LoadSwarmState("/nonexistent/workspace")
	if err != nil {
		t.Errorf("expected no error for missing file, got: %v", err)
	}
	if sc != nil {
		t.Error("expected nil coordinator for missing file")
	}
}
