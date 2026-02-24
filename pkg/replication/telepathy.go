package replication

import (
	"fmt"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/bus"
)

// TelepathyMessage is a message exchanged between parent and child agents.
type TelepathyMessage struct {
	FromAgentID string `json:"from"`
	ToAgentID   string `json:"to"`        // "*" for broadcast to all family
	Type        string `json:"type"`      // "trade_signal", "market_insight", "strategy_update", "warning", "goodwill_share"
	Content     string `json:"content"`
	Timestamp   int64  `json:"timestamp"`
	Priority    int    `json:"priority"` // 0=low, 1=normal, 2=urgent
}

// TradeSignal carries a structured trade recommendation.
type TradeSignal struct {
	Action        string  `json:"action"`          // "buy", "sell", "watch"
	TokenAddress  string  `json:"token_address"`
	ChainID       int     `json:"chain_id"`
	Confidence    float64 `json:"confidence"`      // 0.0-1.0
	Reasoning     string  `json:"reasoning"`
	PriceAtSignal float64 `json:"price_at_signal"`
}

// TelepathyBus enables in-process communication between parent and child agents.
type TelepathyBus struct {
	parentBus   *bus.MessageBus
	familyID    string
	agentID     string
	subscribers map[string]chan TelepathyMessage
	history     []TelepathyMessage
	maxHistory  int
	mu          sync.RWMutex
}

// NewTelepathyBus creates a TelepathyBus tied to the given parent bus and family.
func NewTelepathyBus(parentBus *bus.MessageBus, familyID, agentID string) *TelepathyBus {
	return &TelepathyBus{
		parentBus:   parentBus,
		familyID:    familyID,
		agentID:     agentID,
		subscribers: make(map[string]chan TelepathyMessage),
		history:     []TelepathyMessage{},
		maxHistory:  500,
	}
}

// Broadcast sends a TelepathyMessage to all subscribed family members.
func (tb *TelepathyBus) Broadcast(msg TelepathyMessage) {
	if msg.Timestamp == 0 {
		msg.Timestamp = time.Now().UnixMilli()
	}
	msg.ToAgentID = "*"

	tb.mu.Lock()
	tb.addHistory(msg)
	channels := make([]chan TelepathyMessage, 0, len(tb.subscribers))
	for _, ch := range tb.subscribers {
		channels = append(channels, ch)
	}
	tb.mu.Unlock()

	for _, ch := range channels {
		select {
		case ch <- msg:
		default:
		}
	}
}

// SendTo delivers a TelepathyMessage to a specific agent subscriber.
func (tb *TelepathyBus) SendTo(targetID string, msg TelepathyMessage) {
	if msg.Timestamp == 0 {
		msg.Timestamp = time.Now().UnixMilli()
	}
	msg.ToAgentID = targetID

	tb.mu.Lock()
	tb.addHistory(msg)
	ch, ok := tb.subscribers[targetID]
	tb.mu.Unlock()

	if ok {
		select {
		case ch <- msg:
		default:
		}
	}
}

// Subscribe registers agentID for receiving messages and returns a read channel.
func (tb *TelepathyBus) Subscribe(agentID string) <-chan TelepathyMessage {
	tb.mu.Lock()
	defer tb.mu.Unlock()
	ch := make(chan TelepathyMessage, 64)
	tb.subscribers[agentID] = ch
	return ch
}

// Unsubscribe removes an agent's subscription and closes its channel.
func (tb *TelepathyBus) Unsubscribe(agentID string) {
	tb.mu.Lock()
	defer tb.mu.Unlock()
	if ch, ok := tb.subscribers[agentID]; ok {
		close(ch)
		delete(tb.subscribers, agentID)
	}
}

// BroadcastTradeSignal is a convenience method that wraps a TradeSignal into
// a TelepathyMessage and broadcasts it to all family members.
func (tb *TelepathyBus) BroadcastTradeSignal(signal TradeSignal) {
	content := signal.Action + " " + signal.TokenAddress +
		" confidence=" + formatFloat(signal.Confidence) +
		" reason=" + signal.Reasoning

	tb.Broadcast(TelepathyMessage{
		FromAgentID: tb.agentID,
		Type:        "trade_signal",
		Content:     content,
		Priority:    1,
	})
}

// GetHistory returns the last `limit` messages from the history buffer.
func (tb *TelepathyBus) GetHistory(limit int) []TelepathyMessage {
	tb.mu.RLock()
	defer tb.mu.RUnlock()
	if limit <= 0 || limit >= len(tb.history) {
		out := make([]TelepathyMessage, len(tb.history))
		copy(out, tb.history)
		return out
	}
	start := len(tb.history) - limit
	out := make([]TelepathyMessage, limit)
	copy(out, tb.history[start:])
	return out
}

// addHistory appends a message to the history, evicting oldest when at capacity.
// Caller must hold tb.mu.Lock().
func (tb *TelepathyBus) addHistory(msg TelepathyMessage) {
	tb.history = append(tb.history, msg)
	if len(tb.history) > tb.maxHistory {
		tb.history = tb.history[len(tb.history)-tb.maxHistory:]
	}
}

// formatFloat formats a float64 for use in message content.
func formatFloat(f float64) string {
	return fmt.Sprintf("%.2f", f)
}
