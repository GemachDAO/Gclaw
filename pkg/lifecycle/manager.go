// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

// Package lifecycle provides a ShutdownManager for ordered, graceful shutdown
// of agent components.
package lifecycle

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/logger"
)

// DefaultShutdownTimeout is the default per-hook timeout used by Shutdown.
const DefaultShutdownTimeout = 10 * time.Second

// hook is a named shutdown function registered with the manager.
type hook struct {
	name string
	fn   func(ctx context.Context) error
}

// ShutdownManager executes registered shutdown hooks in reverse registration
// order. It is safe for concurrent use.
type ShutdownManager struct {
	mu      sync.Mutex
	hooks   []hook
	timeout time.Duration
}

// NewShutdownManager returns a ShutdownManager with the given per-hook timeout.
// If timeout is ≤ 0 the DefaultShutdownTimeout is used.
func NewShutdownManager(timeout time.Duration) *ShutdownManager {
	if timeout <= 0 {
		timeout = DefaultShutdownTimeout
	}
	return &ShutdownManager{timeout: timeout}
}

// Register adds a named shutdown hook. Hooks are executed in reverse
// registration order during Shutdown.
func (sm *ShutdownManager) Register(name string, fn func(ctx context.Context) error) {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	sm.hooks = append(sm.hooks, hook{name: name, fn: fn})
}

// Shutdown executes all registered hooks in reverse registration order.
// Each hook runs with a context derived from ctx and bounded by the configured
// timeout. Hook errors are collected and returned as a single combined error;
// a failing hook does not prevent subsequent hooks from running.
func (sm *ShutdownManager) Shutdown(ctx context.Context) error {
	sm.mu.Lock()
	hooks := make([]hook, len(sm.hooks))
	copy(hooks, sm.hooks)
	sm.mu.Unlock()

	var errs []error
	for i := len(hooks) - 1; i >= 0; i-- {
		h := hooks[i]
		logger.InfoCF("lifecycle", "running shutdown hook", map[string]any{"hook": h.name})

		hCtx, cancel := context.WithTimeout(ctx, sm.timeout)
		err := h.fn(hCtx)
		cancel()

		if err != nil {
			logger.ErrorCF("lifecycle", "shutdown hook error",
				map[string]any{"hook": h.name, "error": err.Error()})
			errs = append(errs, fmt.Errorf("%s: %w", h.name, err))
		} else {
			logger.InfoCF("lifecycle", "shutdown hook completed", map[string]any{"hook": h.name})
		}
	}

	if len(errs) == 0 {
		return nil
	}
	return joinErrors(errs)
}

// joinErrors combines multiple errors into a single descriptive error.
func joinErrors(errs []error) error {
	msg := "shutdown errors:"
	for _, e := range errs {
		msg += "\n  - " + e.Error()
	}
	return errors.New(msg)
}
