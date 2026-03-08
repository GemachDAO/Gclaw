package bus

import (
	"context"
	"testing"
	"time"
)

func TestNewMessageBus(t *testing.T) {
	mb := NewMessageBus()
	if mb == nil {
		t.Fatal("expected non-nil MessageBus")
	}
	if mb.closed {
		t.Error("expected bus to not be closed")
	}
	if mb.handlers == nil {
		t.Error("expected handlers map to be initialized")
	}
}

func TestPublishAndConsumeInbound(t *testing.T) {
	mb := NewMessageBus()
	msg := InboundMessage{
		Channel:  "telegram",
		SenderID: "user1",
		ChatID:   "chat1",
		Content:  "hello",
	}

	mb.PublishInbound(msg)

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()

	got, ok := mb.ConsumeInbound(ctx)
	if !ok {
		t.Fatal("expected to receive inbound message")
	}
	if got.Content != msg.Content {
		t.Errorf("expected content %q, got %q", msg.Content, got.Content)
	}
	if got.Channel != msg.Channel {
		t.Errorf("expected channel %q, got %q", msg.Channel, got.Channel)
	}
}

func TestConsumeInbound_ContextCancelled(t *testing.T) {
	mb := NewMessageBus()
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // immediately cancel

	_, ok := mb.ConsumeInbound(ctx)
	if ok {
		t.Error("expected false when context is cancelled")
	}
}

func TestPublishAndSubscribeOutbound(t *testing.T) {
	mb := NewMessageBus()
	msg := OutboundMessage{
		Channel: "discord",
		ChatID:  "channel1",
		Content: "response",
	}

	mb.PublishOutbound(msg)

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()

	got, ok := mb.SubscribeOutbound(ctx)
	if !ok {
		t.Fatal("expected to receive outbound message")
	}
	if got.Content != msg.Content {
		t.Errorf("expected content %q, got %q", msg.Content, got.Content)
	}
}

func TestSubscribeOutbound_ContextCancelled(t *testing.T) {
	mb := NewMessageBus()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, ok := mb.SubscribeOutbound(ctx)
	if ok {
		t.Error("expected false when context is cancelled")
	}
}

func TestRegisterAndGetHandler(t *testing.T) {
	mb := NewMessageBus()
	var called bool
	handler := func(msg InboundMessage) error {
		called = true
		return nil
	}

	mb.RegisterHandler("telegram", handler)
	h, ok := mb.GetHandler("telegram")
	if !ok {
		t.Fatal("expected handler to be registered")
	}
	_ = h(InboundMessage{})
	if !called {
		t.Error("expected handler to be called")
	}
}

func TestGetHandler_NotFound(t *testing.T) {
	mb := NewMessageBus()
	_, ok := mb.GetHandler("nonexistent")
	if ok {
		t.Error("expected handler not found")
	}
}

func TestClose(t *testing.T) {
	mb := NewMessageBus()
	mb.Close()
	if !mb.closed {
		t.Error("expected bus to be closed")
	}
}

func TestClose_Idempotent(t *testing.T) {
	mb := NewMessageBus()
	mb.Close()
	// Second close should not panic
	mb.Close()
}

func TestPublishInbound_AfterClose(t *testing.T) {
	mb := NewMessageBus()
	mb.Close()
	// Publishing after close should be a no-op (not panic)
	mb.PublishInbound(InboundMessage{Content: "test"})
}

func TestPublishOutbound_AfterClose(t *testing.T) {
	mb := NewMessageBus()
	mb.Close()
	// Publishing after close should be a no-op (not panic)
	mb.PublishOutbound(OutboundMessage{Content: "test"})
}

func TestInboundMessage_Fields(t *testing.T) {
	msg := InboundMessage{
		Channel:    "slack",
		SenderID:   "U123",
		ChatID:     "C456",
		Content:    "hello world",
		Media:      []string{"url1"},
		SessionKey: "sess-key",
		Metadata:   map[string]string{"key": "val"},
	}
	if msg.Channel != "slack" {
		t.Errorf("unexpected channel: %s", msg.Channel)
	}
	if msg.SenderID != "U123" {
		t.Errorf("unexpected sender ID: %s", msg.SenderID)
	}
	if msg.ChatID != "C456" {
		t.Errorf("unexpected chat ID: %s", msg.ChatID)
	}
	if msg.Content != "hello world" {
		t.Errorf("unexpected content: %s", msg.Content)
	}
	if msg.SessionKey != "sess-key" {
		t.Errorf("unexpected session key: %s", msg.SessionKey)
	}
	if len(msg.Media) != 1 {
		t.Errorf("expected 1 media, got %d", len(msg.Media))
	}
	if msg.Metadata["key"] != "val" {
		t.Errorf("unexpected metadata value: %s", msg.Metadata["key"])
	}
}

func TestRegisterHandler_Overwrite(t *testing.T) {
	mb := NewMessageBus()
	count := 0
	mb.RegisterHandler("ch", func(msg InboundMessage) error { count += 1; return nil })
	mb.RegisterHandler("ch", func(msg InboundMessage) error { count += 10; return nil })
	h, _ := mb.GetHandler("ch")
	_ = h(InboundMessage{})
	if count != 10 {
		t.Errorf("expected second handler to override, got count=%d", count)
	}
}
