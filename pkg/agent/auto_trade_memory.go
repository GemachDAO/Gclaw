package agent

import (
	"strings"

	"github.com/GemachDAO/Gclaw/pkg/tools"
)

type autoTradeLearningMemory struct {
	ChainScores    map[int64]float64
	TokenScores    map[string]float64
	RealizedTrades int
	LossStreak     int
}

func buildAutoTradeLearningMemory(history []tools.TradeRecord) *autoTradeLearningMemory {
	memory := &autoTradeLearningMemory{
		ChainScores: make(map[int64]float64),
		TokenScores: make(map[string]float64),
	}
	if len(history) == 0 {
		return memory
	}

	currentLossStreak := 0
	for _, trade := range history {
		if !trade.HasPnL {
			continue
		}
		memory.RealizedTrades++
		normalized := normalizePnL(trade.PnL)
		if trade.ChainID != 0 {
			memory.ChainScores[int64(trade.ChainID)] += normalized
		}
		if token := strings.ToLower(strings.TrimSpace(trade.TokenAddress)); token != "" {
			memory.TokenScores[token] += normalized
		}
		if trade.PnL < 0 {
			currentLossStreak++
		} else {
			currentLossStreak = 0
		}
	}
	memory.LossStreak = currentLossStreak
	return memory
}

func (m *autoTradeLearningMemory) chainScore(chainID int64) float64 {
	if m == nil {
		return 0
	}
	return m.ChainScores[chainID]
}

func (m *autoTradeLearningMemory) tokenScore(tokenAddress string) float64 {
	if m == nil {
		return 0
	}
	return m.TokenScores[strings.ToLower(strings.TrimSpace(tokenAddress))]
}

func normalizePnL(pnl float64) float64 {
	switch {
	case pnl >= 15:
		return 3
	case pnl >= 5:
		return 1.5
	case pnl > 0:
		return 0.5
	case pnl <= -15:
		return -3
	case pnl <= -5:
		return -1.5
	case pnl < 0:
		return -0.5
	default:
		return 0
	}
}
