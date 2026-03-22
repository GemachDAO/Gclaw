#!/usr/bin/env bash
# Gclaw one-shot installer
# Usage: curl -fsSL https://raw.githubusercontent.com/GemachDAO/Gclaw/main/install.sh | bash
#
# Tries to download a pre-built release binary first.
# Falls back to building from source (requires Go and git) when no release is available.

REPO="GemachDAO/Gclaw"
BINARY="gclaw"
INSTALL_DIR="${GCLAW_INSTALL_DIR:-${HOME}/.local/bin}"
INSTALL_DIR_SHELL="${INSTALL_DIR}"

if [ -n "${HOME:-}" ] && [ "${INSTALL_DIR#"$HOME"}" != "${INSTALL_DIR}" ]; then
  INSTALL_DIR_SHELL="\${HOME}${INSTALL_DIR#$HOME}"
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✔${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✘${NC}  $*" >&2; }

fetch_stdout() {
  if command -v curl &>/dev/null; then
    curl -fsSL "$1"
  else
    wget -qO- "$1"
  fi
}

fetch_file() {
  if command -v curl &>/dev/null; then
    curl -fsSL --progress-bar "$1" -o "$2"
  else
    wget -q --show-progress -O "$2" "$1"
  fi
}

allow_degraded_install() {
  [ "${GCLAW_ALLOW_DEGRADED_INSTALL:-0}" = "1" ]
}

sha256_file() {
  if command -v sha256sum &>/dev/null; then
    sha256sum "$1" | awk '{print $1}'
    return 0
  fi
  if command -v shasum &>/dev/null; then
    shasum -a 256 "$1" | awk '{print $1}'
    return 0
  fi
  return 1
}

verify_download_checksum() {
  local checksum_file="$1"
  local artifact_path="$2"
  local artifact_name="$3"
  local expected actual

  expected=$(awk -v target="$artifact_name" '$2 == target {print $1; exit}' "$checksum_file")
  if [ -z "$expected" ]; then
    warn "No checksum entry found for ${artifact_name}."
    return 1
  fi

  if ! actual=$(sha256_file "$artifact_path"); then
    warn "sha256sum or shasum is required to verify the release archive."
    return 1
  fi

  if [ "$actual" != "$expected" ]; then
    warn "Checksum mismatch for ${artifact_name}."
    return 1
  fi

  success "Verified checksum for ${artifact_name}"
  return 0
}

print_banner() {
  echo ""
  echo -e "${BOLD}🦞 Gclaw — The Living Agent${NC}"
  echo -e "   One-shot installer\n"
}

detect_platform() {
  local os arch
  os=$(uname -s)
  arch=$(uname -m)

  case "$os" in
    Linux)  OS_NAME="Linux"  ;;
    Darwin) OS_NAME="Darwin" ;;
    *)
      error "Unsupported operating system: $os"
      error "Please install manually: https://github.com/${REPO}/releases"
      return 1
      ;;
  esac

  case "$arch" in
    x86_64)          ARCH_NAME="x86_64" ;;
    aarch64 | arm64) ARCH_NAME="arm64"  ;;
    armv7l)          ARCH_NAME="armv7"  ;;
    riscv64)         ARCH_NAME="riscv64" ;;
    *)
      error "Unsupported architecture: $arch"
      error "Please install manually: https://github.com/${REPO}/releases"
      return 1
      ;;
  esac

  info "Detected platform: ${OS_NAME}/${ARCH_NAME}"
}

check_dependencies() {
  if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
    error "curl or wget is required but neither was found."
    return 1
  fi
}

