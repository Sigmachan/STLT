"""Account-to-account game-data transfer.

Solves the friction of switching Steam accounts just to pick up a Denuvo
activation token or save file: copies the userdata folder of a specific
appid from one logged-in account to another, in-place.

Steam stores per-game per-account state under:
    <Steam>/userdata/<accountId32>/<appid>/

That folder typically contains:
    - remote/        cloud-synced saves (Denuvo activation slips, profile data)
    - remotecache.vdf
    - 7/             local-only blob (sometimes)

Both source and destination must be already logged in at least once
(i.e. have a folder in <Steam>/userdata).

This module is *purely file-system* — Steam protocol is not involved.
Both Steam clients must be CLOSED at the time of transfer to avoid the
destination overwriting our copy on shutdown.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from logger import logger
from steam_utils import detect_steam_install_path
from steamtools import _get_active_account_ids  # reuses loginusers.vdf parser


def _userdata_dir() -> str:
    base = detect_steam_install_path()
    return os.path.join(base, "userdata") if base else ""


def _list_userdata_accounts() -> List[Dict[str, Any]]:
    """List actual on-disk userdata folders.

    Returns [{accountId32, path, sizeMB, appCount, hasGame(appid)}].
    More reliable than loginusers.vdf alone since accounts can have
    a userdata folder even if loginusers.vdf has been edited.
    """
    ud = _userdata_dir()
    if not ud or not os.path.isdir(ud):
        return []

    # Cross-reference with loginusers.vdf for friendly names
    name_map: Dict[int, Dict[str, Any]] = {}
    try:
        for acc in _get_active_account_ids():
            name_map[int(acc["accountId32"])] = acc
    except Exception:
        pass

    results: List[Dict[str, Any]] = []
    for entry in sorted(os.listdir(ud)):
        full = os.path.join(ud, entry)
        if not os.path.isdir(full):
            continue
        try:
            account_id32 = int(entry)
        except ValueError:
            continue

        try:
            apps = [a for a in os.listdir(full) if a.isdigit()]
        except Exception:
            apps = []

        size_bytes = 0
        for dp, _ds, files in os.walk(full):
            for f in files:
                try:
                    size_bytes += os.path.getsize(os.path.join(dp, f))
                except Exception:
                    pass

        meta = name_map.get(account_id32, {})
        results.append({
            "accountId32": account_id32,
            "path": full,
            "username": meta.get("username", ""),
            "personaName": meta.get("personaName", ""),
            "mostRecent": meta.get("mostRecent", False),
            "appCount": len(apps),
            "sizeMB": round(size_bytes / (1024 * 1024), 2),
            "apps": sorted(int(a) for a in apps),
        })
    return results


def _game_userdata_path(account_id32: int, appid: int) -> str:
    ud = _userdata_dir()
    return os.path.join(ud, str(account_id32), str(appid)) if ud else ""


def _dir_summary(path: str) -> Dict[str, Any]:
    """Quick metadata of a userdata/<acc>/<appid>/ folder."""
    if not os.path.isdir(path):
        return {"exists": False}
    files: List[Dict[str, Any]] = []
    total_size = 0
    for dp, _ds, fs in os.walk(path):
        for f in fs:
            fp = os.path.join(dp, f)
            try:
                sz = os.path.getsize(fp)
            except Exception:
                sz = 0
            total_size += sz
            rel = os.path.relpath(fp, path).replace("\\", "/")
            files.append({"name": rel, "sizeBytes": sz})
    files.sort(key=lambda x: -x["sizeBytes"])
    return {
        "exists": True,
        "path": path,
        "fileCount": len(files),
        "sizeBytes": total_size,
        "sizeMB": round(total_size / (1024 * 1024), 3),
        "files": files[:30],
    }


def list_accounts(contentScriptQuery: str = "") -> str:
    """Return all Steam accounts that have a userdata folder."""
    try:
        return json.dumps({"success": True, "accounts": _list_userdata_accounts()})
    except Exception as exc:
        logger.warn(f"LuaTools: list_accounts failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def inspect_game_data(account_id32: int, appid: int,
                      contentScriptQuery: str = "") -> str:
    """Inspect <Steam>/userdata/<accountId>/<appid>/ — what's inside, how big."""
    try:
        account_id32 = int(account_id32); appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid account or appid"})
    path = _game_userdata_path(account_id32, appid)
    return json.dumps({"success": True, "appid": appid,
                        "accountId32": account_id32, **_dir_summary(path)})


