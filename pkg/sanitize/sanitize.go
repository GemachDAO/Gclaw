// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

// Package sanitize provides input sanitization and validation helpers for
// agent tool parameters.
package sanitize

import (
	"fmt"
	"regexp"
	"strings"
	"unicode"
)

// knownChainIDs is the set of valid GDEX chain IDs.
var knownChainIDs = map[int64]struct{}{
	1:         {}, // Ethereum mainnet
	8453:      {}, // Base
	42161:     {}, // Arbitrum
	622112261: {}, // custom chain
}

// ethAddrRe matches a valid Ethereum address (0x + exactly 40 hex chars).
var ethAddrRe = regexp.MustCompile(`^0x[a-fA-F0-9]{40}$`)

// base58Alphabet is the character set accepted for Solana addresses.
const base58Alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

// solanaAddrRe matches a valid Solana base58 address (32-44 chars).
var solanaAddrRe = regexp.MustCompile(`^[` + base58Alphabet + `]{32,44}$`)

// SanitizeToolInput returns a sanitized copy of input:
//   - truncated to at most maxLen bytes
//   - null bytes stripped
//   - control characters stripped (except '\n' and '\t')
func SanitizeToolInput(input string, maxLen int) string {
	// Strip null bytes and unsafe control characters first.
	var b strings.Builder
	b.Grow(len(input))
	for _, r := range input {
		if r == '\x00' {
			continue
		}
		if unicode.IsControl(r) && r != '\n' && r != '\t' {
			continue
		}
		b.WriteRune(r)
	}
	result := b.String()

	if maxLen > 0 && len(result) > maxLen {
		// Truncate at a rune boundary.
		runes := []rune(result)
		if len(runes) > maxLen {
			result = string(runes[:maxLen])
		}
	}
	return result
}

// ValidateTokenAddress validates a token address string as either an Ethereum
// (0x + 40 hex) or Solana (base58, 32-44 chars) address.
func ValidateTokenAddress(addr string) error {
	if addr == "" {
		return fmt.Errorf("token address is empty")
	}
	if strings.HasPrefix(addr, "0x") {
		if !ethAddrRe.MatchString(addr) {
			return fmt.Errorf("invalid Ethereum address: must be 0x followed by 40 hex characters")
		}
		return nil
	}
	if !solanaAddrRe.MatchString(addr) {
		return fmt.Errorf(
			"invalid token address: must be an Ethereum address (0x+40 hex) or a Solana base58 address (32-44 chars)",
		)
	}
	return nil
}

// ValidateChainID returns an error if id is not a known GDEX chain ID.
func ValidateChainID(id int64) error {
	if _, ok := knownChainIDs[id]; !ok {
		return fmt.Errorf("unknown chain ID %d: valid values are 1, 8453, 42161, 622112261", id)
	}
	return nil
}
