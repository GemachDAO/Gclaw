package dashboard

import (
	"encoding/json"
	"strings"
	"testing"
)

// --- GetData: graceful degradation ---

func TestGetData_AllNilSources(t *testing.T) {
	d := NewDashboard(DashboardOptions{
		AgentID:   "test-agent",
		StartedAt: 0,
	})
	data := d.GetData()
	if data == nil {
		t.Fatal("expected non-nil DashboardData")
	}
	if data.AgentID != "test-agent" {
		t.Errorf("expected agent_id 'test-agent', got %q", data.AgentID)
	}
	if data.Metabolism != nil {
		t.Error("expected nil metabolism when no callback")
	}
	if data.Trading != nil {
		t.Error("expected nil trading when no callback")
	}
	if data.Family != nil {
		t.Error("expected nil family when no callback")
	}
	if data.Telepathy != nil {
		t.Error("expected nil telepathy when no callback")
	}
	if data.Swarm != nil {
		t.Error("expected nil swarm when no callback")
	}
}

// --- GetData: with mock sources ---

func TestGetData_WithMetabolism(t *testing.T) {
	snap := &MetabolismSnapshot{
		Balance:   100.5,
		Goodwill:  42,
		Abilities: []string{"replicate"},
	}
	d := NewDashboard(DashboardOptions{
		AgentID:       "agent-1",
		StartedAt:     1000,
		GetMetabolism: func() *MetabolismSnapshot { return snap },
	})
	data := d.GetData()
	if data.Metabolism == nil {
		t.Fatal("expected non-nil metabolism")
	}
	if data.Metabolism.Balance != 100.5 {
		t.Errorf("expected balance 100.5, got %.2f", data.Metabolism.Balance)
	}
	if data.Metabolism.Goodwill != 42 {
		t.Errorf("expected goodwill 42, got %d", data.Metabolism.Goodwill)
	}
}

func TestGetData_WithFamily(t *testing.T) {
	snap := &FamilySnapshot{
		ParentID: "parent-1",
		Children: []ChildInfo{
			{ID: "child-1", Generation: 1, Status: "running", GMAC: 50},
		},
		TotalFamily: 2,
	}
	d := NewDashboard(DashboardOptions{
		GetFamily: func() *FamilySnapshot { return snap },
	})
	data := d.GetData()
	if data.Family == nil {
		t.Fatal("expected non-nil family")
	}
	if len(data.Family.Children) != 1 {
		t.Errorf("expected 1 child, got %d", len(data.Family.Children))
	}
}

func TestGetData_WithTelepathy(t *testing.T) {
	snap := &TelepathySnapshot{
		TotalMessages:  5,
		ActiveChannels: 2,
		RecentMessages: []TelepathyEntry{
			{From: "agent-1", To: "agent-2", Type: "trade_signal", Content: "buy SOL"},
		},
	}
	d := NewDashboard(DashboardOptions{
		GetTelepathy: func() *TelepathySnapshot { return snap },
	})
	data := d.GetData()
	if data.Telepathy == nil {
		t.Fatal("expected non-nil telepathy")
	}
	if data.Telepathy.TotalMessages != 5 {
		t.Errorf("expected 5 messages, got %d", data.Telepathy.TotalMessages)
	}
}

// --- Uptime formatting ---

func TestFormatUptime(t *testing.T) {
	cases := []struct {
		ms   int64
		want string
	}{
		{0, "0s"},
		{-100, "0s"},
		{5000, "5s"},
		{90000, "1m 30s"},
		{3700000, "1h 1m"},
	}
	for _, c := range cases {
		got := formatUptime(c.ms)
		if got != c.want {
			t.Errorf("formatUptime(%d) = %q, want %q", c.ms, got, c.want)
		}
	}
}

// --- FormatCLI ---

