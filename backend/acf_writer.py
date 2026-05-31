"""ACF and config.vdf writers for LuaTools.

Ported from SteaMidra (SFF) with adaptations for the LuaTools architecture.
Provides:
  - ACF file creation/patching for Linux activation
  - Depot key injection into config.vdf
  - Workshop ACF patching to prevent "NO INTERNET CONNECTION"
  - ACF error state clearing

All operations are best-effort and never block the main download flow.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from logger import logger
from paths import data_path
from steam_utils import _parse_vdf_simple, detect_steam_install_path


# ── VDF helpers ──────────────────────────────────────────────────────────────

def _vdf_dump(filepath: str, data: Dict[str, Any]) -> None:
    """Write a dict as VDF to a file. Simple key-value + nested dict support."""
    def _dump(obj: Any, indent: int = 0) -> str:
        prefix = "  " * indent
        if isinstance(obj, dict):
            if not obj:
                return "{}"
            lines = ["{\n"]
            for k, v in obj.items():
                lines.append(f'{prefix}  "{k}"')
                if isinstance(v, dict):
                    lines.append(" " + _dump(v, indent + 1))
                else:
                    lines.append(f' "{v}"')
            lines.append(f"{prefix}}}")
            return "".join(lines)
        return f'"{obj}"'

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(_dump(data))
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to write VDF {filepath}: {exc}")


def _vdf_load(filepath: str) -> Dict[str, Any]:
    """Load a VDF file into a dict."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return _parse_vdf_simple(f.read())
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to read VDF {filepath}: {exc}")
        return {}


def _enter_path(data: Dict[str, Any], *keys: str, mutate: bool = False,
                ignore_case: bool = False) -> Dict[str, Any]:
    """Navigate into nested VDF dict, creating intermediate dicts if mutate=True."""
    current = data
    for key in keys:
        # Handle case-insensitive lookup
        found_key = None
        if ignore_case:
            for k in current:
                if k.lower() == key.lower():
                    found_key = k
                    break
        else:
            found_key = key

        if found_key not in current:
            if mutate:
                current[found_key] = {}
            else:
                return {}
        current = current[found_key]
        if not isinstance(current, dict):
            return {}
    return current


# ── ACF Writer ───────────────────────────────────────────────────────────────

def _get_game_name(appid: int) -> str:
    """Fetch game name from applist cache or Steam API."""
    try:
        from downloads import _get_loaded_app_name, _fetch_app_name
        name = _get_loaded_app_name(appid)
        if name:
            return name
        name = _fetch_app_name(appid)
        if name:
            return name
    except Exception:
        pass
    return f"Game {appid}"


def _sanitize_filename(name: str) -> str:
    """Sanitize a game name for use as a directory name."""
    # Remove characters that are problematic in filenames
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    sanitized = sanitized.replace("'", "").strip()
    return sanitized if sanitized else ""


def write_acf(appid: int, steam_path: str, library_path: str = "",
              manifest_override: Optional[Dict[str, str]] = None,
              installdir: str = "") -> bool:
    """Write or update an appmanifest ACF file.

    Args:
        appid: Steam AppID
        steam_path: Steam installation path
        library_path: Library path (defaults to steam_path)
        manifest_override: Dict of depot_id -> manifest_id
        installdir: Custom install directory name

    Returns:
        True if ACF was written/patched successfully
    """
    if not library_path:
        library_path = steam_path

    acf_file = os.path.join(library_path, "steamapps", f"appmanifest_{appid}.acf")
    app_id_str = str(appid)
    app_name = _get_game_name(appid)

    # Determine install directory
    if not installdir:
        installdir = _sanitize_filename(app_name) or app_id_str

    # Check if ACF exists
    acf_exists = os.path.isfile(acf_file)
    if acf_exists:
        existing = _vdf_load(acf_file)
        app_state = existing.get("AppState", {})
        # If already properly configured, just patch error state
        if app_state.get("appid") == app_id_str:
            return patch_acf_error_state(acf_file)

    # Build ACF content
    app_state: Dict[str, Any] = {
        "appid": app_id_str,
        "Universe": "1",
        "name": app_name,
        "StateFlags": "4",
        "installdir": installdir,
        "LastUpdated": "0",
        "UpdateResult": "0",
        "SizeOnDisk": "0",
        "BytesToDownload": "0",
        "BytesDownloaded": "0",
    }

    if manifest_override:
        app_state["InstalledDepots"] = {
            str(depot_id): {"manifest": str(manifest_id), "size": "0"}
            for depot_id, manifest_id in manifest_override.items()
        }
        app_state["MountedDepots"] = {
            str(depot_id): str(manifest_id)
            for depot_id, manifest_id in manifest_override.items()
        }

    acf_contents = {"AppState": app_state}

    # Ensure steamapps directory exists
    steamapps_dir = os.path.join(library_path, "steamapps")
    os.makedirs(steamapps_dir, exist_ok=True)

    _vdf_dump(acf_file, acf_contents)
    logger.log(f"LuaTools: Wrote ACF to {acf_file}")
    return True


