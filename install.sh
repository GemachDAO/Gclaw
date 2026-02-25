#!/usr/bin/env bash
# Gclaw one-shot installer
# Usage: curl -fsSL https://raw.githubusercontent.com/GemachDAO/Gclaw/main/install.sh | bash
set -euo pipefail

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
echo -e "   Installing the latest release...\n"

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
if ! command -v curl &>/dev/null; then
  error "curl is required but not found. Please install curl and re-run."
  exit 1
fi

# ── Fetch latest release tag ──────────────────────────────────────────────────
LATEST_URL="https://api.github.com/repos/${REPO}/releases/latest"
info "Fetching latest release..."
RELEASE_JSON=$(curl -fsSL "$LATEST_URL" 2>/dev/null || true)
RELEASE_TAG=$(echo "$RELEASE_JSON" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')

if [ -z "$RELEASE_TAG" ]; then
  error "Could not determine the latest release tag."
  error "Check: https://github.com/${REPO}/releases"
  error ""
  error "If you have Go installed, you can build from source instead:"
  error "  git clone https://github.com/${REPO}.git && cd Gclaw && make install"
  exit 1
fi

success "Latest release: ${RELEASE_TAG}"

# ── Download & install ────────────────────────────────────────────────────────
TARBALL="${BINARY}_${OS_NAME}_${ARCH_NAME}.tar.gz"
DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}/${TARBALL}"

info "Downloading ${TARBALL}..."
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

if ! curl -fsSL --progress-bar "$DOWNLOAD_URL" -o "${TMP_DIR}/${TARBALL}"; then
  error "Download failed. URL: ${DOWNLOAD_URL}"
  error "Please check https://github.com/${REPO}/releases and install manually."
  exit 1
fi

info "Extracting archive..."
tar -xzf "${TMP_DIR}/${TARBALL}" -C "$TMP_DIR"

if [ ! -f "${TMP_DIR}/${BINARY}" ]; then
  error "Binary '${BINARY}' not found in archive."
  exit 1
fi

mkdir -p "$INSTALL_DIR"
mv "${TMP_DIR}/${BINARY}" "${INSTALL_DIR}/${BINARY}"
chmod +x "${INSTALL_DIR}/${BINARY}"

success "Installed gclaw ${RELEASE_TAG} → ${INSTALL_DIR}/${BINARY}"

# ── PATH check ────────────────────────────────────────────────────────────────
if ! echo ":${PATH}:" | grep -q ":${INSTALL_DIR}:"; then
  warn "${INSTALL_DIR} is not in your PATH."
  echo ""
  echo "  Add the following line to your shell profile"
  echo "  (~/.bashrc, ~/.zshrc, ~/.profile, etc.) and restart your terminal:"
  echo ""
  echo -e "  ${BOLD}export PATH=\"\${HOME}/.local/bin:\${PATH}\"${NC}"
  echo ""
  # Try to auto-append for common shells
  SHELL_PROFILE=""
  if [ -n "${BASH_VERSION:-}" ] && [ -f "${HOME}/.bashrc" ]; then
    SHELL_PROFILE="${HOME}/.bashrc"
  elif [ -n "${ZSH_VERSION:-}" ] && [ -f "${HOME}/.zshrc" ]; then
    SHELL_PROFILE="${HOME}/.zshrc"
  fi
  if [ -n "$SHELL_PROFILE" ]; then
    echo "  Auto-adding to ${SHELL_PROFILE} ..."
    # shellcheck disable=SC2016
    echo '' >> "$SHELL_PROFILE"
    echo '# Added by gclaw installer' >> "$SHELL_PROFILE"
    echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "$SHELL_PROFILE"
    success "Updated ${SHELL_PROFILE}. Run: source ${SHELL_PROFILE}"
  fi
  echo ""
fi

# ── Run onboard ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Running initial setup...${NC}"
echo ""
"${INSTALL_DIR}/${BINARY}" onboard
