package health

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/x402"
)

func TestNewServer(t *testing.T) {
	s := NewServer("127.0.0.1", 0)
	if s == nil {
		t.Fatal("expected non-nil server")
	}
	if s.ready {
		t.Error("server should not be ready initially")
	}
}

func TestHealthHandler(t *testing.T) {
	s := NewServer("127.0.0.1", 0)

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()

	s.healthHandler(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200, got %d", resp.StatusCode)
	}

	var body StatusResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}
	if body.Status != "ok" {
		t.Errorf("expected status 'ok', got %q", body.Status)
	}
}

func TestReadyHandler_NotReady(t *testing.T) {
	s := NewServer("127.0.0.1", 0)

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	w := httptest.NewRecorder()

	s.readyHandler(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Errorf("expected 503, got %d", resp.StatusCode)
	}

	var body StatusResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}
	if body.Status != "not ready" {
		t.Errorf("expected 'not ready', got %q", body.Status)
	}
}

func TestReadyHandler_Ready(t *testing.T) {
	s := NewServer("127.0.0.1", 0)
	s.SetReady(true)

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	w := httptest.NewRecorder()

	s.readyHandler(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200, got %d", resp.StatusCode)
	}
}

func TestReadyHandler_WithFailingCheck(t *testing.T) {
	s := NewServer("127.0.0.1", 0)
	s.SetReady(true)
	s.RegisterCheck("db", func() (bool, string) {
		return false, "database unreachable"
	})

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	w := httptest.NewRecorder()

	s.readyHandler(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Errorf("expected 503 when check fails, got %d", resp.StatusCode)
	}

	var body StatusResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}
	if body.Status != "not ready" {
		t.Errorf("expected 'not ready', got %q", body.Status)
	}
	if body.Checks["db"].Status != "fail" {
		t.Errorf("expected db check to fail, got %q", body.Checks["db"].Status)
	}
}

func TestReadyHandler_WithPassingCheck(t *testing.T) {
	s := NewServer("127.0.0.1", 0)
	s.SetReady(true)
	s.RegisterCheck("db", func() (bool, string) {
		return true, "connected"
	})

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	w := httptest.NewRecorder()

	s.readyHandler(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200, got %d", resp.StatusCode)
	}

	var body StatusResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}
	if body.Status != "ready" {
		t.Errorf("expected 'ready', got %q", body.Status)
	}
	if body.Checks["db"].Status != "ok" {
		t.Errorf("expected db check to pass, got %q", body.Checks["db"].Status)
	}
}

func TestSetReady(t *testing.T) {
	s := NewServer("127.0.0.1", 0)
	s.SetReady(true)
	if !s.ready {
		t.Error("expected ready=true")
	}
	s.SetReady(false)
	if s.ready {
		t.Error("expected ready=false")
	}
}

func TestStatusString(t *testing.T) {
	if statusString(true) != "ok" {
		t.Error("expected 'ok' for true")
	}
	if statusString(false) != "fail" {
		t.Error("expected 'fail' for false")
	}
}

func TestStop(t *testing.T) {
	s := NewServer("127.0.0.1", 9999)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	// Server was never started, so shutdown should succeed gracefully
	err := s.Stop(ctx)
	if err != nil {
		t.Errorf("expected no error stopping unstarted server, got %v", err)
	}
}

func TestRegisterCheck_MultipleChecks(t *testing.T) {
	s := NewServer("127.0.0.1", 0)
	s.SetReady(true)
	s.RegisterCheck("redis", func() (bool, string) { return true, "ok" })
	s.RegisterCheck("db", func() (bool, string) { return true, "ok" })

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	w := httptest.NewRecorder()
	s.readyHandler(w, req)

	if w.Result().StatusCode != http.StatusOK {
		t.Error("expected 200 when all checks pass")
	}
}

func TestHealthHandler_Uptime(t *testing.T) {
	s := NewServer("127.0.0.1", 0)
	time.Sleep(5 * time.Millisecond) // ensure some uptime

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()
	s.healthHandler(w, req)

	var body StatusResponse
	if err := json.NewDecoder(w.Result().Body).Decode(&body); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if body.Uptime == "" {
		t.Error("expected non-empty uptime")
	}
}

func TestAgentRegistrationHandler_NotSet(t *testing.T) {
	s := NewServer("127.0.0.1", 0)

	req := httptest.NewRequest(http.MethodGet, "/.well-known/agent-registration.json", nil)
	w := httptest.NewRecorder()
	s.agentRegistrationHandler(w, req)

	if w.Result().StatusCode != http.StatusNotFound {
		t.Errorf("expected 404 when registration not set, got %d", w.Result().StatusCode)
	}
}

func TestAgentRegistrationHandler_Set(t *testing.T) {
	s := NewServer("127.0.0.1", 0)
	reg := &x402.AgentRegistration{
		Type:        x402.RegistrationType,
		Name:        "TestAgent",
		Description: "Gclaw autonomous AI agent",
		X402Support: true,
		Active:      true,
		Services: []x402.ServiceDef{
			{Name: "gateway", Endpoint: "http://127.0.0.1:18790"},
		},
	}
	s.SetAgentRegistration(reg)

	req := httptest.NewRequest(http.MethodGet, "/.well-known/agent-registration.json", nil)
	w := httptest.NewRecorder()
	s.agentRegistrationHandler(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200 when registration set, got %d", resp.StatusCode)
	}
	if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected Content-Type application/json, got %q", ct)
	}

	var decoded x402.AgentRegistration
	if err := json.NewDecoder(resp.Body).Decode(&decoded); err != nil {
		t.Fatalf("failed to decode agent registration: %v", err)
	}
	if decoded.Type != x402.RegistrationType {
		t.Errorf("expected type %q, got %q", x402.RegistrationType, decoded.Type)
	}
	if decoded.Name != "TestAgent" {
		t.Errorf("expected name TestAgent, got %q", decoded.Name)
	}
	if !decoded.X402Support {
		t.Error("expected X402Support=true")
	}
	if !decoded.Active {
		t.Error("expected Active=true")
	}
	if len(decoded.Services) != 1 || decoded.Services[0].Name != "gateway" {
		t.Errorf("unexpected services: %v", decoded.Services)
	}
}
