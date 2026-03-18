// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package sanitize

import (
	"strings"
	"testing"
)

func TestSanitizeToolInput_Truncation(t *testing.T) {
	input := strings.Repeat("a", 200)
	result := SanitizeToolInput(input, 100)
	if len([]rune(result)) != 100 {
		t.Errorf("expected 100 runes, got %d", len([]rune(result)))
	}
}

func TestSanitizeToolInput_NullByteStripping(t *testing.T) {
	input := "hello\x00world"
	result := SanitizeToolInput(input, 0)
	if strings.Contains(result, "\x00") {
		t.Error("null byte not stripped")
	}
	if result != "helloworld" {
		t.Errorf("got %q, want %q", result, "helloworld")
	}
}

func TestSanitizeToolInput_ControlCharStripping(t *testing.T) {
	// Bell (0x07), backspace (0x08) should be stripped
	// Tab and newline should be preserved
	input := "hello\x07world\nline2\ttab\x08end"
	result := SanitizeToolInput(input, 0)
	if strings.Contains(result, "\x07") || strings.Contains(result, "\x08") {
		t.Error("control characters not stripped")
	}
	if !strings.Contains(result, "\n") || !strings.Contains(result, "\t") {
		t.Error("newline/tab should be preserved")
	}
}

func TestSanitizeToolInput_EmptyInput(t *testing.T) {
	if SanitizeToolInput("", 100) != "" {
		t.Error("expected empty string")
	}
}

func TestSanitizeToolInput_NoMaxLen(t *testing.T) {
	input := strings.Repeat("x", 1000)
	result := SanitizeToolInput(input, 0)
	if len(result) != 1000 {
		t.Errorf("expected 1000 chars, got %d", len(result))
	}
}

func TestValidateTokenAddress_ValidEthereum(t *testing.T) {
	addr := "0xdAC17F958D2ee523a2206206994597C13D831ec7"
	if err := ValidateTokenAddress(addr); err != nil {
		t.Errorf("expected no error for valid ETH addr, got: %v", err)
	}
}

func TestValidateTokenAddress_InvalidEthereum(t *testing.T) {
	tests := []string{
		"0xshort",
		"0xGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG", // invalid hex
		"0x123",
	}
	for _, addr := range tests {
		if err := ValidateTokenAddress(addr); err == nil {
			t.Errorf("expected error for invalid ETH addr %q", addr)
		}
	}
}

func TestValidateTokenAddress_ValidSolana(t *testing.T) {
	// 32-char base58 address
	addr := "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
	if err := ValidateTokenAddress(addr); err != nil {
		t.Errorf("expected no error for valid Solana addr, got: %v", err)
	}
}

func TestValidateTokenAddress_InvalidSolana(t *testing.T) {
	tests := []string{
		"short",                  // too short
		strings.Repeat("A", 50), // too long
		"has invalid char!",
	}
	for _, addr := range tests {
		if err := ValidateTokenAddress(addr); err == nil {
			t.Errorf("expected error for invalid addr %q", addr)
		}
	}
}

func TestValidateTokenAddress_Empty(t *testing.T) {
	if err := ValidateTokenAddress(""); err == nil {
		t.Error("expected error for empty address")
	}
}

func TestValidateChainID_ValidIDs(t *testing.T) {
	for _, id := range []int64{1, 8453, 42161, 622112261} {
		if err := ValidateChainID(id); err != nil {
			t.Errorf("expected no error for chain ID %d, got: %v", id, err)
		}
	}
}

func TestValidateChainID_InvalidID(t *testing.T) {
	if err := ValidateChainID(9999); err == nil {
		t.Error("expected error for unknown chain ID")
	}
}
