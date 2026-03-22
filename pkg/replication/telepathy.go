package replication

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/bus"
)

// TelepathyMessage is a message exchanged between parent and child agents.
type TelepathyMessage struct {
	FromAgentID string `json:"from"`
	ToAgentID   string `json:"to"`   // "*" for broadcast to all family
	Type        string `json:"type"` // "trade_signal", "market_insight", "strategy_update", "warning", "goodwill_share"
	Content     string `json:"content"`
	Timestamp   int64  `json:"timestamp"`
	Priority    int    `json:"priority"` // 0=low, 1=normal, 2=urgent
}

// TradeSignal carries a structured trade recommendation.
type TradeSignal struct {
	Action        string  `json:"action"` // "buy", "sell", "watch"
	TokenAddress  string  `json:"token_address"`
	ChainID       int     `json:"chain_id"`
	Confidence    float64 `json:"confidence"` // 0.0-1.0
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
	persistDir  string
	seenFiles   map[string]struct{}
	watchDone   chan struct{}
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
		seenFiles:   make(map[string]struct{}),
	}
}

// Broadcast sends a TelepathyMessage to all subscribed family members.
func (tb *TelepathyBus) Broadcast(msg TelepathyMessage) {
	if msg.Timestamp == 0 {
		msg.Timestamp = time.Now().UnixMilli()
	}
	msg.ToAgentID = "*"
	tb.storeAndDispatch(msg, true)
}

// SendTo delivers a TelepathyMessage to a specific agent subscriber.
func (tb *TelepathyBus) SendTo(targetID string, msg TelepathyMessage) {
	if msg.Timestamp == 0 {
		msg.Timestamp = time.Now().UnixMilli()
	}
	msg.ToAgentID = targetID
	tb.storeAndDispatch(msg, true)
}

// Subscribe registers agentID for receiving messages and returns a read channel.
func (tb *TelepathyBus) Subscribe(agentID string) <-chan TelepathyMessage {
	tb.mu.Lock()
	ch := make(chan TelepathyMessage, 64)
	tb.subscribers[agentID] = ch
	replay := tb.replayHistoryLocked(agentID, 16)
	tb.mu.Unlock()

	for _, msg := range replay {
		select {
		case ch <- msg:
		default:
			return ch
		}
	}
	return ch
}

