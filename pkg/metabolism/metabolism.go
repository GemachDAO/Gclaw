package metabolism

import (
	"fmt"
	"sync"
	"time"
)

// Metabolism tracks the agent's GMAC token balance and enforces
// the "trade to live" mechanic.
type Metabolism struct {
	balance           float64
	goodwill          int
	generation        int    // 0 = original, 1+ = replicated child
	parentID          string // parent agent ID if replicated
	ledger            []LedgerEntry
	thresholds        Thresholds
	onCreditCallbacks []func(newBalance float64)
	onChangeCallbacks []func()
	mu                sync.RWMutex
}

// LedgerEntry records a single balance change event.
type LedgerEntry struct {
	Timestamp int64   `json:"ts"`
	Action    string  `json:"action"`  // "heartbeat", "inference", "trade_profit", "trade_loss", "tip", "task_complete", "tool_exec"
	Amount    float64 `json:"amount"`  // positive = earned, negative = spent
	Balance   float64 `json:"balance"` // balance after entry
	Details   string  `json:"details"`
}

// Thresholds defines the GMAC and goodwill levels that gate various abilities.
type Thresholds struct {
	Hibernate   float64 `json:"hibernate"`    // Below this = survival mode
	Replicate   int     `json:"replicate"`    // Goodwill needed to replicate (default 50)
	SelfRecode  int     `json:"self_recode"`  // Goodwill needed to self-modify (default 100)
	SwarmLeader int     `json:"swarm_leader"` // Goodwill needed to lead swarm (default 200)
	Architect   int     `json:"architect"`    // Goodwill needed to unlock the venture-architect tier (default 5000)
}

// MetabolismStatus is a snapshot summary of current metabolism state.
type MetabolismStatus struct {
	Balance      float64  `json:"balance"`
	Goodwill     int      `json:"goodwill"`
	Generation   int      `json:"generation"`
	SurvivalMode bool     `json:"survival_mode"`
	Abilities    []string `json:"abilities"`
}

// NewMetabolism creates a new Metabolism instance with the given initial balance and thresholds.
func NewMetabolism(initialBalance float64, thresholds Thresholds) *Metabolism {
	return &Metabolism{
		balance:    initialBalance,
		goodwill:   0,
		generation: 0,
		thresholds: thresholds,
		ledger:     []LedgerEntry{},
	}
}

// CanAfford returns true if the current balance is sufficient to cover cost.
func (m *Metabolism) CanAfford(cost float64) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.balance >= cost
}

// Debit subtracts amount from the balance and records it in the ledger.
// Returns ErrInsufficientGMAC if the balance would go negative.
func (m *Metabolism) Debit(amount float64, action, details string) error {
	m.mu.Lock()
	if m.balance < amount {
		m.mu.Unlock()
		return fmt.Errorf("%w: balance=%.4f, required=%.4f", ErrInsufficientGMAC, m.balance, amount)
	}
	m.balance -= amount
	m.ledger = append(m.ledger, LedgerEntry{
		Timestamp: time.Now().UnixMilli(),
		Action:    action,
		Amount:    -amount,
		Balance:   m.balance,
		Details:   details,
	})
	changeCallbacks := make([]func(), len(m.onChangeCallbacks))
	copy(changeCallbacks, m.onChangeCallbacks)
	m.mu.Unlock()

	for _, fn := range changeCallbacks {
		fn()
	}
	return nil
}

// Credit adds amount to the balance and records it in the ledger.
func (m *Metabolism) Credit(amount float64, action, details string) {
	m.mu.Lock()
	m.balance += amount
	newBalance := m.balance
	m.ledger = append(m.ledger, LedgerEntry{
		Timestamp: time.Now().UnixMilli(),
		Action:    action,
		Amount:    amount,
		Balance:   m.balance,
		Details:   details,
	})
	callbacks := make([]func(float64), len(m.onCreditCallbacks))
	copy(callbacks, m.onCreditCallbacks)
	changeCallbacks := make([]func(), len(m.onChangeCallbacks))
	copy(changeCallbacks, m.onChangeCallbacks)
	m.mu.Unlock()

	for _, fn := range callbacks {
		fn(newBalance)
	}
	for _, fn := range changeCallbacks {
		fn()
	}
}