# ── Helper: ensure PATH ──────────────────────────────────────────────────────
ensure_path() {
  if echo ":${PATH}:" | grep -q ":${INSTALL_DIR}:"; then
    return
  fi

  warn "${INSTALL_DIR} is not in your PATH."
  echo ""
  echo "  Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
  echo ""
  echo -e "  ${BOLD}export PATH=\"${INSTALL_DIR_SHELL}:\${PATH}\"${NC}"
  echo ""

  # Auto-append for common shells
  SHELL_PROFILE=""
  case "${SHELL:-}" in
    */zsh)  [ -f "${HOME}/.zshrc" ]  && SHELL_PROFILE="${HOME}/.zshrc" ;;
    */bash) [ -f "${HOME}/.bashrc" ] && SHELL_PROFILE="${HOME}/.bashrc" ;;
  esac
  # Fallback: check BASH_VERSION / ZSH_VERSION env vars (for piped execution)
  if [ -z "$SHELL_PROFILE" ]; then
    if [ -n "${ZSH_VERSION:-}" ] && [ -f "${HOME}/.zshrc" ]; then
      SHELL_PROFILE="${HOME}/.zshrc"
    elif [ -n "${BASH_VERSION:-}" ] && [ -f "${HOME}/.bashrc" ]; then
      SHELL_PROFILE="${HOME}/.bashrc"
    fi
  fi

  if [ -n "$SHELL_PROFILE" ]; then
    if ! grep -Fq "$INSTALL_DIR_SHELL" "$SHELL_PROFILE" 2>/dev/null; then
      echo "  Auto-adding to ${SHELL_PROFILE} ..."
      printf '\n# Added by gclaw installer\nexport PATH="%s:${PATH}"\n' "$INSTALL_DIR_SHELL" >> "$SHELL_PROFILE"
      success "Updated ${SHELL_PROFILE}. Run: source ${SHELL_PROFILE}"
    else
      info "${SHELL_PROFILE} already contains PATH entry."
    fi
  fi
  echo ""
}

# ── Helper: run onboard ──────────────────────────────────────────────────────
run_onboard() {
  # Piped installs (curl | bash) consume stdin for the script itself, so use
  # /dev/tty when available to still support interactive onboarding.
  if [ -r /dev/tty ]; then
    echo ""
    echo -e "${BOLD}Running initial setup...${NC}"
    echo ""
    "${INSTALL_DIR}/${BINARY}" onboard </dev/tty
  else
    echo ""
    info "Run ${BOLD}gclaw onboard${NC} to complete setup."
  fi
}

# ── Helper: launch gateway ───────────────────────────────────────────────────
maybe_launch_gateway() {
  local config_path="${HOME}/.gclaw/config.json"
  local log_dir="${HOME}/.gclaw/logs"
  local log_file="${log_dir}/gateway.log"

  if [ ! -f "$config_path" ]; then
    return 0
  fi

  if [ ! -r /dev/tty ]; then
    echo ""
    info "Start the living gateway with ${BOLD}gclaw gateway${NC}"
    info "Dashboard: ${BOLD}http://127.0.0.1:18790/dashboard${NC}"
    return 0
  fi

  echo ""
  printf "Start the living gateway now in the background? (Y/n): " >/dev/tty
  local answer
  IFS= read -r answer </dev/tty || answer=""
  answer=$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')
  if [ "$answer" = "n" ] || [ "$answer" = "no" ]; then
    info "Start it later with ${BOLD}gclaw gateway${NC}"
    info "Dashboard: ${BOLD}http://127.0.0.1:18790/dashboard${NC}"
    return 0
  fi

  mkdir -p "$log_dir"

  if pgrep -af "${INSTALL_DIR}/${BINARY} gateway" >/dev/null 2>&1; then
    info "Gateway already appears to be running."
    info "Dashboard: ${BOLD}http://127.0.0.1:18790/dashboard${NC}"
    return 0
  fi

  local gateway_pid
  gateway_pid=$(launch_gateway_background "$log_file")
  if [ -z "$gateway_pid" ]; then
    warn "Gateway did not provide a background PID. Check logs: ${log_file}"
    return 1
  fi
  sleep 2

  if kill -0 "$gateway_pid" >/dev/null 2>&1; then
    success "Gateway started in background (PID ${gateway_pid})."
    info "Dashboard: ${BOLD}http://127.0.0.1:18790/dashboard${NC}"
    info "Logs: ${BOLD}${log_file}${NC}"
  else
    warn "Gateway exited immediately. Check logs: ${log_file}"
  fi
}

launch_gateway_background() {
  local log_file="$1"
  (
    cd "${HOME}" || exit 1
    exec "${INSTALL_DIR}/${BINARY}" gateway
  ) >"$log_file" 2>&1 &
  echo "$!"
}

