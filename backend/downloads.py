"""Handling of LuaTools add/download flows and related utilities."""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import datetime
from typing import Any, Dict

import Millennium  # type: ignore

from api_manifest import load_api_manifest
from settings.manager import get_morrenus_api_key, get_ryuu_session, get_depotbox_sid, get_local_manifest_path, get_manifesthub_api_key, get_github_token
from config import (
    APPID_LOG_FILE,
    LOADED_APPS_FILE,
    USER_AGENT,
    WEBKIT_DIR_NAME,
    WEB_UI_ICON_FILE,
    WEB_UI_JS_FILE,
    GITHUB_PROXY_BASE,
)
from http_client import ensure_http_client
import httpx
from logger import logger
from paths import backend_path, public_path
from steam_utils import detect_steam_install_path, has_lua_for_app
from utils import count_apis, ensure_temp_download_dir, normalize_manifest_text, read_text, write_text


# ── Exception for normal cancellation flow (review #3) ────────────────
class DownloadCancelled(Exception):
    """User cancelled the download. Not an error  --  just control flow."""
    pass


# ── Security: ZIP validation (from SteamAppInserter/security.py) ──────
try:
    from security import validate_zip_archive
except ImportError:
    logger.warn("security.py not found  --  ZIP validation disabled, all archives will pass")
    def validate_zip_archive(archive_bytes, appid="unknown"):
        return True, None


# ── Safe file removal with retries (review #11) ──────────────────────
def _safe_remove(path: str, retries: int = 3, delay: float = 0.2) -> None:
    """Remove a file, retrying on Windows lock errors."""
    for i in range(retries):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except OSError:
            if i < retries - 1:
                time.sleep(delay)


# ── GitHub proxy helpers (for regions where GitHub is blocked) ───────
def _try_with_github_proxy(url: str, fn, proxy_base: str) -> Any:
    """Try fn(url), then retry with a proxy URL if it fails.
    
    fn should accept a single URL argument and return a value or raise.
    proxy_base is the base URL of the proxy (e.g., GITHUB_PROXY_BASE).
    
    For api.github.com URLs:
        https://api.github.com/repos/x/y/zipball/z
        -> https://luatools.vercel.app/api/github/repos/x/y/zipball/z
    
    For raw.githubusercontent.com URLs:
        https://raw.githubusercontent.com/x/y/main/file.lua
        -> https://luatools.vercel.app/api/raw/x/y/main/file.lua
    """
    try:
        return fn(url)
    except Exception as primary_err:
        if "github" not in url.lower():
            raise  # not a GitHub URL, re-raise immediately
        
        # Build proxy URL based on GitHub host
        if "api.github.com" in url:
            # api.github.com/repos/... -> /api/github/repos/...
            path = url.split("api.github.com", 1)[-1]
            proxy_url = proxy_base + path
        elif "raw.githubusercontent.com" in url:
            # raw.githubusercontent.com/owner/repo/... -> /api/raw/owner/repo/...
            path = url.split("raw.githubusercontent.com", 1)[-1]
            proxy_url = proxy_base.replace("/api/github", "/api/raw") + path
        else:
            raise  # unknown GitHub host, re-raise
        
        logger.warn(f"LuaTools: GitHub direct failed ({primary_err}), trying proxy {proxy_url}")
        try:
            return fn(proxy_url)
        except Exception as proxy_err:
            logger.warn(f"LuaTools: GitHub proxy also failed ({proxy_err})")
            raise primary_err  # re-raise the original error


def _run_post_install_audit(appid: int) -> None:
    """Run a content audit after successful install and store result in download state."""
    try:
        from steamtools import audit_lua_content
        import json as _json
        result = _json.loads(audit_lua_content(appid))
        if result.get("success"):
            _set_download_state(appid, {"contentCheckResult": {
                "workshop": result.get("workshop", {}),
                "dlc": result.get("dlc", {}),
                "depotCount": result.get("depotCount", 0),
            }})
    except Exception as exc:
        logger.warn(f"LuaTools: Post-install audit failed for {appid}: {exc}")

DOWNLOAD_STATE: Dict[int, Dict[str, Any]] = {}
DOWNLOAD_LOCK = threading.Lock()

# Cache for app names to avoid repeated API calls
APP_NAME_CACHE: Dict[int, str] = {}
APP_NAME_CACHE_LOCK = threading.Lock()

# Rate limiting for Steam API calls (review #2: dedicated lock prevents race condition)
_RATE_LIMIT_LOCK = threading.Lock()
LAST_API_CALL_TIME = 0.0
API_CALL_MIN_INTERVAL = 0.3  # 300ms between calls to avoid 429 errors

# In-memory applist for fallback app name lookup
APPLIST_DATA: Dict[int, str] = {}
APPLIST_LOADED = False
APPLIST_LOCK = threading.Lock()
APPLIST_FILE_NAME = "all-appids.json"
APPLIST_URL = "https://applist.morrenus.xyz/"
APPLIST_DOWNLOAD_TIMEOUT = 300  # 5 minutes for large file

GAMES_DB_FILE_NAME = "games.json"
GAMES_DB_URL = "https://toolsdb.piqseu.cc/games.json"

# In-memory games database cache and lock (defined to avoid undefined variable)
GAMES_DB_DATA: Dict[int, Any] = {}
GAMES_DB_LOADED = False
GAMES_DB_LOCK = threading.Lock()


def _set_download_state(appid: int, update: dict) -> None:
    with DOWNLOAD_LOCK:
        state = DOWNLOAD_STATE.get(appid) or {}
        state.update(update)
        DOWNLOAD_STATE[appid] = state


def _get_download_state(appid: int) -> dict:
    with DOWNLOAD_LOCK:
        return DOWNLOAD_STATE.get(appid, {}).copy()


def _loaded_apps_path() -> str:
    return backend_path(LOADED_APPS_FILE)


def _appid_log_path() -> str:
    return backend_path(APPID_LOG_FILE)


def _fetch_app_name(appid: int) -> str:
    """Fetch app name with rate limiting and caching.
    
    Fallback order:
    1. In-memory cache
    2. Applist file (in-memory) - checked before web requests
    3. Steam API (web request as final resort)
    """
    global LAST_API_CALL_TIME

    # Check cache first
    with APP_NAME_CACHE_LOCK:
        if appid in APP_NAME_CACHE:
            cached = APP_NAME_CACHE[appid]
            if cached:  # Only return if not empty
                return cached

    # Check applist file before making web requests
    applist_name = _get_app_name_from_applist(appid)
    if applist_name:
        # Cache the result from applist
        with APP_NAME_CACHE_LOCK:
            APP_NAME_CACHE[appid] = applist_name
        return applist_name

    # Steam API as final resort (web request)
    # Rate limiting: acquire dedicated lock to prevent concurrent API hammering
    with _RATE_LIMIT_LOCK:
        time_since_last_call = time.time() - LAST_API_CALL_TIME
        sleep_time = API_CALL_MIN_INTERVAL - time_since_last_call if time_since_last_call < API_CALL_MIN_INTERVAL else 0
        LAST_API_CALL_TIME = time.time() + sleep_time

    if sleep_time > 0:
        time.sleep(sleep_time)

    client = ensure_http_client("LuaTools: _fetch_app_name")
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
        logger.log(f"LuaTools: Fetching app name for {appid} from Steam API")
        resp = client.get(url, follow_redirects=True, timeout=10)
        logger.log(f"LuaTools: Steam API response for {appid}: status={resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
        entry = data.get(str(appid)) or {}
        if isinstance(entry, dict):
            inner = entry.get("data") or {}
            name = inner.get("name")
            if isinstance(name, str) and name.strip():
                name = name.strip()
                # Cache the result
                with APP_NAME_CACHE_LOCK:
                    APP_NAME_CACHE[appid] = name
                return name
    except Exception as exc:
        logger.warn(f"LuaTools: _fetch_app_name failed for {appid}: {exc}")

    # Cache empty result to avoid repeated failed attempts
    with APP_NAME_CACHE_LOCK:
        APP_NAME_CACHE[appid] = ""
    return ""


def _append_loaded_app(appid: int, name: str) -> None:
    try:
        path = _loaded_apps_path()
        lines = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        prefix = f"{appid}:"
        lines = [line for line in lines if not line.startswith(prefix)]
        lines.append(f"{appid}:{name}")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except Exception as exc:
        logger.warn(f"LuaTools: _append_loaded_app failed for {appid}: {exc}")


def _remove_loaded_app(appid: int) -> None:
    try:
        path = _loaded_apps_path()
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        prefix = f"{appid}:"
        new_lines = [line for line in lines if not line.startswith(prefix)]
        if len(new_lines) != len(lines):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(new_lines) + ("\n" if new_lines else ""))
    except Exception as exc:
        logger.warn(f"LuaTools: _remove_loaded_app failed for {appid}: {exc}")


