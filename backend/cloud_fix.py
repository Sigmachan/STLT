"""SteamTools Cloud-Save diagnostic (STFixer-inspired, read-only + safe).

Selectively11/STFixer fixes the SteamTools cloud-save problem by *binary
patching* SteamTools' hijack DLLs / encrypted payload cache. Reproducing
signature-scanning byte patching of third-party binaries from a plugin is
unsafe (wrong offsets corrupt SteamTools and user saves), so this module
deliberately implements only the **safe subset**:

  * read-only diagnosis of the SteamTools cloud-fix state in the Steam root
    (hijack DLLs xinput1_4.dll / dwmapi.dll, stella fallback remnants), and
  * optional, fully-reversible quarantine of the *obsolete* stella fallback
    files only — STFixer itself states these "are no longer needed and
    should be removed" now that the Morrenus API is gone.

For the actual binary remediation the report points the user to STFixer.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List

from logger import logger as _logger
from steam_utils import detect_steam_install_path

try:
    import Millennium  # type: ignore
except Exception:  # pragma: no cover
    Millennium = None  # type: ignore

# Known-good legit hashes of the SteamTools helper DLLs (from STFixer).
_KNOWN_GOOD = {
    "xinput1_4.dll": "ddb1f0909c7092f06890674f90b5d4f1198724b05b4bf1e656b4063897340243",
    "dwmapi.dll": "1ce49ed63af004ad37a4d2921a5659a17001c4c0026d6245fcc0d543e9c265d0",
}
_HIJACK_DLLS = ["xinput1_4.dll", "dwmapi.dll"]
_STELLA_REMNANTS = ["stella_fallback.dll", "stella.cfg"]
_STFIXER_URL = "https://github.com/Selectively11/STFixer"


def _steam_root() -> str:
    root = detect_steam_install_path()
    if not root and Millennium is not None:
        try:
            root = Millennium.steam_path()
        except Exception:
            root = ""
    return root or ""


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def diagnose_cloud_fix() -> str:
    """Read-only report of the SteamTools cloud-save / fallback state."""
    try:
        root = _steam_root()
        if not root or not os.path.isdir(root):
            return json.dumps({"success": False, "error": "Steam installation not found"})

        dlls: List[Dict[str, Any]] = []
        for name in _HIJACK_DLLS:
            p = os.path.join(root, name)
            if os.path.isfile(p):
                digest = _sha256(p)
                good = _KNOWN_GOOD.get(name, "")
                dlls.append({
                    "name": name,
                    "present": True,
                    "sha256": digest,
                    "isKnownGood": bool(digest) and digest == good,
                })
            else:
                dlls.append({"name": name, "present": False})

        stella = [
            {"name": n, "present": os.path.isfile(os.path.join(root, n))}
            for n in _STELLA_REMNANTS
        ]
        stella_present = any(s["present"] for s in stella)
        httpcache = os.path.join(root, "appcache", "httpcache", "3b")
        st_exe = os.path.isfile(os.path.join(root, "SteamTools.exe"))

        hijack_present = any(d.get("present") for d in dlls)
        suspicious = any(d.get("present") and not d.get("isKnownGood", False) for d in dlls)

        if stella_present:
            verdict = "obsolete_fallback_present"
            recommendation = (
                "Obsolete Morrenus/stella fallback remnants found. They are no "
                "longer needed and can break cloud saves — use 'Quarantine "
                "stella fallback' below (reversible), or run STFixer."
            )
        elif suspicious:
            verdict = "modified_hijack_dll"
            recommendation = (
                "A SteamTools hijack DLL differs from the known-good build. "
                f"Run STFixer ({_STFIXER_URL}) to repair binary patches — "
                "this plugin does not binary-patch for safety."
            )
        elif hijack_present:
            verdict = "ok_known_good"
            recommendation = "SteamTools cloud helper DLLs look healthy."
        else:
            verdict = "no_steamtools_cloud_layer"
            recommendation = "No SteamTools cloud hijack layer detected."

        return json.dumps({
            "success": True,
            "steamPath": root,
            "verdict": verdict,
            "recommendation": recommendation,
            "hijackDlls": dlls,
            "stellaRemnants": stella,
            "stellaFallbackPresent": stella_present,
            "httpCacheDirExists": os.path.isdir(httpcache),
            "steamToolsExePresent": st_exe,
            "stfixerUrl": _STFIXER_URL,
            "binaryPatching": False,
        })
    except Exception as exc:
        _logger.error(f"CloudFix: diagnose failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def remove_stella_fallback() -> str:
    """Quarantine obsolete stella fallback files (reversible).

    Files are MOVED into <Steam>/luatools_cloudfix_backup/<timestamp>/ so the
    action can be undone manually. Nothing is binary-patched or deleted.
    """
    try:
        root = _steam_root()
        if not root or not os.path.isdir(root):
            return json.dumps({"success": False, "error": "Steam installation not found"})

        targets = [
            os.path.join(root, n) for n in _STELLA_REMNANTS
            if os.path.isfile(os.path.join(root, n))
        ]
        if not targets:
            return json.dumps({
                "success": True,
                "moved": [],
                "message": "No stella fallback remnants present — nothing to do.",
            })

        backup_dir = os.path.join(
            root, "luatools_cloudfix_backup", time.strftime("%Y%m%d-%H%M%S")
        )
        os.makedirs(backup_dir, exist_ok=True)

        moved: List[str] = []
        for src in targets:
            dst = os.path.join(backup_dir, os.path.basename(src))
            shutil.move(src, dst)
            moved.append(os.path.basename(src))
            _logger.log(f"CloudFix: quarantined {os.path.basename(src)} -> {dst}")

        return json.dumps({
            "success": True,
            "moved": moved,
            "backupDir": backup_dir,
            "message": "Stella fallback quarantined. Restart Steam. Restore "
                       "from the backup folder if anything misbehaves.",
        })
    except PermissionError:
        return json.dumps({
            "success": False,
            "error": "Permission denied — Steam may be running; close it and retry.",
        })
    except Exception as exc:
        _logger.error(f"CloudFix: remove_stella_fallback failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})
