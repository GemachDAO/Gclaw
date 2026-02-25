package heartbeat

import (
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/bus"
)

func TestIsRunning_NotStarted(t *testing.T) {
	dir := t.TempDir()
	hs := NewHeartbeatService(dir, 30, true)
	if hs.IsRunning() {
		t.Error("expected IsRunning=false before Start()")
	}
}

func TestIsRunning_AfterStart(t *testing.T) {
	dir := t.TempDir()
	hs := NewHeartbeatService(dir, 30, true)
	_ = hs.Start()
	defer hs.Stop()
	if !hs.IsRunning() {
		t.Error("expected IsRunning=true after Start()")
	}
}

func TestSetBus(t *testing.T) {
	dir := t.TempDir()
	hs := NewHeartbeatService(dir, 30, true)
	mb := bus.NewMessageBus()
	hs.SetBus(mb)

	hs.mu.RLock()
	got := hs.bus
	hs.mu.RUnlock()

	if got != mb {
		t.Error("expected bus to be set")
	}
}

func TestParseLastChannel_Valid(t *testing.T) {
	dir := t.TempDir()
	hs := NewHeartbeatService(dir, 30, true)

	tests := []struct {
		input    string
		platform string
		userID   string
	}{
		{"telegram:12345", "telegram", "12345"},
		{"discord:user123", "discord", "user123"},
		{"slack:U123", "slack", "U123"},
	}

	for _, tt := range tests {
		p, u := hs.parseLastChannel(tt.input)
		if p != tt.platform {
			t.Errorf("parseLastChannel(%q) platform = %q, want %q", tt.input, p, tt.platform)
		}
		if u != tt.userID {
			t.Errorf("parseLastChannel(%q) userID = %q, want %q", tt.input, u, tt.userID)
		}
	}
}

func TestParseLastChannel_Empty(t *testing.T) {
	dir := t.TempDir()
	hs := NewHeartbeatService(dir, 30, true)

	p, u := hs.parseLastChannel("")
	if p != "" || u != "" {
		t.Errorf("expected empty for empty input, got platform=%q userID=%q", p, u)
	}
}

func TestParseLastChannel_InternalChannel(t *testing.T) {
	dir := t.TempDir()
	hs := NewHeartbeatService(dir, 30, true)

	p, u := hs.parseLastChannel("cli:user1")
	if p != "" || u != "" {
		t.Errorf("expected empty for internal channel, got platform=%q userID=%q", p, u)
	}
}

func TestParseLastChannel_InvalidFormat(t *testing.T) {
	dir := t.TempDir()
	hs := NewHeartbeatService(dir, 30, true)

	// Missing colon
	p, u := hs.parseLastChannel("invalidformat")
	if p != "" || u != "" {
		t.Errorf("expected empty for invalid format, got platform=%q userID=%q", p, u)
	}

	// Empty platform
	p, u = hs.parseLastChannel(":userid")
	if p != "" || u != "" {
		t.Errorf("expected empty for empty platform, got platform=%q userID=%q", p, u)
	}

	// Empty userID
	p, u = hs.parseLastChannel("platform:")
	if p != "" || u != "" {
		t.Errorf("expected empty for empty userID, got platform=%q userID=%q", p, u)
	}
}
