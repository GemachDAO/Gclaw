package devices

import (
	"context"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/bus"
	"github.com/GemachDAO/Gclaw/pkg/devices/events"
	"github.com/GemachDAO/Gclaw/pkg/state"
)

// TestNewService verifies that the service is created correctly.
func TestNewService(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)

	svc := NewService(Config{Enabled: false}, stateMgr)
	if svc == nil {
		t.Fatal("expected non-nil service")
	}
	if svc.enabled {
		t.Error("expected service to be disabled")
	}
}

func TestNewService_EnabledNoUSB(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)

	svc := NewService(Config{Enabled: true, MonitorUSB: false}, stateMgr)
	if !svc.enabled {
		t.Error("expected service to be enabled")
	}
	if len(svc.sources) != 0 {
		t.Errorf("expected 0 sources, got %d", len(svc.sources))
	}
}

func TestSetBus(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)
	svc := NewService(Config{}, stateMgr)

	mb := bus.NewMessageBus()
	svc.SetBus(mb)

	svc.mu.RLock()
	got := svc.bus
	svc.mu.RUnlock()

	if got != mb {
		t.Error("expected bus to be set")
	}
}

func TestStart_Disabled(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)
	svc := NewService(Config{Enabled: false}, stateMgr)

	err := svc.Start(context.Background())
	if err != nil {
		t.Fatalf("expected no error for disabled service, got: %v", err)
	}
}

func TestStart_NoSources(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)
	svc := NewService(Config{Enabled: true}, stateMgr)

	err := svc.Start(context.Background())
	if err != nil {
		t.Fatalf("expected no error when no sources, got: %v", err)
	}
}

func TestStop_WithoutStart(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)
	svc := NewService(Config{}, stateMgr)
	// Should not panic when stopped without being started
	svc.Stop()
}

func TestParseLastChannel(t *testing.T) {
	tests := []struct {
		input    string
		platform string
		userID   string
	}{
		{"telegram:12345", "telegram", "12345"},
		{"discord:user#1234", "discord", "user#1234"},
		{"slack:U123ABC", "slack", "U123ABC"},
		{"", "", ""},
		{"invalid-no-colon", "", ""},
		{":missing-platform", "", ""},
		{"missing-userid:", "", ""},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			platform, userID := parseLastChannel(tt.input)
			if platform != tt.platform {
				t.Errorf("platform: got %q, want %q", platform, tt.platform)
			}
			if userID != tt.userID {
				t.Errorf("userID: got %q, want %q", userID, tt.userID)
			}
		})
	}
}

func TestSendNotification_NilBus(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)
	svc := NewService(Config{}, stateMgr)
	// Should not panic when bus is nil
	ev := &events.DeviceEvent{
		Action:  events.ActionAdd,
		Kind:    events.KindUSB,
		Vendor:  "TestVendor",
		Product: "TestProduct",
	}
	svc.sendNotification(ev)
}

func TestSendNotification_NoLastChannel(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)
	svc := NewService(Config{}, stateMgr)
	svc.SetBus(bus.NewMessageBus())
	// Last channel is empty, notification should be silently dropped
	ev := &events.DeviceEvent{
		Action:  events.ActionAdd,
		Kind:    events.KindUSB,
		Vendor:  "Vendor",
		Product: "Product",
	}
	svc.sendNotification(ev)
}

func TestSendNotification_InternalChannel(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)
	svc := NewService(Config{}, stateMgr)
	mb := bus.NewMessageBus()
	svc.SetBus(mb)
	// Set last channel to an internal channel
	_ = stateMgr.SetLastChannel("cli:user-1")

	ev := &events.DeviceEvent{
		Action:  events.ActionAdd,
		Kind:    events.KindUSB,
		Vendor:  "Vendor",
		Product: "Product",
	}
	svc.sendNotification(ev)
	// Should not publish to internal channel
}

func TestSendNotification_WithChannel(t *testing.T) {
	dir := t.TempDir()
	stateMgr := state.NewManager(dir)
	svc := NewService(Config{}, stateMgr)
	mb := bus.NewMessageBus()
	svc.SetBus(mb)
	_ = stateMgr.SetLastChannel("telegram:12345")

	ev := &events.DeviceEvent{
		Action:  events.ActionAdd,
		Kind:    events.KindUSB,
		Vendor:  "TestVendor",
		Product: "TestProduct",
	}
	svc.sendNotification(ev)

	ctx, cancel := context.WithTimeout(context.Background(), 100*1000*1000) // 100ms
	defer cancel()
	msg, ok := mb.SubscribeOutbound(ctx)
	if !ok {
		t.Fatal("expected outbound message to be published")
	}
	if msg.Channel != "telegram" {
		t.Errorf("expected channel 'telegram', got %q", msg.Channel)
	}
	if msg.ChatID != "12345" {
		t.Errorf("expected chat ID '12345', got %q", msg.ChatID)
	}
}
