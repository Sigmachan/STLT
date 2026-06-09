"""First-run setup assistant — the "You're all set" moment.

Apple-style setup: on first run (or when something's blocking downloads), check
the environment once, silently apply the safe fixes, and surface the single
thing the user must do themselves — never a wall of checkboxes.

It reuses the health engine and sorts its findings into two buckets:
  - auto-fixable: safe, reversible fixes we apply for the user (enable
    PlayNotOwnedGames, self-heal the UI).
  - blockers: things we refuse to automate because they're destructive or
    out of our hands (install/inject SLSsteam — that's the one manual step).

A tiny marker file records that setup has been seen, so we don't nag.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

try:
    from logger import logger
except Exception:  # pragma: no cover
    class _L:
        def log(self, *a): pass
        def warn(self, *a): pass
        def error(self, *a): pass
    logger = _L()

from paths import data_path

_MARKER = ".setup_seen"
# Fixes we're willing to apply automatically (safe + reversible).
_SAFE_FIX_IPCS = {"SetSlssteamPlayNotOwned", "SelfHealUI"}


def _marker_path() -> str:
    return data_path(_MARKER)


def has_seen_setup() -> bool:
    return os.path.isfile(_marker_path())


def mark_setup_seen() -> bool:
    try:
        with open(_marker_path(), "w", encoding="utf-8") as f:
            f.write("1")
        return True
    except Exception as exc:
        logger.warn(f"setup_assistant: could not write marker: {exc}")
        return False


def _apply_safe_fix(ipc: str, args: Dict[str, Any]) -> bool:
    try:
        if ipc == "SetSlssteamPlayNotOwned":
            import slssteam_config as sc
            sc.set_play_not_owned(bool(args.get("enabled", True)))
            return True
        if ipc == "SelfHealUI":
            import ui_injector as ui
            ui.ensure_ui_injection()
            return True
    except Exception as exc:
        logger.warn(f"setup_assistant: fix {ipc} failed: {exc}")
    return False


def _classify(report: Dict[str, Any]):
    """Split failing checks into auto-fixable vs blockers."""
    auto_fixable: List[Dict[str, Any]] = []
    blockers: List[Dict[str, Any]] = []
    for c in report.get("checks", []):
        if c.get("status") != "fail":
            continue
        fix = c.get("fix") or {}
        ipc = fix.get("ipc")
        if ipc in _SAFE_FIX_IPCS:
            auto_fixable.append({"id": c["id"], "label": c["label"],
                                 "ipc": ipc, "args": fix.get("args") or {}})
        else:
            blockers.append({
                "id": c["id"], "label": c["label"], "detail": c.get("detail", ""),
                "command": (fix.get("args") or {}).get("command"),
            })
    return auto_fixable, blockers


def get_setup_state() -> Dict[str, Any]:
    """Snapshot of whether the user is ready, what we can auto-fix, and what
    they must do themselves."""
    try:
        from health import run_health_check
        report = run_health_check()
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    auto_fixable, blockers = _classify(report)
    return {
        "success": True,
        "firstRun": not has_seen_setup(),
        "ready": report.get("overall") != "fail",
        "overall": report.get("overall"),
        "summary": report.get("summary"),
        "platform": report.get("platform"),
        "autoFixable": auto_fixable,
        "blockers": blockers,
    }


def run_setup() -> Dict[str, Any]:
    """Apply the safe fixes, then return the fresh state."""
    applied: List[str] = []
    try:
        from health import run_health_check
        report = run_health_check()
        auto_fixable, _ = _classify(report)
        for fx in auto_fixable:
            if _apply_safe_fix(fx["ipc"], fx["args"]):
                applied.append(fx["label"])
                logger.log(f"setup_assistant: auto-applied {fx['label']}")
    except Exception as exc:
        logger.warn(f"setup_assistant: run_setup error: {exc}")

    state = get_setup_state()
    state["applied"] = applied
    return state


def self_heal() -> Dict[str, Any]:
    """Quietly maintain the setup the user already established — runs on load.

    DELIBERATELY CONSERVATIVE: it only re-applies state the user already chose,
    and only touches things that are safe and reversible (SLSsteam's OWN
    config, plugin-owned directories). It NEVER modifies Steam's files
    (steam.sh / config.vdf / steamui) automatically — those stay user-confirmed
    via the assistant. No-op until setup has been completed once, so first-run
    is left to the guided assistant.

    Returns {success, ran, healed:[...]}.
    """
    healed: List[str] = []
    if not has_seen_setup():
        return {"success": True, "ran": False, "healed": healed}

    # Re-enable PlayNotOwnedGames if it regressed (writes SLSsteam's own yaml).
    try:
        import slssteam_config as sc
        from linux_platform import check_slssteam_installed
        if check_slssteam_installed() and sc.config_exists() \
                and not sc.is_play_not_owned_enabled():
            sc.set_play_not_owned(True)
            if sc.is_play_not_owned_enabled():
                healed.append("Re-enabled PlayNotOwnedGames")
                logger.log("setup_assistant: self-heal re-enabled PlayNotOwnedGames")
    except Exception as exc:
        logger.warn(f"setup_assistant: self-heal PlayNotOwnedGames skipped: {exc}")

    # Ensure the plugin-owned stplug-in directory exists (harmless to recreate).
    try:
        from linux_platform import get_stplugin_dir
        d = get_stplugin_dir()
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            healed.append("Recreated stplug-in directory")
            logger.log("setup_assistant: self-heal recreated stplug-in dir")
    except Exception as exc:
        logger.warn(f"setup_assistant: self-heal dir check skipped: {exc}")

    return {"success": True, "ran": True, "healed": healed}