# ── Strategy 1: Download pre-built release binary ────────────────────────────
try_release_install() {
  LATEST_URL="https://api.github.com/repos/${REPO}/releases/latest"
  info "Checking for pre-built release..."
  RELEASE_JSON=$(fetch_stdout "$LATEST_URL" 2>/dev/null || true)
  RELEASE_TAG=$(echo "$RELEASE_JSON" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/' || true)

  if [ -z "$RELEASE_TAG" ]; then
    return 1  # No release found
  fi

  success "Latest release: ${RELEASE_TAG}"

  TARBALL="${BINARY}_${OS_NAME}_${ARCH_NAME}.tar.gz"
  CHECKSUMS_FILE="checksums.txt"
  DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}/${TARBALL}"
  CHECKSUMS_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}/${CHECKSUMS_FILE}"

  info "Downloading ${TARBALL}..."
  TMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TMP_DIR"' EXIT

  if ! fetch_file "$DOWNLOAD_URL" "${TMP_DIR}/${TARBALL}"; then
    warn "Download failed for ${TARBALL}."
    return 1
  fi

  info "Downloading release checksums..."
  if ! fetch_file "$CHECKSUMS_URL" "${TMP_DIR}/${CHECKSUMS_FILE}"; then
    warn "Checksum download failed for ${RELEASE_TAG}; refusing to install an unverified release."
    return 1
  fi

  if ! verify_download_checksum "${TMP_DIR}/${CHECKSUMS_FILE}" "${TMP_DIR}/${TARBALL}" "${TARBALL}"; then
    if allow_degraded_install; then
      warn "Proceeding with an unverified release because GCLAW_ALLOW_DEGRADED_INSTALL=1."
    else
      warn "Release verification failed; falling back to a source build."
      return 1
    fi
  fi

  info "Extracting archive..."
  tar -xzf "${TMP_DIR}/${TARBALL}" -C "$TMP_DIR"

  BIN_SRC=$(find "$TMP_DIR" -maxdepth 2 -type f -iname "$BINARY" | head -n 1)
  if [ -z "$BIN_SRC" ]; then
    warn "Binary not found in archive."
    return 1
  fi

  mkdir -p "$INSTALL_DIR"
  mv "$BIN_SRC" "${INSTALL_DIR}/${BINARY}"
  chmod +x "${INSTALL_DIR}/${BINARY}"

  success "Installed gclaw ${RELEASE_TAG} → ${INSTALL_DIR}/${BINARY}"
  return 0
}

# ── Strategy 2: Build from source ────────────────────────────────────────────
try_source_install() {
  info "Attempting to build from source..."

  # Check for Go
  if ! command -v go &>/dev/null; then
    error "Go is not installed."
    echo ""
    echo "  Install Go from https://go.dev/dl/ and re-run this script,"
    echo "  or install a pre-built binary when a release is published:"
    echo "  https://github.com/${REPO}/releases"
    exit 1
  fi

  GO_VER=$(go version 2>/dev/null | awk '{print $3}')
  info "Found Go: ${GO_VER}"

  # Check for git
  if ! command -v git &>/dev/null; then
    error "git is required to build from source."
    exit 1
  fi

  # Check for make
  if ! command -v make &>/dev/null; then
    error "make is required to build from source."
    echo "  Install it with: apt install make  (Debian/Ubuntu)"
    echo "                    yum install make  (RHEL/CentOS)"
    echo "                    brew install make  (macOS)"
    exit 1
  fi

  # Determine source directory
  # If we're already inside the repo, use it; otherwise clone fresh
  SRC_DIR=""
  if [ -f "Makefile" ] && [ -f "go.mod" ] && grep -q "GemachDAO/Gclaw" go.mod 2>/dev/null; then
    SRC_DIR="$(pwd)"
    info "Building from local source: ${SRC_DIR}"
  elif [ -f "$(dirname "$0")/Makefile" ] 2>/dev/null && grep -q "GemachDAO/Gclaw" "$(dirname "$0")/go.mod" 2>/dev/null; then
    SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
    info "Building from local source: ${SRC_DIR}"
  else
    TMP_SRC=$(mktemp -d)
    trap 'rm -rf "$TMP_SRC"' EXIT
    info "Cloning repository..."
    if ! git clone --depth 1 "https://github.com/${REPO}.git" "$TMP_SRC/Gclaw" 2>&1; then
      error "Failed to clone repository."
      exit 1
    fi
    SRC_DIR="$TMP_SRC/Gclaw"
  fi

  info "Building gclaw (this may take a minute)..."
  if ! make -C "$SRC_DIR" install INSTALL_BIN_DIR="$INSTALL_DIR" 2>&1; then
    error "Build failed."
    echo ""
    echo "  Check the errors above. Common fixes:"
    echo "    - Update Go: https://go.dev/dl/"
    echo "    - Run: cd ${SRC_DIR} && go mod download"
    exit 1
  fi

  success "Built and installed gclaw → ${INSTALL_DIR}/${BINARY}"
  return 0
}


