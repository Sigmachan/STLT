"""Steam client version manager.

Inspired by Selectively11/sm0k3r — the core, *safe* value: detect the
installed Steam client build, tell the user whether it is known to be
SteamTools-compatible, and (un)block Steam's self-update via the
well-documented ``steam.cfg`` mechanism so a SteamTools setup is not broken
by an automatic Steam update.

Deliberately NOT in scope (unsafe to automate from a plugin):
  * replacing Steam client binaries / depot downgrade
  * binary patching of any kind

Every write is reversible and the previous ``steam.cfg`` is backed up.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from logger import logger as _logger
from steam_utils import detect_steam_install_path

try:  # Millennium is only present at runtime
    import Millennium  # type: ignore
except Exception:  # pragma: no cover
    Millennium = None  # type: ignore

# ── Known SteamTools-compatible client builds ─────────────────────────────
# Derived from Selectively11/sm0k3r versions.json (build id == ClientVersion
# in steam.inf). Newest first. This is advisory data only.
KNOWN_COMPATIBLE_VERSIONS: List[Dict[str, str]] = [
    {"version": "1773426488", "label": "Mar 13 2026 — SteamTools compatible"},
    {"version": "1773099986", "label": "Mar 10 2026"},
    {"version": "1769025840", "label": "Jan 22 2026"},
    {"version": "1766451605", "label": "Dec 23 2025"},
    {"version": "1766177208", "label": "Dec 19 2025"},
    {"version": "1763795278", "label": "Nov 26 2025"},
]

_CFG_NAME = "steam.cfg"
_INF_NAME = "steam.inf"

# steam.cfg content that inhibits the bootstrapper self-update.
_BLOCK_CFG = "BootStrapperInhibitAll=enable\nBootStrapperForceSelfUpdate=disable\n"


def _steam_is_running() -> bool:
    """True if steam.exe is currently running (Windows tasklist)."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return "steam.exe" in (out.stdout or "").lower()
    except Exception:
        # If we cannot tell, be conservative and assume it is running so
        # the caller refuses to touch steam.cfg rather than risk corruption.
        return True


def _atomic_write(path: str, content: str) -> None:
    """Write text to *path* atomically (temp file in same dir + os.replace)."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".luatools-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


def _steam_root() -> Optional[str]:
    path = detect_steam_install_path()
    if not path and Millennium is not None:
        try:
            path = Millennium.steam_path()
        except Exception:
            path = None
    return path or None


def _read_steam_inf(steam_root: str) -> Dict[str, str]:
    """Parse <Steam>/steam.inf (simple ``key=value`` per line)."""
    info: Dict[str, str] = {}
    inf = os.path.join(steam_root, _INF_NAME)
    try:
        with open(inf, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or "=" not in line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                info[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    except Exception as exc:  # pragma: no cover
        _logger.warn(f"SteamVersion: failed to read steam.inf: {exc}")
    return info


def _cfg_blocks_updates(content: str) -> bool:
    lowered = content.lower()
    return "bootstrapperinhibitall=enable" in lowered.replace(" ", "")


def get_steam_version_info() -> str:
    """Report installed Steam build, update-block state and compatibility."""
    try:
        root = _steam_root()
        if not root or not os.path.isdir(root):
            return json.dumps({"success": False, "error": "Steam installation not found"})

        inf = _read_steam_inf(root)
        client_version = inf.get("ClientVersion") or inf.get("Clientversion") or ""
        package_version = inf.get("PackageVersion", "")

        cfg_path = os.path.join(root, _CFG_NAME)
        cfg_content = ""
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8", errors="ignore") as fh:
                    cfg_content = fh.read()
            except Exception:
                cfg_content = ""
        updates_blocked = _cfg_blocks_updates(cfg_content)

        compat_match = next(
            (v for v in KNOWN_COMPATIBLE_VERSIONS if v["version"] == client_version),
            None,
        )

        return json.dumps({
            "success": True,
            "steamPath": root,
            "clientVersion": client_version,
            "packageVersion": package_version,
            "updatesBlocked": updates_blocked,
            "isKnownCompatible": compat_match is not None,
            "compatibilityLabel": compat_match["label"] if compat_match else "",
            "knownCompatibleVersions": KNOWN_COMPATIBLE_VERSIONS,
            "steamCfgExists": os.path.isfile(cfg_path),
        })
    except Exception as exc:
        _logger.error(f"SteamVersion: get_steam_version_info failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def set_steam_update_block(enabled: bool) -> str:
    """Enable/disable Steam self-update by managing <Steam>/steam.cfg.

    The previous steam.cfg (if any) is backed up next to it before any
    modification, so the action is fully reversible.
    """
    try:
        root = _steam_root()
        if not root or not os.path.isdir(root):
            return json.dumps({"success": False, "error": "Steam installation not found"})

        # Refuse to touch steam.cfg while Steam is running: the change may
        # not take effect and a half-written cfg can confuse the client.
        if _steam_is_running():
            return json.dumps({
                "success": False,
                "error": "Steam is running — close Steam fully, then retry.",
                "steamRunning": True,
            })

        cfg_path = os.path.join(root, _CFG_NAME)
        backup_made = ""

        # Back up any existing steam.cfg once per change.
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8", errors="ignore") as fh:
                    existing = fh.read()
                backup_path = f"{cfg_path}.luatools-bak-{int(time.time())}"
                with open(backup_path, "w", encoding="utf-8") as fh:
                    fh.write(existing)
                backup_made = backup_path
            except Exception as exc:
                _logger.warn(f"SteamVersion: steam.cfg backup failed: {exc}")

        if enabled:
            _atomic_write(cfg_path, _BLOCK_CFG)
            _logger.log("SteamVersion: Steam auto-updates BLOCKED via steam.cfg")
            state = True
        else:
            # Disabling = remove our block. If the file is exactly our block
            # (or any block) we delete it; otherwise leave foreign content.
            if os.path.isfile(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8", errors="ignore") as fh:
                        cur = fh.read()
                except Exception:
                    cur = ""
                if _cfg_blocks_updates(cur):
                    os.remove(cfg_path)
                    _logger.log("SteamVersion: Steam auto-updates UNBLOCKED (steam.cfg removed)")
            state = False

        return json.dumps({
            "success": True,
            "updatesBlocked": state,
            "steamCfgPath": cfg_path,
            "backup": backup_made,
        })
    except PermissionError:
        return json.dumps({
            "success": False,
            "error": "Permission denied writing steam.cfg — run Steam/Millennium with sufficient rights",
        })
    except Exception as exc:
        _logger.error(f"SteamVersion: set_steam_update_block failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def list_steam_cfg_backups() -> str:
    """List steam.cfg backups created by this feature."""
    try:
        root = _steam_root()
        if not root:
            return json.dumps({"success": False, "error": "Steam installation not found"})
        backups = []
        for name in os.listdir(root):
            if name.startswith(f"{_CFG_NAME}.luatools-bak-"):
                full = os.path.join(root, name)
                backups.append({
                    "filename": name,
                    "path": full,
                    "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                    "mtime": int(os.path.getmtime(full)) if os.path.isfile(full) else 0,
                })
        backups.sort(key=lambda b: b["mtime"], reverse=True)
        return json.dumps({"success": True, "backups": backups})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
