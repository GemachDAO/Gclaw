#!/usr/bin/env bash
# Gclaw one-shot installer
# Usage: curl -fsSL https://raw.githubusercontent.com/GemachDAO/Gclaw/main/install.sh | bash
#
# Tries to download a pre-built release binary first.
# Falls back to building from source (requires Go and git) when no release is available.

REPO="GemachDAO/Gclaw"
BINARY="gclaw"
INSTALL_DIR="${GCLAW_INSTALL_DIR:-${HOME}/.local/bin}"

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

echo ""
echo -e "${BOLD}🦞 Gclaw — The Living Agent${NC}"
echo -e "   One-shot installer\n"

# ── OS detection ──────────────────────────────────────────────────────────────
OS=$(uname -s)
ARCH=$(uname -m)

case "$OS" in
  Linux)  OS_NAME="Linux"  ;;
  Darwin) OS_NAME="Darwin" ;;
  *)
    error "Unsupported operating system: $OS"
    error "Please install manually: https://github.com/${REPO}/releases"
    exit 1
    ;;
esac

case "$ARCH" in
  x86_64)          ARCH_NAME="x86_64" ;;
  aarch64 | arm64) ARCH_NAME="arm64"  ;;
  armv7l)          ARCH_NAME="armv7"  ;;
  riscv64)         ARCH_NAME="riscv64" ;;
  *)
    error "Unsupported architecture: $ARCH"
    error "Please install manually: https://github.com/${REPO}/releases"
    exit 1
    ;;
esac

info "Detected platform: ${OS_NAME}/${ARCH_NAME}"

# ── Dependency checks ─────────────────────────────────────────────────────────
if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
  error "curl or wget is required but neither was found."
  exit 1
fi

# ── Helper: ensure PATH ──────────────────────────────────────────────────────
ensure_path() {
  if echo ":${PATH}:" | grep -q ":${INSTALL_DIR}:"; then
    return
  fi

  warn "${INSTALL_DIR} is not in your PATH."
  echo ""
  echo "  Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
  echo ""
  echo -e "  ${BOLD}export PATH=\"\${HOME}/.local/bin:\${PATH}\"${NC}"
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
    if ! grep -q '/.local/bin' "$SHELL_PROFILE" 2>/dev/null; then
      echo "  Auto-adding to ${SHELL_PROFILE} ..."
      printf '\n# Added by gclaw installer\nexport PATH="${HOME}/.local/bin:${PATH}"\n' >> "$SHELL_PROFILE"
      success "Updated ${SHELL_PROFILE}. Run: source ${SHELL_PROFILE}"
    else
      info "${SHELL_PROFILE} already contains PATH entry."
    fi
  fi
  echo ""
}

# ── Helper: run onboard ──────────────────────────────────────────────────────
run_onboard() {
  # Only run onboard when stdin is a terminal (interactive)
  if [ -t 0 ]; then
    echo ""
    echo -e "${BOLD}Running initial setup...${NC}"
    echo ""
    "${INSTALL_DIR}/${BINARY}" onboard
  else
    echo ""
    info "Run ${BOLD}gclaw onboard${NC} to complete setup."
  fi
}

# ── Strategy 1: Download pre-built release binary ────────────────────────────
try_release_install() {
  LATEST_URL="https://api.github.com/repos/${REPO}/releases/latest"
  info "Checking for pre-built release..."
  RELEASE_JSON=$(curl -fsSL "$LATEST_URL" 2>/dev/null || true)
  RELEASE_TAG=$(echo "$RELEASE_JSON" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/' || true)

  if [ -z "$RELEASE_TAG" ]; then
    return 1  # No release found
  fi

  success "Latest release: ${RELEASE_TAG}"

  TARBALL="${BINARY}_${OS_NAME}_${ARCH_NAME}.tar.gz"
  DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}/${TARBALL}"

  info "Downloading ${TARBALL}..."
  TMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TMP_DIR"' EXIT

  if ! curl -fsSL --progress-bar "$DOWNLOAD_URL" -o "${TMP_DIR}/${TARBALL}"; then
    warn "Download failed for ${TARBALL}."
    return 1
  fi

  info "Extracting archive..."
  tar -xzf "${TMP_DIR}/${TARBALL}" -C "$TMP_DIR"

  if [ ! -f "${TMP_DIR}/${BINARY}" ]; then
    warn "Binary not found in archive."
    return 1
  fi

  mkdir -p "$INSTALL_DIR"
  mv "${TMP_DIR}/${BINARY}" "${INSTALL_DIR}/${BINARY}"
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
  if ! make -C "$SRC_DIR" install 2>&1; then
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

# ── Main install flow ─────────────────────────────────────────────────────────
if try_release_install; then
  ensure_path
  run_onboard
  exit 0
fi

warn "No pre-built release available. Falling back to source build..."
echo ""

try_source_install
ensure_path
run_onboard
