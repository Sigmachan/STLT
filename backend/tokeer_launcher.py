"""Tokeer auto-launcher integration for Denuvo-protected games.

Some Denuvo titles work via the Tokeer wrapper -- the game must be launched
through `tokeer_launcher.exe` instead of the default executable. Steam can
do this if launch options are set to:

    "<game install dir>\\<path>\\tokeer_launcher.exe" %command%

This module reads the per-user localconfig.vdf and writes the right launch
options for known Tokeer-compatible AppIDs. The list of (AppID -> Exe -> Name)
mappings is ported from RaiSantos's Devuvo.ps1 (2026-05 update).

Reference: https://github.com/RaiSantos/lt_api_links
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from logger import logger
from steam_utils import detect_steam_install_path


# ── Tokeer-compatible games registry (from Devuvo.ps1 2026-05) ────────────
# AppID -> {exe: relative path inside game folder, name: human-readable}

import sys as _sys
_IS_WINDOWS = _sys.platform.startswith("win")

def _linux_disabled_response(extra: str = "") -> str:
    """Standard JSON response for Tokeer-related calls on Linux."""
    import json as _json
    msg = ("Tokeer launchers are Windows executables. Denuvo-protected games "
           "on Linux run through Proton, which requires a different launch "
           "wrapper. Tokeer auto-configuration is disabled on Linux.")
    return _json.dumps({"success": False, "error": msg, "platform": "linux",
                        "shelved": True, "detail": extra})


_TOKEER_GAMES: Dict[int, Dict[str, str]] = {
    3357650: {"exe": "tokeer_launcher.exe",       "name": "Pragmata"},
    3764200: {"exe": "tokeer_launcher.exe",       "name": "Resident Evil Requiem"},
    2852190: {"exe": "tokeer_launcher.exe",       "name": "Monster Hunter Stories 3: Twisted Reflection"},
     629820: {"exe": "tokeer_launcher.exe",       "name": "Maneater"},
    1570010: {"exe": "tokeer_launcher.exe",       "name": "FAR: Changing Tides"},
     493340: {"exe": "tokeer_launcher.exe",       "name": "Planet Coaster"},
    3321460: {"exe": "tokeer_launcher.exe",       "name": "Crimson Desert"},
     637100: {"exe": "tokeer_launcher.exe",       "name": "Sonic Forces"},
    2688950: {"exe": "tokeer_launcher.exe",       "name": "Planet Coaster 2"},
    2358720: {"exe": "tokeer_launcher.exe",       "name": "Black Myth: Wukong"},
    3489700: {"exe": "tokeer_launcher.exe",       "name": "Stellar Blade"},
     287700: {"exe": "tokeer_launcher.exe",       "name": "METAL GEAR SOLID V: THE PHANTOM PAIN"},
     312660: {"exe": "tokeer_launcher.exe",       "name": "Sniper Elite 4"},
     594570: {"exe": "tokeer_launcher.exe",       "name": "Total War: WARHAMMER II"},
     626690: {"exe": "tokeer_launcher.exe",       "name": "Sword Art Online: Fatal Bullet"},
     668580: {"exe": "tokeer_launcher.exe",       "name": "Atomic Heart"},
     990080: {"exe": "tokeer_launcher.exe",       "name": "Hogwarts Legacy"},
    1029690: {"exe": "tokeer_launcher.exe",       "name": "Sniper Elite 5"},
    1142710: {"exe": "tokeer_launcher.exe",       "name": "Total War: WARHAMMER III"},
    1237320: {"exe": "tokeer_launcher.exe",       "name": "Sonic Frontiers"},
    1413480: {"exe": "tokeer_launcher.exe",       "name": "Shin Megami Tensei III Nocturne HD Remaster"},
    1687950: {"exe": "tokeer_launcher.exe",       "name": "Persona 5 Royal"},
    1693980: {"exe": "tokeer_launcher.exe",       "name": "Dead Space"},
    1844380: {"exe": "tokeer_launcher.exe",       "name": "Warhammer Age of Sigmar: Realms of Ruin"},
    1971870: {"exe": "tokeer_launcher.exe",       "name": "Mortal Kombat 1"},
    2161700: {"exe": "tokeer_launcher.exe",       "name": "Persona 3 Reload"},
    2375550: {"exe": "runtime\\media\\tokeer_launcher.exe",
                                                  "name": "Like a Dragon Gaiden: The Man Who Erased His Name"},
    2513280: {"exe": "tokeer_launcher.exe",       "name": "SONIC X SHADOW GENERATIONS"},
    3061810: {"exe": "runtime\\media\\tokeer_launcher.exe",
                                                  "name": "Like a Dragon: Pirate Yakuza in Hawaii"},
    3717070: {"exe": "tokeer_launcher.exe",       "name": "WWE 2K26"},
    1364780: {"exe": "tokeer_launcher.exe",       "name": "Street Fighter 6"},
    3059520: {"exe": "tokeer_launcher.exe",       "name": "F1 25"},
}


# ── Helpers ───────────────────────────────────────────────────────────────

def _localconfig_path(account_id32: int) -> str:
    base = detect_steam_install_path()
    if not base:
        return ""
    return os.path.join(base, "userdata", str(account_id32), "config", "localconfig.vdf")


def _find_game_install_dir(appid: int) -> str:
    """Find the actual install directory of a game by parsing appmanifest_*.acf."""
    from steam_utils import detect_steam_install_path
    base = detect_steam_install_path()
    if not base:
        return ""

    # Read libraryfolders.vdf -> list of library roots
    lf = os.path.join(base, "config", "libraryfolders.vdf")
    libraries: List[str] = [base]
    if os.path.isfile(lf):
        try:
            with open(lf, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', content):
                p = m.group(1).replace("\\\\", "\\")
                if os.path.isdir(p) and p not in libraries:
                    libraries.append(p)
        except Exception:
            pass

    for lib in libraries:
        acf = os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf")
        if not os.path.isfile(acf):
            continue
        try:
            with open(acf, "r", encoding="utf-8", errors="replace") as f:
                acf_text = f.read()
            m = re.search(r'"installdir"\s+"([^"]+)"', acf_text)
            if m:
                install_path = os.path.join(lib, "steamapps", "common", m.group(1))
                if os.path.isdir(install_path):
                    return install_path
        except Exception:
            continue
    return ""


def _find_launcher_exe(install_dir: str, relative_exe: str) -> str:
    """Locate tokeer_launcher.exe within install dir. Tries the hinted path first,
    then walks the directory tree (max depth 4) looking for tokeer_launcher.exe.
    """
    if not install_dir or not os.path.isdir(install_dir):
        return ""
    # Try the hint path first
    hinted = os.path.join(install_dir, relative_exe)
    if os.path.isfile(hinted):
        return hinted
    # Walk and find tokeer_launcher.exe
    target = os.path.basename(relative_exe).lower()
    base_depth = install_dir.count(os.sep)
    for root, dirs, files in os.walk(install_dir):
        if root.count(os.sep) - base_depth > 4:
            dirs[:] = []
            continue
        for fname in files:
            if fname.lower() == target:
                return os.path.join(root, fname)
    return ""


def _read_localconfig(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _write_localconfig(path: str, text: str) -> bool:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        logger.warn(f"LuaTools: localconfig.vdf write failed: {exc}")
        try: os.remove(tmp)
        except Exception: pass
        return False


def _set_launch_options(localconfig_text: str, appid: int, options: str) -> Tuple[str, str]:
    """Inject or replace "LaunchOptions" for a given appid in localconfig.vdf.

    Returns (new_text, action) where action is 'inserted', 'replaced', or 'unchanged'.

    localconfig.vdf structure (relevant section):
        "UserLocalConfigStore" { ...
            "Software" { "Valve" { "Steam" { "apps" {
                "<appid>" {
                    "LastPlayed" "..."
                    "LaunchOptions" "..."  <-- this is what we set
                    ...
                }
            } } } }
        }
    """
    if not localconfig_text:
        return localconfig_text, "no_file"

    # Find the apps block first
    apps_match = re.search(
        r'("apps"\s*\{)(.*?)(\n\s*\}\s*\n)',
        localconfig_text, re.DOTALL
    )
    if not apps_match:
        return localconfig_text, "no_apps_section"

    apps_body = apps_match.group(2)

    # Find this appid's block within apps
    appid_pattern = rf'("\s*{appid}\s*"\s*\{{)(.*?)(\n\s*\}}\s*\n)'
    appid_match = re.search(appid_pattern, apps_body, re.DOTALL)

    if appid_match:
        app_body = appid_match.group(2)
        lo_match = re.search(r'("LaunchOptions"\s*")[^"]*(")', app_body)
        if lo_match:
            current = re.search(r'"LaunchOptions"\s*"([^"]*)"', app_body)
            if current and current.group(1) == options:
                return localconfig_text, "unchanged"
            new_app_body = re.sub(
                r'("LaunchOptions"\s*")[^"]*(")',
                lambda _m: _m.group(1) + options + _m.group(2),
                app_body, count=1,
            )
            action = "replaced"
        else:
            new_app_body = app_body.rstrip("\n\t ") + f'\n\t\t\t\t\t"LaunchOptions"\t\t"{options}"\n\t\t\t\t'
            action = "inserted"

        new_apps_body = (
            apps_body[:appid_match.start(2)] + new_app_body + apps_body[appid_match.end(2):]
        )
    else:
        # AppID not yet in apps section -- add a fresh block
        new_apps_body = apps_body.rstrip("\n\t ") + (
            f'\n\t\t\t\t"{appid}"\n\t\t\t\t{{\n'
            f'\t\t\t\t\t"LaunchOptions"\t\t"{options}"\n'
            f'\t\t\t\t}}\n\t\t\t'
        )
        action = "inserted"

    new_text = (
        localconfig_text[:apps_match.start(2)] + new_apps_body + localconfig_text[apps_match.end(2):]
    )
    return new_text, action


# ── Public API ────────────────────────────────────────────────────────────

def list_tokeer_games(contentScriptQuery: str = "") -> str:
    """Return the full Tokeer compatibility list with installation status."""
    rows: List[Dict[str, Any]] = []
    for appid, meta in _TOKEER_GAMES.items():
        install_dir = _find_game_install_dir(appid)
        launcher = ""
        if install_dir:
            launcher = _find_launcher_exe(install_dir, meta["exe"])
        rows.append({
            "appid": appid,
            "name": meta["name"],
            "expectedExe": meta["exe"],
            "installed": bool(install_dir),
            "installDir": install_dir,
            "launcherFound": bool(launcher),
            "launcherPath": launcher,
            "ready": bool(launcher),
        })
    rows.sort(key=lambda r: (not r["installed"], not r["launcherFound"], r["name"]))
    return json.dumps({"success": True, "games": rows, "total": len(rows)})


def check_tokeer_status(appid: int, account_id32: int = 0,
                        contentScriptQuery: str = "") -> str:
    if not _IS_WINDOWS:
        return _linux_disabled_response()
    """Per-appid status: is it Tokeer-supported, installed, launcher present, configured?"""
    try:
        appid = int(appid)
        account_id32 = int(account_id32)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid or account_id"})

    meta = _TOKEER_GAMES.get(appid)
    if not meta:
        return json.dumps({
            "success": True,
            "supported": False,
            "message": "This AppID is not in the Tokeer-compatible games list.",
        })

    install_dir = _find_game_install_dir(appid)
    launcher = _find_launcher_exe(install_dir, meta["exe"]) if install_dir else ""

    current_options = ""
    if account_id32:
        lc_path = _localconfig_path(account_id32)
        lc_text = _read_localconfig(lc_path)
        if lc_text:
            apps_match = re.search(
                r'"apps"\s*\{(.+?)\n\s*\}\s*\n', lc_text, re.DOTALL
            )
            if apps_match:
                body = apps_match.group(1)
                a_match = re.search(
                    rf'"\s*{appid}\s*"\s*\{{(.+?)\n\s*\}}\s*\n', body, re.DOTALL
                )
                if a_match:
                    lo = re.search(r'"LaunchOptions"\s*"([^"]*)"', a_match.group(1))
                    if lo:
                        current_options = lo.group(1)

    expected_options = ""
    if launcher:
        expected_options = f'"{launcher}" %command%'

    configured = bool(current_options and "tokeer_launcher" in current_options.lower())

    return json.dumps({
        "success": True,
        "supported": True,
        "appid": appid,
        "name": meta["name"],
        "installed": bool(install_dir),
        "installDir": install_dir,
        "launcherFound": bool(launcher),
        "launcherPath": launcher,
        "configured": configured,
        "currentLaunchOptions": current_options,
        "recommendedLaunchOptions": expected_options,
        "needsAction": (bool(launcher) and not configured),
    })


def configure_tokeer_launch(appid: int, account_id32: int,
                            contentScriptQuery: str = "") -> str:
    if not _IS_WINDOWS:
        return _linux_disabled_response()
    """Write Tokeer launch options to localconfig.vdf for (appid, account).

    Pre-conditions:
        - AppID must be in _TOKEER_GAMES
        - Game must be installed
        - tokeer_launcher.exe must exist in the install dir
        - Steam must be closed (otherwise localconfig.vdf is overwritten on exit)
    """
    try:
        appid = int(appid)
        account_id32 = int(account_id32)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid or account_id"})

    meta = _TOKEER_GAMES.get(appid)
    if not meta:
        return json.dumps({"success": False, "error": "AppID is not Tokeer-supported"})

    # Steam-running guard
    try:
        from steam_version import _steam_is_running
        if _steam_is_running():
            return json.dumps({
                "success": False,
                "error": "Steam is running. Close it first -- otherwise Steam will "
                         "overwrite our launch options on exit.",
                "requiresSteamClose": True,
            })
    except Exception:
        pass

    install_dir = _find_game_install_dir(appid)
    if not install_dir:
        return json.dumps({"success": False,
                           "error": f"Game not installed (no appmanifest for {appid})"})

    launcher = _find_launcher_exe(install_dir, meta["exe"])
    if not launcher:
        return json.dumps({
            "success": False,
            "error": f"tokeer_launcher.exe not found inside '{install_dir}'. "
                     "Install Tokeer for this game first.",
            "expectedPath": os.path.join(install_dir, meta["exe"]),
        })

    lc_path = _localconfig_path(account_id32)
    if not os.path.isfile(lc_path):
        return json.dumps({"success": False,
                           "error": f"localconfig.vdf not found at {lc_path}. "
                                    "This account has never logged in here."})

    # Backup
    backup = lc_path + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    try:
        shutil.copy2(lc_path, backup)
    except Exception as exc:
        return json.dumps({"success": False,
                           "error": f"Failed to back up localconfig.vdf: {exc}"})

    lc_text = _read_localconfig(lc_path)
    options = f'"{launcher}" %command%'
    new_text, action = _set_launch_options(lc_text, appid, options)

    if action in ("no_file", "no_apps_section"):
        return json.dumps({"success": False, "error": f"localconfig.vdf parse: {action}"})

    if action == "unchanged":
        return json.dumps({
            "success": True,
            "action": "unchanged",
            "appid": appid,
            "launchOptions": options,
            "message": "Launch options already correct.",
        })

    if not _write_localconfig(lc_path, new_text):
        return json.dumps({"success": False, "error": "Write failed"})

    logger.log(
        f"LuaTools: Tokeer launch options ({action}) for {meta['name']} "
        f"(appid={appid}, account={account_id32}): {options}"
    )
    return json.dumps({
        "success": True,
        "action": action,
        "appid": appid,
        "name": meta["name"],
        "launcherPath": launcher,
        "launchOptions": options,
        "localconfigPath": lc_path,
        "backupPath": backup,
        "message": f"{'Replaced' if action == 'replaced' else 'Added'} launch options. "
                   "Start Steam to apply.",
    })


def remove_tokeer_launch(appid: int, account_id32: int,
                         contentScriptQuery: str = "") -> str:
    if not _IS_WINDOWS:
        return _linux_disabled_response()
    """Clear LaunchOptions for an appid (revert to defaults)."""
    try:
        appid = int(appid)
        account_id32 = int(account_id32)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid or account_id"})

    lc_path = _localconfig_path(account_id32)
    lc_text = _read_localconfig(lc_path)
    if not lc_text:
        return json.dumps({"success": False, "error": "localconfig.vdf not found"})

    new_text, action = _set_launch_options(lc_text, appid, "")
    if action == "unchanged":
        return json.dumps({"success": True, "message": "Launch options were already empty."})
    if not _write_localconfig(lc_path, new_text):
        return json.dumps({"success": False, "error": "Write failed"})
    return json.dumps({"success": True, "action": action, "message": "Launch options cleared."})