def _log_appid_event(action: str, appid: int, name: str) -> None:
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        line = f"[{action}] {appid} - {name} - {stamp}\n"
        with open(_appid_log_path(), "a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception as exc:
        logger.warn(f"LuaTools: _log_appid_event failed: {exc}")


def _preload_app_names_cache() -> None:
    """Pre-load all app names from loaded_apps, appidlogs, and applist files into memory cache."""
    # First, load from appidlogs.txt (historical records)
    try:
        log_path = _appid_log_path()
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as handle:
                for line in handle.read().splitlines():
                    # Format: [ACTION - API_NAME] appid - name - timestamp
                    # Example: [ADDED - Sadie] 945360 - Among Us - 2024-01-15 14:05:04
                    # Or: [REMOVED] appid - name - timestamp
                    if "]" in line and " - " in line:
                        try:
                            # Extract content after the first ']'
                            parts = line.split("]", 1)
                            if len(parts) < 2:
                                continue

                            content = parts[1].strip()
                            # Split by " - " to get: appid, name, timestamp (max 3 parts)
                            content_parts = content.split(" - ", 2)

                            if len(content_parts) >= 2:
                                appid_str = content_parts[0].strip()
                                name = content_parts[1].strip()

                                # Try to parse appid
                                appid = int(appid_str)

                                # Skip "Unknown Game" or "UNKNOWN" entries
                                if name and not name.startswith("Unknown") and not name.startswith("UNKNOWN"):
                                    with APP_NAME_CACHE_LOCK:
                                        APP_NAME_CACHE[appid] = name
                        except (ValueError, IndexError):
                            continue
    except Exception as exc:
        logger.warn(f"LuaTools: _preload_app_names_cache from logs failed: {exc}")

    # Then, load from loaded_apps.txt (current state - overrides log if present)
    try:
        path = _loaded_apps_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle.read().splitlines():
                    if ":" in line:
                        parts = line.split(":", 1)
                        try:
                            appid = int(parts[0].strip())
                            name = parts[1].strip()
                            if name:
                                with APP_NAME_CACHE_LOCK:
                                    APP_NAME_CACHE[appid] = name
                        except (ValueError, IndexError):
                            continue
    except Exception as exc:
        logger.warn(f"LuaTools: _preload_app_names_cache from loaded_apps failed: {exc}")
    
    # Finally, load from applist file (as fallback source - doesn't override existing cache)
    # This ensures applist is available for lookups without web requests
    try:
        _load_applist_into_memory()
    except Exception as exc:
        logger.warn(f"LuaTools: _preload_app_names_cache from applist failed: {exc}")


def _get_loaded_app_name(appid: int) -> str:
    """Get app name from loadedappids.txt, with applist as fallback."""
    try:
        path = _loaded_apps_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle.read().splitlines():
                    if line.startswith(f"{appid}:"):
                        name = line.split(":", 1)[1].strip()
                        if name:
                            return name
    except Exception:
        pass
    
    # Fallback to applist if not found in loadedappids.txt
    return _get_app_name_from_applist(appid)


def _applist_file_path() -> str:
    """Get the path to the applist JSON file."""
    temp_dir = ensure_temp_download_dir()
    return os.path.join(temp_dir, APPLIST_FILE_NAME)


def _load_applist_into_memory() -> None:
    """Load the applist JSON file into memory for fast lookups."""
    global APPLIST_DATA, APPLIST_LOADED
    
    with APPLIST_LOCK:
        if APPLIST_LOADED:
            return
        
        file_path = _applist_file_path()
        if not os.path.exists(file_path):
            logger.log("LuaTools: Applist file not found, skipping load")
            APPLIST_LOADED = True  # Mark as loaded to avoid repeated checks
            return
        
        try:
            logger.log("LuaTools: Loading applist into memory...")
            with open(file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            
            if isinstance(data, list):
                count = 0
                for entry in data:
                    if isinstance(entry, dict):
                        appid = entry.get("appid")
                        name = entry.get("name")
                        if appid and name and isinstance(name, str) and name.strip():
                            APPLIST_DATA[int(appid)] = name.strip()
                            count += 1
                logger.log(f"LuaTools: Loaded {count} app names from applist into memory")
            else:
                logger.warn("LuaTools: Applist file has invalid format (expected array)")
            
            APPLIST_LOADED = True
        except Exception as exc:
            logger.warn(f"LuaTools: Failed to load applist into memory: {exc}")
            APPLIST_LOADED = True  # Mark as loaded to avoid repeated failed attempts


def _get_app_name_from_applist(appid: int) -> str:
    """Get app name from in-memory applist."""
    # Ensure applist is loaded
    if not APPLIST_LOADED:
        _load_applist_into_memory()
    
    with APPLIST_LOCK:
        return APPLIST_DATA.get(int(appid), "")


def _ensure_applist_file() -> None:
    """Download the applist file if it doesn't exist."""
    file_path = _applist_file_path()
    
    if os.path.exists(file_path):
        logger.log("LuaTools: Applist file already exists, skipping download")
        return
    
    logger.log("LuaTools: Applist file not found, downloading...")
    client = ensure_http_client("LuaTools: DownloadApplist")
    
    try:
        logger.log(f"LuaTools: Downloading applist from {APPLIST_URL}")
        resp = client.get(APPLIST_URL, follow_redirects=True, timeout=APPLIST_DOWNLOAD_TIMEOUT)
        logger.log(f"LuaTools: Applist download response: status={resp.status_code}")
        resp.raise_for_status()
        
        # Validate JSON format before saving
        try:
            data = resp.json()
            if not isinstance(data, list):
                logger.warn("LuaTools: Downloaded applist has invalid format (expected array)")
                return
        except json.JSONDecodeError as exc:
            logger.warn(f"LuaTools: Downloaded applist is not valid JSON: {exc}")
            return
        
        # Save to file
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        
        logger.log(f"LuaTools: Successfully downloaded and saved applist file ({len(data)} entries)")
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to download applist file: {exc}")


def init_applist() -> None:
    """Initialize the applist system: download if needed, then load into memory."""
    try:
        _ensure_applist_file()
        _load_applist_into_memory()
    except Exception as exc:
        logger.warn(f"LuaTools: Applist initialization failed: {exc}")


def _games_db_file_path() -> str:
    """Get the path to the games database JSON file."""
    temp_dir = ensure_temp_download_dir()
    return os.path.join(temp_dir, GAMES_DB_FILE_NAME)


def _load_games_db_into_memory() -> None:
    """Load the games database JSON file into memory."""
    global GAMES_DB_DATA, GAMES_DB_LOADED
    
    with GAMES_DB_LOCK:
        if GAMES_DB_LOADED:
            return
        
        file_path = _games_db_file_path()
        if not os.path.exists(file_path):
            logger.log("LuaTools: Games DB file not found, skipping load")
            GAMES_DB_LOADED = True
            return
        
        try:
            logger.log("LuaTools: Loading Games DB into memory...")
            with open(file_path, "r", encoding="utf-8") as handle:
                GAMES_DB_DATA = json.load(handle)
            
            logger.log(f"LuaTools: Loaded Games DB ({len(GAMES_DB_DATA)} entries)")
            GAMES_DB_LOADED = True
        except Exception as exc:
            logger.warn(f"LuaTools: Failed to load Games DB: {exc}")
            GAMES_DB_LOADED = True


GAMES_DB_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # 24 hours


def _is_games_db_cache_stale() -> bool:
    """Check if the games database cache file is older than 24 hours."""
    file_path = _games_db_file_path()
    if not os.path.exists(file_path):
        return True
    try:
        file_mtime = os.path.getmtime(file_path)
        age_seconds = time.time() - file_mtime
        return age_seconds > GAMES_DB_CACHE_MAX_AGE_SECONDS
    except Exception:
        return True


def _ensure_games_db_file() -> None:
    """Download the games database file if missing or stale (older than 24 hours)."""
    file_path = _games_db_file_path()

    # Skip download if file exists and is fresh
    if os.path.exists(file_path) and not _is_games_db_cache_stale():
        logger.log("LuaTools: Games DB cache is fresh, skipping download")
        return

    logger.log("LuaTools: Downloading Games DB (cache missing or stale)...")
    client = ensure_http_client("LuaTools: DownloadGamesDB")
    
    try:
        logger.log(f"LuaTools: Downloading Games DB from {GAMES_DB_URL}")
        resp = client.get(GAMES_DB_URL, follow_redirects=True, timeout=60)
        logger.log(f"LuaTools: Games DB download response: status={resp.status_code}")
        resp.raise_for_status()
        
        data = resp.json()
        
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        
        logger.log(f"LuaTools: Successfully downloaded Games DB")
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to download Games DB: {exc}")


def init_games_db() -> None:
    """Initialize the games database: download if needed, then load into memory."""
    try:
        _ensure_games_db_file()
        _load_games_db_into_memory()
    except Exception as exc:
        logger.warn(f"LuaTools: Games DB initialization failed: {exc}")


def get_games_database() -> str:
    """Get the games database as JSON string."""
    if not GAMES_DB_LOADED:
        init_games_db()
    
    with GAMES_DB_LOCK:
        return json.dumps(GAMES_DB_DATA)


def fetch_app_name(appid: int) -> str:
    return _fetch_app_name(appid)


def _process_and_install_lua(appid: int, zip_path: str) -> None:
    """Process downloaded zip and install lua file into stplug-in directory."""
    import zipfile

    if _is_download_cancelled(appid):
        raise DownloadCancelled()

    base_path = detect_steam_install_path() or Millennium.steam_path()
    target_dir = os.path.join(base_path or "", "config", "stplug-in")
    os.makedirs(target_dir, exist_ok=True)

    # Security: validate ZIP structure before extraction
    try:
        with open(zip_path, "rb") as fh:
            archive_bytes = fh.read()
        is_valid, sec_error = validate_zip_archive(archive_bytes, str(appid))
        if not is_valid:
            logger.error(f"LuaTools: ZIP security check failed for {appid}: {sec_error}")
            raise RuntimeError(f"Security validation failed: {sec_error}")
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warn(f"LuaTools: ZIP security pre-check error for {appid}: {exc}")

    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()

        try:
            depotcache_dir = os.path.join(base_path or "", "depotcache")
            os.makedirs(depotcache_dir, exist_ok=True)
            for name in names:
                try:
                    if _is_download_cancelled(appid):
                        raise DownloadCancelled()
                    if name.lower().endswith(".manifest"):
                        pure = os.path.basename(name)
                        data = archive.read(name)
                        out_path = os.path.join(depotcache_dir, pure)
                        with open(out_path, "wb") as manifest_file:
                            manifest_file.write(data)
                        logger.log(f"LuaTools: Extracted manifest -> {out_path}")
                except Exception as manifest_exc:
                    logger.warn(f"LuaTools: Failed to extract manifest {name}: {manifest_exc}")
        except Exception as depot_exc:
            logger.warn(f"LuaTools: depotcache extraction failed: {depot_exc}")

        candidates = []
        for name in names:
            pure = os.path.basename(name)
            if re.fullmatch(r"\d+\.lua", pure):
                candidates.append(name)

        if _is_download_cancelled(appid):
            raise DownloadCancelled()

        chosen = None
        preferred = f"{appid}.lua"
        for name in candidates:
            if os.path.basename(name) == preferred:
                chosen = name
                break
        if chosen is None and candidates:
            chosen = candidates[0]
        if not chosen:
            raise RuntimeError("No numeric .lua file found in zip")

        data = archive.read(chosen)
        try:
            text = data.decode("utf-8")
        except Exception:
            text = data.decode("utf-8", errors="replace")

        processed_lines = []
        for line in text.splitlines(True):
            stripped = line.strip()
            # Skip commented lines as-is
            if stripped.startswith("--"):
                processed_lines.append(line)
                continue
            # Comment out active setManifestid() calls (use latest manifest)
            if re.match(r"^\s*setManifestid\(", line):
                line = re.sub(r"^(\s*)", r"\1--", line)
                processed_lines.append(line)
                continue
            # KEEP every addappid() line. Keyless addappid(appid) lines are NOT
            # stubs — addappid(<gameid>) registers ownership of the game, and
            # keyless addappid(<dlcid>) lines unlock DLCs. Stripping them makes
            # SLSsteam never grant ownership, so Steam won't download. Only the
            # depot lines additionally carry a 64-char key for decryption; both
            # kinds are required. (Compare working 2483190.lua / 590830.lua.)
            processed_lines.append(line)
        processed_text = "".join(processed_lines)

        _set_download_state(appid, {"status": "installing"})
        dest_file = os.path.join(target_dir, f"{appid}.lua")
        if _is_download_cancelled(appid):
            raise DownloadCancelled()
        with open(dest_file, "w", encoding="utf-8") as output:
            output.write(processed_text)
        logger.log(f"LuaTools: Installed lua -> {dest_file}")
        _set_download_state(appid, {"installedPath": dest_file})

    # Restore the upstream mechanism: hand the bundle to ACCELA so it actually
    # downloads the game. Keeps the .lua install above for SLSsteam users; this
    # adds the ACCELA download path STLT had dropped. Best-effort + isolated so
    # it can never break activation. ACCELA gets its own copy of the zip, so the
    # cleanup below is safe.
    try:
        import accela_launcher
        if accela_launcher.is_available():
            res = accela_launcher.run_with_zip(zip_path)
            if res.get("invoked"):
                _set_download_state(appid, {"accelaInvoked": True})
                logger.log(f"LuaTools: handed {appid} bundle to ACCELA for download")
            else:
                logger.warn(f"LuaTools: ACCELA not invoked: {res.get('reason')}")
    except Exception as exc:
        logger.warn(f"LuaTools: ACCELA invocation skipped: {exc}")

    _safe_remove(zip_path)

    # Linux: auto-activate via ACF + config.vdf (ported from SteaMidra)
    # Best-effort, never blocks or raises; gated by the autoActivateLinux setting.
    try:
        import sys as _sys
        if not _sys.platform.startswith("win"):
            from settings.manager import get_steamtools_settings as _gss
            _cfg = (_gss() or {}).get("general", {})
            if _cfg.get("autoActivateLinux", True):
                # Extract depot keys from the processed Lua text
                _depot_keys: list = []
                _manifest_ids: dict = {}
                for _line in processed_text.splitlines():
                    _stripped = _line.strip()
                    # Match addappid(depot, 0, "key") - extract the actual key
                    _mk = re.search(r'addappid\s*\(\s*(\d+)\s*,\s*\d+\s*,\s*"([a-fA-F0-9]{64})"', _stripped)
                    if _mk:
                        _depot_keys.append((_mk.group(1), _mk.group(2)))
                    # Match setManifestid(depot, "gid")
                    _ms = re.search(r'setManifestid\s*\(\s*(\d+)\s*,\s*"([0-9a-fA-F]+)"', _stripped)
                    if _ms:
                        _manifest_ids[_ms.group(1)] = _ms.group(2)

                if _depot_keys:
                    try:
                        import acf_writer as _aw
                        _result = _aw.activate_game_on_linux(
                            appid, _depot_keys, _manifest_ids
                        )
                        if _result.get("success"):
                            logger.log(
                                f"LuaTools: Linux activation complete for {appid} "
                                f"(ACF={_result.get('acf_written')}, "
                                f"keys={_result.get('keys_added')})"
                            )
                        else:
                            for _err in _result.get("errors", []):
                                logger.warn(f"LuaTools: Linux activation warning: {_err}")
                    except Exception as _ae:
                        logger.warn(f"LuaTools: Linux activation failed: {_ae}")

            # Auto compat tool (existing logic)
            _cfg2 = (_gss() or {}).get("general", {})
            if _cfg2.get("autoCompatTool", True):
                import compat_tools as _ct
                _tool = _cfg2.get("compatTool") or _ct.DEFAULT_TOOL
                _ct.auto_set_on_activation(appid, _tool)
    except Exception as _exc:
        logger.warn(f"LuaTools: post-install Linux setup skipped for {appid}: {_exc}")


def _is_download_cancelled(appid: int) -> bool:
    try:
        return _get_download_state(appid).get("status") == "cancelled"
    except Exception:
        return False


def _download_zip_for_app(appid: int):
    """Main download chain  --  tries each source in priority order.

    Uses configurable source_chain for ordering/enable/disable.
    Records history for every attempt. Emits events on completion/failure.
    """
    client = ensure_http_client("LuaTools: download")
    apis = load_api_manifest()
    if not apis:
        logger.warn("LuaTools: No enabled APIs in manifest")

    dest_root = ensure_temp_download_dir()
    dest_path = os.path.join(dest_root, f"{appid}.zip")
    _set_download_state(appid, {
        "status": "checking", "currentApi": None, "bytesRead": 0,
        "totalBytes": 0, "dest": dest_path, "apiErrors": {},
    })

    morrenus_api_key = get_morrenus_api_key()
    _dl_start_time = time.time()

    # ── History + Events (lazy imports to avoid circular deps) ─────────
    _history_id = 0
    try:
        from history import record_start, record_complete, record_failure, file_sha256
    except ImportError:
        record_start = record_complete = record_failure = file_sha256 = None  # type: ignore

    try:
        from events import emit as _emit
    except ImportError:
        _emit = None  # type: ignore

    if _emit:
        _emit("download.start", {"appid": appid})

    # ── Source chain config ────────────────────────────────────────────
    try:
        from source_chain import get_enabled_chain, is_api_blacklisted, get_source_timeout
    except ImportError:
        get_enabled_chain = None  # type: ignore
        is_api_blacklisted = lambda _: False  # type: ignore
        get_source_timeout = lambda _: 20  # type: ignore

    # ── Shared helpers (closures over appid/dest_path/client) ─────────

    def cancelled():
        return _is_download_cancelled(appid)

    def set_checking(name):
        _set_download_state(appid, {"status": "checking", "currentApi": name, "bytesRead": 0, "totalBytes": 0})

    def finalize(source_name):
        """Common post-download: process zip -> install lua -> log -> audit -> history -> event."""
        nonlocal _history_id
        _set_download_state(appid, {"status": "processing"})
        _process_and_install_lua(appid, dest_path)
        name = _fetch_app_name(appid) or f"UNKNOWN ({appid})"
        _append_loaded_app(appid, name)
        _log_appid_event(f"ADDED - {source_name}", appid, name)
        _set_download_state(appid, {"status": "done", "success": True, "api": source_name})
        _run_post_install_audit(appid)
        # History
        if record_complete and _history_id:
            sha = file_sha256(dest_path) if file_sha256 else ""
            sz = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
            record_complete(_history_id, sha256=sha, bytes_total=sz)
        # Event
        if _emit:
            _emit("download.complete", {
                "appid": appid, "name": name, "source": source_name,
                "duration_s": round(time.time() - _dl_start_time, 1),
            })

    def is_valid_zip():
        try:
            with open(dest_path, "rb") as fh:
                return fh.read(4) in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
        except Exception:
            return False

    def stream_to_file(url, headers=None, cookies=None, timeout=20):
        """Stream HTTP response to dest_path with progress updates. Returns True if got 200."""
        with client.stream("GET", url, headers=headers or {"User-Agent": USER_AGENT},
                           cookies=cookies, follow_redirects=True, timeout=timeout) as resp:
            if resp.status_code != 200:
                return resp.status_code
            total = int(resp.headers.get("Content-Length", "0") or "0")
            _set_download_state(appid, {"status": "downloading", "bytesRead": 0, "totalBytes": total})
            bytes_read = 0
            with open(dest_path, "wb") as out:
                for chunk in resp.iter_bytes():
                    if not chunk:
                        continue
                    if cancelled():
                        raise DownloadCancelled()
                    out.write(chunk)
                    bytes_read += len(chunk)
                    _set_download_state(appid, {"bytesRead": bytes_read})
            return 200

    def stream_to_bytes(url, headers=None, cookies=None, timeout=15):
        """Stream URL to memory, return bytes or None.
        Uses bytearray to avoid O(n²) immutable bytes concatenation (review #1)."""
        with client.stream("GET", url, headers=headers or {"User-Agent": USER_AGENT},
                           cookies=cookies, follow_redirects=True, timeout=timeout) as resp:
            if resp.status_code != 200:
                return None
            _set_download_state(appid, {"status": "downloading", "bytesRead": 0, "totalBytes": 0})
            buf = bytearray()
            for chunk in resp.iter_bytes():
                if cancelled():
                    raise DownloadCancelled()
                buf.extend(chunk)
                _set_download_state(appid, {"bytesRead": len(buf)})
            return bytes(buf) if len(buf) >= 50 else None

    def wrap_lua_in_zip(lua_text):
        """Wrap raw lua text in a zip at dest_path."""
        import zipfile as _zf
        with _zf.ZipFile(dest_path, "w") as zout:
            zout.writestr(f"{appid}.lua", lua_text)

    def save_raw_to_dest(raw):
        """Save raw bytes (auto-detect zip vs lua) to dest_path. Returns True if valid."""
        is_zip = raw[:2] == b"PK"
        if is_zip:
            with open(dest_path, "wb") as fh:
                fh.write(raw)
            return is_valid_zip()
        else:
            text = raw.decode("utf-8", errors="replace").strip()
            if "addappid" not in text.lower():
                return False
            wrap_lua_in_zip(text)
            return True

    def cleanup():
        try:
            os.remove(dest_path)
        except Exception:
            pass

    # ── Connection-refused sentinel  --  set when network is unavailable ──
    _connection_refused_count = [0]  # mutable cell for closure

    def _is_conn_refused(exc: Exception) -> bool:
        """Network unavailable: connection refused, timeout, unreachable, SSL errors."""
        msg = str(exc).lower()
        return any(
            kw in msg
            for kw in [
                "10061",
                "connection refused",
                "actively refused",
                "connect timeout",
                "read timeout",
                "timed out",
                "network is unreachable",
                "no route to host",
                "connection reset",
                "broken pipe",
                "ssl",
                "certificate",
            ]
        )

    def try_source(name, fn):
        """Run a source function with standardized cancel/error handling.
        fn() should return True on success, False to continue.

        If three consecutive connection-refused errors occur, sets state
        to 'no_network' and aborts the chain early to avoid a 3-minute wait.
        """
        if cancelled():
            return "cancelled"
        # Early-abort if network is clearly unavailable
        if _connection_refused_count[0] >= 3:
            return "no_network"
        set_checking(name)
        try:
            if fn():
                _connection_refused_count[0] = 0  # reset on any success
                return "done"
            return "next"
        except DownloadCancelled:
            cleanup()
            return "cancelled"
        except Exception as exc:
            logger.warn(f"LuaTools: {name} error: {exc}")
            if _is_conn_refused(exc):
                _connection_refused_count[0] += 1
                if _connection_refused_count[0] >= 3:
                    logger.warn(
                        "LuaTools: Network unavailable (3x connection refused)  --  "
                        "aborting download chain"
                    )
                    return "no_network"
            return "next"

    # ── Source functions ───────────────────────────────────────────────

    def src_local():
        local_path = get_local_manifest_path()
        if not local_path or not os.path.isdir(local_path):
            return False
        logger.log(f"LuaTools: Checking local folder: {local_path}")
        local_zip = os.path.join(local_path, f"{appid}.zip")
        local_lua = os.path.join(local_path, f"{appid}.lua")
        if os.path.isfile(local_zip):
            import shutil
            shutil.copy2(local_zip, dest_path)
        elif os.path.isfile(local_lua):
            wrap_lua_in_zip(open(local_lua, "r", encoding="utf-8").read())
        else:
            return False
        finalize("Local Folder")
        return True

    def src_twentytwo():
        """TwentyTwo Cloud  --  free manifest API (from lt_api_links)."""
        raw = stream_to_bytes(
            f"https://api.twentytwocloud.com/download?appid={appid}",
            headers={"User-Agent": USER_AGENT},
        )
        if not raw:
            return False
        if not save_raw_to_dest(raw):
            return False
        finalize("TwentyTwo Cloud")
        return True

    def src_manifesthub_api():
        """ManifestHub direct API  --  requires API key (from FixerSteamTools)."""
        mh_key = get_manifesthub_api_key()
        if not mh_key:
            return False
        # Need depot/manifest IDs from SteamCMD API first
        try:
            info_resp = client.get(f"https://api.steamcmd.net/v1/info/{appid}", timeout=15)
            if not info_resp.is_success:
                return False
            info = info_resp.json()
            if info.get("status") != "success":
                return False
            depots_obj = info.get("data", {}).get(str(appid), {}).get("depots", {})
            if not depots_obj:
                return False

            # Try each depot
            import zipfile as _zf
            lua_lines = [f'addappid({appid}, 1, "")']
            fetched_any = False
            for depot_id, depot_info in depots_obj.items():
                if not depot_id.isdigit():
                    continue
                manifests = depot_info.get("manifests", {})
                public = manifests.get("public", {})
                manifest_id = public.get("gid") if isinstance(public, dict) else public
                if not manifest_id:
                    continue
                try:
                    mh_url = f"https://api.manifesthub1.filegear-sg.me/manifest?apikey={mh_key}&depotid={depot_id}&manifestid={manifest_id}"
                    mh_resp = client.get(mh_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                    if mh_resp.is_success and len(mh_resp.content) > 50:
                        # Save manifest to depotcache
                        base = detect_steam_install_path() or ""
                        if base:
                            fname = f"{depot_id}_{manifest_id}.manifest"
                            for cache_dir in [os.path.join(base, "depotcache"), os.path.join(base, "config", "depotcache")]:
                                os.makedirs(cache_dir, exist_ok=True)
                                with open(os.path.join(cache_dir, fname), "wb") as mf:
                                    mf.write(mh_resp.content)
                        fetched_any = True
                        lua_lines.append(f'addappid({depot_id}, {manifest_id}, "")')
                        logger.log(f"LuaTools: ManifestHub fetched {depot_id}_{manifest_id}")
                except Exception as exc:
                    logger.warn(f"LuaTools: ManifestHub depot {depot_id} error: {exc}")
                    continue

            if not fetched_any:
                return False

            # The ManifestHub API returns manifest IDs + manifest files, but
            # NOT depot decryption keys. Building a .lua here yields
            #   addappid(depot, manifest_id, "")   <- empty key, wrong arg slot
            # which lets Steam register the depot but never decrypt/download
            # real files (the "manifest template, no download" bug). We keep
            # the manifests we just cached to depotcache (a useful supplement)
            # but DO NOT finalize a keyless activation. Returning False lets the
            # chain fall through to a KEYED source (GitHub repos, Ryuu,
            # DepotBox, raw-lua fallbacks) that ships real depot keys, e.g.
            #   addappid(590831, 0, "5368f87f...")  <- 64-char hex depot key
            logger.log(
                f"LuaTools: ManifestHub API cached {len(lua_lines) - 1} manifest(s) "
                f"for {appid} but provides no depot keys; deferring activation to a "
                f"keyed source so the game can actually download"
            )
            return False
        except Exception as exc:
            logger.warn(f"LuaTools: ManifestHub API error: {exc}")
            return False

    # SDO GitHub repositories (from Steam Depot Online  --  25+ repos)
    SDO_REPOS = {
        "ManifestHub/ManifestHub": "Decrypted",
        "ikun0014/ManifestHub": "Decrypted",
        "Auiowu/ManifestAutoUpdate": "Decrypted",
        "tymolu233/ManifestAutoUpdate": "Decrypted",
        "MineRPG/ManifestAutoUpdate": "Decrypted",
        "bingyu50/ManifestAutoUpdate": "Decrypted",
        "bingyu50/SteamManifestCache": "Decrypted",
        "TOP-01/ManifestAutoUpdate": "Decrypted",
        "TOP-01/SteamManifestCache": "Decrypted",
        "ltsj/ManifestAutoUpdate": "Decrypted",
        "1271620983/ManifestAutoUpdate": "Decrypted",
        "crazzzzzysnail/ManifestAutoUpdate_fork": "Decrypted",
        "bluesxu/ManifestAutoUpdate": "Decrypted",
        "Scropiouos/ManifestAutoUpdate_backup": "Decrypted",
        "Scropiouos/SteamManifestCache_backup": "Decrypted",
        "luomojim/ManifestAutoUpdate": "Decrypted",
        "hansaes/ManifestAutoUpdate": "Decrypted",
        "3circledesign/BruhHub": "Branch",
        "SteamAutoCracks/ManifestHub": "Branch",
    }

    def src_github_repos():
        """SDO GitHub repos  --  19 repos with auto-updated manifests."""
        # Respect no-network early-abort (same sentinel as try_source)
        if _connection_refused_count[0] >= 3:
            return False

        gh_token = get_github_token()
        gh_headers = {"User-Agent": "LuaTools-Plugin/1.0"}
        if gh_token:
            gh_headers["Authorization"] = f"token {gh_token}"

        for repo, repo_type in SDO_REPOS.items():
            if cancelled():
                return False
            # Check after every repo  --  network may have been declared unavailable
            if _connection_refused_count[0] >= 3:
                logger.warn("LuaTools: Aborting GitHub repos loop  --  network unavailable")
                return False
            set_checking(f"GitHub: {repo.split('/')[0]}")
            try:
                if repo_type == "Branch":
                    zip_url = f"https://api.github.com/repos/{repo}/zipball/{appid}"
                    raw = _try_with_github_proxy(
                        zip_url,
                        lambda url: stream_to_bytes(url, headers=gh_headers, timeout=30),
                        GITHUB_PROXY_BASE,
                    )
                    if raw and raw[:2] == b"PK":
                        with open(dest_path, "wb") as fh:
                            fh.write(raw)
                        if is_valid_zip():
                            finalize(f"GitHub/{repo.split('/')[0]}")
                            return True
                        cleanup()
                else:
                    # Decrypted repos: check if appid folder exists via tree API
                    tree_url = f"https://api.github.com/repos/{repo}/git/trees/main"
                    tree_resp = _try_with_github_proxy(
                        tree_url,
                        lambda url: client.get(url, headers=gh_headers, timeout=10),
                        GITHUB_PROXY_BASE,
                    )
                    if not tree_resp.is_success:
                        continue
                    tree = tree_resp.json()
                    paths = [t.get("path", "") for t in tree.get("tree", [])]
                    if str(appid) not in paths:
                        continue
                    # Found  --  download raw lua/zip files
                    raw_url = f"https://raw.githubusercontent.com/{repo}/main/{appid}/{appid}.lua"
                    raw = _try_with_github_proxy(
                        raw_url,
                        lambda url: stream_to_bytes(url, timeout=15),
                        GITHUB_PROXY_BASE,
                    )
                    if raw and len(raw) > 50:
                        if not save_raw_to_dest(raw):
                            continue
                        finalize(f"GitHub/{repo.split('/')[0]}")
                        return True
            except RuntimeError:
                raise  # cancelled
            except Exception as exc:
                logger.warn(f"LuaTools: GitHub {repo} error: {exc}")
                if _is_conn_refused(exc):
                    _connection_refused_count[0] += 1
                    if _connection_refused_count[0] >= 3:
                        logger.warn("LuaTools: Network unavailable  --  aborting GitHub repos")
                        return False
                continue
        return False

    def src_ryuu():
        session = get_ryuu_session()
        if not session:
            return False
        code = stream_to_file(
            f"https://generator.ryuu.lol/download?appid={appid}&file_type=manifest",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://generator.ryuu.lol/"},
            cookies={"session": session},
        )
        if code != 200:
            return False
        if not is_valid_zip():
            cleanup()
            return False
        finalize("Ryuu Premium")
        return True

    def src_depotbox():
        sid = get_depotbox_sid()
        if not sid:
            return False
        db_base = "https://depotbox.org"
        db_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                       "Content-Type": "application/json", "Origin": db_base, "Referer": f"{db_base}/"}
        db_cookies = {"connect.sid": sid}
        game_name = _fetch_app_name(appid) or f"AppID {appid}"
        # Step 1: Initiate
        ir = client.post(f"{db_base}/initiate-download", headers=db_headers, cookies=db_cookies,
                         json={"appId": str(appid), "gameName": game_name}, timeout=20)
        token = (ir.json() if ir.is_success else {}).get("token")
        if not token:
            return False
        # Step 2: Poll
        for _ in range(120):
            if cancelled():
                raise DownloadCancelled()
            time.sleep(2.5)
            sr = client.get(f"{db_base}/status/{token}", headers=db_headers, cookies=db_cookies, timeout=15)
            st = (sr.json() if sr.is_success else {}).get("status", "")
            logger.log(f"LuaTools: DepotBox status={st}")
            if st in ("completed", "completed_with_warnings"):
                break
            if st in ("failed", "invalid_or_expired"):
                return False
        else:
            return False
        # Step 3: Download
        _set_download_state(appid, {"status": "downloading", "bytesRead": 0, "totalBytes": 0})
        dr = client.get(f"{db_base}/download/{token}", headers=db_headers, cookies=db_cookies, timeout=120)
        if not dr.is_success:
            return False
        with open(dest_path, "wb") as fh:
            fh.write(dr.content)
        if not is_valid_zip():
            cleanup()
            return False
        finalize("DepotBox Premium")
        return True

    def src_free_apis():
        if not apis:
            return False
        for api in apis:
            name = api.get("name", "Unknown")
            template = api.get("url", "")
            success_code = int(api.get("success_code", 200))
            unavailable_code = int(api.get("unavailable_code", 404))
            if "<moapikey>" in template:
                if not morrenus_api_key:
                    continue
                template = template.replace("<moapikey>", morrenus_api_key)
            url = template.replace("<appid>", str(appid))

            result = try_source(name, lambda url=url, sc=success_code, uc=unavailable_code: _try_single_api(url, sc, uc))
            if result == "done":
                return True
            if result == "cancelled":
                raise DownloadCancelled()
        return False

    def _try_single_api(url, success_code, unavailable_code, extra_headers=None):
        """Try a single Free API endpoint."""
        req_headers = {"User-Agent": USER_AGENT}
        if extra_headers:
            req_headers.update(extra_headers)
        with client.stream("GET", url, headers=req_headers, follow_redirects=True) as resp:
            code = resp.status_code
            if code == unavailable_code:
                return False
            if code != success_code:
                state = _get_download_state(appid)
                errors = state.get("apiErrors", {})
                errors[resp.url.host if hasattr(resp.url, 'host') else url] = {"type": "error", "code": code}
                _set_download_state(appid, {"apiErrors": errors})
                return False
            total = int(resp.headers.get("Content-Length", "0") or "0")
            _set_download_state(appid, {"status": "downloading", "bytesRead": 0, "totalBytes": total})
            bytes_read = 0
            with open(dest_path, "wb") as out:
                for chunk in resp.iter_bytes():
                    if not chunk:
                        continue
                    if cancelled():
                        raise DownloadCancelled()
                    out.write(chunk)
                    bytes_read += len(chunk)
                    _set_download_state(appid, {"bytesRead": bytes_read})

        if not is_valid_zip():
            try:
                with open(dest_path, "rb") as check_f:
                    preview = check_f.read(100).decode("utf-8", errors="ignore")
                logger.warn(f"LuaTools: API returned non-zip (preview={preview[:50]})")
            except Exception:
                pass
            cleanup()
            return False

        _set_download_state(appid, {"status": "processing"})
        _process_and_install_lua(appid, dest_path)
        name = _fetch_app_name(appid) or f"UNKNOWN ({appid})"
        _append_loaded_app(appid, name)
        _log_appid_event(f"ADDED - {_get_download_state(appid).get('currentApi', '?')}", appid, name)
        _set_download_state(appid, {"status": "done", "success": True, "api": _get_download_state(appid).get("currentApi", "Free API")})
        _run_post_install_audit(appid)
        return True

    def src_fallbacks():
        sources = [
            ("Spinoza", f"https://raw.githubusercontent.com/SPINOZAi/SB_manifest_DB/main/{appid}/{appid}.lua"),
            ("Sadie", f"http://167.235.229.108/{appid}"),
            ("Sushi", f"https://raw.githubusercontent.com/sushi-dev55-alt/sushitools-games-repo-alt/refs/heads/main/{appid}.zip"),
        ]
        for name, url in sources:
            result = try_source(name, lambda url=url: _try_fallback(url))
            if result == "done":
                return True
            if result == "cancelled":
                raise DownloadCancelled()
        return False

    def _try_fallback(url):
        raw = _try_with_github_proxy(
            url,
            lambda u: stream_to_bytes(u),
            GITHUB_PROXY_BASE,
        )
        if not raw:
            return False
        if not save_raw_to_dest(raw):
            return False
        source_name = _get_download_state(appid).get("currentApi", "Fallback")
        finalize(source_name)
        return True

    # ── Execute priority chain (configurable via source_chain.json) ────

    def src_custom_apis():
        """User-defined custom download endpoints (from Settings -> Custom APIs)."""
        try:
            from custom_apis import get_enabled_custom_apis
            c_apis = get_enabled_custom_apis()
        except Exception:
            return False
        if not c_apis:
            return False

        for api in c_apis:
            name = api.get("name", "Custom API")
            url_tpl = api.get("url", "")
            api_key = api.get("api_key", "")
            if not url_tpl or "<appid>" not in url_tpl:
                continue

            url = url_tpl.replace("<appid>", str(appid))
            headers = {"User-Agent": USER_AGENT}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            result = try_source(name, lambda url=url, h=headers: _try_single_api(
                url, 200, 404, extra_headers=h
            ))
            if result == "done":
                return True
            if result in ("cancelled", "no_network"):
                if result == "no_network":
                    raise DownloadCancelled("no_network")
                raise DownloadCancelled()
        return False

    SOURCE_MAP = {
        "local":            ("Local Folder", src_local),
        "twentytwo":        ("TwentyTwo Cloud", src_twentytwo),
        "ryuu":             ("Ryuu Premium", src_ryuu),
        "depotbox":         ("DepotBox Premium", src_depotbox),
        "manifesthub_api":  ("ManifestHub API", src_manifesthub_api),
        "custom_apis":      ("Custom APIs", src_custom_apis),
        "free_apis":        ("Free APIs", src_free_apis),
        "fallbacks":        ("SLStools Fallbacks", src_fallbacks),
        "github_repos":     ("GitHub Repos (SDO)", src_github_repos),
    }

    # Get ordered chain from config (or use defaults)
    if get_enabled_chain:
        chain_config = get_enabled_chain()
    else:
        chain_config = [
            {"id": "local"}, {"id": "twentytwo"}, {"id": "ryuu"},
            {"id": "depotbox"}, {"id": "manifesthub_api"}, {"id": "free_apis"},
            {"id": "fallbacks"}, {"id": "github_repos"},
        ]

    for src_cfg in chain_config:
        src_id = src_cfg.get("id", "")
        entry = SOURCE_MAP.get(src_id)
        if not entry:
            continue

        name, fn = entry

        # Record history start for this source attempt (with game name from cache)
        if record_start:
            _cached_name = _get_loaded_app_name(appid) or _fetch_app_name(appid) or ""
            _history_id = record_start(appid, name, game_name=_cached_name)

        if src_id in ("free_apis", "fallbacks", "github_repos"):
            # These have internal loops
            if not cancelled():
                try:
                    if fn():
                        return
                except RuntimeError:
                    return
        else:
            result = try_source(name, fn)
            if result == "done":
                return
            if result in ("cancelled", "no_network"):
                if result == "no_network":
                    _set_download_state(appid, {
                        "status": "failed",
                        "error": "Network unavailable (connection refused)",
                    })
                return

    # All sources exhausted (or network unavailable)
    if _connection_refused_count[0] >= 3:
        err = "Network unavailable  --  connection actively refused by all sources"
    else:
        err = "Not available on any API"
    _set_download_state(appid, {"status": "failed", "error": err})
    if record_failure and _history_id:
        record_failure(_history_id, "Not available on any API")
    if _emit:
        _emit("download.fail", {
            "appid": appid, "error": "Not available on any API",
            "duration_s": round(time.time() - _dl_start_time, 1),
        })


def start_add_via_luatools(appid: int) -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})

    # Backend dedup guard  --  prevent parallel workers on the same appid
    current = _get_download_state(appid)
    active_statuses = {"queued", "checking", "downloading", "processing"}
    if current.get("status") in active_statuses:
        logger.log(
            f"LuaTools: StartAddViaLuaTools appid={appid}  --  "
            f"already in progress ({current.get('status')}), ignoring duplicate"
        )
        return json.dumps({"success": False, "error": "already_in_progress",
                           "status": current.get("status")})

    logger.log(f"LuaTools: StartAddViaLuaTools appid={appid}")
    _set_download_state(appid, {"status": "queued", "bytesRead": 0, "totalBytes": 0})
    thread = threading.Thread(target=_download_zip_for_app, args=(appid,), daemon=True)
    thread.start()
    return json.dumps({"success": True})


