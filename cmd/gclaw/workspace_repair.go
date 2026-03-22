package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var frontmatterBlockRE = regexp.MustCompile(`(?s)^---(?:\r\n|\n|\r).*?(?:\r\n|\n|\r)---(?:\r\n|\n|\r)*`)

var legacyWorkspaceSkillFiles = []string{
	"skills/tempo-payment/SKILL.md",
	"skills/x402-payment/SKILL.md",
}

var legacyWorkspaceTemplateFiles = []string{
	"skills/gdex-trading/helpers/market.js",
	"skills/gdex-trading/helpers/trade.js",
}

func repairLegacyWorkspaceFiles(workspace string) error {
	var errs []string
	for _, relPath := range legacyWorkspaceSkillFiles {
		if err := repairLegacyWorkspaceFile(workspace, relPath); err != nil {
			errs = append(errs, err.Error())
		}
	}
	for _, relPath := range legacyWorkspaceTemplateFiles {
		if err := repairLegacyWorkspaceTemplateFile(workspace, relPath); err != nil {
			errs = append(errs, err.Error())
		}
	}
	if len(errs) == 0 {
		return nil
	}
	return fmt.Errorf("%s", strings.Join(errs, "; "))
}

func repairLegacyWorkspaceFile(workspace, relativePath string) error {
	targetPath := filepath.Join(workspace, filepath.FromSlash(relativePath))
	content, err := os.ReadFile(targetPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("read %s: %w", targetPath, err)
	}
	if hasFrontmatter(content) {
		return nil
	}

	embeddedPath := filepath.ToSlash(filepath.Join("workspace", filepath.FromSlash(relativePath)))
	templateContent, err := embeddedFiles.ReadFile(embeddedPath)
	if err != nil {
		return fmt.Errorf("read embedded template %s: %w", embeddedPath, err)
	}
	block := extractFrontmatterBlock(templateContent)
	if block == "" {
		return nil
	}

	info, err := os.Stat(targetPath)
	if err != nil {
		return fmt.Errorf("stat %s: %w", targetPath, err)
	}

	trimmedBody := strings.TrimLeft(string(content), "\r\n")
	updated := block + trimmedBody
	if err := os.WriteFile(targetPath, []byte(updated), info.Mode()); err != nil {
		return fmt.Errorf("repair %s: %w", targetPath, err)
	}
	return nil
}

func hasFrontmatter(content []byte) bool {
	return frontmatterBlockRE.Find(content) != nil
}

func extractFrontmatterBlock(content []byte) string {
	block := frontmatterBlockRE.Find(content)
	if len(block) == 0 {
		return ""
	}
	return string(block)
}

func repairLegacyWorkspaceTemplateFile(workspace, relativePath string) error {
	targetPath := filepath.Join(workspace, filepath.FromSlash(relativePath))
	content, err := os.ReadFile(targetPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("read %s: %w", targetPath, err)
	}

	if !needsWorkspaceTemplateRepair(relativePath, content) {
		return nil
	}

	embeddedPath := filepath.ToSlash(filepath.Join("workspace", filepath.FromSlash(relativePath)))
	templateContent, err := embeddedFiles.ReadFile(embeddedPath)
	if err != nil {
		return fmt.Errorf("read embedded template %s: %w", embeddedPath, err)
	}

	info, err := os.Stat(targetPath)
	if err != nil {
		return fmt.Errorf("stat %s: %w", targetPath, err)
	}
	if err := os.WriteFile(targetPath, templateContent, info.Mode()); err != nil {
		return fmt.Errorf("repair %s: %w", targetPath, err)
	}
	return nil
}

func needsWorkspaceTemplateRepair(relativePath string, content []byte) bool {
	switch filepath.ToSlash(relativePath) {
	case "skills/gdex-trading/helpers/market.js":
		// Older installs used the dead /v1/balances endpoint for holdings,
		// lacked fuller helper error bodies, or lacked bridge actions. Do not
		// treat signIn(skill, 1) as legacy: the current HL helper still uses the
		// EVM auth context for deposit/order/bridge flows.
		return bytes.Contains(content, []byte("skill.client.get('/v1/balances'")) ||
			!bytes.Contains(content, []byte("formatHelperError")) ||
			!bytes.Contains(content, []byte("bridge_estimate")) ||
			!bytes.Contains(content, []byte("prepareHyperLiquidDeposit"))
	case "skills/gdex-trading/helpers/trade.js":
		// Older installs passed numeric Solana chain IDs directly to buyToken/sellToken,
		// which makes the SDK validate base58 mints as EVM addresses. Older installs
		// also lacked the managed EVM purchase flow for purchase_v2.
		return bytes.Contains(content, []byte("chain: chainId")) &&
			!bytes.Contains(content, []byte("normalizeSpotTradeChain")) ||
			!bytes.Contains(content, []byte("submitManagedEvmPurchase"))
	default:
		return false
	}
}
