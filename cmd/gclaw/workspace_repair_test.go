package main

import "testing"

func TestNeedsWorkspaceTemplateRepair_CurrentEmbeddedMarketTemplateDoesNotRepair(t *testing.T) {
	content, err := embeddedFiles.ReadFile("workspace/skills/gdex-trading/helpers/market.js")
	if err != nil {
		t.Fatalf("read embedded market helper: %v", err)
	}

	if needsWorkspaceTemplateRepair("skills/gdex-trading/helpers/market.js", content) {
		t.Fatal("needsWorkspaceTemplateRepair() unexpectedly flagged the current embedded market helper as legacy")
	}
}

func TestNeedsWorkspaceTemplateRepair_LegacyMarketTemplateStillRepairs(t *testing.T) {
	legacy := []byte(`
		async function broken(skill) {
		  return skill.client.get('/v1/balances');
		}
	`)

	if !needsWorkspaceTemplateRepair("skills/gdex-trading/helpers/market.js", legacy) {
		t.Fatal("needsWorkspaceTemplateRepair() should flag legacy market helper content")
	}
}
