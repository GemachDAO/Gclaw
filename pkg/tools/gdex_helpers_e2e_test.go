package tools

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// gdexHelpersDir returns the absolute path to the GDEX trading helpers directory.
// It prefers GDEX_HELPERS_DIR env var, then falls back to the project workspace.
func gdexHelpersDir(t *testing.T) string {
	t.Helper()
	if dir := os.Getenv("GDEX_HELPERS_DIR"); dir != "" {
		return dir
	}
	// Walk up from this test file to the project root.
	_, testFile, _, _ := runtime.Caller(0)
	root := filepath.Join(filepath.Dir(testFile), "..", "..")
	abs, err := filepath.Abs(root)
	if err != nil {
		t.Skip("cannot determine project root:", err)
	}
	return filepath.Join(abs, "workspace", "skills", "gdex-trading", "helpers")
}

// nodeAvailable returns true if the node binary is on PATH.
func nodeAvailable() bool {
	_, err := exec.LookPath("node")
	return err == nil
}

// sdkBuilt returns true when the @gdexsdk/gdex-skill dist/index.js has been
// compiled. The SDK ships as TypeScript source and requires a build step
// (run setup.sh) before the helper scripts can be executed.
func sdkBuilt(dir string) bool {
	dist := filepath.Join(dir, "node_modules", "@gdexsdk", "gdex-skill", "dist", "index.js")
	_, err := os.Stat(dist)
	return err == nil
}

// skipIfSDKNotBuilt skips the test with a descriptive message when the SDK
// dist isn't compiled. Call at the top of every test that executes a helper
// script, because the scripts require('@gdexsdk/gdex-skill') at load time.
func skipIfSDKNotBuilt(t *testing.T) {
	t.Helper()
	dir := gdexHelpersDir(t)
	if !sdkBuilt(dir) {
		t.Skip("@gdexsdk/gdex-skill dist not built; run workspace/skills/gdex-trading/helpers/setup.sh first")
	}
}

// runHelper runs a GDEX Node.js helper script with the given JSON input and
// returns the parsed JSON output. envVars is an optional list of KEY=VALUE pairs.
func runHelper(t *testing.T, scriptName string, input map[string]any, envVars ...string) map[string]any {
	t.Helper()
	dir := gdexHelpersDir(t)
	scriptPath := filepath.Join(dir, scriptName)

	if _, err := os.Stat(scriptPath); err != nil {
		t.Fatalf("helper script not found: %s", scriptPath)
	}

	inputJSON, err := json.Marshal(input)
	if err != nil {
		t.Fatalf("marshal input: %v", err)
	}

	cmd := exec.CommandContext(context.Background(), "node", scriptPath)
	cmd.Stdin = bytes.NewReader(inputJSON)
	// Start with a clean environment that includes PATH and the GDEX_API_KEY default.
	cmd.Env = append(os.Environ(), envVars...)

	out, _ := cmd.Output() // exit code may be non-zero for error results, which is fine
	if len(out) == 0 {
		t.Fatalf("empty output from %s; may be a require/load error", scriptName)
	}

	var result map[string]any
	if err := json.Unmarshal(out, &result); err != nil {
		t.Fatalf("parse output from %s: %v (raw: %s)", scriptName, err, string(out))
	}
	return result
}

// ── trade.js E2E Tests ───────────────────────────────────────────────────────

func TestGDEXTradeHelper_LoadsWithoutError(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	dir := gdexHelpersDir(t)
	cmd := exec.Command("node", "--check", filepath.Join(dir, "trade.js"))
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Errorf("trade.js has syntax errors: %s", string(out))
	}
}

func TestGDEXTradeHelper_InvalidJSON(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	dir := gdexHelpersDir(t)
	cmd := exec.Command("node", filepath.Join(dir, "trade.js"))
	cmd.Stdin = bytes.NewReader([]byte(`not json`))
	cmd.Env = os.Environ()
	out, _ := cmd.Output()

	var result map[string]any
	if err := json.Unmarshal(out, &result); err != nil {
		t.Fatalf("expected JSON output even on error, got: %s", string(out))
	}
	if result["success"] != false {
		t.Error("expected success=false for invalid JSON")
	}
	if _, ok := result["error"]; !ok {
		t.Error("expected error field in output")
	}
}