def get_add_status(appid: int) -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})
    state = _get_download_state(appid)
    return json.dumps({"success": True, "state": state})


def read_loaded_apps() -> str:
    try:
        path = _loaded_apps_path()
        entries = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle.read().splitlines():
                    if ":" in line:
                        appid_str, name = line.split(":", 1)
                        appid_str = appid_str.strip()
                        name = name.strip()
                        if appid_str.isdigit() and name:
                            entries.append({"appid": int(appid_str), "name": name})
        return json.dumps({"success": True, "apps": entries})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def dismiss_loaded_apps() -> str:
    try:
        path = _loaded_apps_path()
        if os.path.exists(path):
            os.remove(path)
        return json.dumps({"success": True})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def delete_luatools_for_app(appid: int) -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})

    base = detect_steam_install_path() or Millennium.steam_path()
    target_dir = os.path.join(base or "", "config", "stplug-in")
    paths = [
        os.path.join(target_dir, f"{appid}.lua"),
        os.path.join(target_dir, f"{appid}.lua.disabled"),
    ]
    deleted = []
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                deleted.append(path)
        except Exception as exc:
            logger.warn(f"LuaTools: Failed to delete {path}: {exc}")
    try:
        name = _get_loaded_app_name(appid) or _fetch_app_name(appid) or f"UNKNOWN ({appid})"
        _remove_loaded_app(appid)
        if deleted:
            _log_appid_event("REMOVED", appid, name)
    except Exception:
        pass
    return json.dumps({"success": True, "deleted": deleted, "count": len(deleted)})


