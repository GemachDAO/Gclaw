package recode

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
)

// RecodeAction records a single self-modification applied by the agent.
type RecodeAction struct {
	Type      string `json:"type"` // "prompt", "cron", "skill", "trading_param"
	Details   string `json:"details"`
	Timestamp int64  `json:"timestamp"`
	Approved  bool   `json:"approved"` // self-approved via goodwill
}

// Recoder allows the agent to modify its own configuration
// when it has earned sufficient goodwill.
type Recoder struct {
	configPath string
	workspace  string
	actionLog  []RecodeAction
	mu         sync.Mutex
}

// NewRecoder creates a Recoder for the given config file and workspace.
func NewRecoder(configPath, workspace string) *Recoder {
	return &Recoder{
		configPath: configPath,
		workspace:  workspace,
		actionLog:  []RecodeAction{},
	}
}

// ModifySystemPrompt appends `addition` to the system prompt of every agent in config.
func (rc *Recoder) ModifySystemPrompt(addition string) error {
	rc.mu.Lock()
	defer rc.mu.Unlock()

	cfg, err := config.LoadConfig(rc.configPath)
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}

	// Append a marker comment to the defaults workspace path for persistence of prompt note.
	// The actual system prompt is maintained by the agent loop from a separate file;
	// we record the action here and write the addition to a prompt-additions file.
	additionPath := rc.workspace + "/recode/prompt_additions.txt"
	if err := appendToFile(additionPath, addition+"\n"); err != nil {
		return fmt.Errorf("write prompt addition: %w", err)
	}

	if err := config.SaveConfig(rc.configPath, cfg); err != nil {
		return fmt.Errorf("save config: %w", err)
	}

	rc.logAction("prompt", addition)
	return nil
}

// AddCronJob appends a new cron entry to the agent's config.
// schedule must be a valid cron expression; task is a natural-language description.
func (rc *Recoder) AddCronJob(schedule, task string) error {
	rc.mu.Lock()
	defer rc.mu.Unlock()

	cfg, err := config.LoadConfig(rc.configPath)
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}

	if cfg.Tools.Cron.ExecTimeoutMinutes == 0 {
		cfg.Tools.Cron.ExecTimeoutMinutes = 5 // sensible default
	}

	if err := config.SaveConfig(rc.configPath, cfg); err != nil {
		return fmt.Errorf("save config: %w", err)
	}

	// Record the cron job in a dedicated file for the cron tool to pick up.
	cronEntry := fmt.Sprintf("%s\t%s\n", schedule, task)
	cronPath := rc.workspace + "/recode/cron_additions.txt"
	if err := appendToFile(cronPath, cronEntry); err != nil {
		return fmt.Errorf("write cron addition: %w", err)
	}

	rc.logAction("cron", fmt.Sprintf("schedule=%s task=%s", schedule, task))
	return nil
}

// InstallSkill records a skill installation request that the skills tool can act on.
func (rc *Recoder) InstallSkill(skillSlug, registry string) error {
	rc.mu.Lock()
	defer rc.mu.Unlock()

	installPath := rc.workspace + "/recode/skill_installs.txt"
	entry := fmt.Sprintf("%s\t%s\n", registry, skillSlug)
	if err := appendToFile(installPath, entry); err != nil {
		return fmt.Errorf("write skill install request: %w", err)
	}

	rc.logAction("skill", fmt.Sprintf("slug=%s registry=%s", skillSlug, registry))
	return nil
}

// AdjustTradingParams merges params into the GDEX config section and saves.
func (rc *Recoder) AdjustTradingParams(params map[string]any) error {
	rc.mu.Lock()
	defer rc.mu.Unlock()

	cfg, err := config.LoadConfig(rc.configPath)
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}

	// Apply params to GDEXConfig fields by name.
	if v, ok := params["max_trade_size_sol"]; ok {
		if f, ok := toFloat64(v); ok {
			cfg.Tools.GDEX.MaxTradeSizeSOL = f
		}
	}
	if v, ok := params["auto_trade"]; ok {
		if b, ok := v.(bool); ok {
			cfg.Tools.GDEX.AutoTrade = b
		}
	}
	if v, ok := params["default_chain_id"]; ok {
		if f, ok := toFloat64(v); ok {
			cfg.Tools.GDEX.DefaultChainID = int64(f)
		}
	}

	if err := config.SaveConfig(rc.configPath, cfg); err != nil {
		return fmt.Errorf("save config: %w", err)
	}

	details, _ := json.Marshal(params)
	rc.logAction("trading_param", string(details))
	return nil
}

// GetActionLog returns a copy of all recorded recode actions.
func (rc *Recoder) GetActionLog() []RecodeAction {
	rc.mu.Lock()
	defer rc.mu.Unlock()
	out := make([]RecodeAction, len(rc.actionLog))
	copy(out, rc.actionLog)
	return out
}

// Rollback reverts the action at actionIndex by recording a reversal note.
// Full undo of arbitrary config changes is complex; this implementation marks
// the action as un-approved and records a rollback entry.
func (rc *Recoder) Rollback(actionIndex int) error {
	rc.mu.Lock()
	defer rc.mu.Unlock()

	if actionIndex < 0 || actionIndex >= len(rc.actionLog) {
		return fmt.Errorf("invalid action index %d (log has %d entries)", actionIndex, len(rc.actionLog))
	}

	original := rc.actionLog[actionIndex]
	rc.actionLog[actionIndex].Approved = false
	rc.logAction("rollback", fmt.Sprintf("rolled back action %d (type=%s)", actionIndex, original.Type))
	return nil
}

// logAction appends an approved RecodeAction. Caller must hold rc.mu.
func (rc *Recoder) logAction(typ, details string) {
	rc.actionLog = append(rc.actionLog, RecodeAction{
		Type:      typ,
		Details:   details,
		Timestamp: time.Now().UnixMilli(),
		Approved:  true,
	})
}

// appendToFile ensures the directory exists and appends content to a file.
func appendToFile(path, content string) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.WriteString(content)
	return err
}

// toFloat64 attempts to convert an any value to float64.
func toFloat64(v any) (float64, bool) {
	switch val := v.(type) {
	case float64:
		return val, true
	case int:
		return float64(val), true
	case int64:
		return float64(val), true
	case json.Number:
		f, err := val.Float64()
		return f, err == nil
	}
	return 0, false
}
