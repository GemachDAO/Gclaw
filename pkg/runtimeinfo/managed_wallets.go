package runtimeinfo

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
	"github.com/GemachDAO/Gclaw/pkg/utils"
)

const (
	gdexHelperSubdir      = "gdex-trading/helpers"
	managedWalletCacheTTL = 2 * time.Minute
	solanaManagedChainID  = 622112261
	evmManagedLookupChain = 1
)

// ManagedWalletStatus captures the backend-managed wallet addresses derived
// from the control wallet after GDEX sign-in.
type ManagedWalletStatus struct {
	ControlWallet string   `json:"control_wallet,omitempty"`
	EVMAddress    string   `json:"evm_address,omitempty"`
	SolanaAddress string   `json:"solana_address,omitempty"`
	State         string   `json:"state"`
	Error         string   `json:"error,omitempty"`
	Warnings      []string `json:"warnings,omitempty"`
	UpdatedAt     int64    `json:"updated_at,omitempty"`
}

var managedWalletCache struct {
	mu      sync.Mutex
	key     string
	expires time.Time
	value   *ManagedWalletStatus
}

// PopulateManagedWallets enriches TradingStatus with backend-managed wallet
// addresses, using a short in-process cache to avoid repeated network calls.
func PopulateManagedWallets(cfg *config.Config, status *TradingStatus, timeout time.Duration) *TradingStatus {
	if status == nil {
		status = BuildTradingStatus(cfg, nil)
	}
	status.ManagedWallets = resolveManagedWalletsCached(cfg, timeout)
	status.FundingInstructions = buildFundingInstructions(status)
	status.CapitalMobility = buildCapitalMobilityStatus(status)
	return status
}

func resolveManagedWalletsCached(cfg *config.Config, timeout time.Duration) *ManagedWalletStatus {
	addr, _ := ResolveWalletCredentials(cfg)
	key := ResolveGDEXAPIKey(cfg) + "|" + addr

	managedWalletCache.mu.Lock()
	defer managedWalletCache.mu.Unlock()

	if managedWalletCache.key == key && managedWalletCache.value != nil && time.Now().Before(managedWalletCache.expires) {
		cached := *managedWalletCache.value
		return &cached
	}

	var previous *ManagedWalletStatus
	if managedWalletCache.key == key && managedWalletCache.value != nil {
		copyValue := *managedWalletCache.value
		previous = &copyValue
	}
	resolved := resolveManagedWallets(cfg, timeout)
	resolved = mergeManagedWalletStatus(previous, resolved)

	managedWalletCache.key = key
	managedWalletCache.value = resolved
	managedWalletCache.expires = time.Now().Add(managedWalletCacheTTL)

	copyValue := *resolved
	return &copyValue
}