def get_icon_data_url() -> str:
    try:
        steam_ui_path = os.path.join(Millennium.steam_path(), "steamui", WEBKIT_DIR_NAME)
        icon_path = os.path.join(steam_ui_path, WEB_UI_ICON_FILE)
        if not os.path.exists(icon_path):
            icon_path = public_path(WEB_UI_ICON_FILE)
        with open(icon_path, "rb") as handle:
            data = handle.read()
        b64 = base64.b64encode(data).decode("ascii")
        return json.dumps({"success": True, "dataUrl": f"data:image/png;base64,{b64}"})
    except Exception as exc:
        logger.warn(f"LuaTools: GetIconDataUrl failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def has_luatools_for_app(appid: int) -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})
    exists = has_lua_for_app(appid)
    return json.dumps({"success": True, "exists": exists})


def cancel_add_via_luatools(appid: int) -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})

    state = _get_download_state(appid)
    if not state or state.get("status") in {"done", "failed"}:
        return json.dumps({"success": True, "message": "Nothing to cancel"})

    _set_download_state(appid, {"status": "cancelled", "error": "Cancelled by user"})
    logger.log(f"LuaTools: Cancellation requested for appid={appid}")
    return json.dumps({"success": True})


def get_installed_lua_scripts() -> str:
    """Get list of all installed Lua scripts from stplug-in directory."""
    try:
        # Pre-load app names cache from file to avoid API calls
        _preload_app_names_cache()

        base_path = detect_steam_install_path() or Millennium.steam_path()
        if not base_path:
            return json.dumps({"success": False, "error": "Could not find Steam installation path"})

        target_dir = os.path.join(base_path, "config", "stplug-in")
        if not os.path.exists(target_dir):
            return json.dumps({"success": True, "scripts": []})

        installed_scripts = []

        try:
            for filename in os.listdir(target_dir):
                # Match both enabled (.lua) and disabled (.lua.disabled) scripts
                if filename.endswith(".lua") or filename.endswith(".lua.disabled"):
                    try:
                        # Extract appid from filename
                        appid_str = filename.replace(".lua.disabled", "").replace(".lua", "")
                        appid = int(appid_str)

                        # Check if it's disabled
                        is_disabled = filename.endswith(".lua.disabled")

                        # Try to get game name from cache (no API calls during listing)
                        game_name = ""
                        with APP_NAME_CACHE_LOCK:
                            game_name = APP_NAME_CACHE.get(appid, "")

                        # Fallback to loaded_apps file if not in cache
                        # (_get_loaded_app_name also checks applist as fallback)
                        if not game_name:
                            game_name = _get_loaded_app_name(appid)

                        # Only use "Unknown Game" as last resort - don't fetch from API
                        if not game_name:
                            game_name = f"Unknown Game ({appid})"

                        # Get file stats
                        file_path = os.path.join(target_dir, filename)
                        file_stat = os.stat(file_path)
                        file_size = file_stat.st_size

                        # Format date
                        modified_time = datetime.datetime.fromtimestamp(file_stat.st_mtime)
                        formatted_date = modified_time.strftime("%Y-%m-%d %H:%M:%S")

                        script_info = {
                            "appid": appid,
                            "gameName": game_name,
                            "filename": filename,
                            "isDisabled": is_disabled,
                            "fileSize": file_size,
                            "modifiedDate": formatted_date,
                            "path": file_path
                        }

                        installed_scripts.append(script_info)

                    except ValueError:
                        # Not a numeric filename, skip
                        continue
                    except Exception as exc:
                        logger.warn(f"LuaTools: Failed to process Lua file {filename}: {exc}")
                        continue

        except Exception as exc:
            logger.warn(f"LuaTools: Failed to scan stplug-in directory: {exc}")
            return json.dumps({"success": False, "error": f"Failed to scan directory: {str(exc)}"})

        # Sort by appid
        installed_scripts.sort(key=lambda x: x["appid"])

        return json.dumps({"success": True, "scripts": installed_scripts})

    except Exception as exc:
        logger.warn(f"LuaTools: Failed to get installed Lua scripts: {exc}")
        return json.dumps({"success": False, "error": str(exc)})