def transfer_game_data(from_account_id32: int, to_account_id32: int,
                       appid: int, overwrite: bool = False,
                       backup_dest: bool = True,
                       contentScriptQuery: str = "") -> str:
    """Copy <Steam>/userdata/<from>/<appid>/ into <Steam>/userdata/<to>/<appid>/.

    Useful for moving a Denuvo activation token, cloud save, or local profile
    between two of your own Steam accounts without re-logging-in.

    Args:
        from_account_id32: Source account (must have the appid folder)
        to_account_id32:   Destination account (target folder may be empty)
        appid:             Steam AppID of the game
        overwrite:         If destination has data, replace it (with backup)
        backup_dest:       Always create a .bak timestamped copy of destination
                            before overwrite (default True). Ignored if dest is empty.

    Pre-flight checks:
      - Steam must not be running (else the destination client will overwrite
        our copy on shutdown)
      - Both accounts must already have a userdata folder
    """
    try:
        from_id = int(from_account_id32)
        to_id   = int(to_account_id32)
        appid   = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid account or appid"})

    if from_id == to_id:
        return json.dumps({"success": False, "error": "Source and destination are the same account"})

    # Steam-running guard
    try:
        from steam_version import _steam_is_running
        if _steam_is_running():
            return json.dumps({
                "success": False,
                "error": "Steam is currently running. Please close Steam "
                         "completely before transferring -- otherwise it will "
                         "overwrite the transferred data on shutdown.",
                "requiresSteamClose": True,
            })
    except Exception:
        pass  # _steam_is_running missing -- proceed with warning

    src = _game_userdata_path(from_id, appid)
    dst = _game_userdata_path(to_id, appid)

    if not os.path.isdir(src):
        return json.dumps({
            "success": False,
            "error": f"Source has no data for appid {appid} at {src}",
        })

    # Ensure destination account folder itself exists
    dst_parent = os.path.dirname(dst)
    if not os.path.isdir(dst_parent):
        return json.dumps({
            "success": False,
            "error": f"Destination account {to_id} has never logged into "
                     "this Steam install. Log in once first.",
        })

    backup_path = ""
    if os.path.isdir(dst):
        if not overwrite:
            return json.dumps({
                "success": False,
                "error": f"Destination already has data for appid {appid}. "
                         "Pass overwrite=True (existing data will be backed up).",
                "destExists": True,
            })
        if backup_dest:
            ts = time.strftime("%Y%m%d-%H%M%S")
            backup_path = f"{dst}.bak-{ts}"
            try:
                shutil.move(dst, backup_path)
                logger.log(f"LuaTools: Backed up dest -> {backup_path}")
            except Exception as exc:
                return json.dumps({
                    "success": False,
                    "error": f"Could not back up destination: {exc}",
                })
        else:
            try:
                shutil.rmtree(dst)
            except Exception as exc:
                return json.dumps({
                    "success": False,
                    "error": f"Could not remove destination: {exc}",
                })

    # Copy src -> dst
    try:
        shutil.copytree(src, dst, dirs_exist_ok=False)
    except Exception as exc:
        # Try to restore backup
        if backup_path and os.path.isdir(backup_path):
            try:
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                shutil.move(backup_path, dst)
            except Exception:
                pass
        return json.dumps({"success": False, "error": f"Copy failed: {exc}"})

    # Verify
    summary = _dir_summary(dst)
    logger.log(
        f"LuaTools: Transferred appid={appid} from acc={from_id} to acc={to_id} "
        f"({summary.get('fileCount', 0)} files, {summary.get('sizeMB', 0)} MB)"
    )

    return json.dumps({
        "success": True,
        "appid": appid,
        "fromAccountId32": from_id,
        "toAccountId32": to_id,
        "filesCopied": summary.get("fileCount", 0),
        "sizeMB": summary.get("sizeMB", 0),
        "backupPath": backup_path,
        "destPath": dst,
    })


def restore_transfer_backup(account_id32: int, appid: int,
                            backup_path: str = "",
                            contentScriptQuery: str = "") -> str:
    """Restore the most recent .bak-* folder over current userdata.

    If backup_path is empty, picks the newest .bak-* matching the appid.
    """
    try:
        account_id32 = int(account_id32); appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid account or appid"})

    dst = _game_userdata_path(account_id32, appid)
    parent = os.path.dirname(dst)
    target_name = str(appid)

    if not backup_path:
        # Find newest .bak-* for this appid
        candidates: List[str] = []
        try:
            for entry in os.listdir(parent):
                if entry.startswith(f"{target_name}.bak-"):
                    candidates.append(os.path.join(parent, entry))
        except Exception:
            pass
        if not candidates:
            return json.dumps({"success": False,
                                "error": "No backups found for this appid"})
        candidates.sort(reverse=True)
        backup_path = candidates[0]

    if not os.path.isdir(backup_path):
        return json.dumps({"success": False, "error": "Backup not found"})

    try:
        if os.path.isdir(dst):
            ts = time.strftime("%Y%m%d-%H%M%S")
            shutil.move(dst, f"{dst}.pre-restore-{ts}")
        shutil.move(backup_path, dst)
    except Exception as exc:
        return json.dumps({"success": False, "error": f"Restore failed: {exc}"})

    return json.dumps({"success": True, "restored": dst, "from": backup_path})


def list_game_data_backups(contentScriptQuery: str = "") -> str:
    """List all .bak-* folders across all accounts."""
    ud = _userdata_dir()
    if not ud or not os.path.isdir(ud):
        return json.dumps({"success": False, "error": "userdata folder not found"})

    backups: List[Dict[str, Any]] = []
    try:
        for account in os.listdir(ud):
            acc_dir = os.path.join(ud, account)
            if not os.path.isdir(acc_dir):
                continue
            try:
                acc_id = int(account)
            except ValueError:
                continue
            try:
                for entry in os.listdir(acc_dir):
                    if ".bak-" not in entry and ".pre-restore-" not in entry:
                        continue
                    bak_path = os.path.join(acc_dir, entry)
                    if not os.path.isdir(bak_path):
                        continue
                    try:
                        appid_part = entry.split(".")[0]
                        bak_appid = int(appid_part)
                    except ValueError:
                        continue
                    try:
                        mtime = os.path.getmtime(bak_path)
                    except Exception:
                        mtime = 0
                    backups.append({
                        "accountId32": acc_id,
                        "appid": bak_appid,
                        "path": bak_path,
                        "name": entry,
                        "mtime": mtime,
                    })
            except (OSError, PermissionError):
                logger.warn(f"LuaTools: Unable to list backups in account {acc_id}")
                continue
    except Exception as exc:
        logger.error(f"LuaTools: list_game_data_backups failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})

    backups.sort(key=lambda b: -b["mtime"])
    return json.dumps({"success": True, "backups": backups})