def patch_acf_error_state(acf_file: str) -> bool:
    """Clear stale error flags in an ACF file to prevent update loops.

    Fixes "NO INTERNET CONNECTION" and other update errors by clearing
    UpdateResult, FullValidateAfterNextUpdate, and related flags.
    """
    if not os.path.isfile(acf_file):
        return False

    try:
        data = _vdf_load(acf_file)
        app_state = data.get("AppState", {})
        patched = False

        clean_values = [
            ("UpdateResult", "0"),
            ("FullValidateAfterNextUpdate", "0"),
            ("ScheduledAutoUpdate", "0"),
            ("BytesToDownload", "0"),
            ("BytesDownloaded", "0"),
            ("BytesToStage", "0"),
            ("BytesStaged", "0"),
            ("StagingSize", "0"),
        ]

        for key, clean_val in clean_values:
            if app_state.get(key) != clean_val:
                app_state[key] = clean_val
                patched = True

        # Clear the "update required" flag (bit 4 = 16)
        try:
            flags = int(app_state.get("StateFlags", "0"))
            if flags & 16:
                app_state["StateFlags"] = str(flags & ~16)
                patched = True
        except (ValueError, TypeError):
            pass

        if patched:
            data["AppState"] = app_state
            _vdf_dump(acf_file, data)
            logger.log(f"LuaTools: Patched ACF error state in {acf_file}")
            return True
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to patch ACF error state: {exc}")

    return False


def patch_workshop_acf(appid: int, steam_path: str, library_path: str = "") -> bool:
    """Patch workshop ACF to clear NeedsDownload flag.

    Prevents "NO INTERNET CONNECTION" errors when Steam tries to download
    workshop content for non-owned games.
    """
    if not library_path:
        library_path = steam_path

    ws_acf = os.path.join(library_path, "steamapps", "workshop", f"appworkshop_{appid}.acf")
    if not os.path.isfile(ws_acf):
        return False

    try:
        data = _vdf_load(ws_acf)
        ws = data.get("AppWorkshop", {})

        needs_dl = ws.get("NeedsDownload", "0")
        size_on_disk = ws.get("SizeOnDisk", "0")

        if needs_dl != "1":
            return False

        # Only wipe when nothing is actually installed
        if size_on_disk not in ("0", ""):
            return False

        ws["NeedsDownload"] = "0"
        ws["NeedsUpdate"] = "0"

        # Clear workshop item details to prevent "Access Denied" failures
        if "WorkshopItemDetails" in ws:
            ws["WorkshopItemDetails"] = {}

        data["AppWorkshop"] = ws
        _vdf_dump(ws_acf, data)
        logger.log(f"LuaTools: Patched workshop ACF for {appid}")
        return True
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to patch workshop ACF: {exc}")

    return False


# ── Config VDF Writer ────────────────────────────────────────────────────────