func TestGDEXTradeHelper_UnknownAction(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	result := runHelper(t, "trade.js", map[string]any{
		"action": "unknown_action",
		"params": map[string]any{},
	})
	if result["success"] != false {
		t.Error("expected success=false for unknown action")
	}
	errMsg, _ := result["error"].(string)
	if errMsg == "" {
		t.Error("expected non-empty error message")
	}
}

func TestGDEXTradeHelper_BuyMissingTokenAddress(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	result := runHelper(t, "trade.js", map[string]any{
		"action": "buy",
		"params": map[string]any{
			"amount": "100000",
		},
	})
	if result["success"] != false {
		t.Error("expected success=false for missing token_address")
	}
}

func TestGDEXTradeHelper_LimitBuyRequiresWallet(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	// Unset WALLET_ADDRESS and PRIVATE_KEY to trigger the validation error.
	env := []string{}
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "WALLET_ADDRESS=") || strings.HasPrefix(e, "PRIVATE_KEY=") {
			continue
		}
		env = append(env, e)
	}

	dir := gdexHelpersDir(t)
	payload := `{"action":"limit_buy","params":` +
		`{"token_address":"EKpQ","amount":"1000000","trigger_price":"0.5"}}`
	cmd := exec.Command("node", filepath.Join(dir, "trade.js"))
	cmd.Stdin = bytes.NewReader([]byte(payload))
	cmd.Env = env
	out, _ := cmd.Output()

	var result map[string]any
	if err := json.Unmarshal(out, &result); err != nil {
		t.Fatalf("parse output: %v (raw: %s)", err, string(out))
	}
	if result["success"] != false {
		t.Error("expected success=false when WALLET_ADDRESS/PRIVATE_KEY missing")
	}
	errMsg, _ := result["error"].(string)
	if errMsg == "" {
		t.Error("expected non-empty error message")
	}
}

func TestGDEXTradeHelper_UsesNewSDK(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	// Verify the script uses @gdexsdk/gdex-skill (not gdex.pro-sdk) by checking
	// the error message when buyToken is called with missing tokenAddress.
	// The new SDK throws "tokenAddress must be a non-empty string" whereas the
	// old SDK would throw a different error.
	result := runHelper(t, "trade.js", map[string]any{
		"action": "buy",
		"params": map[string]any{
			"chain_id": 622112261,
		},
	})
	errMsg, _ := result["error"].(string)
	if errMsg == "" {
		t.Fatal("expected an error message")
	}
	// Verify the error comes from @gdexsdk/gdex-skill (tokenAddress validation).
	const oldSDKMsg = "Missing required environment variables: GDEX_API_KEY, WALLET_ADDRESS, PRIVATE_KEY"
	if errMsg == oldSDKMsg {
		t.Error("helper still uses old gdex.pro-sdk error; must be migrated to @gdexsdk/gdex-skill")
	}
}

// ── market.js E2E Tests ──────────────────────────────────────────────────────

func TestGDEXMarketHelper_LoadsWithoutError(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	dir := gdexHelpersDir(t)
	cmd := exec.Command("node", "--check", filepath.Join(dir, "market.js"))
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Errorf("market.js has syntax errors: %s", string(out))
	}
}

func TestGDEXMarketHelper_InvalidJSON(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	dir := gdexHelpersDir(t)
	cmd := exec.Command("node", filepath.Join(dir, "market.js"))
	cmd.Stdin = bytes.NewReader([]byte(`{invalid`))
	cmd.Env = os.Environ()
	out, _ := cmd.Output()

	var result map[string]any
	if err := json.Unmarshal(out, &result); err != nil {
		t.Fatalf("expected JSON even on error: %s", string(out))
	}
	if result["success"] != false {
		t.Error("expected success=false for invalid JSON")
	}
}

func TestGDEXMarketHelper_UnknownAction(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	result := runHelper(t, "market.js", map[string]any{
		"action": "bogus",
		"params": map[string]any{},
	})
	if result["success"] != false {
		t.Error("expected success=false for unknown action")
	}
}

