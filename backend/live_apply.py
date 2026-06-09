"""Apply activations to a *running* Steam — no restart needed.

The recurring pain: activate a game, then restart Steam for it to download.
But the restart is mostly unnecessary on Linux. Here's the mechanism:

  - SLSsteam is injected into Steam at launch (LD_AUDIT) and supplies BOTH
    ownership grants AND depot keys *live* from the .lua at runtime — it
    intercepts Steam's API calls. So once the .lua is on disk, the data Steam
    needs is already available without restarting.
  - The only reason a freshly-activated game doesn't immediately download is
    that Steam caches your license/ownership list in memory and won't
    re-evaluate a game it already decided you don't own — until something pokes
    it. Opening `steam://install/<appid>` does exactly that: the running Steam
    re-checks ownership (SLSsteam answers "owned") and opens the download.

So this module hands `steam://install/<appid>` to the OS, which the running
Steam picks up — no kill/relaunch. We deliberately use the stable steam://
protocol (handed off via the OS, like xdg-open) rather than a reverse-
engineered, version-fragile SteamClient JS call.

IMPORTANT LIMITATION (stated honestly): things written to **config.vdf**
(Proton/compat-tool mappings, and config.vdf key injection) genuinely DO need
Steam closed, because Steam rewrites config.vdf on exit and clobbers external
edits made while it runs. This module cannot work around that — but on Linux
those are redundant when SLSsteam is injected, so activation+download does not
need them.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict, List

try:
    from logger import logger
except Exception:  # pragma: no cover
    class _L:
        def log(self, *a): pass
        def warn(self, *a): pass
        def error(self, *a): pass
    logger = _L()

_IS_WINDOWS = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"


def _open_url(url: str) -> bool:
    """Hand a URL (incl. steam:// protocol) to the OS. Returns True if the
    launcher was invoked without raising. Indirected so tests can stub it."""
    try:
        if _IS_WINDOWS:
            os.startfile(url)  # type: ignore[attr-defined]  # handles protocols
        elif _IS_MAC:
            subprocess.Popen(["open", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        logger.warn(f"live_apply: failed to open {url}: {exc}")
        return False


def _gather_warnings(appid: int) -> List[str]:
    """Best-effort, non-blocking prerequisite warnings (reuses the same checks
    as the health engine). We still fire the URL even if these warn — the
    handoff is harmless — but we tell the caller what might stop it working."""
    warnings: List[str] = []
    if _IS_WINDOWS:
        return warnings
    try:
        from linux_platform import detect_activation_tool, check_slssteam_installed, \
            check_slssteam_injection
        tool = detect_activation_tool()
        if not tool.get("anyAvailable"):
            warnings.append("No activation tool (SLSsteam/ACCELA) detected — the "
                            "game won't be seen as owned, so the download won't start.")
        elif check_slssteam_installed():
            inj = check_slssteam_injection()
            if not inj.get("injected"):
                warnings.append("SLSsteam is installed but not injected into steam.sh "
                                "— restart Steam via the installer so it hooks in.")
    except Exception:
        pass
    try:
        import slssteam_config as sc
        if sc.config_exists() and not sc.is_play_not_owned_enabled():
            warnings.append("SLSsteam PlayNotOwnedGames is OFF — unowned games won't "
                            "download. Enable it (Health Scan has a one-click fix).")
    except Exception:
        pass
    return warnings


def _setting_enabled(key: str, default: bool = True) -> bool:
    """Read a steamtools.general.<key> flag the same way the rest of the plugin
    does (default-on, overridable via the settings dict)."""
    try:
        from settings.manager import get_steamtools_settings
        return bool((get_steamtools_settings() or {}).get("general", {}).get(key, default))
    except Exception:
        return default


def auto_finalize_activation(appid: int) -> Dict[str, Any]:
    """One automatic outcome after activating a game: apply the safe, reversible
    setup it needs, then start the download on the running Steam — no restart,
    no manual checklist. Returns a single clear result.

    What it WILL auto-fix (safe, reversible): enable SLSsteam PlayNotOwnedGames
    (the #1 cause of 'won't download'). What it WON'T touch: steam.sh injection
    (destructive — needs the installer) and config.vdf (clobbered while Steam
    runs). If a hard blocker exists, it stops and says exactly what you must do.

    Returns:
        {success, appid, skipped?, autoFixed:[...], blocker?, downloadTriggered,
         message}
    """
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "invalid appid"}

    # Respect the opt-out (default on, like autoActivateLinux).
    if not _setting_enabled("autoStartDownload", True):
        return {"success": True, "skipped": True, "reason": "autoStartDownload disabled",
                "appid": appid, "message": "Auto-start is off; use the download button."}

    # 1. Must be activated.
    try:
        from steam_utils import has_lua_for_app
        if not has_lua_for_app(appid):
            return {"success": False, "appid": appid, "downloadTriggered": False,
                    "blocker": "no_lua",
                    "message": f"Activate {appid} first, then it can auto-download."}
    except Exception:
        pass

    auto_fixed: List[str] = []

    # 2. Hard blockers we cannot safely auto-fix (Linux).
    if not _IS_WINDOWS:
        try:
            from linux_platform import detect_activation_tool, check_slssteam_installed, \
                check_slssteam_injection
            tool = detect_activation_tool()
            if not tool.get("anyAvailable"):
                return {"success": False, "appid": appid, "downloadTriggered": False,
                        "blocker": "no_activation_tool", "autoFixed": auto_fixed,
                        "message": "No activation tool (SLSsteam/ACCELA) is installed. "
                                   "Run the enter-the-wired installer first — this is the "
                                   "one step that can't be automated safely."}
            if check_slssteam_installed() and not check_slssteam_injection().get("injected"):
                return {"success": False, "appid": appid, "downloadTriggered": False,
                        "blocker": "not_injected", "autoFixed": auto_fixed,
                        "message": "SLSsteam isn't injected into Steam yet. Re-run the "
                                   "installer once (editing steam.sh automatically is too "
                                   "risky to do for you)."}

            # 3. Safe auto-fix: enable PlayNotOwnedGames if it's the blocker.
            try:
                import slssteam_config as sc
                if check_slssteam_installed() and sc.config_exists() \
                        and not sc.is_play_not_owned_enabled():
                    sc.set_play_not_owned(True)  # returns None; verify by read-back
                    if sc.is_play_not_owned_enabled():
                        auto_fixed.append("Enabled SLSsteam PlayNotOwnedGames")
                        logger.log("live_apply: auto-enabled PlayNotOwnedGames")
            except Exception as exc:
                logger.warn(f"live_apply: PlayNotOwnedGames auto-fix skipped: {exc}")
        except Exception as exc:
            logger.warn(f"live_apply: prerequisite check skipped: {exc}")

    # 4. Start the download. Two mechanisms, picked by what's installed:
    #    - ACCELA present: the bundle was already handed to ACCELA during
    #      activation, so ACCELA is downloading. Don't also fire steam://install
    #      (it would pop a redundant Steam dialog).
    #    - SLSsteam-only: poke Steam via steam://install so it re-checks
    #      ownership (SLSsteam answers "owned") and downloads.
    accela = False
    try:
        import accela_launcher
        accela = accela_launcher.is_available()
    except Exception:
        accela = False

    if accela:
        msg = (f"ACCELA is downloading {appid} — no restart needed.")
        if auto_fixed:
            msg = "Auto-setup: " + "; ".join(auto_fixed) + ". " + msg
        return {
            "success": True, "appid": appid, "autoFixed": auto_fixed,
            "downloadTriggered": True, "downloader": "accela",
            "warnings": [], "message": msg,
        }

    trig = trigger_steam_install(appid)
    msg = trig.get("message", "")
    if auto_fixed:
        msg = "Auto-setup: " + "; ".join(auto_fixed) + ". " + msg
    return {
        "success": bool(trig.get("success")),
        "appid": appid,
        "autoFixed": auto_fixed,
        "downloadTriggered": bool(trig.get("triggered")),
        "downloader": "slssteam",
        "steam_running": trig.get("steam_running"),
        "warnings": trig.get("warnings", []),
        "message": msg or trig.get("message", ""),
    }


def trigger_steam_install(appid: int) -> Dict[str, Any]:
    """Ask a running Steam to start downloading an activated game — no restart.

    Returns:
        {success, triggered, appid, steam_running, hasLua, warnings, message}
    """
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "invalid appid"}

    # 1. The .lua must be installed, or there's nothing for SLSsteam to serve.
    has_lua = False
    try:
        from steam_utils import has_lua_for_app
        has_lua = bool(has_lua_for_app(appid))
    except Exception as exc:
        logger.warn(f"live_apply: has_lua_for_app failed: {exc}")
    if not has_lua:
        return {
            "success": False, "triggered": False, "appid": appid, "hasLua": False,
            "message": f"No activation (.lua) installed for {appid} yet — activate "
                       f"the game first, then start the download.",
        }

    # 2. Is Steam running? (Informational — the URL works either way: if Steam
    #    is closed the OS will start it, which also injects SLSsteam.)
    steam_running = False
    try:
        from steam_version import _steam_is_running
        steam_running = bool(_steam_is_running())
    except Exception:
        pass

    # 3. Collect non-blocking prerequisite warnings.
    warnings = _gather_warnings(appid)

    # 4. Hand the install URL to the OS. The running Steam re-checks ownership
    #    (SLSsteam answers "owned") and opens the download — no restart.
    url = f"steam://install/{appid}"
    triggered = _open_url(url)
    if not triggered:
        return {
            "success": False, "triggered": False, "appid": appid,
            "steam_running": steam_running, "hasLua": True, "warnings": warnings,
            "message": f"Could not hand {url} to the OS. Open it manually, or use "
                       f"Smart Restart as a fallback.",
        }

    if steam_running:
        msg = (f"Asked the running Steam to install {appid} — no restart needed. "
               f"Confirm in the install dialog Steam just opened.")
    else:
        msg = (f"Steam wasn't running, so it's being started for {appid}; the "
               f"install dialog will appear once it's up.")
    if warnings:
        msg += " Note: " + " ".join(warnings)

    logger.log(f"live_apply: triggered {url} (steam_running={steam_running}, "
               f"warnings={len(warnings)})")
    return {
        "success": True, "triggered": True, "appid": appid,
        "steam_running": steam_running, "hasLua": True, "warnings": warnings,
        "message": msg,
    }