def add_decryption_keys_to_config(steam_path: str,
                                  depot_keys: List[Tuple[str, str]]) -> int:
    """Add depot decryption keys to Steam's config.vdf.

    Args:
        steam_path: Steam installation path
        depot_keys: List of (depot_id, decryption_key) tuples

    Returns:
        Number of keys added
    """
    if not depot_keys:
        return 0

    vdf_file = os.path.join(steam_path, "config", "config.vdf")
    if not os.path.isfile(vdf_file):
        logger.warn(f"LuaTools: config.vdf not found at {vdf_file}")
        return 0

    # Backup config.vdf
    backup_file = vdf_file + ".luatools.bak"
    try:
        shutil.copy2(vdf_file, backup_file)
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to backup config.vdf: {exc}")

    try:
        data = _vdf_load(vdf_file)
        depots = _enter_path(data, "InstallConfigStore", "Software", "Valve",
                            "Steam", "depots", mutate=True, ignore_case=True)

        if not depots:
            logger.warn("LuaTools: Could not navigate to depots in config.vdf")
            return 0

        added = 0
        for depot_id, key in depot_keys:
            if not key:
                continue  # Skip stubs

            if depot_id not in depots:
                depots[depot_id] = {"DecryptionKey": key}
                added += 1
                logger.log(f"LuaTools: Added depot key for {depot_id} to config.vdf")
            else:
                logger.log(f"LuaTools: Depot {depot_id} already in config.vdf")

        if added:
            _vdf_dump(vdf_file, data)
            logger.log(f"LuaTools: Added {added} depot key(s) to config.vdf")

        return added
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to write to config.vdf: {exc}")
        # Restore backup on failure
        try:
            shutil.copy2(backup_file, vdf_file)
        except Exception:
            pass
        return 0


def remove_decryption_keys_from_config(steam_path: str,
                                       depot_ids: List[str]) -> int:
    """Remove depot decryption keys from Steam's config.vdf.

    Args:
        steam_path: Steam installation path
        depot_ids: List of depot IDs to remove

    Returns:
        Number of keys removed
    """
    vdf_file = os.path.join(steam_path, "config", "config.vdf")
    if not os.path.isfile(vdf_file):
        return 0

    # Backup config.vdf
    backup_file = vdf_file + ".luatools.bak"
    try:
        shutil.copy2(vdf_file, backup_file)
    except Exception:
        pass

    try:
        data = _vdf_load(vdf_file)
        depots = _enter_path(data, "InstallConfigStore", "Software", "Valve",
                            "Steam", "depots", mutate=True, ignore_case=True)

        if not depots:
            return 0

        removed = 0
        for depot_id in depot_ids:
            depot_str = str(depot_id)
            if depot_str in depots:
                del depots[depot_str]
                removed += 1

        if removed:
            _vdf_dump(vdf_file, data)
            logger.log(f"LuaTools: Removed {removed} depot key(s) from config.vdf")

        return removed
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to remove keys from config.vdf: {exc}")
        # Restore backup on failure
        try:
            shutil.copy2(backup_file, vdf_file)
        except Exception:
            pass
        return 0


# ── High-level activation helper ─────────────────────────────────────────────

def activate_game_on_linux(appid: int, depot_keys: List[Tuple[str, str]],
                          manifest_ids: Optional[Dict[str, str]] = None,
                          installdir: str = "") -> Dict[str, Any]:
    """Complete Linux activation: ACF + config.vdf + workshop patch.

    This is the main entry point for post-download activation on Linux.
    It handles everything Steam needs to recognize and download the game.

    Args:
        appid: Steam AppID
        depot_keys: List of (depot_id, decryption_key) tuples
        manifest_ids: Optional dict of depot_id -> manifest_id
        installdir: Optional custom install directory name

    Returns:
        Dict with success status and details of what was done
    """
    result = {
        "success": False,
        "acf_written": False,
        "keys_added": 0,
        "workshop_patched": False,
        "errors": [],
    }

    steam_path = detect_steam_install_path()
    if not steam_path:
        result["errors"].append("Steam path not found")
        return result

    # 1. Write ACF
    try:
        result["acf_written"] = write_acf(appid, steam_path,
                                          manifest_override=manifest_ids,
                                          installdir=installdir)
    except Exception as exc:
        result["errors"].append(f"ACF write failed: {exc}")

    # 2. Add keys to config.vdf
    try:
        result["keys_added"] = add_decryption_keys_to_config(steam_path, depot_keys)
    except Exception as exc:
        result["errors"].append(f"Config VDF write failed: {exc}")

    # 3. Patch workshop ACF
    try:
        result["workshop_patched"] = patch_workshop_acf(appid, steam_path)
    except Exception as exc:
        result["errors"].append(f"Workshop ACF patch failed: {exc}")

    # 4. Patch any existing ACF error state
    acf_file = os.path.join(steam_path, "steamapps", f"appmanifest_{appid}.acf")
    if os.path.isfile(acf_file):
        try:
            patch_acf_error_state(acf_file)
        except Exception as exc:
            result["errors"].append(f"ACF error state patch failed: {exc}")

    result["success"] = result["acf_written"] and result["keys_added"] > 0
    return result