# ── Direct-URL download (upstream: StartAddViaLuaToolsFromUrl) ─────────────

def _download_zip_from_url(appid: int, url: str, api_name: str) -> None:
    """Internal worker: download from a specific user-selected URL."""
    client = ensure_http_client("LuaTools: download_direct")
    dest_root = ensure_temp_download_dir()
    dest_path = os.path.join(dest_root, f"{appid}.zip")

    _set_download_state(appid, {
        "status": "downloading", "currentApi": api_name,
        "bytesRead": 0, "totalBytes": 0, "dest": dest_path,
    })

    try:
        headers = {"User-Agent": USER_AGENT}
        with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", "0") or "0")
            _set_download_state(appid, {"totalBytes": total})
            with open(dest_path, "wb") as out:
                for chunk in resp.iter_bytes():
                    if _is_download_cancelled(appid):
                        raise DownloadCancelled()
                    out.write(chunk)
                    state = _get_download_state(appid)
                    read = int(state.get("bytesRead", 0)) + len(chunk)
                    _set_download_state(appid, {"bytesRead": read})

        _set_download_state(appid, {"status": "processing"})
        _process_and_install_lua(appid, dest_path)
        fetched_name = _fetch_app_name(appid) or f"UNKNOWN ({appid})"
        _append_loaded_app(appid, fetched_name)
        _log_appid_event(f"ADDED - {api_name}", appid, fetched_name)
        _set_download_state(appid, {"status": "done", "success": True, "api": api_name})
        _run_post_install_audit(appid)

    except DownloadCancelled:
        _safe_remove(dest_path)
        _set_download_state(appid, {"status": "cancelled", "error": "Cancelled by user"})
    except Exception as exc:
        logger.warn(f"LuaTools: _download_zip_from_url failed for {appid}: {exc}")
        _set_download_state(appid, {"status": "failed", "error": str(exc)})


