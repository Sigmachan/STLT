"""LuaTools Mod System — plugin-within-plugin framework.

Based on Kite Loader architecture by nitaybl, reimplemented natively.
Scans mods/ directory for mod folders with manifest.json + mod.js.
Serves mod files to frontend, manages enable/disable state.
Compatible with Kite mod format for ecosystem compatibility.

Mod structure:
    mods/
        my-mod/
            manifest.json   {id, name, version, author, description, main, style, hooks, dependencies}
            mod.js           Main script (registered via LuaToolsMods.registerMod)
            style.css        Optional CSS
        single-file.js       Single-file mods also supported

API:
    GetModList()           → [{id, name, version, enabled, main, style, ...}]
    GetModFile(mod_id, filename) → file content string
    ToggleMod(mod_id, enabled)   → {success, mod_id, enabled}
    GetModLoaderInfo()     → {version, mods_dir, mod_count}
    InstallModFromUrl(url) → {success, mod_id}
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Dict, List, Optional

from logger import logger
from paths import get_plugin_dir
try:
    from security import MAX_ZIP_SIZE, safe_extract_archive, validate_zip_archive
except Exception:  # pragma: no cover - security.py is bundled with the plugin
    MAX_ZIP_SIZE = 100 * 1024 * 1024
    safe_extract_archive = None  # type: ignore
    validate_zip_archive = None  # type: ignore

MOD_LOADER_VERSION = "1.0.0"

_mods_dir: Optional[str] = None
_config_cache: Optional[Dict] = None
_config_mtime: float = 0

_SAFE_MOD_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _is_safe_mod_id(mod_id: str) -> bool:
    """Return True for simple folder-safe mod identifiers."""
    return bool(_SAFE_MOD_ID_RE.fullmatch(str(mod_id or "")))


def _path_is_within(base_dir: str, candidate: str) -> bool:
    try:
        base = os.path.normcase(os.path.realpath(base_dir))
        target = os.path.normcase(os.path.realpath(candidate))
        return os.path.commonpath([base, target]) == base
    except (OSError, ValueError):
        return False


def _is_safe_download_url(url: str) -> bool:
    """Reject local/file URLs and obvious localhost/private-IP SSRF cases."""
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
    except Exception:
        return False
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False

    host = parsed.hostname.strip().lower().rstrip(".")
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    except ValueError:
        pass
    return True


def _download_url_to_file(url: str, zip_path: str) -> Optional[str]:
    """Download a ZIP with a hard size cap. Returns an error string on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "LuaTools-ModLoader/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        try:
            content_length = int(resp.headers.get("Content-Length", "0") or "0")
        except Exception:
            content_length = 0
        if content_length > MAX_ZIP_SIZE:
            return f"Archive too large: {content_length} bytes"

        total = 0
        with open(zip_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ZIP_SIZE:
                    return f"Archive too large: {total} bytes"
                f.write(chunk)
    return None


def _get_mods_dir() -> str:
    global _mods_dir
    if _mods_dir is None:
        _mods_dir = os.path.join(get_plugin_dir(), "mods")
    os.makedirs(_mods_dir, exist_ok=True)
    return _mods_dir


def _config_path() -> str:
    return os.path.join(_get_mods_dir(), "mods_config.json")


def _load_config() -> Dict[str, bool]:
    """Load mod enable/disable config. Cached by mtime."""
    global _config_cache, _config_mtime
    path = _config_path()
    if not os.path.exists(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
        if _config_cache is not None and mtime == _config_mtime:
            return _config_cache
        with open(path, "r", encoding="utf-8") as f:
            _config_cache = json.load(f)
            _config_mtime = mtime
            return _config_cache
    except Exception:
        return {}


def _save_config(config: Dict[str, bool]) -> None:
    global _config_cache, _config_mtime
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    _config_cache = config
    _config_mtime = os.path.getmtime(path)


# ── Mod discovery ─────────────────────────────────────────────────────

def get_mod_list() -> str:
    """Scan mods/ directory and return JSON list of mods."""
    mods_dir = _get_mods_dir()
    config = _load_config()
    mods: List[Dict[str, Any]] = []

    if not os.path.exists(mods_dir):
        return json.dumps([])

    for entry in sorted(os.listdir(mods_dir)):
        if entry == "mods_config.json":
            continue

        entry_path = os.path.join(mods_dir, entry)

        # Single-file .js mods
        if os.path.isfile(entry_path) and entry.endswith(".js"):
            mod_id = entry[:-3]
            if not _is_safe_mod_id(mod_id):
                logger.warn(f"LuaTools: Skipping single-file mod {entry}: unsafe file name")
                continue
            mods.append({
                "id": mod_id,
                "name": mod_id,
                "version": "1.0.0",
                "author": "Unknown",
                "description": "Single-file mod",
                "main": entry,
                "style": None,
                "enabled": config.get(mod_id, True),
                "type": "single-file",
                "hooks": [],
                "dependencies": [],
            })

        # Folder mods with manifest.json
        elif os.path.isdir(entry_path):
            manifest_path = os.path.join(entry_path, "manifest.json")
            if not os.path.exists(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                mod_id = str(manifest.get("id", entry))
                if not _is_safe_mod_id(mod_id):
                    logger.warn(f"LuaTools: Skipping mod {entry}: unsafe mod id {mod_id!r}")
                    continue
                mods.append({
                    "id": mod_id,
                    "name": manifest.get("name", entry),
                    "version": manifest.get("version", "1.0.0"),
                    "author": manifest.get("author", "Unknown"),
                    "description": manifest.get("description", ""),
                    "main": manifest.get("main", "mod.js"),
                    "style": manifest.get("style"),
                    "enabled": config.get(mod_id, True),
                    "type": "folder",
                    "hooks": manifest.get("hooks", []),
                    "dependencies": manifest.get("dependencies", []),
                    "repository": manifest.get("repository", ""),
                    "minLuaToolsVersion": manifest.get("minLuaToolsVersion", ""),
                })
            except (json.JSONDecodeError, IOError) as exc:
                logger.warn(f"LuaTools: Skipping mod {entry}: bad manifest.json ({exc})")

    return json.dumps(mods)


def get_mod_file(mod_id: str, filename: str) -> str:
    """Read a mod file with path traversal protection."""
    if not _is_safe_mod_id(mod_id):
        return ""
    if ".." in filename:
        return ""
    # Allow subdirectory access in filename (e.g., "assets/icon.png") but sanitize
    filename = filename.replace("\\", "/")
    if filename.startswith("/") or ".." in filename:
        return ""

    mods_dir = _get_mods_dir()
    real_mods = os.path.realpath(mods_dir)

    # Try folder mod first: mods/{mod_id}/{filename}
    folder_path = os.path.join(mods_dir, mod_id, filename)
    real_target = os.path.realpath(folder_path)
    if _path_is_within(real_mods, real_target) and os.path.isfile(real_target):
        with open(real_target, "r", encoding="utf-8") as f:
            return f.read()

    # Try single-file: mods/{filename}
    if filename.endswith(".js"):
        single_path = os.path.join(mods_dir, filename)
        real_single = os.path.realpath(single_path)
        if _path_is_within(real_mods, real_single) and os.path.isfile(real_single):
            with open(real_single, "r", encoding="utf-8") as f:
                return f.read()

    return ""


def toggle_mod(mod_id: str, enabled: bool) -> str:
    """Enable or disable a mod."""
    if not _is_safe_mod_id(mod_id):
        return json.dumps({"success": False, "error": "Invalid mod_id"})
    config = _load_config()
    config[mod_id] = enabled
    _save_config(config)
    logger.log(f"LuaTools: Mod '{mod_id}' {'enabled' if enabled else 'disabled'}")
    return json.dumps({"success": True, "mod_id": mod_id, "enabled": enabled})


def get_mod_loader_info() -> str:
    """Return mod loader metadata."""
    mods_dir = _get_mods_dir()
    mod_count = 0
    if os.path.exists(mods_dir):
        for entry in os.listdir(mods_dir):
            if entry == "mods_config.json":
                continue
            ep = os.path.join(mods_dir, entry)
            if os.path.isdir(ep) and os.path.exists(os.path.join(ep, "manifest.json")):
                mod_count += 1
            elif os.path.isfile(ep) and entry.endswith(".js"):
                mod_count += 1

    return json.dumps({
        "version": MOD_LOADER_VERSION,
        "mods_dir": mods_dir,
        "mod_count": mod_count,
        "compatible_with": "kite-loader",
    })


# ── Mod installation from URL ─────────────────────────────────────────

def install_mod_from_url(url: str) -> str:
    """Download and install a mod from an HTTPS ZIP URL."""
    tmp_dir = ""
    try:
        url = str(url or "").strip()
        if not _is_safe_download_url(url):
            return json.dumps({
                "success": False,
                "error": "Only HTTPS mod ZIP URLs from public hosts are allowed",
            })

        mods_dir = _get_mods_dir()
        tmp_dir = tempfile.mkdtemp(prefix="ltmod_install_")
        zip_path = os.path.join(tmp_dir, "mod.zip")

        error = _download_url_to_file(url, zip_path)
        if error:
            return json.dumps({"success": False, "error": error})

        if validate_zip_archive is not None:
            with open(zip_path, "rb") as f:
                archive_bytes = f.read()
            is_valid, validation_error = validate_zip_archive(archive_bytes, "mod")
            if not is_valid:
                return json.dumps({"success": False, "error": validation_error or "Unsafe ZIP archive"})

        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(zip_path, "r") as zf:
            if safe_extract_archive is not None:
                safe_extract_archive(zf, extract_dir)
            else:
                zf.extractall(extract_dir)

        # Find manifest.json
        manifest = None
        mod_root = None
        for root, _dirs, files in os.walk(extract_dir):
            if "manifest.json" in files:
                with open(os.path.join(root, "manifest.json"), "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                mod_root = root
                break

        if not manifest or not mod_root:
            return json.dumps({"success": False, "error": "No manifest.json found in archive"})

        mod_id = str(manifest.get("id", "")).strip()
        if not _is_safe_mod_id(mod_id):
            return json.dumps({"success": False, "error": "manifest.json contains an invalid mod id"})

        dest = os.path.join(mods_dir, mod_id)
        if not _path_is_within(mods_dir, dest):
            return json.dumps({"success": False, "error": "Invalid mod destination"})

        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(mod_root, dest)

        logger.log(f"LuaTools: Installed mod '{mod_id}' from {url}")
        return json.dumps({"success": True, "mod_id": mod_id, "name": manifest.get("name", mod_id)})

    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

def uninstall_mod(mod_id: str) -> str:
    """Remove an installed mod."""
    if not _is_safe_mod_id(mod_id):
        return json.dumps({"success": False, "error": "Invalid mod_id"})
    mods_dir = _get_mods_dir()
    # Folder mod
    folder = os.path.join(mods_dir, mod_id)
    if os.path.isdir(folder) and _path_is_within(mods_dir, folder):
        shutil.rmtree(folder)
        logger.log(f"LuaTools: Uninstalled mod '{mod_id}'")
        return json.dumps({"success": True})
    # Single file
    single = os.path.join(mods_dir, f"{mod_id}.js")
    if os.path.isfile(single) and _path_is_within(mods_dir, single):
        os.remove(single)
        return json.dumps({"success": True})
    return json.dumps({"success": False, "error": "Mod not found"})
