#!/usr/bin/env python3
"""LuaTools Ultimate — Steam UI injector / self-heal utility.

Ported and adapted from upstream LuaToolsLinux for Millennium 3.0-beta.

WHY THIS EXISTS
---------------
On Millennium 3.0 the plugin's frontend JS (public/luatools.js) is normally
loaded by Millennium itself. But Millennium betas churn, and if the loader
changes or the plugin fails to inject, the whole UI disappears. This module
is a *self-heal fallback*: it patches Steam's own ``steamui/index.html`` to
load luatools.js directly (between LuaTools markers), so the UI keeps working
independent of Millennium's plugin loader.

luatools.js carries an idempotency guard (window.__LUATOOLS_ULTIMATE_LOADED__),
so it is safe even if BOTH Millennium and this injector load it — it only runs
once per context.

SAFETY
------
- UI injection (steamui/index.html) is reversible and low-risk — we own the
  marker block and only touch our own block.
- steam.sh repair (removing a broken LD_AUDIT line) is DESTRUCTIVE and is NEVER
  run automatically here. It is exposed only via an explicit call, honoring the
  project rule that steam.sh is otherwise read-only.
"""

from __future__ import annotations

import os
import shutil
import subprocess

try:
    from logger import logger
except Exception:  # pragma: no cover - standalone use
    class _L:
        def log(self, *a): pass
        def warn(self, *a): pass
        def error(self, *a): pass
    logger = _L()


MARKER_START = "<!-- LuaTools Ultimate Inject START -->"
MARKER_END = "<!-- LuaTools Ultimate Inject END -->"
# Fallback tag if inlining fails. Steam serves steamui/ as the web root, so a
# relative path under steamui/LuaTools/ resolves correctly.
SCRIPT_TAG = '<script src="LuaTools/luatools.js"></script>'


def _candidate_steam_roots() -> list:
    return [
        os.path.expanduser("~/.steam/steam"),
        os.path.expanduser("~/.local/share/Steam"),
        os.path.expanduser("~/.steam/root"),
        os.path.expanduser("~/.var/app/com.valvesoftware.Steam/.steam/steam"),
    ]


def _public_dir(install_root: str = "") -> str:
    """Locate the plugin's public/ directory (where luatools.js lives)."""
    if install_root:
        cand = os.path.join(install_root, "public")
        if os.path.isdir(cand):
            return cand
    try:
        from paths import get_plugin_dir
        cand = os.path.join(get_plugin_dir(), "public")
        if os.path.isdir(cand):
            return cand
    except Exception:
        pass
    # Last resort: relative to this file (backend/.. /public)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "public")


def _sync_assets(public_dir: str, target_dir: str) -> None:
    """Copy luatools.js + icon + themes into steamui/LuaTools/ (for the
    relative-path fallback tag)."""
    os.makedirs(target_dir, exist_ok=True)

    for fname in ("luatools.js", "luatools-icon.png", "luatools.css"):
        src = os.path.join(public_dir, fname)
        if os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(target_dir, fname))
            except Exception as exc:
                logger.warn(f"LuaTools ui_injector: copy {fname} failed: {exc}")

    themes_src = os.path.join(public_dir, "themes")
    themes_dst = os.path.join(target_dir, "themes")
    if os.path.isdir(themes_src):
        try:
            if os.path.isdir(themes_dst):
                shutil.rmtree(themes_dst)
            shutil.copytree(themes_src, themes_dst)
        except Exception as exc:
            logger.warn(f"LuaTools ui_injector: copy themes failed: {exc}")


def _build_inline_script_tag(script_path: str):
    """Inline luatools.js directly into the page. More robust than a relative
    src= tag because it doesn't depend on Steam's web root / CSP resolving the
    LuaTools/ path."""
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            script_content = f.read()
    except Exception:
        return None
    # Prevent a literal </script> inside the JS from terminating the tag early.
    script_content = script_content.replace("</script>", "<\\/script>")
    return f"<script>\n{script_content}\n</script>"


