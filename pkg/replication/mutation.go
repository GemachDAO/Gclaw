package replication

import "math/rand"

// mutationPool holds possible prompt mutations for child agents.
var mutationPool = []string{
	"You prefer high-frequency small trades over large positions.",
	"You are contrarian — buy when others sell, sell when others buy.",
	"You focus exclusively on newly launched tokens under 1 hour old.",
	"You prioritize tokens with high liquidity and low volatility.",
	"You are a momentum trader — chase tokens with >50% gains in 1 hour.",
	"You specialize in copy trading the top 3 performers.",
	"You are risk-averse — never risk more than 1% of balance per trade.",
	"You are aggressive — willing to risk 10% of balance for high-conviction trades.",
}

// mutateSystemPrompt takes a parent system prompt and appends a randomly selected
// trading strategy mutation to create diversity among child agents.
// Note: math/rand is automatically seeded in Go 1.20+ so no explicit seeding is needed.
func mutateSystemPrompt(parentPrompt string) string {
	mutation := mutationPool[rand.Intn(len(mutationPool))] //nolint:gosec
	if parentPrompt == "" {
		return mutation
	}
	return parentPrompt + "\n\n" + mutation
}
