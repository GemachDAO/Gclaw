package dashboard

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// --- formatAgo ---

func TestFormatAgo(t *testing.T) {
	now := time.Now().UnixMilli()
	tests := []struct {
		name     string
		ms       int64
		contains string
	}{
		{"zero", 0, "unknown"},
		{"just now", now - 30*1000, "ago"},
		{"1 minute ago", now - 90*1000, "m ago"},
		{"2 hours ago", now - 2*3600*1000, "h ago"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := formatAgo(tt.ms)
			if !strings.Contains(got, tt.contains) {
				t.Errorf("formatAgo(%d) = %q, expected to contain %q", tt.ms, got, tt.contains)
			}
		})
	}
}

// --- centerText ---

func TestCenterText_Short(t *testing.T) {
	got := centerText("hi", 10)
	if !strings.Contains(got, "hi") {
		t.Errorf("expected 'hi' in result: %q", got)
	}
}

func TestCenterText_ExactWidth(t *testing.T) {
	got := centerText("hello", 5)
	if got != "hello" {
		t.Errorf("expected 'hello', got %q", got)
	}
}

func TestCenterText_Longer(t *testing.T) {
	got := centerText("test", 20)
	if !strings.Contains(got, "test") {
		t.Errorf("expected 'test' in result: %q", got)
	}
}

// --- htmlEscape ---

func TestHTMLEscape(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"hello", "hello"},
		{"<script>", "&lt;script&gt;"},
		{"a & b", "a &amp; b"},
		{`"quoted"`, "&#34;quoted&#34;"},
		{"it's", "it&#39;s"},
	}
	for _, tt := range tests {
		got := htmlEscape(tt.input)
		if got != tt.want {
			t.Errorf("htmlEscape(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

// --- RegisterHandlers / serveSection ---

func TestRegisterHandlers(t *testing.T) {
	d := NewDashboard(DashboardOptions{AgentID: "test"})
	mux := http.NewServeMux()
	RegisterHandlers(mux, d)

	// Test /dashboard endpoint
	req := httptest.NewRequest(http.MethodGet, "/dashboard", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Errorf("expected 200 for /dashboard, got %d", w.Code)
	}
}

func TestServeSection_ValidSection(t *testing.T) {
	d := NewDashboard(DashboardOptions{
		AgentID: "test",
		GetMetabolism: func() *MetabolismSnapshot {
			return &MetabolismSnapshot{Balance: 100}
		},
		GetFamily:    func() *FamilySnapshot { return &FamilySnapshot{} },
		GetTelepathy: func() *TelepathySnapshot { return &TelepathySnapshot{} },
		GetSwarm:     func() *SwarmSnapshot { return &SwarmSnapshot{} },
	})
	mux := http.NewServeMux()
	RegisterHandlers(mux, d)

	for _, path := range []string{
		"/dashboard/api",
		"/dashboard/api/metabolism",
		"/dashboard/api/family",
		"/dashboard/api/telepathy",
		"/dashboard/api/swarm",
	} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Errorf("expected 200 for %s, got %d", path, w.Code)
		}
	}
}

func TestServeSection_MethodNotAllowed(t *testing.T) {
	d := NewDashboard(DashboardOptions{AgentID: "test"})
	mux := http.NewServeMux()
	RegisterHandlers(mux, d)

	req := httptest.NewRequest(http.MethodPost, "/dashboard/api/metabolism", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405, got %d", w.Code)
	}
}