// SubscriberCount returns the current number of live family subscribers.
func (tb *TelepathyBus) SubscriberCount() int {
	tb.mu.RLock()
	defer tb.mu.RUnlock()
	return len(tb.subscribers)
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

// EnableFilePersistence enables workspace-backed telepathy history and live replay.
func (tb *TelepathyBus) EnableFilePersistence(dir string) error {
	if strings.TrimSpace(dir) == "" {
		return nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	tb.mu.Lock()
	startWatcher := tb.persistDir == ""
	tb.persistDir = dir
	if tb.watchDone == nil {
		tb.watchDone = make(chan struct{})
	}
	tb.mu.Unlock()

	if err := tb.loadPersistedHistory(); err != nil {
		return err
	}

	if startWatcher {
		go tb.watchPersistedFiles()
	}
	return nil
}

// PersistenceEnabled reports whether the bus is writing messages to disk.
func (tb *TelepathyBus) PersistenceEnabled() bool {
	tb.mu.RLock()
	defer tb.mu.RUnlock()
	return strings.TrimSpace(tb.persistDir) != ""
}

// BroadcastTradeSignal is a convenience method that wraps a TradeSignal into
// a TelepathyMessage and broadcasts it to all family members.
func (tb *TelepathyBus) BroadcastTradeSignal(signal TradeSignal) {
	tb.BroadcastTradeSignalFrom(tb.agentID, signal)
}

// BroadcastTradeSignalFrom broadcasts a structured trade signal from the given agent.
func (tb *TelepathyBus) BroadcastTradeSignalFrom(fromAgentID string, signal TradeSignal) {
	content := signal.Action + " " + signal.TokenAddress +
		" confidence=" + formatFloat(signal.Confidence) +
		" reason=" + signal.Reasoning

	tb.Broadcast(TelepathyMessage{
		FromAgentID: fromAgentID,
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

func (tb *TelepathyBus) storeAndDispatch(msg TelepathyMessage, persist bool) {
	tb.mu.Lock()
	tb.addHistory(msg)
	channels := tb.collectChannelsLocked(msg)
	tb.mu.Unlock()

	if persist {
		tb.persistMessage(msg)
	}
	tb.dispatch(msg, channels)
}

func (tb *TelepathyBus) collectChannelsLocked(msg TelepathyMessage) []chan TelepathyMessage {
	channels := make([]chan TelepathyMessage, 0, len(tb.subscribers))
	if msg.ToAgentID == "*" {
		for _, ch := range tb.subscribers {
			channels = append(channels, ch)
		}
		return channels
	}
	if ch, ok := tb.subscribers[msg.ToAgentID]; ok {
		channels = append(channels, ch)
	}
	return channels
}

func (tb *TelepathyBus) dispatch(msg TelepathyMessage, channels []chan TelepathyMessage) {
	for _, ch := range channels {
		select {
		case ch <- msg:
		default:
		}
	}
}

func (tb *TelepathyBus) replayHistoryLocked(agentID string, limit int) []TelepathyMessage {
	if limit <= 0 {
		return nil
	}
	replay := make([]TelepathyMessage, 0, limit)
	for i := len(tb.history) - 1; i >= 0 && len(replay) < limit; i-- {
		msg := tb.history[i]
		if msg.ToAgentID != "*" && msg.ToAgentID != agentID {
			continue
		}
		if msg.FromAgentID == agentID {
			continue
		}
		replay = append(replay, msg)
	}
	for i, j := 0, len(replay)-1; i < j; i, j = i+1, j-1 {
		replay[i], replay[j] = replay[j], replay[i]
	}
	return replay
}

func (tb *TelepathyBus) persistMessage(msg TelepathyMessage) {
	tb.mu.RLock()
	dir := tb.persistDir
	tb.mu.RUnlock()
	if strings.TrimSpace(dir) == "" {
		return
	}
	path, err := writeMessageFile(dir, msg)
	if err != nil {
		return
	}
	tb.mu.Lock()
	tb.seenFiles[filepath.Base(path)] = struct{}{}
	tb.mu.Unlock()
}

func (tb *TelepathyBus) loadPersistedHistory() error {
	tb.mu.RLock()
	dir := tb.persistDir
	tb.mu.RUnlock()
	if strings.TrimSpace(dir) == "" {
		return nil
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Name() < entries[j].Name()
	})
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		path := filepath.Join(dir, entry.Name())
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		var msg TelepathyMessage
		if err := json.Unmarshal(data, &msg); err != nil {
			continue
		}
		tb.mu.Lock()
		if _, ok := tb.seenFiles[entry.Name()]; ok {
			tb.mu.Unlock()
			continue
		}
		tb.seenFiles[entry.Name()] = struct{}{}
		tb.addHistory(msg)
		tb.mu.Unlock()
	}
	return nil
}

func (tb *TelepathyBus) watchPersistedFiles() {
	tb.mu.RLock()
	done := tb.watchDone
	dir := tb.persistDir
	tb.mu.RUnlock()
	if done == nil || strings.TrimSpace(dir) == "" {
		return
	}

	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			cleanOldMessages(dir, 24*time.Hour)
			entries, err := os.ReadDir(dir)
			if err != nil {
				continue
			}
			sort.Slice(entries, func(i, j int) bool {
				return entries[i].Name() < entries[j].Name()
			})
			for _, entry := range entries {
				if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" {
					continue
				}
				tb.mu.RLock()
				_, seen := tb.seenFiles[entry.Name()]
				tb.mu.RUnlock()
				if seen {
					continue
				}
				path := filepath.Join(dir, entry.Name())
				data, err := os.ReadFile(path)
				if err != nil {
					continue
				}
				var msg TelepathyMessage
				if err := json.Unmarshal(data, &msg); err != nil {
					continue
				}
				tb.mu.Lock()
				if _, seen := tb.seenFiles[entry.Name()]; seen {
					tb.mu.Unlock()
					continue
				}
				tb.seenFiles[entry.Name()] = struct{}{}
				tb.addHistory(msg)
				channels := tb.collectChannelsLocked(msg)
				tb.mu.Unlock()
				tb.dispatch(msg, channels)
			}
		}
	}
}

// formatFloat formats a float64 for use in message content.
func formatFloat(f float64) string {
	return fmt.Sprintf("%.2f", f)
}
