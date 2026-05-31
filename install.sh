#!/usr/bin/env bash
# LuaTools Ultimate — Linux installer (v9.1, Millennium 3.0 / Lua build)
#
# Sets up the plugin under Millennium's plugins directory and prepares the
# Python virtual environment AT INSTALL TIME, so the first Steam launch is
# fast and the localhost bridge comes up immediately (no silent venv/pip
# delay during startup).
#
# Steam-tool installation (SLSsteam / ACCELA) and steam.sh injection are NOT
# handled here — use the upstream installer (ciscosweater/enter-the-wired),
# which is the canonical, maintained path. This script never edits steam.sh.
#
# Install flow patterns adapted from the LuaToolsLinux installer by
# StarWarsK (github.com/Star123451). Credit to them.

set -euo pipefail

PLUGIN_NAME="luatools"
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()   { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Pre-flight ────────────────────────────────────────────────────────────
[[ "$(uname -m)" == "x86_64" ]] || fail "Unsupported arch: $(uname -m) (need x86_64)"
command -v python3 >/dev/null || fail "python3 not found"
command -v curl    >/dev/null || warn "curl not found (only needed for deps)"

# Native Steam check — Millennium does not work on Flatpak/Snap Steam.
steam_type="native"
if command -v flatpak >/dev/null && flatpak list 2>/dev/null | grep -q "com.valvesoftware.Steam"; then
    steam_type="flatpak"
elif command -v snap >/dev/null && snap list 2>/dev/null | grep -q "^steam "; then
    steam_type="snap"
fi
if [[ "$steam_type" != "native" ]]; then
    warn "Detected $steam_type Steam. Millennium requires NATIVE Steam."
    warn "Install the native package (e.g. 'sudo pacman -S steam' on CachyOS/Arch)."
    fail "Aborting — native Steam required."
fi
ok "Native Steam OK"

# ── Locate Millennium plugins dir ─────────────────────────────────────────
plugins_dir=""
for d in \
    "$HOME/.local/share/millennium/plugins" \
    "$HOME/.millennium/plugins" \
    "$HOME/.steam/steam/millennium/plugins"; do
    [[ -d "$d" ]] && { plugins_dir="$d"; break; }
done
if [[ -z "$plugins_dir" ]]; then
    plugins_dir="$HOME/.local/share/millennium/plugins"
    mkdir -p "$plugins_dir"
    warn "Millennium plugins dir not found; created $plugins_dir"
    warn "If Millennium isn't installed yet, install the beta:"
    warn "  curl -fsSL https://steambrew.app/install.sh | bash -s -- --beta"
fi
install_dir="$plugins_dir/$PLUGIN_NAME"

# ── Copy plugin into place (unless we're already running from there) ──────
if [[ "$SCRIPT_DIR" != "$install_dir" ]]; then
    info "Installing plugin to $install_dir"
    rm -rf "$install_dir"
    mkdir -p "$install_dir"
    # Copy everything except the venv and VCS noise
    (cd "$SCRIPT_DIR" && tar --exclude='.venv' --exclude='__pycache__' \
        --exclude='*.pyc' -cf - .) | (cd "$install_dir" && tar -xf -)
    ok "Files copied"
else
    info "Running from install dir; updating in place"
fi

# ── Create the venv + install deps AT INSTALL TIME ────────────────────────
venv_dir="$install_dir/.venv"
info "Creating Python virtual environment..."
if ! python3 -m venv "$venv_dir" 2>/dev/null; then
    warn "venv creation failed — is python3-venv installed?"
    warn "  Debian/Ubuntu: sudo apt install python3-venv"
    warn "  Fedora:        sudo dnf install python3-virtualenv"
    warn "Continuing; the plugin will try system python3 at runtime."
else
    ok "venv created at $venv_dir"
    info "Installing Python requirements (httpx, beautifulsoup4, ruamel.yaml)..."
    if "$venv_dir/bin/pip" install --quiet --disable-pip-version-check \
            -r "$install_dir/requirements.txt"; then
        ok "Python requirements installed"
    else
        warn "pip install failed; bridge may not start. Re-run after fixing network/deps."
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
ok "LuaTools Ultimate installed."
echo -e "${CYAN}Next steps:${NC}"
echo "  1) (Re)start Steam."
echo "  2) Steam → menu (top-left) → Millennium → Plugins → enable 'LuaTools Ultimate'."
echo "  3) For game activation you also need SLSsteam or ACCELA installed:"
echo "       curl -fsSL https://raw.githubusercontent.com/ciscosweater/enter-the-wired/main/enter-the-wired | bash"
echo "     (That installer handles steam.sh injection — this script never touches it.)"
echo ""
echo "  Bridge log (for troubleshooting): /tmp/luatools_bridge.log"
