package session

import (
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/providers"
)

func TestGetSummary_NotFound(t *testing.T) {
	sm := NewSessionManager("")
	summary := sm.GetSummary("nonexistent-key")
	if summary != "" {
		t.Errorf("expected empty summary for nonexistent key, got %q", summary)
	}
}

func TestGetSummary_Set(t *testing.T) {
	sm := NewSessionManager("")
	key := "test-session"
	sm.GetOrCreate(key)

	sm.SetSummary(key, "This is a summary")
	got := sm.GetSummary(key)
	if got != "This is a summary" {
		t.Errorf("expected 'This is a summary', got %q", got)
	}
}

func TestSetSummary_NonExistentSession(t *testing.T) {
	sm := NewSessionManager("")
	// Should not panic for nonexistent key
	sm.SetSummary("nonexistent", "summary")
}

func TestTruncateHistory_Basic(t *testing.T) {
	sm := NewSessionManager("")
	key := "trunc-test"
	sm.GetOrCreate(key)

	for i := 0; i < 10; i++ {
		sm.AddMessage(key, "user", "msg")
	}

	sm.TruncateHistory(key, 3)
	history := sm.GetHistory(key)
	if len(history) != 3 {
		t.Errorf("expected 3 messages after truncate, got %d", len(history))
	}
}

func TestTruncateHistory_ZeroKeep(t *testing.T) {
	sm := NewSessionManager("")
	key := "trunc-zero"
	sm.GetOrCreate(key)
	sm.AddMessage(key, "user", "msg1")
	sm.AddMessage(key, "user", "msg2")

	sm.TruncateHistory(key, 0)
	history := sm.GetHistory(key)
	if len(history) != 0 {
		t.Errorf("expected 0 messages after truncate to 0, got %d", len(history))
	}
}

func TestTruncateHistory_NonExistentSession(t *testing.T) {
	sm := NewSessionManager("")
	// Should not panic
	sm.TruncateHistory("nonexistent", 5)
}

func TestTruncateHistory_KeepMoreThanExist(t *testing.T) {
	sm := NewSessionManager("")
	key := "trunc-less"
	sm.GetOrCreate(key)
	sm.AddMessage(key, "user", "msg1")

	sm.TruncateHistory(key, 10)
	history := sm.GetHistory(key)
	if len(history) != 1 {
		t.Errorf("expected 1 message unchanged, got %d", len(history))
	}
}

func TestSetHistory(t *testing.T) {
	sm := NewSessionManager("")
	key := "set-hist"
	sm.GetOrCreate(key)

	history := []providers.Message{
		{Role: "user", Content: "hello"},
		{Role: "assistant", Content: "world"},
	}
	sm.SetHistory(key, history)

	got := sm.GetHistory(key)
	if len(got) != 2 {
		t.Fatalf("expected 2 messages, got %d", len(got))
	}
	if got[0].Content != "hello" {
		t.Errorf("expected 'hello', got %q", got[0].Content)
	}
}

func TestSetHistory_NonExistent(t *testing.T) {
	sm := NewSessionManager("")
	history := []providers.Message{{Role: "user", Content: "msg"}}
	// Should not panic for nonexistent session
	sm.SetHistory("nonexistent", history)
}

func TestAddMessage_CreatesSession(t *testing.T) {
	sm := NewSessionManager("")
	key := "auto-create"

	// AddMessage without prior GetOrCreate should create session
	sm.AddMessage(key, "user", "hello")
	history := sm.GetHistory(key)
	if len(history) != 1 {
		t.Fatalf("expected 1 message, got %d", len(history))
	}
}

func TestNewSessionManager_NoStorage(t *testing.T) {
	sm := NewSessionManager("")
	if sm == nil {
		t.Fatal("expected non-nil SessionManager")
	}
}

func TestGetOrCreate_ReturnsExisting(t *testing.T) {
	sm := NewSessionManager("")
	key := "existing"

	s1 := sm.GetOrCreate(key)
	s2 := sm.GetOrCreate(key)

	if s1 != s2 {
		t.Error("expected same session on second GetOrCreate")
	}
}
