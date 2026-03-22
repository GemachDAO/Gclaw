package venture

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var (
	deployedAddressPattern = regexp.MustCompile(`(?m)Deployed to:\s*(0x[0-9a-fA-F]{40})`)
	txHashPattern          = regexp.MustCompile(`(?m)Transaction hash:\s*(0x[0-9a-fA-F]{64})`)
)

var publicRPCFallbacks = map[string]string{
	"ethereum": "https://ethereum-rpc.publicnode.com",
	"arbitrum": "https://arbitrum-one-rpc.publicnode.com",
	"base":     "https://base-rpc.publicnode.com",
}

// CommandRunner executes a shell command and returns combined output.
type CommandRunner func(ctx context.Context, dir, name string, args ...string) (string, error)

// ForgeDeployer deploys venture contract scaffolds with Foundry.
type ForgeDeployer struct {
	OwnerAddress string
	PrivateKey   string
	LookupEnv    func(string) (string, bool)
	RunCommand   CommandRunner
	LookPath     func(string) (string, error)
}

// NewForgeDeployer creates a deployer using the provided owner and deployer key.
func NewForgeDeployer(ownerAddress, privateKey string) *ForgeDeployer {
	return &ForgeDeployer{
		OwnerAddress: strings.TrimSpace(ownerAddress),
		PrivateKey:   strings.TrimSpace(privateKey),
		LookupEnv:    os.LookupEnv,
		RunCommand:   defaultCommandRunner,
		LookPath:     exec.LookPath,
	}
}

// ApplyReadiness updates deployment readiness fields on the venture.
func (d *ForgeDeployer) ApplyReadiness(v *Venture) {
	if d == nil || v == nil {
		return
	}

	rpcURL, envName := d.rpcURLForChain(v.Chain)
	forgePath, forgeReady := d.lookPath("forge")

	v.OwnerAddress = d.OwnerAddress
	v.FoundryAvailable = forgeReady
	v.WalletReady = d.OwnerAddress != "" && d.PrivateKey != ""
	v.RPCConfigured = rpcURL != ""
	v.RPCEnvVar = envName
	v.ForgeBinaryPath = forgePath

	switch {
	case v.DeployedAddress != "":
		v.DeploymentState = "deployed"
	case !v.FoundryAvailable:
		v.DeploymentState = "foundry_missing"
		v.DeployError = "forge binary not found"
	case !v.WalletReady:
		v.DeploymentState = "wallet_missing"
		v.DeployError = "wallet credentials missing"
	case !v.RPCConfigured:
		v.DeploymentState = "rpc_missing"
		v.DeployError = "chain RPC URL missing"
	default:
		v.DeploymentState = "deploy_ready"
		v.DeployError = ""
	}
}

// Deploy compiles and deploys the venture contract if readiness checks pass.
func (d *ForgeDeployer) Deploy(v *Venture) error {
	if d == nil || v == nil {
		return fmt.Errorf("venture deployer not configured")
	}
	d.ApplyReadiness(v)
	if v.DeploymentState != "deploy_ready" && v.DeploymentState != "deploy_failed" {
		return fmt.Errorf("venture not deployable: %s", v.DeploymentState)
	}
	if strings.TrimSpace(v.FoundryProjectPath) == "" {
		return fmt.Errorf("venture foundry project path not set")
	}

	rpcURL, _ := d.rpcURLForChain(v.Chain)
	contractRef := filepath.ToSlash(filepath.Join("contracts", filepath.Base(v.ContractPath))) + ":" + sanitizeIdentifier(v.ContractSystem)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	v.LastDeployAttempt = time.Now().UnixMilli()
	v.DeployError = ""
	v.DeploymentState = "deploying"
	forgeBinary := firstNonEmptyString(v.ForgeBinaryPath, "forge")
	output, err := d.run(ctx, v.FoundryProjectPath, forgeBinary, "create", contractRef,
		"--rpc-url", rpcURL,
		"--private-key", d.PrivateKey,
		"--constructor-args", d.OwnerAddress,
	)
	if err != nil {
		v.DeploymentState = "deploy_failed"
		v.DeployError = strings.TrimSpace(output)
		if v.DeployError == "" {
			v.DeployError = err.Error()
		}
		return fmt.Errorf("forge create failed: %w", err)
	}

	if match := deployedAddressPattern.FindStringSubmatch(output); len(match) == 2 {
		v.DeployedAddress = match[1]
	}
	if match := txHashPattern.FindStringSubmatch(output); len(match) == 2 {
		v.DeploymentTxHash = match[1]
	}
	if v.DeployedAddress == "" {
		v.DeploymentState = "deploy_failed"
		v.DeployError = strings.TrimSpace(output)
		return fmt.Errorf("forge create did not report deployed address")
	}

	v.DeploymentState = "deployed"
	v.Status = "deployed_live"
	v.DeployError = ""
	return nil
}

func (d *ForgeDeployer) rpcURLForChain(chain string) (string, string) {
	lookup := d.LookupEnv
	if lookup == nil {
		lookup = os.LookupEnv
	}

	candidates := []string{"GCLAW_VENTURE_RPC_URL"}
	switch strings.ToLower(strings.TrimSpace(chain)) {
	case "ethereum":
		candidates = append(candidates, "GCLAW_ETHEREUM_RPC_URL", "ETHEREUM_RPC_URL")
	case "arbitrum":
		candidates = append(candidates, "GCLAW_ARBITRUM_RPC_URL", "ARBITRUM_RPC_URL")
	case "base":
		candidates = append(candidates, "GCLAW_BASE_RPC_URL", "BASE_RPC_URL")
	}

	for _, name := range candidates {
		if value, ok := lookup(name); ok && strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value), name
		}
	}

	key := strings.ToLower(strings.TrimSpace(chain))
	if value := strings.TrimSpace(publicRPCFallbacks[key]); value != "" {
		return value, "builtin_public_rpc"
	}
	return "", ""
}

func (d *ForgeDeployer) lookPath(name string) (string, bool) {
	lookPath := d.LookPath
	if lookPath == nil {
		lookPath = exec.LookPath
	}
	path, err := lookPath(name)
	if err == nil {
		return path, true
	}
	if home, homeErr := os.UserHomeDir(); homeErr == nil {
		fallback := filepath.Join(home, ".foundry", "bin", name)
		if info, statErr := os.Stat(fallback); statErr == nil && !info.IsDir() {
			return fallback, true
		}
	}
	return "", false
}

func (d *ForgeDeployer) run(ctx context.Context, dir, name string, args ...string) (string, error) {
	runner := d.RunCommand
	if runner == nil {
		runner = defaultCommandRunner
	}
	return runner(ctx, dir, name, args...)
}

func defaultCommandRunner(ctx context.Context, dir, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	return string(out), err
}

func firstNonEmptyString(values ...string) string {
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" {
			return value
		}
	}
	return ""
}