func TestGDEXMarketHelper_SearchMissingQuery(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	result := runHelper(t, "market.js", map[string]any{
		"action": "search",
		"params": map[string]any{},
	})
	if result["success"] != false {
		t.Error("expected success=false when query is missing")
	}
	errMsg, _ := result["error"].(string)
	if errMsg != "query is required" {
		t.Errorf("unexpected error: %s", errMsg)
	}
}

func TestGDEXMarketHelper_HLBalanceMissingWallet(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	// Remove WALLET_ADDRESS from env so the helper returns an error.
	env := []string{}
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "WALLET_ADDRESS=") {
			continue
		}
		env = append(env, e)
	}

	dir := gdexHelpersDir(t)
	cmd := exec.Command("node", filepath.Join(dir, "market.js"))
	cmd.Stdin = bytes.NewReader([]byte(`{"action":"hl_balance","params":{}}`))
	cmd.Env = env
	out, _ := cmd.Output()

	var result map[string]any
	if err := json.Unmarshal(out, &result); err != nil {
		t.Fatalf("parse output: %v (raw: %s)", err, string(out))
	}
	if result["success"] != false {
		t.Error("expected success=false when wallet_address missing")
	}
}

func TestGDEXMarketHelper_HLDepositRequiresWallet(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	// Without WALLET_ADDRESS + PRIVATE_KEY, hl_deposit should fail with a clear error.
	env := []string{}
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "WALLET_ADDRESS=") || strings.HasPrefix(e, "PRIVATE_KEY=") {
			continue
		}
		env = append(env, e)
	}

	dir := gdexHelpersDir(t)
	cmd := exec.Command("node", filepath.Join(dir, "market.js"))
	cmd.Stdin = bytes.NewReader([]byte(`{"action":"hl_deposit","params":{"amount":"10"}}`))
	cmd.Env = env
	out, _ := cmd.Output()

	var result map[string]any
	if err := json.Unmarshal(out, &result); err != nil {
		t.Fatalf("parse output: %v (raw: %s)", err, string(out))
	}
	if result["success"] != false {
		t.Error("expected success=false when WALLET_ADDRESS/PRIVATE_KEY missing")
	}
}

func TestGDEXMarketHelper_TrendingNetworkError(t *testing.T) {
	if !nodeAvailable() {
		t.Skip("node not available")
	}
	skipIfSDKNotBuilt(t)
	// In the sandbox (no network), the trending request will fail with a network error.
	// This test verifies the JSON contract: { success: false, error: "<msg>" }.
	result := runHelper(t, "market.js", map[string]any{
		"action": "trending",
		"params": map[string]any{"limit": 3},
	})
	if result["success"] != false {
		// If we somehow have network access and got real data, that's fine too.
		t.Log("trending succeeded (network available)")
		return
	}
	errMsg, _ := result["error"].(string)
	if errMsg == "" {
		t.Error("expected non-empty error message on network failure")
	}
}

// ── Package.json Contract Tests ──────────────────────────────────────────────

func TestGDEXHelpersPackageJSON_UsesNewSDK(t *testing.T) {
	dir := gdexHelpersDir(t)
	pkgPath := filepath.Join(dir, "package.json")
	data, err := os.ReadFile(pkgPath)
	if err != nil {
		t.Fatalf("read package.json: %v", err)
	}
	var pkg map[string]any
	if err := json.Unmarshal(data, &pkg); err != nil {
		t.Fatalf("parse package.json: %v", err)
	}

	deps, ok := pkg["dependencies"].(map[string]any)
	if !ok {
		t.Fatal("package.json missing dependencies")
	}

	// Must use @gdexsdk/gdex-skill.
	if _, ok := deps["@gdexsdk/gdex-skill"]; !ok {
		t.Error("package.json must depend on @gdexsdk/gdex-skill")
	}

	// Must NOT use the old gdex.pro-sdk.
	if _, ok := deps["gdex.pro-sdk"]; ok {
		t.Error("package.json must not depend on gdex.pro-sdk (use @gdexsdk/gdex-skill instead)")
	}

	// Must not be an ES module (new SDK is CJS-only).
	if pkg["type"] == "module" {
		t.Error(`package.json "type" must not be "module"; @gdexsdk/gdex-skill uses CommonJS`)
	}
}
