// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package replication

import (
	"testing"
)

func TestPruneHistory_TrimsOldMessages(t *testing.T) {
	tb := &TelepathyBus{
		subscribers: make(map[string]chan TelepathyMessage),
		maxHistory:  500,
	}

	// Add 20 messages
	for i := 0; i < 20; i++ {
		tb.addHistory(TelepathyMessage{Content: "msg"})
	}

	tb.PruneHistory(10)
	if len(tb.history) != 10 {
		t.Errorf("want 10 messages, got %d", len(tb.history))
	}
}

func TestPruneHistory_NoOpWhenUnderLimit(t *testing.T) {
	tb := &TelepathyBus{
		subscribers: make(map[string]chan TelepathyMessage),
		maxHistory:  500,
	}
	for i := 0; i < 5; i++ {
		tb.addHistory(TelepathyMessage{Content: "msg"})
	}

	tb.PruneHistory(100)
	if len(tb.history) != 5 {
		t.Errorf("want 5 messages, got %d", len(tb.history))
	}
}

func TestPruneHistory_ZeroMaxNoOp(t *testing.T) {
	tb := &TelepathyBus{
		subscribers: make(map[string]chan TelepathyMessage),
		maxHistory:  500,
	}
	for i := 0; i < 5; i++ {
		tb.addHistory(TelepathyMessage{Content: "msg"})
	}
	tb.PruneHistory(0)
	if len(tb.history) != 5 {
		t.Errorf("want 5 messages unchanged, got %d", len(tb.history))
	}
}
