"""Linux platform layer for LuaTools (v9.1).

Linux-specific Steam paths and activation-tool detection. On Linux the
Windows-only SteamTools is replaced by SLSsteam (an LD_AUDIT-injected .so)
or ACCELA — but both read .lua activation scripts from the same
config/stplug-in/ directory SteamTools uses, so the plugin's activation
model carries over unchanged.

The Steam-root resolution and SLSsteam/ACCELA detection logic here is
adapted from the LuaToolsLinux fork by StarWarsK (github.com/Star123451)
and geovanygrdt (github.com/gr33dster-glitch), used as reference for the
platform layer. Credit to them.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional, Dict, Any

from logger import logger


# ---------------------------------------------------------------------------
# Steam root — Linux prefers a directory containing steam.sh
# ---------------------------------------------------------------------------

def find_steam_root() -> Optional[str]:
    """Return the Steam install dir, preferring one that contains steam.sh.

    Delegates the candidate list to paths.get_steam_path() but additionally
    prefers a root with steam.sh present — the strongest Linux indicator.
    """
    try:
        from paths import get_steam_path, _linux_steam_candidates
    except Exception:
        return None

    # Strongest signal: steam.sh present
    for cand in _linux_steam_candidates():
        resolved = os.path.realpath(cand)
        if os.path.isdir(resolved) and os.path.isfile(os.path.join(resolved, "steam.sh")):
            return resolved

    # Fall back to the general resolver
    resolved = get_steam_path()
    return resolved or None


def get_stplugin_dir(steam_root: Optional[str] = None) -> Optional[str]:
    """Return config/stplug-in/ — where .lua activation scripts live.

    Same location SLSsteam reads from, identical to the SteamTools layout.
    """
    root = steam_root or find_steam_root()
    return os.path.join(root, "config", "stplug-in") if root else None


def get_depotcache_dir(steam_root: Optional[str] = None) -> Optional[str]:
    """Return depotcache/ under the Steam root."""
    root = steam_root or find_steam_root()
    return os.path.join(root, "depotcache") if root else None


# ---------------------------------------------------------------------------
# SLSsteam — the Linux drop-in for SteamTools
# ---------------------------------------------------------------------------

_SLSSTEAM_CANDIDATES = [
    os.path.expanduser("~/.local/share/SLSsteam"),
    os.path.expanduser("~/SLSsteam"),
    "/opt/SLSsteam",
]


def get_slssteam_install_dir() -> str:
    """Return the SLSsteam install dir if found, else the default location."""
    for path in _SLSSTEAM_CANDIDATES:
        if os.path.isfile(os.path.join(path, "SLSsteam.so")):
            return path
    return os.path.expanduser("~/.local/share/SLSsteam")


def get_slssteam_config_dir() -> str:
    return os.path.expanduser("~/.config/SLSsteam")


def get_slssteam_config_path() -> str:
    return os.path.join(get_slssteam_config_dir(), "config.yaml")


def check_slssteam_installed() -> bool:
    """True if SLSsteam.so exists in any known install dir."""
    return any(
        os.path.isfile(os.path.join(p, "SLSsteam.so"))
        for p in _SLSSTEAM_CANDIDATES
    )


def check_slssteam_injection() -> Dict[str, Any]:
    """READ-ONLY: report whether steam.sh already carries the LD_AUDIT export.

    This function NEVER modifies steam.sh. Editing Steam's launch script is
    destructive (a wrong LD_AUDIT path makes Steam unstartable), so it must
    only ever happen as an explicit, clearly-warned user action via
    patch_steam_sh_explicit() — never as a side effect of a status query.
    """
    if not check_slssteam_installed():
        return {"injected": False, "error": "SLSsteam not installed"}

    root = find_steam_root()
    steam_sh = os.path.join(root, "steam.sh") if root else ""
    if not steam_sh or not os.path.isfile(steam_sh):
        return {"injected": False, "error": "steam.sh not found"}

    try:
        with open(steam_sh, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return {"injected": False, "error": f"read failed: {exc}"}

    injected = ("LD_AUDIT" in content and "SLSsteam" in content)
    return {"injected": injected, "steamShPath": steam_sh, "error": None}


def patch_steam_sh_explicit(confirm: bool = False) -> Dict[str, Any]:
    """Insert the SLSsteam LD_AUDIT export into steam.sh. DESTRUCTIVE.

    Requires confirm=True. Backs up steam.sh first. This is intentionally NOT
    called by get_platform_summary() or any status path — only by an explicit
    user action that has been warned about the risk. The SLSsteam installer
    itself normally does this; prefer letting it do so.
    """
    if not confirm:
        return {"patched": False, "error": "refused: explicit confirm=True required"}
    if not check_slssteam_installed():
        return {"patched": False, "error": "SLSsteam not installed"}

    root = find_steam_root()
    steam_sh = os.path.join(root, "steam.sh") if root else ""
    if not steam_sh or not os.path.isfile(steam_sh):
        return {"patched": False, "error": "steam.sh not found"}

    try:
        with open(steam_sh, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return {"patched": False, "error": f"read failed: {exc}"}

    if "LD_AUDIT" in content and "SLSsteam" in content:
        return {"patched": False, "already_ok": True, "error": None}

    sls_dir = get_slssteam_install_dir()
    so_path = os.path.join(sls_dir, "SLSsteam.so")
    if not os.path.isfile(so_path):
        return {"patched": False,
                "error": f"SLSsteam.so not found at {so_path}; refusing to "
                         f"write an LD_AUDIT path that would brick Steam"}

    try:
        import time
        backup = f"{steam_sh}.luatools-bak-{int(time.time())}"
        with open(backup, "w", encoding="utf-8") as f:
            f.write(content)
        lines = content.splitlines(keepends=True)
        # Insert right after the shebang, not at a fixed line number.
        insert_pos = 1 if (lines and lines[0].startswith("#!")) else 0
        lines.insert(insert_pos, f"export LD_AUDIT={so_path}\n")
        with open(steam_sh, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.log(f"linux_platform: patched steam.sh (backup: {backup})")
        return {"patched": True, "backup": backup, "error": None}
    except Exception as exc:
        return {"patched": False, "error": f"write failed: {exc}"}


# ---------------------------------------------------------------------------
# ACCELA — alternative Linux activation tool
# ---------------------------------------------------------------------------

_ACCELA_CANDIDATES = [
    os.path.expanduser("~/.local/share/ACCELA"),
    os.path.expanduser("~/accela"),
]


def get_accela_dir() -> Optional[str]:
    for path in _ACCELA_CANDIDATES:
        if os.path.isdir(path):
            return path
    return None


def check_accela_installed() -> bool:
    return get_accela_dir() is not None


# ---------------------------------------------------------------------------
# Activation-tool resolution — the Linux analogue of "is SteamTools present"
# ---------------------------------------------------------------------------

def detect_activation_tool() -> Dict[str, Any]:
    """Report which Linux activation tool is available.

    The plugin needs *some* tool that consumes config/stplug-in/*.lua.
    On Windows that is SteamTools; on Linux it is SLSsteam or ACCELA.
    """
    sls = check_slssteam_installed()
    accela = check_accela_installed()
    return {
        "slssteam": sls,
        "accela": accela,
        "anyAvailable": sls or accela,
        "preferred": "slssteam" if sls else ("accela" if accela else None),
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def open_directory(path: str) -> None:
    """Open a directory in the desktop file manager via xdg-open."""
    try:
        subprocess.Popen(
            ["xdg-open", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.warn(f"linux_platform: xdg-open failed: {exc}")


def get_platform_summary() -> Dict[str, Any]:
    """Diagnostics dict for logging / the settings UI."""
    summary: Dict[str, Any] = {
        "steamRoot": find_steam_root(),
        "stplugInDir": get_stplugin_dir(),
        "depotcacheDir": get_depotcache_dir(),
        "activationTool": detect_activation_tool(),
    }
    if summary["activationTool"]["slssteam"]:
        # READ-ONLY check — never writes to steam.sh.
        summary["slssteamInjection"] = check_slssteam_injection()
    return summary