func TestFormatCLI_NonEmpty(t *testing.T) {
	d := NewDashboard(DashboardOptions{AgentID: "gclaw-test"})
	output := FormatCLI(d.GetData())
	if output == "" {
		t.Error("expected non-empty CLI output")
	}
	if !strings.Contains(output, "GCLAW LIVING AGENT") {
		t.Error("expected header in CLI output")
	}
}

func TestFormatCLI_NilData(t *testing.T) {
	output := FormatCLI(nil)
	if output != "" {
		t.Error("expected empty output for nil data")
	}
}

func TestFormatCLI_WithAllSections(t *testing.T) {
	d := NewDashboard(DashboardOptions{
		AgentID:   "gclaw-main",
		StartedAt: 1000,
		GetMetabolism: func() *MetabolismSnapshot {
			return &MetabolismSnapshot{
				Balance:      847.5,
				Goodwill:     127,
				SurvivalMode: false,
				Abilities:    []string{"replicate", "self_recode"},
			}
		},
		GetFamily: func() *FamilySnapshot {
			return &FamilySnapshot{
				Children: []ChildInfo{
					{ID: "gclaw-child-1", Status: "running", Generation: 1, Mutations: []string{"momentum"}},
				},
				TotalFamily: 2,
			}
		},
		GetTelepathy: func() *TelepathySnapshot {
			return &TelepathySnapshot{
				TotalMessages:  47,
				ActiveChannels: 3,
			}
		},
		GetSwarm: func() *SwarmSnapshot {
			return &SwarmSnapshot{
				IsLeader:      true,
				MemberCount:   3,
				ConsensusMode: "majority",
			}
		},
		GetSystem: func() *SystemSnapshot {
			return &SystemSnapshot{
				HeartbeatActive:   true,
				HeartbeatInterval: 30,
				ToolCount:         18,
				Platform:          "linux",
			}
		},
	})

	output := FormatCLI(d.GetData())
	for _, want := range []string{
		"METABOLISM",
		"TRADING",
		"FAMILY",
		"TELEPATHY",
		"SWARM",
		"SYSTEM",
	} {
		if !strings.Contains(output, want) {
			t.Errorf("expected %q in CLI output", want)
		}
	}
}

func TestFormatCLI_EmptySections(t *testing.T) {
	// Dashboard with no sources — should render gracefully with "(not configured)"
	d := NewDashboard(DashboardOptions{})
	output := FormatCLI(d.GetData())
	if !strings.Contains(output, "not configured") {
		t.Error("expected 'not configured' for empty sections")
	}
}

// --- JSON round-trip ---

func TestJSONRoundTrip(t *testing.T) {
	d := NewDashboard(DashboardOptions{
		AgentID:   "round-trip-agent",
		StartedAt: 12345678,
		GetMetabolism: func() *MetabolismSnapshot {
			return &MetabolismSnapshot{Balance: 500, Goodwill: 100}
		},
	})
	b, err := d.GetJSON()
	if err != nil {
		t.Fatalf("GetJSON error: %v", err)
	}

	var decoded DashboardData
	if err := json.Unmarshal(b, &decoded); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}
	if decoded.AgentID != "round-trip-agent" {
		t.Errorf("expected agent_id 'round-trip-agent', got %q", decoded.AgentID)
	}
	if decoded.Metabolism == nil {
		t.Fatal("expected non-nil metabolism after round-trip")
	}
	if decoded.Metabolism.Balance != 500 {
		t.Errorf("expected balance 500, got %.2f", decoded.Metabolism.Balance)
	}
}

// --- truncate helper ---

func TestTruncate(t *testing.T) {
	if got := truncate("hello", 10); got != "hello" {
		t.Errorf("unexpected truncate: %q", got)
	}
	if got := truncate("hello world", 6); got != "hello…" {
		t.Errorf("unexpected truncate: %q", got)
	}
	if got := truncate("", 5); got != "" {
		t.Errorf("unexpected truncate of empty: %q", got)
	}
}