def _inject_index(index_html: str, script_tag: str) -> bool:
    """Insert/update our marker block in steamui/index.html. Idempotent."""
    try:
        with open(index_html, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
    except Exception as exc:
        logger.warn(f"LuaTools ui_injector: read {index_html} failed: {exc}")
        return False

    block = f"{MARKER_START}\n{script_tag}\n{MARKER_END}"

    # Replace existing block if present
    if MARKER_START in html and MARKER_END in html:
        start_idx = html.find(MARKER_START)
        end_idx = html.find(MARKER_END)
        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            return False
        end_idx += len(MARKER_END)
        if html[start_idx:end_idx] == block:
            return False  # already up to date
        patched = html[:start_idx] + block + html[end_idx:]
    else:
        # Insert before </body>
        idx = html.lower().rfind("</body>")
        if idx == -1:
            logger.warn(f"LuaTools ui_injector: no </body> in {index_html}")
            return False
        patched = html[:idx] + "\n" + block + "\n" + html[idx:]

    try:
        with open(index_html, "w", encoding="utf-8") as f:
            f.write(patched)
        return True
    except Exception as exc:
        logger.warn(f"LuaTools ui_injector: write {index_html} failed: {exc}")
        return False


def ensure_ui_injection(install_root: str = "", inline: bool = True) -> dict:
    """Self-heal: make sure luatools.js loads in Steam's UI on every root found.

    Returns a stats dict. Safe to call repeatedly (idempotent)."""
    public_dir = _public_dir(install_root)
    result = {"success": True, "roots_seen": 0, "roots_patched": 0,
              "assets_synced": 0, "publicDir": public_dir, "roots": []}

    inline_tag = None
    if inline:
        inline_tag = _build_inline_script_tag(os.path.join(public_dir, "luatools.js"))
    script_tag = inline_tag or SCRIPT_TAG

    for root in _candidate_steam_roots():
        index_html = os.path.join(root, "steamui", "index.html")
        if not os.path.isfile(index_html):
            continue
        result["roots_seen"] += 1
        # Always sync assets for the fallback path
        _sync_assets(public_dir, os.path.join(root, "steamui", "LuaTools"))
        result["assets_synced"] += 1
        if _inject_index(index_html, script_tag):
            result["roots_patched"] += 1
            result["roots"].append(root)
            logger.log(f"LuaTools ui_injector: patched {index_html}")

    if result["roots_seen"] == 0:
        result["success"] = False
        result["error"] = "Steam UI not found (open Steam, then retry)."
    return result


def remove_ui_injection() -> dict:
    """Undo: strip our marker block from every steamui/index.html. Clean removal."""
    result = {"success": True, "removed": 0}
    for root in _candidate_steam_roots():
        index_html = os.path.join(root, "steamui", "index.html")
        if not os.path.isfile(index_html):
            continue
        try:
            with open(index_html, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
            if MARKER_START in html and MARKER_END in html:
                s = html.find(MARKER_START)
                e = html.find(MARKER_END) + len(MARKER_END)
                # Also eat a leading newline we may have added
                lead = s
                if lead > 0 and html[lead - 1] == "\n":
                    lead -= 1
                # ...and a single trailing newline, so inject+remove round-trips
                # back to the exact original page.
                if e < len(html) and html[e] == "\n":
                    e += 1
                patched = html[:lead] + html[e:]
                with open(index_html, "w", encoding="utf-8") as f:
                    f.write(patched)
                result["removed"] += 1
        except Exception as exc:
            logger.warn(f"LuaTools ui_injector: remove failed for {index_html}: {exc}")
    return result


# ── steam.sh repair (EXPLICIT, never automatic) ─────────────────────────────

def _audit_library_is_compatible(path: str) -> bool:
    """True unless the .so is 32-bit (which breaks 64-bit Steam's LD_AUDIT)."""
    try:
        if not os.path.isfile(path):
            return True  # nothing to judge
        result = subprocess.run(["file", path], capture_output=True,
                                text=True, check=False)
        output = (result.stdout or "") + (result.stderr or "")
        return "ELF 32-bit" not in output
    except Exception:
        return True


def repair_steam_launcher(confirm: bool = False) -> dict:
    """Remove a broken SLSsteam LD_AUDIT line from steam.sh.

    DESTRUCTIVE — modifies steam.sh. Requires confirm=True and is NEVER called
    automatically. Only needed when the injected SLSsteam .so is 32-bit and is
    crashing Steam's launcher. Backs up steam.sh before editing.
    """
    result = {"success": False, "modified": False, "messages": []}
    if not confirm:
        result["error"] = "Refused: pass confirm=True (this edits steam.sh)."
        return result

    for root in _candidate_steam_roots():
        steam_sh = os.path.join(root, "steam.sh")
        if not os.path.isfile(steam_sh):
            continue
        sls_so = os.path.expanduser("~/.local/share/SLSsteam/SLSsteam.so")
        if _audit_library_is_compatible(sls_so):
            result["messages"].append(
                f"{steam_sh}: SLSsteam library looks compatible; no repair needed.")
            continue
        try:
            with open(steam_sh, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            filtered = [ln for ln in lines
                        if not ("LD_AUDIT" in ln and "SLSsteam" in ln)]
            if filtered == lines:
                result["messages"].append(f"{steam_sh}: no LD_AUDIT line to remove.")
                continue
            # Backup before write
            import time
            bak = steam_sh + ".luatools-bak-" + time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(steam_sh, bak)
            with open(steam_sh, "w", encoding="utf-8") as fh:
                fh.writelines(filtered)
            result["modified"] = True
            result["messages"].append(
                f"Removed incompatible LD_AUDIT from {steam_sh} (backup: {bak}). Restart Steam.")
        except Exception as exc:
            result["messages"].append(f"{steam_sh}: repair failed: {exc}")
            result["error"] = str(exc)
            return result

    result["success"] = True
    return result


def main() -> int:
    install_root = os.path.expanduser(
        os.environ.get("LUATOOLS_INSTALL_ROOT", ""))
    stats = ensure_ui_injection(install_root)
    print(f"roots_seen={stats['roots_seen']} roots_patched={stats['roots_patched']} "
          f"assets_synced={stats['assets_synced']}")
    if stats["roots_seen"] == 0:
        print("Steam UI not found. Open Steam and rerun after it has started.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