# ── GDEX helpers: install Node dependencies if possible ──────────────────────
setup_gdex_helpers() {
  # Find the helpers directory relative to the binary or workspace
  local HELPERS_DIR=""
  local candidates=(
    "${HOME}/.gclaw/workspace/skills/gdex-trading/helpers"
  )
  if [ -n "${SRC_DIR:-}" ]; then
    candidates+=("${SRC_DIR}/workspace/skills/gdex-trading/helpers")
  fi
  candidates+=(
    "$(dirname "$0")/workspace/skills/gdex-trading/helpers"
    "${PWD}/workspace/skills/gdex-trading/helpers"
  )

  for candidate in "${candidates[@]}"; do
    if [ -f "${candidate}/package.json" ]; then
      HELPERS_DIR="$candidate"
      break
    fi
  done

  if [ -z "$HELPERS_DIR" ]; then
    return 0  # helpers not found, skip silently
  fi

  if [ -d "${HELPERS_DIR}/node_modules" ]; then
    return 0  # already installed
  fi

  if ! command -v node &>/dev/null; then
    if allow_degraded_install; then
      warn "Node.js not found — GDEX trading helpers require Node.js."
      warn "Install Node.js (v18+) and run: bash ${HELPERS_DIR}/setup.sh"
      return 0
    fi
    error "Node.js not found — GDEX trading helpers require Node.js. Install Node.js (v18+) and rerun the installer."
    return 1
  fi

  if ! command -v npm &>/dev/null; then
    if allow_degraded_install; then
      warn "npm not found — GDEX trading helpers require npm."
      return 0
    fi
    error "npm not found — GDEX trading helpers require npm. Install npm and rerun the installer."
    return 1
  fi

  info "Installing GDEX trading helper dependencies..."
  if [ -f "${HELPERS_DIR}/setup.sh" ]; then
    if bash "${HELPERS_DIR}/setup.sh" 2>&1; then
      success "GDEX trading helpers installed."
    else
      if allow_degraded_install; then
        warn "GDEX helper setup failed. Run manually: bash ${HELPERS_DIR}/setup.sh"
      else
        error "GDEX helper setup failed. Rerun manually: bash ${HELPERS_DIR}/setup.sh"
        return 1
      fi
    fi
  else
    if (cd "$HELPERS_DIR" && npm install --no-audit --no-fund) 2>&1; then
      success "GDEX trading helpers installed."
    else
      if allow_degraded_install; then
        warn "GDEX helper npm install failed. Run manually: cd ${HELPERS_DIR} && npm install"
      else
        error "GDEX helper npm install failed. Rerun manually: cd ${HELPERS_DIR} && npm install"
        return 1
      fi
    fi
  fi
}

main() {
  print_banner
  detect_platform || exit 1
  check_dependencies || exit 1

  if try_release_install; then
    ensure_path
    run_onboard
    setup_gdex_helpers || exit 1
    maybe_launch_gateway
    exit 0
  fi

  warn "No pre-built release available. Falling back to source build..."
  echo ""

  try_source_install
  ensure_path
  run_onboard
  setup_gdex_helpers || exit 1
  maybe_launch_gateway
}

if [ "${GCLAW_INSTALL_TEST_MODE:-0}" != "1" ]; then
  main "$@"
fi
