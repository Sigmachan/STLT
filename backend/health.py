"""LuaTools Ultimate — health & preflight diagnostic engine.

The plugin has many features but, until now, no single answer to the question
that causes the most pain: "is my setup actually correct, and if not, exactly
what is wrong and how do I fix it?" Every failure mode we know about —
PlayNotOwnedGames off, SLSsteam not injected, no activation tool, a keyless
.lua, no network to sources — fails *silently* and looks identical to the user
("it just doesn't download").

This module runs every prerequisite check, returns a structured, severity-ranked
report, and — crucially — attaches the exact fix (an IPC the frontend/CLI can
call) to each problem. It is read-only and side-effect-free: it diagnoses, it
never changes anything. Fixes are surfaced as suggestions, applied only on an
explicit user action.

Report shape:
    {
      "success": true,
      "overall": "ok" | "warn" | "fail",
      "summary": "1-line human summary",
      "checks": [ {id,label,status,detail,fix?}, ... ],
      "fixes":  [ {label, ipc, args}, ... ],   # ordered, deduped, actionable
      "generatedAt": <unix ts>,
      "platform": "linux" | "windows",
    }

status: ok | warn | fail | info | skip
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

try:
    from logger import logger
except Exception:  # pragma: no cover
    class _L:
        def log(self, *a): pass
        def warn(self, *a): pass
        def error(self, *a): pass
    logger = _L()

_IS_WINDOWS = sys.platform.startswith("win")

# Ordering of severities, worst-first, for rollups.
_SEV_ORDER = {"fail": 3, "warn": 2, "ok": 1, "info": 0, "skip": -1}


def _check(id_: str, label: str, status: str, detail: str = "",
           fix: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    c = {"id": id_, "label": label, "status": status, "detail": detail}
    if fix:
        c["fix"] = fix
    return c


# ── Individual checks ───────────────────────────────────────────────────────
# Each returns a check dict. They never raise; any internal error becomes a
# "warn" so the report is always complete.

def _chk_platform() -> Dict[str, Any]:
    return _check("platform", "Platform", "info",
                  "Windows (SteamTools)" if _IS_WINDOWS else "Linux (SLSsteam/ACCELA)")


def _chk_steam_root() -> Dict[str, Any]:
    try:
        from linux_platform import find_steam_root
        root = find_steam_root()
    except Exception:
        try:
            from steam_utils import detect_steam_install_path
            root = detect_steam_install_path()
        except Exception as exc:
            return _check("steam_root", "Steam installation", "warn",
                          f"could not detect: {exc}")
    if root and os.path.isdir(root):
        return _check("steam_root", "Steam installation", "ok", root)
    return _check("steam_root", "Steam installation", "fail",
                  "Steam install not found. Native Steam (not Flatpak/Snap) is required.")


def _chk_activation_tool() -> Dict[str, Any]:
    if _IS_WINDOWS:
        return _check("activation_tool", "Activation tool", "info",
                      "SteamTools (Windows) assumed.")
    try:
        from linux_platform import detect_activation_tool
        info = detect_activation_tool()
    except Exception as exc:
        return _check("activation_tool", "Activation tool", "warn",
                      f"detection failed: {exc}")
    if info.get("anyAvailable"):
        which = info.get("preferred")
        return _check("activation_tool", "Activation tool", "ok",
                      f"{which} detected")
    return _check(
        "activation_tool", "Activation tool", "fail",
        "Neither SLSsteam nor ACCELA found. Without one, .lua scripts do nothing "
        "and games never activate.",
        fix={"label": "How to install (enter-the-wired)",
             "ipc": None,
             "args": {"command": "curl -fsSL https://raw.githubusercontent.com/"
                                  "ciscosweater/enter-the-wired/main/enter-the-wired | bash"}},
    )


def _chk_slssteam_injection() -> Dict[str, Any]:
    if _IS_WINDOWS:
        return _check("slssteam_injection", "SLSsteam injection", "skip", "Windows")
    try:
        from linux_platform import check_slssteam_installed, check_slssteam_injection
    except Exception as exc:
        return _check("slssteam_injection", "SLSsteam injection", "warn", str(exc))
    if not check_slssteam_installed():
        # Not installed — covered by activation_tool check; ACCELA may be in use.
        return _check("slssteam_injection", "SLSsteam injection", "skip",
                      "SLSsteam not installed (ACCELA may be in use instead).")
    res = check_slssteam_injection()
    if res.get("injected"):
        return _check("slssteam_injection", "SLSsteam injection", "ok",
                      "steam.sh carries the LD_AUDIT hook.")
    return _check(
        "slssteam_injection", "SLSsteam injection", "fail",
        "SLSsteam is installed but not injected into steam.sh — Steam isn't being "
        "hooked, so activations are ignored. Re-run the enter-the-wired installer "
        "(it patches steam.sh correctly).",
        fix={"label": "Re-run enter-the-wired installer", "ipc": None,
             "args": {"command": "curl -fsSL https://raw.githubusercontent.com/"
                                  "ciscosweater/enter-the-wired/main/enter-the-wired | bash"}},
    )


def _chk_play_not_owned() -> Dict[str, Any]:
    if _IS_WINDOWS:
        return _check("play_not_owned", "SLSsteam PlayNotOwnedGames", "skip", "Windows")
    try:
        import slssteam_config as sc
    except Exception as exc:
        return _check("play_not_owned", "SLSsteam PlayNotOwnedGames", "warn", str(exc))
    if not sc.config_exists():
        return _check("play_not_owned", "SLSsteam PlayNotOwnedGames", "skip",
                      "SLSsteam config.yaml not found yet (created on first SLSsteam run).")
    if sc.is_play_not_owned_enabled():
        return _check("play_not_owned", "SLSsteam PlayNotOwnedGames", "ok", "Enabled.")
    return _check(
        "play_not_owned", "SLSsteam PlayNotOwnedGames", "fail",
        "PlayNotOwnedGames is OFF. Unowned games will NOT activate or download, no "
        "matter how correct the .lua is. This is the single most common cause of "
        "'it just won't download'.",
        fix={"label": "Enable PlayNotOwnedGames", "ipc": "SetSlssteamPlayNotOwned",
             "args": {"enabled": True}},
    )


def _chk_safe_mode() -> Dict[str, Any]:
    if _IS_WINDOWS:
        return _check("safe_mode", "SLSsteam SafeMode", "skip", "Windows")
    try:
        import slssteam_config as sc
        if not sc.config_exists():
            return _check("safe_mode", "SLSsteam SafeMode", "skip", "no config yet")
        if sc.is_safe_mode_enabled():
            return _check("safe_mode", "SLSsteam SafeMode", "warn",
                          "SafeMode is ON — limits SLSsteam features; disable if "
                          "activations behave oddly.")
        return _check("safe_mode", "SLSsteam SafeMode", "ok", "Off.")
    except Exception as exc:
        return _check("safe_mode", "SLSsteam SafeMode", "warn", str(exc))


def _chk_stplugin_dir() -> Dict[str, Any]:
    try:
        if _IS_WINDOWS:
            from steam_utils import detect_steam_install_path
            base = detect_steam_install_path() or ""
            d = os.path.join(base, "config", "stplug-in") if base else ""
        else:
            from linux_platform import get_stplugin_dir
            d = get_stplugin_dir() or ""
    except Exception as exc:
        return _check("stplugin_dir", "stplug-in directory", "warn", str(exc))
    if not d:
        return _check("stplugin_dir", "stplug-in directory", "fail",
                      "Could not resolve the stplug-in directory.")
    if os.path.isdir(d) and os.access(d, os.W_OK):
        return _check("stplugin_dir", "stplug-in directory", "ok", d)
    if os.path.isdir(d):
        return _check("stplugin_dir", "stplug-in directory", "fail",
                      f"{d} exists but is not writable.")
    return _check("stplugin_dir", "stplug-in directory", "warn",
                  f"{d} does not exist yet (created on first activation).")


def _chk_installed_lua() -> Dict[str, Any]:
    try:
        if _IS_WINDOWS:
            from steam_utils import detect_steam_install_path
            base = detect_steam_install_path() or ""
            d = os.path.join(base, "config", "stplug-in") if base else ""
        else:
            from linux_platform import get_stplugin_dir
            d = get_stplugin_dir() or ""
        n = 0
        if d and os.path.isdir(d):
            n = len([f for f in os.listdir(d) if f.endswith(".lua")])
        return _check("installed_lua", "Installed .lua scripts", "info",
                      f"{n} activated game(s).")
    except Exception as exc:
        return _check("installed_lua", "Installed .lua scripts", "info", str(exc))


def _chk_ui_injection() -> Dict[str, Any]:
    """Whether our self-heal marker is present. Not a failure if absent —
    Millennium may be loading the JS natively."""
    if _IS_WINDOWS:
        return _check("ui_injection", "UI self-heal", "skip", "Windows")
    try:
        import ui_injector as ui
        present = 0
        for root in ui._candidate_steam_roots():
            idx = os.path.join(root, "steamui", "index.html")
            if os.path.isfile(idx):
                try:
                    with open(idx, "r", encoding="utf-8", errors="ignore") as f:
                        if ui.MARKER_START in f.read():
                            present += 1
                except Exception:
                    pass
        if present:
            return _check("ui_injection", "UI self-heal", "ok",
                          f"Self-heal injection active in {present} root(s).")
        return _check("ui_injection", "UI self-heal", "info",
                      "Self-heal not applied (fine if Millennium loads the UI). "
                      "Run if the LuaTools button is missing.",
                      fix={"label": "Self-heal the Steam UI", "ipc": "SelfHealUI",
                           "args": {}})
    except Exception as exc:
        return _check("ui_injection", "UI self-heal", "info", str(exc))


def _chk_network() -> Dict[str, Any]:
    """Can we reach a manifest source? Quick, low-timeout."""
    try:
        import urllib.request
        req = urllib.request.Request("https://api.github.com/",
                                     headers={"User-Agent": "LuaTools-Health/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status < 500:
                return _check("network", "Network to sources", "ok",
                              "github.com reachable.")
    except Exception as exc:
        return _check("network", "Network to sources", "warn",
                      f"Could not reach github.com ({exc}). Sources may be blocked; "
                      f"a VPN/proxy may be needed.")
    return _check("network", "Network to sources", "warn", "Unexpected response.")


def _chk_python_deps() -> Dict[str, Any]:
    missing = []
    for mod in ("httpx", "bs4"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    if missing:
        return _check("python_deps", "Python dependencies", "fail",
                      f"Missing: {', '.join(missing)}. Install: pip install httpx "
                      f"beautifulsoup4 ruamel.yaml")
    return _check("python_deps", "Python dependencies", "ok", "httpx, bs4 present.")


def _chk_app(appid: int) -> List[Dict[str, Any]]:
    """Per-game checks: is it activated, and does its .lua actually carry keys?"""
    out: List[Dict[str, Any]] = []
    try:
        if _IS_WINDOWS:
            from steam_utils import detect_steam_install_path
            base = detect_steam_install_path() or ""
            d = os.path.join(base, "config", "stplug-in") if base else ""
        else:
            from linux_platform import get_stplugin_dir
            d = get_stplugin_dir() or ""
        lua = os.path.join(d, f"{appid}.lua") if d else ""
        if not lua or not os.path.isfile(lua):
            out.append(_check("app_activated", f"App {appid}: activated", "warn",
                              "No .lua installed for this app yet."))
            return out
        with open(lua, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        import re
        has_owner = bool(re.search(r"^\s*addappid\s*\(\s*\d+\s*\)", text, re.M))
        has_key = bool(re.search(r'addappid\s*\(\s*\d+\s*,\s*\d+\s*,\s*"[a-fA-F0-9]{64}"',
                                 text))
        out.append(_check("app_activated", f"App {appid}: .lua installed", "ok", lua))
        if has_owner:
            out.append(_check("app_ownership", f"App {appid}: ownership grant", "ok",
                              "Base addappid() present."))
        else:
            out.append(_check("app_ownership", f"App {appid}: ownership grant", "fail",
                              "No base addappid(<id>) line — game won't be marked owned. "
                              "Re-activate; do not strip keyless addappid lines."))
        if has_key:
            out.append(_check("app_keys", f"App {appid}: depot keys", "ok",
                              "At least one 64-char depot key present."))
        else:
            out.append(_check("app_keys", f"App {appid}: depot keys", "warn",
                              "No 64-char depot key found — depots may stay encrypted. "
                              "The source may not ship keys for this title."))
    except Exception as exc:
        out.append(_check("app_check", f"App {appid}", "warn", str(exc)))
    return out


# ── Aggregator ──────────────────────────────────────────────────────────────

def run_health_check(appid: Optional[int] = None) -> Dict[str, Any]:
    """Run every check and return a structured, actionable report."""
    checks: List[Dict[str, Any]] = [
        _chk_platform(),
        _chk_steam_root(),
        _chk_activation_tool(),
        _chk_slssteam_injection(),
        _chk_play_not_owned(),
        _chk_safe_mode(),
        _chk_stplugin_dir(),
        _chk_installed_lua(),
        _chk_ui_injection(),
        _chk_python_deps(),
        _chk_network(),
    ]
    if appid:
        try:
            checks.extend(_chk_app(int(appid)))
        except Exception:
            pass

    # Roll up worst severity among real checks (ignore info/skip).
    worst = "ok"
    for c in checks:
        s = c["status"]
        if s in ("fail", "warn") and _SEV_ORDER[s] > _SEV_ORDER[worst]:
            worst = s

    # Ordered, deduped fix list (fails first, then warns).
    fixes: List[Dict[str, Any]] = []
    seen = set()
    for sev in ("fail", "warn"):
        for c in checks:
            if c["status"] == sev and "fix" in c:
                key = (c["fix"].get("ipc"), str(c["fix"].get("args")))
                if key in seen:
                    continue
                seen.add(key)
                fixes.append({**c["fix"], "for": c["id"]})

    n_fail = sum(1 for c in checks if c["status"] == "fail")
    n_warn = sum(1 for c in checks if c["status"] == "warn")
    if worst == "ok":
        summary = "All prerequisites look good — activations should download normally."
    elif worst == "warn":
        summary = f"Mostly OK, {n_warn} warning(s) to review."
    else:
        summary = (f"{n_fail} blocking issue(s) found — games will not download until "
                   f"fixed. See the fix list.")

    return {
        "success": True,
        "platform": "windows" if _IS_WINDOWS else "linux",
        "overall": worst,
        "summary": summary,
        "checks": checks,
        "fixes": fixes,
        "generatedAt": int(time.time()),
    }


def render_text(report: Dict[str, Any]) -> str:
    """Human-readable rendering for the CLI."""
    icon = {"ok": "✓", "warn": "!", "fail": "✗", "info": "·", "skip": "–"}
    lines = [f"LuaTools Health — {report['overall'].upper()}", report["summary"], ""]
    for c in report["checks"]:
        lines.append(f"  [{icon.get(c['status'], '?')}] {c['label']}: {c['detail']}")
    if report["fixes"]:
        lines.append("")
        lines.append("Suggested fixes:")
        for i, fx in enumerate(report["fixes"], 1):
            how = fx.get("ipc") or (fx.get("args", {}).get("command", ""))
            lines.append(f"  {i}. {fx['label']}"
                         + (f"  ->  {how}" if how else ""))
    return "\n".join(lines)