func resolveManagedWallets(cfg *config.Config, timeout time.Duration) *ManagedWalletStatus {
	addr, key := ResolveWalletCredentials(cfg)
	apiKey := ResolveGDEXAPIKey(cfg)
	status := &ManagedWalletStatus{
		ControlWallet: addr,
		State:         "unavailable",
		UpdatedAt:     time.Now().UnixMilli(),
	}

	switch {
	case apiKey == "":
		status.Error = "GDEX API key not configured"
		return status
	case addr == "":
		status.Error = "control wallet not configured"
		return status
	case key == "":
		status.Error = "control wallet private key not configured"
		return status
	}

	helperDir := utils.ResolveWorkspaceSkillDir("GDEX_HELPERS_DIR", gdexHelperSubdir)
	if helperDir == "" {
		status.State = "error"
		status.Error = "GDEX helper directory not found"
		return status
	}
	if err := ensureManagedWalletHelperDeps(helperDir); err != nil {
		status.State = "error"
		status.Error = err.Error()
		return status
	}

	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	script := `
const {
  GdexSkill,
  generateGdexSessionKeyPair,
  buildGdexSignInMessage,
  buildGdexSignInComputedData,
  buildGdexUserSessionData,
} = require('@gdexsdk/gdex-skill');
const { ethers } = require('ethers');

const apiKey = process.env.GDEX_API_KEY || '';
const walletAddress = process.env.WALLET_ADDRESS || '';
const privateKey = process.env.PRIVATE_KEY || '';
const SOLANA_CHAIN_ID = 622112261;

function pickAddress(user) {
  if (!user || typeof user !== 'object') return '';
  return String(
    user.address ||
    user.walletAddress ||
    user.evmAddress ||
    user.solanaAddress ||
    user.userWallet ||
    ''
  );
}

async function signInForChain(skill, chainId) {
  const { sessionKey } = generateGdexSessionKeyPair();
  const nonce = String(Math.floor(Date.now() / 1000) + Math.floor(Math.random() * 1000));
  const wallet = new ethers.Wallet(privateKey);
  const message = buildGdexSignInMessage(walletAddress, nonce, sessionKey);
  const signature = await wallet.signMessage(message);
  const payload = buildGdexSignInComputedData({
    apiKey,
    userId: walletAddress,
    sessionKey,
    nonce,
    signature,
  });
  await skill.signInWithComputedData({ computedData: payload.computedData, chainId });
  return buildGdexUserSessionData(sessionKey, apiKey);
}

(async () => {
  const skill = new GdexSkill({ timeout: 15000, maxRetries: 1 });
  skill.loginWithApiKey(apiKey);

  const warnings = [];
  let evmUser = null;
  let solanaUser = null;

  const evmData = await signInForChain(skill, 1);

  try {
    evmUser = await skill.getManagedUser({ userId: walletAddress, data: evmData, chainId: 1 });
  } catch (err) {
    warnings.push('evm: ' + (err && err.message ? err.message : String(err)));
  }

  try {
    solanaUser = await skill.getManagedUser({
      userId: walletAddress,
      data: evmData,
      chainId: SOLANA_CHAIN_ID,
    });
  } catch (err) {
    warnings.push('solana: ' + (err && err.message ? err.message : String(err)));
    try {
      const solanaData = await signInForChain(skill, SOLANA_CHAIN_ID);
      solanaUser = await skill.getManagedUser({
        userId: walletAddress,
        data: solanaData,
        chainId: SOLANA_CHAIN_ID,
      });
    } catch (retryErr) {
      warnings.push('solana_retry: ' + (retryErr && retryErr.message ? retryErr.message : String(retryErr)));
    }
  }

  process.stdout.write(JSON.stringify({
    control_wallet: walletAddress,
    evm_address: pickAddress(evmUser),
    solana_address: pickAddress(solanaUser),
    warnings,
  }));
})().catch((err) => {
  process.stdout.write(JSON.stringify({
    error: err && err.message ? err.message : String(err),
  }));
  process.exit(1);
});
`

	cmd := exec.CommandContext(ctx, "node", "-e", script)
	cmd.Dir = helperDir
	cmd.Env = append(os.Environ(),
		"GDEX_API_KEY="+apiKey,
		"WALLET_ADDRESS="+addr,
		"PRIVATE_KEY="+key,
	)

	out, err := cmd.CombinedOutput()
	if err != nil {
		status.State = "error"
		status.Error = fmt.Sprintf("managed wallet lookup failed: %s", strings.TrimSpace(string(out)))
		return status
	}

	var resolved ManagedWalletStatus
	if err := json.Unmarshal(out, &resolved); err != nil {
		status.State = "error"
		status.Error = fmt.Sprintf("managed wallet lookup returned invalid JSON: %v", err)
		return status
	}

	status.EVMAddress = resolved.EVMAddress
	status.SolanaAddress = resolved.SolanaAddress
	status.Warnings = resolved.Warnings
	switch {
	case resolved.EVMAddress != "" || resolved.SolanaAddress != "":
		status.State = "ready"
	case len(resolved.Warnings) > 0:
		status.State = "error"
		status.Error = strings.Join(resolved.Warnings, "; ")
	default:
		status.State = "pending"
	}
	return status
}

func mergeManagedWalletStatus(previous, current *ManagedWalletStatus) *ManagedWalletStatus {
	if current == nil {
		return previous
	}
	if previous == nil || previous.ControlWallet == "" || previous.ControlWallet != current.ControlWallet {
		return current
	}

	reusedCachedAddress := false
	if current.EVMAddress == "" && previous.EVMAddress != "" {
		current.EVMAddress = previous.EVMAddress
		reusedCachedAddress = true
	}
	if current.SolanaAddress == "" && previous.SolanaAddress != "" {
		current.SolanaAddress = previous.SolanaAddress
		reusedCachedAddress = true
	}
	if !reusedCachedAddress {
		return current
	}

	warnings := make([]string, 0, len(current.Warnings)+1)
	warnings = append(warnings, current.Warnings...)
	if current.Error != "" {
		warnings = append(warnings, "using cached managed wallet addresses after transient lookup failure: "+current.Error)
		current.Error = ""
	} else {
		warnings = append(warnings, "using cached managed wallet addresses after transient lookup gap")
	}
	current.Warnings = warnings
	current.State = "ready"
	return current
}

func ensureManagedWalletHelperDeps(helperDir string) error {
	if helperPackagesInstalled(helperDir) {
		return nil
	}

	if _, err := exec.LookPath("node"); err != nil {
		return fmt.Errorf("node is required for managed wallet lookup: %w", err)
	}

	setupScript := filepath.Join(helperDir, "setup.sh")
	if info, err := os.Stat(setupScript); err == nil && !info.IsDir() {
		cmd := exec.Command("bash", setupScript)
		cmd.Dir = helperDir
		cmd.Env = os.Environ()
		if out, err := cmd.CombinedOutput(); err == nil && helperPackagesInstalled(helperDir) {
			return nil
		} else if _, lookErr := exec.LookPath("npm"); lookErr != nil {
			return fmt.Errorf("GDEX helper setup failed and npm is unavailable: %s", strings.TrimSpace(string(out)))
		}
	}

	if _, err := exec.LookPath("npm"); err != nil {
		return fmt.Errorf("npm is required to install GDEX helper dependencies: %w", err)
	}

	cmd := exec.Command("npm", "install", "--no-audit", "--no-fund")
	cmd.Dir = helperDir
	cmd.Env = os.Environ()
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("install GDEX helper dependencies: %w: %s", err, strings.TrimSpace(string(out)))
	}
	if !helperPackagesInstalled(helperDir) {
		return fmt.Errorf("GDEX helper dependencies are still incomplete after npm install")
	}
	return nil
}