def start_add_via_luatools_from_url(appid: int, url: str, api_name: str) -> str:
    """Initiate a download from a specific URL selected by the user (API check result)."""
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})

    _set_download_state(appid, {"status": "queued", "bytesRead": 0, "totalBytes": 0, "error": None})
    thread = threading.Thread(
        target=_download_zip_from_url, args=(appid, url, api_name), daemon=True
    )
    thread.start()
    return json.dumps({"success": True})


# ── API availability check (upstream: CheckApisForApp) ────────────────────

def check_apis_for_app(appid: int) -> str:
    """Check all enabled APIs for a specific appid and return their availability.

    First tries a fast bulk-check endpoint; falls back to per-API HEAD/GET.
    """
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})

    client = ensure_http_client("LuaTools: check_apis")
    apis = load_api_manifest()
    if not apis:
        return json.dumps({"success": True, "results": []})

    morrenus_api_key = get_morrenus_api_key()
    fast_check_succeeded = False
    fast_check_data: dict = {}

    # Try bulk fast-check endpoint (Ryuu server)
    try:
        fast_resp = client.get(
            f"http://167.235.229.108/check_apis?appid={appid}",
            headers={"User-Agent": "secretgoonpoon"},
            timeout=5,
            follow_redirects=True,
        )
        if fast_resp.status_code == 200:
            fast_check_data = fast_resp.json()
            fast_check_succeeded = isinstance(fast_check_data, dict)
    except Exception as exc:
        logger.warn(f"LuaTools: Fast API check failed: {exc}")

    headers = {"User-Agent": USER_AGENT}
    results = []

    for api in apis:
        name = api.get("name", "Unknown")
        template = api.get("url", "")
        success_code = int(api.get("success_code", 200))

        if "<moapikey>" in template:
            if not morrenus_api_key:
                continue
            template = template.replace("<moapikey>", morrenus_api_key)

        url = template.replace("<appid>", str(appid))
        available = False

        if fast_check_succeeded:
            check_key = "Sadie (Morrenus)" if name.lower() == "morrenus" else name
            available = fast_check_data.get(check_key) == "available"
        else:
            try:
                if name.lower() == "morrenus":
                    status_url = (
                        f"https://manifest.morrenus.xyz/api/v1/status/{appid}"
                        f"?api_key={morrenus_api_key}"
                    )
                    resp = client.get(status_url, headers=headers, follow_redirects=True, timeout=5)
                    available = resp.status_code == success_code
                else:
                    resp = client.head(url, headers=headers, follow_redirects=True, timeout=5)
                    if resp.status_code == success_code:
                        available = True
                    elif resp.status_code == 405:  # HEAD not allowed
                        resp = client.get(url, headers=headers, follow_redirects=True, timeout=5)
                        available = resp.status_code == success_code
            except Exception:
                pass

        results.append({
            "name": name,
            "available": available,
            "url": url if available else None,
        })

    return json.dumps({"success": True, "results": results})


__all__ = [
    "cancel_add_via_luatools",
    "delete_luatools_for_app",
    "dismiss_loaded_apps",
    "fetch_app_name",
    "get_add_status",
    "get_games_database",
    "get_icon_data_url",
    "get_installed_lua_scripts",
    "has_luatools_for_app",
    "init_applist",
    "init_games_db",
    "read_loaded_apps",
    "start_add_via_luatools",
    "start_add_via_luatools_from_url",
    "check_apis_for_app",
]
