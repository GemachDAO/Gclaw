// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package lifecycle

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestShutdownManager_EmptyIsNoOp(t *testing.T) {
	sm := NewShutdownManager(time.Second)
	if err := sm.Shutdown(context.Background()); err != nil {
		t.Errorf("expected nil error for empty manager, got: %v", err)
	}
}

func TestShutdownManager_HooksExecuteInReverseOrder(t *testing.T) {
	var order []string
	mu := sync.Mutex{}

	sm := NewShutdownManager(time.Second)
	sm.Register("first", func(_ context.Context) error {
		mu.Lock()
		order = append(order, "first")
		mu.Unlock()
		return nil
	})
	sm.Register("second", func(_ context.Context) error {
		mu.Lock()
		order = append(order, "second")
		mu.Unlock()
		return nil
	})
	sm.Register("third", func(_ context.Context) error {
		mu.Lock()
		order = append(order, "third")
		mu.Unlock()
		return nil
	})

	if err := sm.Shutdown(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	want := []string{"third", "second", "first"}
	for i, got := range order {
		if got != want[i] {
			t.Errorf("hook[%d] = %q, want %q", i, got, want[i])
		}
	}
}

func TestShutdownManager_ErrorsCollectedButOtherHooksRun(t *testing.T) {
	var ran []string
	mu := sync.Mutex{}

	sm := NewShutdownManager(time.Second)
	sm.Register("a", func(_ context.Context) error {
		mu.Lock()
		ran = append(ran, "a")
		mu.Unlock()
		return nil
	})
	sm.Register("b", func(_ context.Context) error {
		return errors.New("hook b failed")
	})
	sm.Register("c", func(_ context.Context) error {
		mu.Lock()
		ran = append(ran, "c")
		mu.Unlock()
		return nil
	})

	err := sm.Shutdown(context.Background())
	if err == nil {
		t.Fatal("expected error from failing hook")
	}
	if !strings.Contains(err.Error(), "hook b failed") {
		t.Errorf("expected error to mention 'hook b failed', got: %v", err)
	}

	// Both 'a' and 'c' must have run despite 'b' failing
	got := strings.Join(ran, ",")
	if !strings.Contains(got, "a") || !strings.Contains(got, "c") {
		t.Errorf("expected hooks 'a' and 'c' to run, but ran: %s", got)
	}
}

func TestShutdownManager_TimeoutCancelsHook(t *testing.T) {
	blocker := make(chan struct{})

	sm := NewShutdownManager(50 * time.Millisecond)
	sm.Register("slow", func(ctx context.Context) error {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-blocker:
			return nil
		}
	})

	start := time.Now()
	err := sm.Shutdown(context.Background())
	elapsed := time.Since(start)
	close(blocker)

	if err == nil {
		t.Fatal("expected timeout error")
	}
	if elapsed > 500*time.Millisecond {
		t.Errorf("shutdown took too long: %v", elapsed)
	}
}

func TestShutdownManager_ConcurrentRegisterIsSafe(t *testing.T) {
	sm := NewShutdownManager(time.Second)

	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			sm.Register("hook", func(_ context.Context) error { return nil })
		}()
	}
	wg.Wait()

	// Should run without panics
	if err := sm.Shutdown(context.Background()); err != nil {
		t.Errorf("unexpected error: %v", err)
	}
}

func TestShutdownManager_DefaultTimeout(t *testing.T) {
	sm := NewShutdownManager(0) // zero → default
	if sm.timeout != DefaultShutdownTimeout {
		t.Errorf("expected default timeout %v, got %v", DefaultShutdownTimeout, sm.timeout)
	}
}
