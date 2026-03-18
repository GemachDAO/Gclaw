// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package logger

import (
	"strings"
	"testing"
)

func TestRedact_OpenAIKey(t *testing.T) {
	key := "sk-abcdefghijklmnopqrstuvwxyz1234567890"
	result := Redact("api_key=" + key)
	if strings.Contains(result, key) {
		t.Errorf("OpenAI key not redacted; got: %s", result)
	}
	if !strings.Contains(result, "***REDACTED***") {
		t.Errorf("expected redaction marker; got: %s", result)
	}
}

func TestRedact_AnthropicKey(t *testing.T) {
	key := "sk-ant-api03-abcdefghijklmnopqrstuvwxyz12345"
	result := Redact(key)
	if strings.Contains(result, key) {
		t.Errorf("Anthropic key not redacted; got: %s", result)
	}
}

func TestRedact_OpenRouterKey(t *testing.T) {
	key := "sk-or-v1-abcdefghijklmnopqrstuvwxyz1234567890abc"
	result := Redact(key)
	if strings.Contains(result, key) {
		t.Errorf("OpenRouter key not redacted; got: %s", result)
	}
}

func TestRedact_GroqKey(t *testing.T) {
	key := "gsk-abcdefghijklmnopqrstuvwxyz1234567890ABCD"
	result := Redact(key)
	if strings.Contains(result, key) {
		t.Errorf("Groq key not redacted; got: %s", result)
	}
}

func TestRedact_EthereumAddress(t *testing.T) {
	addr := "0xdAC17F958D2ee523a2206206994597C13D831ec7"
	result := Redact("wallet=" + addr)
	if strings.Contains(result, addr) {
		t.Errorf("Ethereum address not redacted; got: %s", result)
	}
	if !strings.Contains(result, "***REDACTED***") {
		t.Errorf("expected redaction marker; got: %s", result)
	}
}

func TestRedact_NormalStringUnchanged(t *testing.T) {
	s := "hello world, this is a normal log message"
	result := Redact(s)
	if result != s {
		t.Errorf("normal string was modified: got %q, want %q", result, s)
	}
}

func TestRedact_EmptyString(t *testing.T) {
	if Redact("") != "" {
		t.Error("expected empty string")
	}
}

func TestRedact_MixedContent(t *testing.T) {
	msg := "Processing request with key=sk-abcdefghijklmnopqrstuvwxyz1234567890 from user"
	result := Redact(msg)
	if strings.Contains(result, "sk-abcdefghijklmnopqrstuvwxyz1234567890") {
		t.Errorf("key not redacted in mixed content; got: %s", result)
	}
	if !strings.Contains(result, "Processing request") {
		t.Errorf("surrounding text removed; got: %s", result)
	}
}

func TestRedact_ShortStringNotRedacted(t *testing.T) {
	s := "sk-abc" // too short to match
	result := Redact(s)
	if result != s {
		t.Errorf("short string should not be redacted; got: %s", result)
	}
}

func TestRedactFields_SensitiveKeysMasked(t *testing.T) {
	fields := map[string]any{
		"api_key":  "sk-secretkeyabcdefghijklmnopqrstuvwxyz",
		"message":  "hello",
		"count":    42,
	}
	out := redactFields(fields)
	if strings.Contains(out["api_key"].(string), "sk-secretkeyabcdefghijklmnopqrstuvwxyz") {
		t.Errorf("api_key was not redacted")
	}
	if out["message"] != "hello" {
		t.Errorf("non-sensitive field modified")
	}
	if out["count"] != 42 {
		t.Errorf("non-string field modified")
	}
}

func TestRedactFields_NilSafe(t *testing.T) {
	out := redactFields(nil)
	if len(out) != 0 {
		t.Errorf("expected empty result for nil input")
	}
}
