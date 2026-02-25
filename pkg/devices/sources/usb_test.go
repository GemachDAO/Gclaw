package sources

import (
	"context"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/devices/events"
)

func TestUSBMonitor_Kind(t *testing.T) {
	m := NewUSBMonitor()
	if m.Kind() != events.KindUSB {
		t.Errorf("expected kind %q, got %q", events.KindUSB, m.Kind())
	}
}

func TestUSBMonitor_Stop(t *testing.T) {
	m := NewUSBMonitor()
	err := m.Stop()
	if err != nil {
		t.Errorf("expected no error from Stop(), got: %v", err)
	}
}

func TestUSBMonitor_Start(t *testing.T) {
	m := NewUSBMonitor()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ch, err := m.Start(ctx)
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}
	if ch == nil {
		t.Fatal("expected non-nil channel")
	}
}
