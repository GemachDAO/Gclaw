package voice

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestNewGroqTranscriber(t *testing.T) {
	tr := NewGroqTranscriber("test-key")
	if tr == nil {
		t.Fatal("expected non-nil transcriber")
	}
	if tr.apiKey != "test-key" {
		t.Errorf("unexpected apiKey: %s", tr.apiKey)
	}
}

func TestIsAvailable_WithKey(t *testing.T) {
	tr := NewGroqTranscriber("some-key")
	if !tr.IsAvailable() {
		t.Error("expected IsAvailable=true when API key is set")
	}
}

func TestIsAvailable_NoKey(t *testing.T) {
	tr := NewGroqTranscriber("")
	if tr.IsAvailable() {
		t.Error("expected IsAvailable=false when no API key")
	}
}

func TestTranscribe_Success(t *testing.T) {
	// Create a test HTTP server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify request headers
		if r.Header.Get("Authorization") != "Bearer test-key" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}

		resp := TranscriptionResponse{
			Text:     "Hello, world!",
			Language: "en",
			Duration: 2.5,
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	tr := NewGroqTranscriber("test-key")
	tr.apiBase = server.URL

	// Create a temporary audio file
	tmpDir := t.TempDir()
	audioFile := filepath.Join(tmpDir, "audio.mp3")
	if err := os.WriteFile(audioFile, []byte("fake audio data"), 0o600); err != nil {
		t.Fatalf("create temp audio file: %v", err)
	}

	result, err := tr.Transcribe(context.Background(), audioFile)
	if err != nil {
		t.Fatalf("Transcribe failed: %v", err)
	}
	if result.Text != "Hello, world!" {
		t.Errorf("expected text 'Hello, world!', got %q", result.Text)
	}
	if result.Language != "en" {
		t.Errorf("expected language 'en', got %q", result.Language)
	}
}

func TestTranscribe_FileNotFound(t *testing.T) {
	tr := NewGroqTranscriber("test-key")
	_, err := tr.Transcribe(context.Background(), "/nonexistent/audio.mp3")
	if err == nil {
		t.Error("expected error for nonexistent file")
	}
}

func TestTranscribe_APIError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "rate limit exceeded", http.StatusTooManyRequests)
	}))
	defer server.Close()

	tr := NewGroqTranscriber("test-key")
	tr.apiBase = server.URL

	tmpDir := t.TempDir()
	audioFile := filepath.Join(tmpDir, "audio.wav")
	if err := os.WriteFile(audioFile, []byte("fake audio"), 0o600); err != nil {
		t.Fatalf("create temp audio file: %v", err)
	}

	_, err := tr.Transcribe(context.Background(), audioFile)
	if err == nil {
		t.Error("expected error for API error response")
	}
}

func TestTranscribe_InvalidJSON(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("not valid json"))
	}))
	defer server.Close()

	tr := NewGroqTranscriber("test-key")
	tr.apiBase = server.URL

	tmpDir := t.TempDir()
	audioFile := filepath.Join(tmpDir, "audio.ogg")
	if err := os.WriteFile(audioFile, []byte("fake audio"), 0o600); err != nil {
		t.Fatalf("create temp audio file: %v", err)
	}

	_, err := tr.Transcribe(context.Background(), audioFile)
	if err == nil {
		t.Error("expected error for invalid JSON response")
	}
}

func TestTranscribe_ContextCancelled(t *testing.T) {
	// Server that blocks
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	}))
	defer server.Close()

	tr := NewGroqTranscriber("test-key")
	tr.apiBase = server.URL

	tmpDir := t.TempDir()
	audioFile := filepath.Join(tmpDir, "audio.mp3")
	if err := os.WriteFile(audioFile, []byte("fake audio"), 0o600); err != nil {
		t.Fatalf("create temp audio file: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := tr.Transcribe(ctx, audioFile)
	if err == nil {
		t.Error("expected error for cancelled context")
	}
}
