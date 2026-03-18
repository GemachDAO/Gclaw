// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package logger

import (
	"regexp"
	"strings"
)

// sensitiveFieldNames is the set of field names whose string values are always
// redacted regardless of content.
var sensitiveFieldNames = map[string]struct{}{
	"api_key":     {},
	"apiKey":      {},
	"private_key": {},
	"privateKey":  {},
	"token":       {},
	"secret":      {},
}

// apiKeyPatterns matches well-known LLM API key formats.
var apiKeyPatterns = []*regexp.Regexp{
	// OpenAI  sk-...
	regexp.MustCompile(`sk-[a-zA-Z0-9\-]{20,}`),
	// Groq    gsk-...
	regexp.MustCompile(`gsk-[a-zA-Z0-9]{20,}`),
	// Anthropic  sk-ant-...
	regexp.MustCompile(`sk-ant-[a-zA-Z0-9\-]{20,}`),
	// OpenRouter  sk-or-v1-...
	regexp.MustCompile(`sk-or-v1-[a-zA-Z0-9]{20,}`),
}

// ethAddressRe matches full Ethereum addresses (0x + 40 hex chars).
var ethAddressRe = regexp.MustCompile(`0x[a-fA-F0-9]{40}`)

// uuidRe matches UUID v4-style strings (used as GDEX API keys etc.).
var uuidRe = regexp.MustCompile(
	`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`,
)

// base58Alphabet is the alphabet used by Solana / Bitcoin base58.
const base58Alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

// base58Re matches 32–44-character base58 strings (Solana wallet addresses).
var base58Re = regexp.MustCompile(`[` + base58Alphabet + `]{32,44}`)

// redactValue replaces sensitive content inside a single string value with a
// masked token that preserves the first/last 4 characters for identification.
func redactValue(s string) string {
	// API keys
	for _, re := range apiKeyPatterns {
		s = re.ReplaceAllStringFunc(s, mask)
	}

	// Ethereum addresses — replace middle with ***
	s = ethAddressRe.ReplaceAllStringFunc(s, func(addr string) string {
		// addr is 0x + 40 hex = 42 chars; show first 6 chars (0x + 4 hex) + *** + last 4 hex
		return addr[:6] + "***REDACTED***" + addr[len(addr)-4:]
	})

	// Solana-style base58 addresses (must look like a standalone token)
	s = redactBase58(s)

	return s
}

// redactBase58 replaces standalone base58 strings in s.
// A "standalone" match is one not embedded in a longer alphanumeric token.
func redactBase58(s string) string {
	indices := base58Re.FindAllStringIndex(s, -1)
	if len(indices) == 0 {
		return s
	}

	var b strings.Builder
	prev := 0
	for _, loc := range indices {
		start, end := loc[0], loc[1]

		// Skip if this is part of a longer token (adjacent non-space chars)
		if start > 0 && isBase58Char(rune(s[start-1])) {
			b.WriteString(s[prev:end])
			prev = end
			continue
		}
		if end < len(s) && isBase58Char(rune(s[end])) {
			b.WriteString(s[prev:end])
			prev = end
			continue
		}

		matched := s[start:end]
		b.WriteString(s[prev:start])
		b.WriteString(mask(matched))
		prev = end
	}
	b.WriteString(s[prev:])
	return b.String()
}

// isBase58Char returns true if the byte is part of the base58 alphabet.
func isBase58Char(c rune) bool {
	return strings.ContainsRune(base58Alphabet, c)
}

// mask replaces the middle of s with ***REDACTED***, keeping the first and
// last 4 characters for identification. If s is shorter than 8 chars it
// is replaced entirely.
func mask(s string) string {
	if len(s) <= 8 {
		return "***REDACTED***"
	}
	return s[:4] + "***REDACTED***" + s[len(s)-4:]
}

// Redact applies content-based secret detection to s and returns the sanitized
// string. It is safe for concurrent use (all state is package-level read-only).
func Redact(s string) string {
	return redactValue(s)
}

// redactFields returns a copy of fields with sensitive values masked.
// Values of keys listed in sensitiveFieldNames are always masked;
// other string values are scanned for known secret patterns.
func redactFields(fields map[string]any) map[string]any {
	if len(fields) == 0 {
		return fields
	}
	out := make(map[string]any, len(fields))
	for k, v := range fields {
		sv, isStr := v.(string)
		if !isStr {
			out[k] = v
			continue
		}
		if _, sensitive := sensitiveFieldNames[k]; sensitive {
			// Always mask sensitive-named fields (including UUIDs)
			sv = maskFull(sv)
		} else {
			sv = Redact(sv)
		}
		out[k] = sv
	}
	return out
}

// maskFull replaces the entire value, preserving first/last 4 chars.
func maskFull(s string) string {
	if s == "" {
		return s
	}
	return mask(s)
}