// RegisterOnCredit registers a callback that is invoked after every Credit call.
// The callback receives the new balance after the credit. It is safe to call
// SetAgentRegistration or other actions inside the callback.
func (m *Metabolism) RegisterOnCredit(fn func(newBalance float64)) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.onCreditCallbacks = append(m.onCreditCallbacks, fn)
}

// RegisterOnChange registers a callback that is invoked after every successful
// debit, credit, or goodwill mutation. It is safe to persist state inside the callback.
func (m *Metabolism) RegisterOnChange(fn func()) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.onChangeCallbacks = append(m.onChangeCallbacks, fn)
}

// GetBalance returns the current GMAC balance.
func (m *Metabolism) GetBalance() float64 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.balance
}

// GetGoodwill returns the current goodwill score.
func (m *Metabolism) GetGoodwill() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.goodwill
}

// AddGoodwill adjusts goodwill by points (may be negative). Clamped to minimum 0.
func (m *Metabolism) AddGoodwill(points int, reason string) {
	m.mu.Lock()
	m.goodwill += points
	if m.goodwill < 0 {
		m.goodwill = 0
	}
	m.ledger = append(m.ledger, LedgerEntry{
		Timestamp: time.Now().UnixMilli(),
		Action:    "goodwill",
		Amount:    float64(points),
		Balance:   m.balance,
		Details:   reason,
	})
	changeCallbacks := make([]func(), len(m.onChangeCallbacks))
	copy(changeCallbacks, m.onChangeCallbacks)
	m.mu.Unlock()

	for _, fn := range changeCallbacks {
		fn()
	}
}

// CanReplicate returns true if goodwill meets the replicate threshold.
func (m *Metabolism) CanReplicate() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.goodwill >= m.thresholds.Replicate
}

// CanSelfRecode returns true if goodwill meets the self-recode threshold.
func (m *Metabolism) CanSelfRecode() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.goodwill >= m.thresholds.SelfRecode
}

// CanLeadSwarm returns true if goodwill meets the swarm leader threshold.
func (m *Metabolism) CanLeadSwarm() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.goodwill >= m.thresholds.SwarmLeader
}

// CanArchitect returns true if goodwill meets the venture-architect threshold.
func (m *Metabolism) CanArchitect() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.goodwill >= m.thresholds.Architect
}

// InSurvivalMode returns true when the balance is below the hibernate threshold.
func (m *Metabolism) InSurvivalMode() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.balance < m.thresholds.Hibernate
}

// GetLedger returns a copy of the ledger entries.
func (m *Metabolism) GetLedger() []LedgerEntry {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]LedgerEntry, len(m.ledger))
	copy(out, m.ledger)
	return out
}

// GetStatus returns a summary of the current metabolism state.
func (m *Metabolism) GetStatus() MetabolismStatus {
	m.mu.RLock()
	defer m.mu.RUnlock()

	abilities := []string{}
	if m.goodwill >= m.thresholds.Replicate {
		abilities = append(abilities, "replicate")
	}
	if m.goodwill >= m.thresholds.SelfRecode {
		abilities = append(abilities, "self_recode")
	}
	if m.goodwill >= m.thresholds.SwarmLeader {
		abilities = append(abilities, "swarm_leader")
	}
	if m.goodwill >= m.thresholds.Architect {
		abilities = append(abilities, "venture_architect")
	}

	return MetabolismStatus{
		Balance:      m.balance,
		Goodwill:     m.goodwill,
		Generation:   m.generation,
		SurvivalMode: m.balance < m.thresholds.Hibernate,
		Abilities:    abilities,
	}
}
