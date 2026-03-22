package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func runInstallScriptShell(t *testing.T, script string) (string, error) {
	t.Helper()

	cmd := exec.Command("bash", "-lc", script)
	cmd.Dir = filepath.Clean(filepath.Join("..", ".."))
	out, err := cmd.CombinedOutput()
	return string(out), err
}

func TestInstallScriptEnsurePathUsesCustomInstallDir(t *testing.T) {
	home := t.TempDir()
	bashrc := filepath.Join(home, ".bashrc")
	if err := os.WriteFile(bashrc, nil, 0o644); err != nil {
		t.Fatalf("write bashrc: %v", err)
	}

	script := `
set -euo pipefail
export HOME=` + shellQuote(home) + `
export SHELL=/bin/bash
export PATH=/usr/bin:/bin
export GCLAW_INSTALL_DIR="$HOME/custom-bin"
export GCLAW_INSTALL_TEST_MODE=1
source ./install.sh
ensure_path
`

	if out, err := runInstallScriptShell(t, script); err != nil {
		t.Fatalf("ensure_path failed: %v\n%s", err, out)
	}

	content, err := os.ReadFile(bashrc)
	if err != nil {
		t.Fatalf("read bashrc: %v", err)
	}
	got := string(content)
	if !strings.Contains(got, `export PATH="${HOME}/custom-bin:${PATH}"`) {
		t.Fatalf("bashrc missing custom install dir entry: %q", got)
	}
	if strings.Contains(got, `export PATH="${HOME}/.local/bin:${PATH}"`) {
		t.Fatalf("bashrc still contains hard-coded default bin path: %q", got)
	}
}

func TestInstallScriptSetupGdexHelpersFailsOnSetupError(t *testing.T) {
	home := t.TempDir()
	helpersDir := filepath.Join(home, ".gclaw", "workspace", "skills", "gdex-trading", "helpers")
	if err := os.MkdirAll(helpersDir, 0o755); err != nil {
		t.Fatalf("mkdir helpers dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(helpersDir, "package.json"), []byte(`{"name":"helpers"}`), 0o644); err != nil {
		t.Fatalf("write package.json: %v", err)
	}
	setupPath := filepath.Join(helpersDir, "setup.sh")
	if err := os.WriteFile(setupPath, []byte("#!/usr/bin/env bash\nexit 7\n"), 0o755); err != nil {
		t.Fatalf("write setup.sh: %v", err)
	}

	script := `
set -uo pipefail
export HOME=` + shellQuote(home) + `
export PATH=/usr/bin:/bin
export GCLAW_INSTALL_TEST_MODE=1
source ./install.sh
setup_gdex_helpers
status=$?
printf '%s' "$status"
`

	out, err := runInstallScriptShell(t, script)
	if err != nil && !strings.Contains(out, "status") {
		// The function itself should fail, but the shell command should still
		// reach the printf above.
		t.Fatalf("setup_gdex_helpers shell failed unexpectedly: %v\n%s", err, out)
	}
	if !strings.HasSuffix(strings.TrimSpace(out), "1") {
		t.Fatalf("setup_gdex_helpers status = %q, want 1", out)
	}
}

func TestInstallScriptLaunchGatewayBackgroundUsesHomeAsWorkdir(t *testing.T) {
	home := t.TempDir()
	binDir := filepath.Join(home, "bin")
	if err := os.MkdirAll(binDir, 0o755); err != nil {
		t.Fatalf("mkdir bin dir: %v", err)
	}
	pwdFile := filepath.Join(home, "gateway_pwd.txt")
	fakeBinary := filepath.Join(binDir, "gclaw")
	fakeScript := "#!/usr/bin/env bash\npwd > " + shellQuote(pwdFile) + "\nsleep 1\n"
	if err := os.WriteFile(fakeBinary, []byte(fakeScript), 0o755); err != nil {
		t.Fatalf("write fake gclaw: %v", err)
	}

	script := `
set -euo pipefail
export HOME=` + shellQuote(home) + `
export PATH=/usr/bin:/bin
export GCLAW_INSTALL_DIR="$HOME/bin"
export GCLAW_INSTALL_TEST_MODE=1
source ./install.sh
pid=$(launch_gateway_background "$HOME/gateway.log")
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if [ -f "$HOME/gateway_pwd.txt" ]; then
    break
  fi
  sleep 0.1
done
wait "$pid" 2>/dev/null || true
`

	if out, err := runInstallScriptShell(t, script); err != nil {
		t.Fatalf("launch_gateway_background failed: %v\n%s", err, out)
	}

	content, err := os.ReadFile(pwdFile)
	if err != nil {
		t.Fatalf("read gateway pwd file: %v", err)
	}
	if got := strings.TrimSpace(string(content)); got != home {
		t.Fatalf("gateway workdir = %q, want %q", got, home)
	}
}

func TestInstallScriptVerifyDownloadChecksum(t *testing.T) {
	if _, err := exec.LookPath("sha256sum"); err != nil {
		if _, err := exec.LookPath("shasum"); err != nil {
			t.Skip("sha256sum/shasum not available")
		}
	}

	tmp := t.TempDir()
	artifact := filepath.Join(tmp, "gclaw_Linux_x86_64.tar.gz")
	payload := []byte("verified release payload")
	if err := os.WriteFile(artifact, payload, 0o644); err != nil {
		t.Fatalf("write artifact: %v", err)
	}
	sum := sha256.Sum256(payload)
	checksums := filepath.Join(tmp, "checksums.txt")
	line := hex.EncodeToString(sum[:]) + "  " + filepath.Base(artifact) + "\n"
	if err := os.WriteFile(checksums, []byte(line), 0o644); err != nil {
		t.Fatalf("write checksums: %v", err)
	}

	script := `
set -euo pipefail
export HOME=` + shellQuote(tmp) + `
export GCLAW_INSTALL_TEST_MODE=1
source ./install.sh
verify_download_checksum ` + shellQuote(checksums) + ` ` + shellQuote(artifact) + ` ` + shellQuote(filepath.Base(artifact)) + `
`

	if out, err := runInstallScriptShell(t, script); err != nil {
		t.Fatalf("verify_download_checksum failed: %v\n%s", err, out)
	}
}

func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", `'"'"'`) + "'"
}
