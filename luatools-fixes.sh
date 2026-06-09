#!/usr/bin/env bash
# LuaTools Ultimate — fixes & repair menu
# Ported/adapted from upstream LuaToolsLinux install.sh fix suite.
# Standalone: run `bash luatools-fixes.sh` and pick from the menu.

set -uo pipefail

BOLD=$'\033[1m'; NC=$'\033[0m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'
info()  { echo -e "${CYAN}[*]${NC} $*"; }
ok()    { echo -e "${GREEN}[ok]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }

# ── fix-deps runner (delegates to enter-the-wired's dependency fixer) ────────
run_fix_deps() {
    info "Running dependency fix (enter-the-wired fix-deps)..."
    curl -fsSL https://raw.githubusercontent.com/ciscosweater/enter-the-wired/main/fix-deps | bash \
        || warn "fix-deps failed; continuing."
}

# ── Remove anti-piracy CSS blocks that hide luatools/manilua/lumea ──────────
# Some Millennium themes (e.g. SpaceTheme) ship CSS that hides "piracy" plugins,
# so the LuaTools button never appears. This strips those blocks. Backs up first.
fix_remove_piracy_blocks() {
    local theme_dirs=(
        "$HOME/.steam/steam/millennium/themes/Steam"
        "$HOME/.local/share/Steam/millennium/themes/Steam"
        "$HOME/.millennium/themes/Steam"
    )
    local theme_dir=""
    for dir in "${theme_dirs[@]}"; do
        [[ -d "$dir/src/css" ]] && { theme_dir="$dir"; break; }
    done
    if [[ -z "$theme_dir" ]]; then
        warn "Theme directory not found (Millennium theme not installed?)."
        return 1
    fi
    ok "Theme directory: $theme_dir"
    local css_dir="$theme_dir/src/css"
    local files=(friends.custom.css inputs/inputs.css plugins/hltb.css webkit.css \
                 startupLogin.custom.css regular.css libraryroot.custom.css)
    local any_fixed=false
    for filename in "${files[@]}"; do
        local filepath="$css_dir/$filename"
        [[ -f "$filepath" ]] || { echo "  $filename -> not found, skip"; continue; }
        echo -n "  $filename ... "
        cp "$filepath" "$filepath.bak"
        python3 - "$filepath" <<'PY'
import re, sys
p = sys.argv[1]
with open(p) as f: c = f.read()
old = c
c = re.sub(r'/\*.*?Ban piracy plugins.*?\*/.*?color: #fff !important;\n\}', '', c, flags=re.DOTALL)
c = re.sub(r'.*?(luatools|manilua|lumea).*?\n', '', c)
c = re.sub(r'\n{3,}', '\n\n', c)
if c != old:
    with open(p, 'w') as f: f.write(c)
    sys.exit(0)
sys.exit(1)
PY
        if [[ $? -eq 0 ]]; then echo "removed"; any_fixed=true
        else rm -f "$filepath.bak"; echo "no block"; fi
    done
    $any_fixed && ok "Anti-piracy blocks removed. Restart Steam to apply." \
               || warn "No anti-piracy blocks found."
}

# ── Self-heal the Steam UI via the ported ui_injector ───────────────────────
fix_heal_ui() {
    local backend
    backend="$(dirname "$0")/backend"
    [[ -d "$backend" ]] || backend="$HOME/.local/share/millennium/plugins/luatools/backend"
    if [[ -f "$backend/ui_injector.py" ]]; then
        ( cd "$backend" && python3 ui_injector.py )
    else
        warn "ui_injector.py not found at $backend"
    fi
}

# ── Interactive troubleshooting guides (text) ───────────────────────────────
guide_not_downloading() {
    cat <<'TXT'

⚠️  GAME NOT DOWNLOADING?
Most common cause: ACCELA (the external launcher that performs the download)
is not configured, OR you're trying to download straight from Steam without it.

  1) Open ACCELA → Options/Downloads.
  2) Ensure "Limit downloads to Steam Library" is ENABLED.
  3) In Steam: Steam menu (top-left) → Millennium → Plugins → enable LuaTools.
  4) In the LuaTools menu → "External Launcher (ACCELA)" → click the folder icon.
  5) Navigate to ~/.local/share/ACCELA and select run.sh OR ACCELA.AppImage.
  6) Click the save (diskette) icon.
  7) Also verify SLSsteam PlayNotOwnedGames is ON:
       cd backend && python3 standalone_cli.py play-not-owned on
  8) Re-activate the game; it should download.
TXT
    read -p "Press Enter to continue..." < /dev/tty
}

guide_content_encrypted() {
    cat <<'TXT'

Error: "Content Still Encrypted"
  1) Right-click the game → Properties → Compatibility.
  2) Tick "Force a specific Steam Play compatibility tool".
  3) Windows games: pick Proton (Experimental, or per ProtonDB).
  4) Properties → Installed Files → "Verify integrity of game files".
  5) Wait for verification, then launch.
TXT
    read -p "Press Enter to continue..." < /dev/tty
}

menu() {
    while true; do
        echo ""
        echo -e "${BOLD}LuaTools Ultimate — Fixes${NC}"
        echo "  1) Run fix-deps (system dependencies)"
        echo "  2) Remove anti-piracy CSS blocks (unhide the LuaTools button)"
        echo "  3) Self-heal Steam UI (re-inject luatools.js)"
        echo "  4) Guide: game not downloading (ACCELA config)"
        echo "  5) Guide: content still encrypted"
        echo "  q) Quit"
        read -p "Choose: " choice < /dev/tty
        case "$choice" in
            1) run_fix_deps ;;
            2) fix_remove_piracy_blocks ;;
            3) fix_heal_ui ;;
            4) guide_not_downloading ;;
            5) guide_content_encrypted ;;
            q|Q) break ;;
            *) warn "Invalid choice." ;;
        esac
    done
}

menu
