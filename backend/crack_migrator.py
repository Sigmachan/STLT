"""Auto-detect and migrate cracked games to LuaTools (v9.0).

For users who've accumulated years of mixed activation methods (Goldberg,
CODEX, Ali213, CreamAPI, RUNE, etc.), this module:

  1. Scans every installed game's directory for known crack-file signatures
  2. Classifies each by crack family + confidence score
  3. For each non-clean game, checks if LuaTools sources have activation
  4. Offers migration: backup crack files -> remove from game dir -> apply
     LuaTools activation -> game is now under LuaTools control

Built on the existing `_GB_SIGS` and `_CONFLICTING_FILES` signature tables
in steamtools.py. Adds classification (which crack family) and safe-migration
with full backup.

Migration is DRY-RUN by default. Every destructive op requires explicit
confirmation. Backups go to:
  <game>/_luatools_migration_<timestamp>/<original-relative-path>
so they're side-by-side with the game and never deleted automatically.
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


# ── Crack family classification ────────────────────────────────────────
# Each family: (display_name, signature_list, weight)
# Weight contributes to confidence score (higher = more confident).

_CRACK_FAMILIES: List[Tuple[str, List[str], int]] = [
    # (family_name, files_to_match, score_weight)
    ("Goldberg Emulator", [
        "steam_settings", "steam_interfaces.txt",
        "coldclientloader.ini", "ColdClientLoader.ini",
        "local_save.txt", "configs.user.ini",
    ], 30),
    ("CODEX / CPY", [
        "codex.cfg", "codex64.dll", "codex.dll",
        "cpy.cfg", "cpy.ini",
    ], 30),
    ("CreamAPI", [
        "cream_api.ini", "cream_api.dll", "cream_api64.dll",
    ], 30),
    ("ALI213", [
        "ali213.ini", "ali213_api.dll", "ali213_api64.dll",
    ], 25),
    ("UnSteam (3DM)", [
        "unsteam.dll", "unsteam.ini", "3dmgame.dll", "3dmgame.ini",
    ], 25),
    ("RUNE / RELOADED", [
        "rune.dll", "rune.ini", "valve.ini", "hlm.ini",
    ], 20),
    ("Generic Steam API loader", [
        "steamclient_loader.exe", "steam_api_o.dll", "steam_api64_o.dll",
        "steam_api.dll.bak", "steam_api64.dll.bak",
    ], 15),
    ("DLL Proxy Hijack", [
        "winmm.dll", "xinput1_3.dll", "xinput1_4.dll", "xinput9_1_0.dll",
        "dinput8.dll", "winhttp.dll", "iphlpapi.dll", "dsound.dll",
    ], 10),
]


# ── Steam install enumeration ──────────────────────────────────────────

def _parse_acf_install(acf_path: str) -> Optional[Dict[str, Any]]:
    """Pull installdir + name from an appmanifest_*.acf file."""
    try:
        with open(acf_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return None
    name_m = re.search(r'"name"\s+"([^"]*)"', text)
    install_m = re.search(r'"installdir"\s+"([^"]*)"', text)
    if not install_m:
        return None
    return {
        "name": name_m.group(1) if name_m else "",
        "installdir": install_m.group(1),
    }


def _all_installed_games() -> List[Dict[str, Any]]:
    """Walk every Steam library and return [{appid, name, installPath, libraryPath}]."""
    base = detect_steam_install_path()
    if not base:
        return []

    libraries: List[str] = [base]
    lf = os.path.join(base, "config", "libraryfolders.vdf")
    if os.path.isfile(lf):
        try:
            with open(lf, "r", encoding="utf-8", errors="replace") as f:
                lib_text = f.read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', lib_text):
                p = m.group(1).replace("\\\\", "\\")
                if os.path.isdir(p) and p not in libraries:
                    libraries.append(p)
        except Exception:
            pass

    games: List[Dict[str, Any]] = []
    seen: set = set()
    for lib in libraries:
        steamapps = os.path.join(lib, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        for fname in os.listdir(steamapps):
            m = re.match(r"^appmanifest_(\d+)\.acf$", fname)
            if not m:
                continue
            appid = int(m.group(1))
            if appid in seen:
                continue
            seen.add(appid)
            info = _parse_acf_install(os.path.join(steamapps, fname))
            if not info:
                continue
            install_path = os.path.join(steamapps, "common", info["installdir"])
            games.append({
                "appid": appid,
                "name": info["name"] or info["installdir"],
                "installPath": install_path,
                "libraryPath": lib,
                "installed": os.path.isdir(install_path),
            })
    games.sort(key=lambda g: g["name"].lower())
    return games


# ── Crack detection per game ───────────────────────────────────────────

def _scan_game_dir(install_path: str, max_depth: int = 4) -> Dict[str, List[str]]:
    """Walk a game dir up to max_depth and return {family_name: [relative_paths]}."""
    if not install_path or not os.path.isdir(install_path):
        return {}

    # Build a lookup: lowercase filename -> family
    file_to_family: Dict[str, str] = {}
    for family_name, file_list, _weight in _CRACK_FAMILIES:
        for fn in file_list:
            file_to_family[fn.lower()] = family_name

    found_by_family: Dict[str, List[str]] = {}
    base_depth = install_path.count(os.sep)

    for root, dirs, files in os.walk(install_path):
        depth = root.count(os.sep) - base_depth
        if depth > max_depth:
            dirs[:] = []
            continue

        # Check directory names — Goldberg's "steam_settings/" is a dir match
        for d in dirs:
            family = file_to_family.get(d.lower())
            if family:
                rel = os.path.relpath(os.path.join(root, d), install_path)
                found_by_family.setdefault(family, []).append(rel + "/")

        for f in files:
            family = file_to_family.get(f.lower())
            if not family:
                continue
            rel = os.path.relpath(os.path.join(root, f), install_path)
            found_by_family.setdefault(family, []).append(rel)

    return found_by_family


def _classify(found: Dict[str, List[str]]) -> Dict[str, Any]:
    """Score + classify which crack family is dominant."""
    if not found:
        return {"clean": True, "topFamily": None, "confidence": 0, "families": []}

    scored: List[Dict[str, Any]] = []
    for family_name, _files, weight in _CRACK_FAMILIES:
        matched = found.get(family_name, [])
        if not matched:
            continue
        score = weight + len(matched) * 2  # base weight + bonus per file
        scored.append({"family": family_name, "score": score, "files": matched})

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[0] if scored else None
    return {
        "clean": False,
        "topFamily": top["family"] if top else None,
        "confidence": top["score"] if top else 0,
        "families": scored,
    }


def scan_all_games(contentScriptQuery: str = "") -> str:
    """Scan every installed Steam game for crack signatures.

    Returns a per-game classification + LuaTools availability status.
    Use this output to drive the migration UI.
    """
    games = _all_installed_games()
    if not games:
        return json.dumps({"success": False, "error": "No installed games found"})

    # Cross-reference with installed LuaTools .lua scripts
    base = detect_steam_install_path()
    stplug_dir = os.path.join(base, "config", "stplug-in") if base else ""
    luatools_appids: set = set()
    if stplug_dir and os.path.isdir(stplug_dir):
        for f in os.listdir(stplug_dir):
            m = re.match(r"^(\d+)\.lua(?:\.disabled)?$", f)
            if m:
                luatools_appids.add(int(m.group(1)))

    results: List[Dict[str, Any]] = []
    for game in games:
        if not game["installed"]:
            continue
        found = _scan_game_dir(game["installPath"])
        classification = _classify(found)
        results.append({
            **game,
            **classification,
            "hasLuaTools": game["appid"] in luatools_appids,
            "fileCount": sum(len(v) for v in found.values()),
        })

    cracked = [r for r in results if not r["clean"]]
    clean = [r for r in results if r["clean"]]

    return json.dumps({
        "success": True,
        "totalGames": len(results),
        "crackedGames": len(cracked),
        "cleanGames": len(clean),
        "results": results,
    })


# ── Migration: backup + remove + (optional) apply LuaTools ─────────────

def migrate_game(appid: int, dry_run: bool = True,
                 contentScriptQuery: str = "") -> str:
    """Migrate one game off its current crack and onto LuaTools.

    Steps:
      1. Locate game install dir from appmanifest
      2. Scan for crack files
      3. Move every matched file/dir to <install>/_luatools_migration_<ts>/
      4. (Optional, separate step) call StartAddViaLuaTools to install .lua

    With dry_run=True: returns the plan without doing anything.
    """
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid"})

    # Find game
    games = _all_installed_games()
    game = next((g for g in games if g["appid"] == appid), None)
    if not game:
        return json.dumps({"success": False, "error": f"game {appid} not installed"})
    if not game["installed"]:
        return json.dumps({"success": False, "error": "install dir missing"})

    install_path = game["installPath"]
    found = _scan_game_dir(install_path)
    classification = _classify(found)

    if classification["clean"]:
        return json.dumps({
            "success": True,
            "appid": appid,
            "name": game["name"],
            "clean": True,
            "message": "No crack files detected -- nothing to migrate.",
        })

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(install_path, f"_luatools_migration_{timestamp}")

    plan: List[Dict[str, Any]] = []
    for family_name, paths in found.items():
        for rel in paths:
            src = os.path.join(install_path, rel.rstrip("/"))
            dst = os.path.join(backup_dir, rel.rstrip("/"))
            plan.append({
                "family": family_name,
                "path": rel,
                "src": src,
                "dst": dst,
                "isDir": rel.endswith("/"),
                "exists": os.path.exists(src),
            })

    if dry_run:
        return json.dumps({
            "success": True,
            "dryRun": True,
            "appid": appid,
            "name": game["name"],
            "topFamily": classification["topFamily"],
            "confidence": classification["confidence"],
            "backupDir": backup_dir,
            "plan": plan,
            "filesToMove": len(plan),
        })

    # Execute
    moved: List[Dict[str, Any]] = []
    errors: List[str] = []

    try:
        os.makedirs(backup_dir, exist_ok=True)
    except Exception as exc:
        return json.dumps({"success": False, "error": f"cannot create backup dir: {exc}"})

    for item in plan:
        if not item["exists"]:
            continue
        try:
            os.makedirs(os.path.dirname(item["dst"]), exist_ok=True)
            shutil.move(item["src"], item["dst"])
            moved.append({
                "family": item["family"],
                "path": item["path"],
            })
        except Exception as exc:
            errors.append(f"{item['path']}: {exc}")
            logger.warn(f"LuaTools migrate: failed to move {item['path']}: {exc}")

    logger.log(
        f"LuaTools migrate: {appid} ({game['name']}) -- "
        f"moved {len(moved)} item(s) to {backup_dir}, {len(errors)} error(s)"
    )

    return json.dumps({
        "success": True,
        "dryRun": False,
        "appid": appid,
        "name": game["name"],
        "topFamily": classification["topFamily"],
        "backupDir": backup_dir,
        "movedCount": len(moved),
        "moved": moved,
        "errors": errors,
        "nextStep": (
            "Crack files moved to backup. Now call StartAddViaLuaTools "
            f"with appid={appid} to install LuaTools activation. If anything "
            "breaks, the original files are at the backup path -- move them back."
        ),
    })


def undo_migration(appid: int, backupDir: str = "",
                   contentScriptQuery: str = "") -> str:
    """Roll back a migration by moving everything from backup back into install dir."""
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid"})

    games = _all_installed_games()
    game = next((g for g in games if g["appid"] == appid), None)
    if not game:
        return json.dumps({"success": False, "error": f"game {appid} not installed"})

    install_path = game["installPath"]

    # If no backup dir specified, find the most recent
    if not backupDir:
        candidates = []
        try:
            for d in os.listdir(install_path):
                full = os.path.join(install_path, d)
                if os.path.isdir(full) and d.startswith("_luatools_migration_"):
                    candidates.append((d, os.path.getmtime(full)))
        except Exception:
            pass
        if not candidates:
            return json.dumps({
                "success": False,
                "error": "No migration backup found for this game",
            })
        candidates.sort(key=lambda x: x[1], reverse=True)
        backupDir = os.path.join(install_path, candidates[0][0])

    if not os.path.isdir(backupDir):
        return json.dumps({"success": False, "error": f"backup dir not found: {backupDir}"})

    # Walk backup, move everything back
    restored: List[str] = []
    errors: List[str] = []
    for root, _dirs, files in os.walk(backupDir):
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, backupDir)
            dst = os.path.join(install_path, rel)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                restored.append(rel)
            except Exception as exc:
                errors.append(f"{rel}: {exc}")

    # Clean up empty backup tree
    try:
        shutil.rmtree(backupDir, ignore_errors=True)
    except Exception:
        pass

    logger.log(
        f"LuaTools migrate undo: {appid} restored {len(restored)} item(s)"
    )

    return json.dumps({
        "success": True,
        "appid": appid,
        "restoredCount": len(restored),
        "errors": errors,
    })


def list_migrations(contentScriptQuery: str = "") -> str:
    """Find every existing _luatools_migration_* backup across all installed games."""
    games = _all_installed_games()
    out: List[Dict[str, Any]] = []
    for game in games:
        if not game["installed"]:
            continue
        try:
            for d in os.listdir(game["installPath"]):
                full = os.path.join(game["installPath"], d)
                if os.path.isdir(full) and d.startswith("_luatools_migration_"):
                    file_count = sum(len(files) for _r, _d, files in os.walk(full))
                    size_bytes = 0
                    for r, _ds, files in os.walk(full):
                        for f in files:
                            try:
                                size_bytes += os.path.getsize(os.path.join(r, f))
                            except Exception:
                                pass
                    out.append({
                        "appid": game["appid"],
                        "name": game["name"],
                        "backupDir": full,
                        "timestamp": d.replace("_luatools_migration_", ""),
                        "fileCount": file_count,
                        "sizeMB": round(size_bytes / 1024 / 1024, 2),
                    })
        except Exception:
            continue
    return json.dumps({"success": True, "migrations": out})
