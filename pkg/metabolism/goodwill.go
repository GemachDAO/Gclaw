package metabolism

// Goodwill point values for common events.
const (
	GoodwillProfitableTrade   = 10  // Trade with >5% profit
	GoodwillUserThanks        = 5   // User explicitly thanks agent
	GoodwillTaskComplete      = 3   // Successfully completed a task
	GoodwillHelpAgent         = 2   // Helped another agent (subagent spawn)
	GoodwillBadTrade          = -8  // Trade with >10% loss
	GoodwillFailedTask        = -2  // Failed to complete task
	GoodwillSelfFundInference = 15  // Agent successfully paid for its own LLM inference
)

// GoodwillTracker wraps Metabolism.AddGoodwill with domain-specific helpers.
type GoodwillTracker struct {
	m *Metabolism
}

// NewGoodwillTracker creates a GoodwillTracker backed by the given Metabolism.
func NewGoodwillTracker(m *Metabolism) *GoodwillTracker {
	return &GoodwillTracker{m: m}
}

// RecordTradeResult auto-calculates goodwill from trade P&L percentage.
// profitPercent > 5 awards GoodwillProfitableTrade; loss > 10% deducts GoodwillBadTrade.
func (g *GoodwillTracker) RecordTradeResult(profitPercent float64) {
	switch {
	case profitPercent > 5:
		g.m.AddGoodwill(GoodwillProfitableTrade, "profitable trade")
	case profitPercent < -10:
		g.m.AddGoodwill(GoodwillBadTrade, "bad trade")
	}
}

// RecordTaskResult awards or deducts goodwill based on task success.
func (g *GoodwillTracker) RecordTaskResult(success bool) {
	if success {
		g.m.AddGoodwill(GoodwillTaskComplete, "task completed")
	} else {
		g.m.AddGoodwill(GoodwillFailedTask, "task failed")
	}
}

// RecordUserFeedback awards goodwill when the user gives positive feedback.
func (g *GoodwillTracker) RecordUserFeedback(positive bool) {
	if positive {
		g.m.AddGoodwill(GoodwillUserThanks, "user thanks")
	}
}

// RecordSelfFunding awards goodwill when the agent pays for its own inference.
func (g *GoodwillTracker) RecordSelfFunding() {
	g.m.AddGoodwill(GoodwillSelfFundInference, "self-funded inference")
}

// GetAbilities returns a list of ability names the agent has unlocked.
func (g *GoodwillTracker) GetAbilities() []string {
	return g.m.GetStatus().Abilities
}
