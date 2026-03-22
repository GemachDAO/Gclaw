package runtimeinfo

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/cron"
)

const (
	AutoTradeJobName      = "gclaw-auto-trade"
	AutoTradeCycleCommand = "__gclaw_auto_trade_cycle__"
)

var autoTradeInterval = 5 * time.Minute

// AutoTradeRuntimeStatus reports whether the auto-trade scheduler is actually
// armed and what happened during the last cycle.
type AutoTradeRuntimeStatus struct {
	State      string `json:"state"`
	Active     bool   `json:"active"`
	JobID      string `json:"job_id,omitempty"`
	Schedule   string `json:"schedule,omitempty"`
	LastStatus string `json:"last_status,omitempty"`
	LastError  string `json:"last_error,omitempty"`
	LastRunAt  int64  `json:"last_run_at,omitempty"`
	NextRunAt  int64  `json:"next_run_at,omitempty"`
}

// AutoTradeInterval returns the scheduler cadence used for autonomous trade cycles.
func AutoTradeInterval() time.Duration {
	return autoTradeInterval
}

// BuildAutoTradeRuntimeStatus reads the cron store and reports the live
// scheduler state for the managed auto-trade job.
func BuildAutoTradeRuntimeStatus(cfg *config.Config) *AutoTradeRuntimeStatus {
	status := &AutoTradeRuntimeStatus{
		State: "disabled",
	}
	if cfg == nil || !cfg.Tools.GDEX.AutoTrade {
		return status
	}

	status.State = "not_scheduled"

	job, err := loadAutoTradeJob(filepath.Join(cfg.WorkspacePath(), "cron", "jobs.json"))
	if err != nil {
		if os.IsNotExist(err) {
			return status
		}
		status.LastError = err.Error()
		return status
	}
	if job == nil {
		return status
	}

	status.Active = job.Enabled
	status.JobID = job.ID
	status.Schedule = formatAutoTradeSchedule(job.Schedule)
	status.LastStatus = job.State.LastStatus
	status.LastError = job.State.LastError
	if job.State.LastRunAtMS != nil {
		status.LastRunAt = *job.State.LastRunAtMS
	}
	if job.State.NextRunAtMS != nil {
		status.NextRunAt = *job.State.NextRunAtMS
	}
	if job.Enabled {
		status.State = "scheduled"
	} else {
		status.State = "paused"
	}
	return status
}

func loadAutoTradeJob(storePath string) (*cron.CronJob, error) {
	data, err := os.ReadFile(storePath)
	if err != nil {
		return nil, err
	}

	var store cron.CronStore
	if err := json.Unmarshal(data, &store); err != nil {
		return nil, fmt.Errorf("parse cron store: %w", err)
	}

	for i := range store.Jobs {
		job := store.Jobs[i]
		if job.Name == AutoTradeJobName || job.Payload.Message == AutoTradeCycleCommand {
			copyJob := job
			return &copyJob, nil
		}
	}
	return nil, nil
}

func formatAutoTradeSchedule(schedule cron.CronSchedule) string {
	switch schedule.Kind {
	case "every":
		if schedule.EveryMS == nil || *schedule.EveryMS <= 0 {
			return "every ?"
		}
		d := time.Duration(*schedule.EveryMS) * time.Millisecond
		if d%time.Minute == 0 {
			return fmt.Sprintf("every %dm", int(d/time.Minute))
		}
		if d%time.Second == 0 {
			return fmt.Sprintf("every %ds", int(d/time.Second))
		}
		return d.String()
	case "cron":
		if schedule.Expr == "" {
			return "cron"
		}
		return schedule.Expr
	case "at":
		return "one-time"
	default:
		return "unknown"
	}
}
