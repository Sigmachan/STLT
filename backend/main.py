"""LuaTools Ultimate  --  main plugin entry point.

Merges:
  • madoiscool/ltsteamplugin core (downloads, fixes, APIs, auto-update)
  • sigmachan modded extensions (Ryuu Premium, DepotBox Premium, themes)
  • clemdotla/steamtools-collection (collection sync, lua audit)
  • New: smart cache mgmt, backups, folder stats  --  all Win11 native
"""

import json
import os
import shutil
import sys
import threading
import webbrowser

from typing import Any

import Millennium  # type: ignore
import PluginUtils  # type: ignore

from api_manifest import (
    fetch_free_apis_now as api_fetch_free_apis_now,
    get_api_list as api_get_api_list,
    get_init_apis_message as api_get_init_message,
    init_apis as api_init_apis,
    store_last_message,
)
from custom_apis import get_custom_apis, save_custom_apis
from auto_update import (
    apply_pending_update_if_any,
    check_for_updates_now as auto_check_for_updates_now,
    restart_steam as auto_restart_steam,
    start_auto_update_background_check,
)
from config import WEBKIT_DIR_NAME, WEB_UI_ICON_FILE, WEB_UI_JS_FILE
from downloads import (
    cancel_add_via_luatools,
    check_apis_for_app,
    delete_luatools_for_app,
    dismiss_loaded_apps,
    get_add_status,
    get_icon_data_url,
    get_installed_lua_scripts,
    has_luatools_for_app,
    get_games_database,
    init_applist,
    read_loaded_apps,
    start_add_via_luatools,
    start_add_via_luatools_from_url,
)
from fixes import (
    apply_game_fix,
    cancel_apply_fix,
    check_for_fixes,
    get_apply_fix_status,
    get_installed_fixes,
    get_unfix_status,
    unfix_game,
)
from steamtools import (
    audit_lua_content,
    batch_health_scan,
    check_manifest_staleness,
    clean_cache,
    clean_lua_content,
    create_backup,
    delete_backup,
    detect_depot_conflicts,
    diagnose_app,
    export_diagnostic_report,
    extract_lua_keys,
    generate_dlc_config,
    get_cache_info,
    get_quick_dashboard,
    get_steam_folder_stats,
    get_steam_process_info,
    get_steamtools_ids,
    list_backups,
    restore_backup,
    scan_steam_libraries,
    smart_restart_steam,
    sync_depotcache,
    toggle_lua_script,
    update_manifests,
    validate_lua_syntax,
    get_achievement_info,
    seed_achievement_files,
    get_active_accounts,
    repair_depot_cache,
)
from utils import ensure_temp_download_dir
from http_client import close_http_client, ensure_http_client
from logger import logger as shared_logger
from paths import get_plugin_dir, public_path
from settings.manager import (
    apply_settings_changes,
    get_available_locales,
    get_settings_payload,
    get_steamtools_settings,
    get_translation_map,
    init_settings,
)
from steam_utils import detect_steam_install_path, get_game_install_path_response, open_game_folder
from steam_version import (
    get_steam_version_info as _sv_info,
    set_steam_update_block as _sv_set_block,
    list_steam_cfg_backups as _sv_backups,
)
from cloud_fix import (
    diagnose_cloud_fix as _cf_diagnose,
    remove_stella_fallback as _cf_remove_stella,
)

# ── New modules (v8.2+) ──────────────────────────────────────────────
from batch import start_batch as _batch_start, get_batch_status as _batch_status, cancel_batch as _batch_cancel, resume_batch as _batch_resume, pause_batch as _batch_pause, unpause_batch as _batch_unpause, skip_batch_item as _batch_skip_item
from events import get_hooks_config as _get_hooks, save_hooks_config as _save_hooks
from history import get_download_history_json as _get_history, get_download_stats_json as _get_dl_stats
from source_chain import get_source_chain_json as _get_chain, save_source_chain_json as _save_chain
from config_transfer import export_config as _export_config, import_config as _import_config
from account_transfer import (
    list_accounts as _at_list_accounts,
    inspect_game_data as _at_inspect,
    transfer_game_data as _at_transfer,
    restore_transfer_backup as _at_restore,
    list_game_data_backups as _at_list_backups,
)
from key_vault import (
    list_profiles as _kv_list,
    save_profile as _kv_save,
    load_profile as _kv_load,
    delete_profile as _kv_delete,
    export_profile as _kv_export,
    import_profile as _kv_import,
)
from sentinel import (
    start_sentinel as _sentinel_start,
    stop_sentinel as _sentinel_stop,
    get_sentinel_status as _sentinel_status,
    set_sentinel_config as _sentinel_config,
    ignore_game as _sentinel_ignore,
    unignore_game as _sentinel_unignore,
)
from mod_system import (
    get_mod_list as _get_mod_list,
    get_mod_file as _get_mod_file,
    toggle_mod as _toggle_mod,
    get_mod_loader_info as _get_mod_info,
    install_mod_from_url as _install_mod_url,
    uninstall_mod as _uninstall_mod,
)

logger = shared_logger


def GetPluginDir() -> str:  # Legacy API used by the frontend
    return get_plugin_dir()


class Logger:
    @staticmethod
    def log(message: str) -> str:
        shared_logger.log(f"[Frontend] {message}")
        return json.dumps({"success": True})

    @staticmethod
    def warn(message: str) -> str:
        shared_logger.warn(f"[Frontend] {message}")
        return json.dumps({"success": True})

    @staticmethod
    def error(message: str) -> str:
        shared_logger.error(f"[Frontend] {message}")
        return json.dumps({"success": True})


def _steam_ui_path() -> str:
    return os.path.join(Millennium.steam_path(), "steamui", WEBKIT_DIR_NAME)


def _copy_webkit_files() -> None:
    plugin_dir = get_plugin_dir()
    steam_ui_path = _steam_ui_path()
    os.makedirs(steam_ui_path, exist_ok=True)

    js_src = public_path(WEB_UI_JS_FILE)
    js_dst = os.path.join(steam_ui_path, WEB_UI_JS_FILE)
    logger.log(f"Copying LuaTools web UI from {js_src} to {js_dst}")
    try:
        shutil.copy(js_src, js_dst)
    except Exception as exc:
        logger.error(f"Failed to copy LuaTools web UI: {exc}")

    icon_src = public_path(WEB_UI_ICON_FILE)
    icon_dst = os.path.join(steam_ui_path, WEB_UI_ICON_FILE)
    if os.path.exists(icon_src):
        try:
            shutil.copy(icon_src, icon_dst)
            logger.log(f"Copied LuaTools icon to {icon_dst}")
        except Exception as exc:
            logger.error(f"Failed to copy LuaTools icon: {exc}")
    else:
        logger.warn(f"LuaTools icon not found at {icon_src}")

    # Copy theme CSS files
    themes_src = os.path.join(plugin_dir, "public", "themes")
    themes_dst = os.path.join(steam_ui_path, "themes")
    if os.path.exists(themes_src):
        try:
            os.makedirs(themes_dst, exist_ok=True)
            for filename in os.listdir(themes_src):
                if filename.endswith(".css"):
                    theme_src = os.path.join(themes_src, filename)
                    theme_dst = os.path.join(themes_dst, filename)
                    shutil.copy(theme_src, theme_dst)
                    logger.log(f"Copied theme file {filename} to {theme_dst}")
        except Exception as exc:
            logger.warn(f"Failed to copy theme files: {exc}")


def _millennium_version() -> str:
    """Return the running Millennium version, tolerant of API changes."""
    try:
        ver = Millennium.version()
        return str(ver) if ver is not None else "unknown"
    except Exception as exc:  # pragma: no cover - depends on host
        logger.warn(f"LuaTools: Millennium.version() unavailable: {exc}")
        return "unknown"


def _inject_webkit_files() -> None:
    js_path = os.path.join(WEBKIT_DIR_NAME, WEB_UI_JS_FILE)
    try:
        # Millennium 2.36+/3.0 returns an integer module id (0 on failure);
        # older builds returned None. A thrown exception must not abort
        # _load(), otherwise the plugin is flagged as failed to load.
        module_id = Millennium.add_browser_js(js_path)
        logger.log(f"LuaTools injected web UI: {js_path} (module={module_id})")
    except Exception as exc:
        logger.error(f"LuaTools: add_browser_js failed for {js_path}: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# ORIGINAL LUATOOLS API SURFACE (from madoiscool/ltsteamplugin + mods)
# ═══════════════════════════════════════════════════════════════════════════

def InitApis(contentScriptQuery: str = "") -> str:
    return api_init_apis(contentScriptQuery)

def GetInitApisMessage(contentScriptQuery: str = "") -> str:
    return api_get_init_message(contentScriptQuery)

def FetchFreeApisNow(contentScriptQuery: str = "") -> str:
    return api_fetch_free_apis_now(contentScriptQuery)

def CheckForUpdatesNow(contentScriptQuery: str = "") -> str:
    result = auto_check_for_updates_now()
    return json.dumps(result)

def RestartSteam(contentScriptQuery: str = "") -> str:
    success = auto_restart_steam()
    if success:
        return json.dumps({"success": True})
    return json.dumps({"success": False, "error": "Failed to restart Steam"})

def HasLuaToolsForApp(appid: int, contentScriptQuery: str = "") -> str:
    return has_luatools_for_app(appid)


def CheckApisForApp(appid: int, contentScriptQuery: str = "") -> str:
    """Check availability of all enabled download sources for a given appid."""
    return check_apis_for_app(appid)


def StartAddViaLuaToolsFromUrl(appid: int, url: str, apiName: str, contentScriptQuery: str = "") -> str:
    """Start a download directly from a URL returned by CheckApisForApp."""
    return start_add_via_luatools_from_url(appid, url, apiName)


MORRENUS_STATS_CACHE: dict = {}


def GetMorrenusStats(api_key: str, force_refresh: bool = False, contentScriptQuery: str = "", **kwargs: Any) -> str:
    """Fetch Morrenus account stats. Results are cached for 10 minutes."""
    import time
    global MORRENUS_STATS_CACHE

    if "force_refresh" in kwargs:
        force_refresh = bool(kwargs["force_refresh"])

    now = time.time()

    if not force_refresh:
        cached = MORRENUS_STATS_CACHE.get(api_key)
        if cached and (now - cached["time"] < 600):
            return cached["data"]

    try:
        from http_client import ensure_http_client
        client = ensure_http_client("LuaTools: GetMorrenusStats")
        resp = client.get(
            f"https://manifest.morrenus.xyz/api/v1/user/stats?api_key={api_key}",
            follow_redirects=True,
            timeout=10,
        )
        data = resp.text
        if resp.status_code == 200:
            MORRENUS_STATS_CACHE[api_key] = {"time": now, "data": data}
        return data
    except Exception as exc:
        logger.warn(f"LuaTools: GetMorrenusStats failed: {exc}")
        return json.dumps({"error": str(exc)})

def StartAddViaLuaTools(appid: int, contentScriptQuery: str = "") -> str:
    return start_add_via_luatools(appid)

def GetAddViaLuaToolsStatus(appid: int, contentScriptQuery: str = "") -> str:
    return get_add_status(appid)

def GetApiList(contentScriptQuery: str = "") -> str:
    return api_get_api_list(contentScriptQuery)

def CancelAddViaLuaTools(appid: int, contentScriptQuery: str = "") -> str:
    return cancel_add_via_luatools(appid)

def GetIconDataUrl(contentScriptQuery: str = "") -> str:
    return get_icon_data_url()

def GetGamesDatabase(contentScriptQuery: str = "") -> str:
    return get_games_database()

def ReadLoadedApps(contentScriptQuery: str = "") -> str:
    return read_loaded_apps()

def DismissLoadedApps(contentScriptQuery: str = "") -> str:
    return dismiss_loaded_apps()

def DeleteLuaToolsForApp(appid: int, contentScriptQuery: str = "") -> str:
    return delete_luatools_for_app(appid)

def CheckForFixes(appid: int, contentScriptQuery: str = "") -> str:
    return check_for_fixes(appid)

def ApplyGameFix(appid: int, downloadUrl: str, installPath: str, fixType: str = "", gameName: str = "", contentScriptQuery: str = "") -> str:
    return apply_game_fix(appid, downloadUrl, installPath, fixType, gameName)

def GetApplyFixStatus(appid: int, contentScriptQuery: str = "") -> str:
    return get_apply_fix_status(appid)

def CancelApplyFix(appid: int, contentScriptQuery: str = "") -> str:
    return cancel_apply_fix(appid)

def UnFixGame(appid: int, installPath: str = "", fixDate: str = "", contentScriptQuery: str = "") -> str:
    return unfix_game(appid, installPath, fixDate)

def GetUnfixStatus(appid: int, contentScriptQuery: str = "") -> str:
    return get_unfix_status(appid)

def GetInstalledFixes(contentScriptQuery: str = "") -> str:
    return get_installed_fixes()

def GetInstalledLuaScripts(contentScriptQuery: str = "") -> str:
    return get_installed_lua_scripts()

def GetGameInstallPath(appid: int, contentScriptQuery: str = "") -> str:
    result = get_game_install_path_response(appid)
    return json.dumps(result)

def OpenGameFolder(path: str, contentScriptQuery: str = "") -> str:
    success = open_game_folder(path)
    if success:
        return json.dumps({"success": True})
    return json.dumps({"success": False, "error": "Failed to open path"})

def OpenExternalUrl(url: str, contentScriptQuery: str = "") -> str:
    try:
        value = str(url or "").strip()
        if not (value.startswith("http://") or value.startswith("https://")):
            return json.dumps({"success": False, "error": "Invalid URL"})
        if sys.platform.startswith("win"):
            try:
                os.startfile(value)  # type: ignore[attr-defined]
            except Exception:
                webbrowser.open(value)
        else:
            webbrowser.open(value)
        return json.dumps({"success": True})
    except Exception as exc:
        logger.warn(f"LuaTools: OpenExternalUrl failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


# ═══════════════════════════════════════════════════════════════════════════
# SETTINGS API
# ═══════════════════════════════════════════════════════════════════════════

def GetSettingsConfig(contentScriptQuery: str = "") -> str:
    try:
        payload = get_settings_payload()
        response = {
            "success": True,
            "schemaVersion": payload.get("version"),
            "schema": payload.get("schema", []),
            "values": payload.get("values", {}),
            "language": payload.get("language"),
            "locales": payload.get("locales", []),
            "translations": payload.get("translations", {}),
        }
        return json.dumps(response)
    except Exception as exc:
        logger.warn(f"LuaTools: GetSettingsConfig failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def GetThemes(contentScriptQuery: str = "") -> str:
    """Return the full themes palette list for the frontend."""
    try:
        themes_path = os.path.join(get_plugin_dir(), 'public', 'themes', 'themes.json')
        if os.path.exists(themes_path):
            try:
                with open(themes_path, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    return json.dumps({"success": True, "themes": data})
            except Exception as exc:
                logger.warn(f"LuaTools: Failed to read themes.json: {exc}")
                return json.dumps({"success": False, "error": "Failed to read themes.json"})
        else:
            return json.dumps({"success": True, "themes": []})
    except Exception as exc:
        logger.warn(f"LuaTools: GetThemes failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def ApplySettingsChanges(
    _contentScriptQuery: str = "", changes: Any = None, **kwargs: Any
) -> str:
    try:
        if "changes" in kwargs and changes is None:
            changes = kwargs["changes"]
        if changes is None:
            changes = kwargs

        try:
            logger.log(
                "LuaTools: ApplySettingsChanges raw argument "
                f"type={type(changes)} value={changes!r}"
            )
            logger.log(f"LuaTools: ApplySettingsChanges kwargs: {kwargs}")
        except Exception:
            pass

        payload: Any = None

        if isinstance(changes, str) and changes:
            try:
                payload = json.loads(changes)
            except Exception:
                logger.warn("LuaTools: Failed to parse changes string payload")
                return json.dumps({"success": False, "error": "Invalid JSON payload"})
            else:
                if isinstance(payload, dict) and "changes" in payload:
                    payload = payload.get("changes")
                elif isinstance(payload, dict) and "changesJson" in payload and isinstance(payload["changesJson"], str):
                    try:
                        payload = json.loads(payload["changesJson"])
                    except Exception:
                        logger.warn("LuaTools: Failed to parse changesJson string inside payload")
                        return json.dumps({"success": False, "error": "Invalid JSON payload"})
        elif isinstance(changes, dict) and changes:
            if "changesJson" in changes and isinstance(changes["changesJson"], str):
                try:
                    payload = json.loads(changes["changesJson"])
                except Exception:
                    logger.warn("LuaTools: Failed to parse changesJson payload from dict")
                    return json.dumps({"success": False, "error": "Invalid JSON payload"})
            elif "changes" in changes:
                payload = changes.get("changes")
            else:
                payload = changes
        else:
            changes_json = kwargs.get("changesJson")
            if isinstance(changes_json, dict):
                payload = changes_json
            elif isinstance(changes_json, str) and changes_json:
                try:
                    payload = json.loads(changes_json)
                except Exception:
                    logger.warn("LuaTools: Failed to parse changesJson payload")
                    return json.dumps({"success": False, "error": "Invalid JSON payload"})
            else:
                payload = changes

        if payload is None:
            payload = {}
        elif not isinstance(payload, dict):
            logger.warn(f"LuaTools: Parsed payload is not a dict: {payload!r}")
            return json.dumps({"success": False, "error": "Invalid payload format"})

        try:
            logger.log(f"LuaTools: ApplySettingsChanges received payload: {payload}")
        except Exception:
            pass

        result = apply_settings_changes(payload)
        try:
            logger.log(f"LuaTools: ApplySettingsChanges result: {result}")
        except Exception:
            pass
        response = json.dumps(result)
        try:
            logger.log(f"LuaTools: ApplySettingsChanges response json: {response}")
        except Exception:
            pass
        return response
    except Exception as exc:
        logger.warn(f"LuaTools: ApplySettingsChanges failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def GetAvailableLocales(contentScriptQuery: str = "") -> str:
    try:
        locales = get_available_locales()
        return json.dumps({"success": True, "locales": locales})
    except Exception as exc:
        logger.warn(f"LuaTools: GetAvailableLocales failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def GetTranslations(contentScriptQuery: str = "", language: str = "", **kwargs: Any) -> str:
    try:
        if not language and "language" in kwargs:
            language = kwargs["language"]
        bundle = get_translation_map(language)
        bundle["success"] = True
        return json.dumps(bundle)
    except Exception as exc:
        logger.warn(f"LuaTools: GetTranslations failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def GetAvailableThemes(contentScriptQuery: str = "") -> str:
    """Return list of available theme CSS files."""
    try:
        themes_dir = os.path.join(get_plugin_dir(), "public", "themes")
        themes = []
        if os.path.exists(themes_dir):
            for filename in os.listdir(themes_dir):
                if filename.endswith(".css"):
                    theme_name = filename[:-4]
                    display_name = theme_name.capitalize()
                    themes.append({"value": theme_name, "label": display_name})
        themes.sort(key=lambda x: (x["value"] != "original", x["label"]))
        return json.dumps({"success": True, "themes": themes})
    except Exception as exc:
        logger.warn(f"LuaTools: GetAvailableThemes failed: {exc}")
        return json.dumps({"success": False, "error": str(exc), "themes": []})


# ═══════════════════════════════════════════════════════════════════════════
# STEAMTOOLS ULTIMATE API  (new  --  collection, cache, backup, audit)
# ═══════════════════════════════════════════════════════════════════════════

def GetSteamToolsIds(showDisabled: bool = False, contentScriptQuery: str = "") -> str:
    """Collection sync: return all appids from stplug-in (clemdotla port)."""
    return get_steamtools_ids(include_disabled=showDisabled)


def AuditLuaContent(appid: int, contentScriptQuery: str = "") -> str:
    """Verify depot/DLC/workshop completeness for a lua script."""
    return audit_lua_content(appid)


def GetCacheInfo(contentScriptQuery: str = "") -> str:
    """Get size info for all cleanable Steam cache categories."""
    return get_cache_info()


def CleanSteamCache(categories: str = "", contentScriptQuery: str = "") -> str:
    """Clean selected cache categories. Comma-separated keys or empty for all."""
    return clean_cache(categories)


def CreateBackup(label: str = "", contentScriptQuery: str = "") -> str:
    """Create timestamped backup of stplug-in + depotcache."""
    return create_backup(label)


def ListBackups(contentScriptQuery: str = "") -> str:
    """List available backups."""
    return list_backups()


def RestoreBackup(filename: str = "", contentScriptQuery: str = "") -> str:
    """Restore a backup zip."""
    return restore_backup(filename)


def DeleteBackup(filename: str = "", contentScriptQuery: str = "") -> str:
    """Delete a backup file."""
    return delete_backup(filename)


def GetSteamFolderStats(contentScriptQuery: str = "") -> str:
    """Disk usage breakdown for Steam directories."""
    return get_steam_folder_stats()


def ToggleLuaScript(appid: int, enable: bool = True, contentScriptQuery: str = "") -> str:
    """Enable or disable a lua script."""
    return toggle_lua_script(appid, enable)


def ValidateLuaSyntax(appid: int = 0, contentScriptQuery: str = "") -> str:
    """Validate .lua file syntax (cleanluas.ps1 port). appid=0 for batch mode."""
    return validate_lua_syntax(appid)


def UpdateManifests(appid: int = 0, contentScriptQuery: str = "") -> str:
    """Download missing/outdated .manifest files from ManifestHub mirror."""
    return update_manifests(appid)


def DiagnoseApp(appid: int = 0, contentScriptQuery: str = "") -> str:
    """Full diagnostic report: install, Goldberg, lua, manifests, updates."""
    return diagnose_app(appid)


def CleanLuaContent(appid: int = 0, contentScriptQuery: str = "") -> str:
    """Strip branding/credit comments from a .lua file."""
    return clean_lua_content(appid)


def ExtractLuaKeys(appid: int = 0, contentScriptQuery: str = "") -> str:
    """Extract depot keys, manifest IDs, tokens from a .lua file."""
    return extract_lua_keys(appid)


def BatchHealthScan(contentScriptQuery: str = "") -> str:
    """One-click health scan of ALL installed lua scripts."""
    return batch_health_scan()


def SmartRestartSteam(clearBeta: bool = True, contentScriptQuery: str = "") -> str:
    """Safely kill and restart Steam with optional -clearbeta."""
    return smart_restart_steam(clear_beta=clearBeta)


def ExportDiagnosticReport(appid: int = 0, contentScriptQuery: str = "") -> str:
    """Generate a formatted text diagnostic report for sharing."""
    return export_diagnostic_report(appid)


def DetectDepotConflicts(contentScriptQuery: str = "") -> str:
    """Find depot IDs referenced by multiple lua files (conflicts)."""
    return detect_depot_conflicts()


def GetSteamProcessInfo(contentScriptQuery: str = "") -> str:
    """Check if Steam is running, show PID and memory."""
    return get_steam_process_info()


def GetSteamVersionInfo(contentScriptQuery: str = "") -> str:
    """Steam build, SteamTools-compatibility and auto-update block state."""
    return _sv_info()


def SetSteamUpdateBlock(enabled: bool = True, contentScriptQuery: str = "") -> str:
    """Block or unblock Steam self-update via steam.cfg (reversible, backed up)."""
    return _sv_set_block(bool(enabled))


def ListSteamCfgBackups(contentScriptQuery: str = "") -> str:
    """List steam.cfg backups created by the version manager."""
    return _sv_backups()


def DiagnoseCloudFix(contentScriptQuery: str = "") -> str:
    """Read-only SteamTools cloud-save / fallback state diagnostic."""
    return _cf_diagnose()


def RemoveStellaFallback(contentScriptQuery: str = "") -> str:
    """Quarantine obsolete stella fallback remnants (reversible)."""
    return _cf_remove_stella()


def GetQuickDashboard(contentScriptQuery: str = "") -> str:
    """Combined stats: lua count, manifests, cache size, backup count."""
    return get_quick_dashboard()


def ScanSteamLibraries(contentScriptQuery: str = "") -> str:
    """Scan all drives for Steam libraries with game counts and sizes."""
    return scan_steam_libraries()


def CheckManifestStaleness(appid: int = 0, contentScriptQuery: str = "") -> str:
    """Check if installed manifests are outdated vs SteamCMD. appid=0 checks all."""
    return check_manifest_staleness(int(appid))


def GenerateDlcConfig(appid: int = 0, format: str = "creamapi", contentScriptQuery: str = "") -> str:
    """Generate CreamAPI/SmokeAPI/GreenLuma/CODEX DLC configs from Steam Store data."""
    return generate_dlc_config(int(appid), format)


def SyncDepotcache(appid: int = 0, contentScriptQuery: str = "") -> str:
    """Verify depotcache integrity and auto-fetch missing manifests via ManifestHub."""
    return sync_depotcache(int(appid))


def GetAchievementInfo(appid: int, contentScriptQuery: str = "") -> str:
    """Fetch achievement count and local schema file status for an appid.

    Queries Steam Web API (ISteamUserStats/GetSchemaForGame -- no key needed)
    and checks Steam/appcache/stats/ for UserGameStats*.bin files.
    """
    return get_achievement_info(appid)


def SeedAchievementFiles(appid: int, accountId32: int = 0, contentScriptQuery: str = "") -> str:
    """Seed empty UserGameStats_{accountId}_{appid}.bin in Steam/appcache/stats/.

    Seeds the minimal 38-byte stats template for each logged-in account.
    Steam downloads the schema binary automatically on first game launch.
    Pass accountId32=0 to seed for all accounts in loginusers.vdf.
    """
    return seed_achievement_files(appid, accountId32)


def GetActiveAccounts(contentScriptQuery: str = "") -> str:
    """Return Steam accounts from loginusers.vdf with schema file status."""
    return get_active_accounts()


def RepairDepotCache(appid: int = 0, fix_lua: bool = False,
                     remove_orphans: bool = True, orphan_age_days: int = 30,
                     dry_run: bool = False, contentScriptQuery: str = "") -> str:
    """Full depot cache repair pipeline.

    Phase 1 -- Scan: classify every .manifest as valid/corrupt/zero-byte/orphaned.
    Phase 2 -- Download: re-fetch missing and corrupt manifests from all sources.
    Phase 3 -- Cleanup: delete zero-byte, replaced corrupt, old orphaned, stplug-in junk.
    Phase 4 -- Lua fix: comment-out syntactically broken lines (only if fix_lua=True).

    dry_run=True reports what would be done without making any changes.
    """
    return repair_depot_cache(
        appid=int(appid),
        fix_lua=bool(fix_lua),
        remove_orphans=bool(remove_orphans),
        orphan_age_days=int(orphan_age_days),
        dry_run=bool(dry_run),
    )


# ── Account-to-account transfer (Denuvo tokens / cloud saves) ─────────────

def ListUserdataAccounts(contentScriptQuery: str = "") -> str:
    """Steam accounts with on-disk userdata folder. Includes size + app count."""
    return _at_list_accounts(contentScriptQuery)


def InspectGameUserdata(accountId32: int, appid: int,
                        contentScriptQuery: str = "") -> str:
    """Inspect <Steam>/userdata/<accountId>/<appid>/ -- file list + total size."""
    return _at_inspect(int(accountId32), int(appid), contentScriptQuery)


def TransferGameUserdata(fromAccountId32: int, toAccountId32: int,
                         appid: int, overwrite: bool = False,
                         backup: bool = True,
                         contentScriptQuery: str = "") -> str:
    """Copy a game's userdata folder from one account to another.

    Used to migrate Denuvo activation tokens or save files between two of your
    own Steam accounts without re-logging-in.

    Steam must be closed before transfer (otherwise the destination Steam
    will overwrite our copy on shutdown).
    """
    return _at_transfer(
        int(fromAccountId32), int(toAccountId32), int(appid),
        overwrite=bool(overwrite),
        backup_dest=bool(backup),
        contentScriptQuery=contentScriptQuery,
    )


def RestoreGameUserdataBackup(accountId32: int, appid: int,
                              backupPath: str = "",
                              contentScriptQuery: str = "") -> str:
    """Restore the most recent .bak-* userdata backup for an appid."""
    return _at_restore(int(accountId32), int(appid),
                       backup_path=backupPath,
                       contentScriptQuery=contentScriptQuery)


def ListUserdataBackups(contentScriptQuery: str = "") -> str:
    """List all .bak-* and .pre-restore-* userdata folders across accounts."""
    return _at_list_backups(contentScriptQuery)


# ── API key vault (Ryuu / DepotBox / Morrenus / etc. profiles) ────────────

def ListKeyProfiles(contentScriptQuery: str = "") -> str:
    """List saved key profiles with masked credentials + active marker."""
    return _kv_list(contentScriptQuery)


def SaveKeyProfile(name: str = "main", contentScriptQuery: str = "") -> str:
    """Snapshot the currently active API keys into a named profile."""
    return _kv_save(name, contentScriptQuery)


def LoadKeyProfile(name: str = "main", contentScriptQuery: str = "") -> str:
    """Apply the named profile's keys to current settings."""
    return _kv_load(name, contentScriptQuery)


def DeleteKeyProfile(name: str = "", contentScriptQuery: str = "") -> str:
    """Remove a profile from the vault (does not clear active settings)."""
    return _kv_delete(name, contentScriptQuery)


def ExportKeyProfile(name: str = "", contentScriptQuery: str = "") -> str:
    """Export a profile as a portable base64 .ltkeys blob."""
    return _kv_export(name, contentScriptQuery)


def ImportKeyProfile(blob: str = "", nameOverride: str = "",
                     activate: bool = False,
                     contentScriptQuery: str = "") -> str:
    """Import a profile from a base64 blob produced by ExportKeyProfile."""
    return _kv_import(blob, nameOverride, bool(activate), contentScriptQuery)


def GetCustomApis(contentScriptQuery: str = "") -> str:
    """Return user-defined custom API endpoints."""
    return get_custom_apis()


def SaveCustomApis(apis_json: str = "[]", contentScriptQuery: str = "") -> str:
    """Save user-defined custom API endpoints."""
    return save_custom_apis(apis_json)


# ═══════════════════════════════════════════════════════════════════════════
# BATCH PIPELINE (v8.2+)
# ═══════════════════════════════════════════════════════════════════════════

def StartBatchDownload(appids_json: str = "[]", parallel: int = 3,
                       max_retries: int = 2, delay: float = 1.0,
                       priority_json: str = "[]", skip_installed: bool = True,
                       force: bool = False, contentScriptQuery: str = "") -> str:
    """Start batch download of multiple appids with concurrency control."""
    try:
        appids = json.loads(appids_json) if isinstance(appids_json, str) else appids_json
        priority = json.loads(priority_json) if isinstance(priority_json, str) else priority_json
        return _batch_start(appids, parallel=int(parallel), max_retries=int(max_retries),
                              skip_installed=bool(skip_installed), force=bool(force),
                            delay=float(delay), priority_appids=priority)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def GetBatchStatus(contentScriptQuery: str = "") -> str:
    """Get aggregate batch progress: total/done/failed/active/ETA."""
    return _batch_status()


def CancelBatch(contentScriptQuery: str = "") -> str:
    """Cancel running batch download."""
    return _batch_cancel()


def PauseBatch(contentScriptQuery: str = "") -> str:
    """Pause the running batch  --  in-flight downloads finish, no new ones start."""
    return _batch_pause()


def UnpauseBatch(contentScriptQuery: str = "") -> str:
    """Resume a paused batch."""
    return _batch_unpause()


def SkipBatchItem(appid: int, contentScriptQuery: str = "") -> str:
    """Skip a specific queued appid in the running batch."""
    return _batch_skip_item(int(appid))


def ResumeBatch(contentScriptQuery: str = "") -> str:
    """Resume a persisted batch queue after restart."""
    return _batch_resume()


# ═══════════════════════════════════════════════════════════════════════════
# EVENT HOOKS (v8.2+)
# ═══════════════════════════════════════════════════════════════════════════

def GetHooksConfig(contentScriptQuery: str = "") -> str:
    """Get webhook/exec hook configuration."""
    return _get_hooks()


def SaveHooksConfig(config_json: str = "{}", contentScriptQuery: str = "") -> str:
    """Save webhook/exec hook configuration."""
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
        _save_hooks(config)
        return json.dumps({"success": True})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


# ═══════════════════════════════════════════════════════════════════════════
# DOWNLOAD HISTORY (v8.2+)
# ═══════════════════════════════════════════════════════════════════════════

def GetDownloadHistory(appid: int = 0, limit: int = 50, status: str = "",
                       source: str = "", contentScriptQuery: str = "") -> str:
    """Query download history. appid=0 returns all."""
    return _get_history(appid=int(appid), limit=int(limit), status=status, source=source)


def GetDownloadStats(contentScriptQuery: str = "") -> str:
    """Aggregate download statistics  --  by source, by status, avg duration."""
    return _get_dl_stats()


def PruneHistory(days: int = 30, contentScriptQuery: str = "") -> str:
    """Delete history records older than `days` days (keeps newest per appid)."""
    from history import prune_history_json
    return prune_history_json(days=int(days))


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE CHAIN CONFIG (v8.2+)
# ═══════════════════════════════════════════════════════════════════════════

def GetSourceChain(contentScriptQuery: str = "") -> str:
    """Get download source priority chain (reorderable by user)."""
    return _get_chain()


def SaveSourceChain(chain_json: str = "{}", contentScriptQuery: str = "") -> str:
    """Save customized source chain order and settings."""
    return _save_chain(chain_json)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG EXPORT/IMPORT (v8.2+)
# ═══════════════════════════════════════════════════════════════════════════

def ExportConfig(contentScriptQuery: str = "") -> str:
    """Export full plugin config as JSON (settings, chain, hooks, APIs)."""
    return _export_config()


def ImportConfig(config_json: str = "{}", contentScriptQuery: str = "") -> str:
    """Import plugin config from JSON. Merges with existing."""
    return _import_config(config_json)


# ═══════════════════════════════════════════════════════════════════════════
# MOD SYSTEM (v8.2+  --  Kite-compatible)
# ═══════════════════════════════════════════════════════════════════════════

def GetModList(contentScriptQuery: str = "") -> str:
    """Scan mods/ directory and return available mods with enable/disable state."""
    return _get_mod_list()


def GetModFile(mod_id: str = "", filename: str = "", contentScriptQuery: str = "") -> str:
    """Read a mod file (JS/CSS) with path traversal protection."""
    return _get_mod_file(mod_id, filename)


def ToggleMod(mod_id: str = "", enabled: bool = True, contentScriptQuery: str = "") -> str:
    """Enable or disable a mod."""
    return _toggle_mod(mod_id, enabled)


def GetModLoaderInfo(contentScriptQuery: str = "") -> str:
    """Return mod loader version, mods directory, count."""
    return _get_mod_info()


def InstallModFromUrl(url: str = "", contentScriptQuery: str = "") -> str:
    """Download and install a mod from a GitHub ZIP URL."""
    return _install_mod_url(url)


def UninstallMod(mod_id: str = "", contentScriptQuery: str = "") -> str:
    """Remove an installed mod completely."""
    return _uninstall_mod(mod_id)


# ═══════════════════════════════════════════════════════════════════════════
# SENTINEL DAEMON (v9.0) — Background automation
# ═══════════════════════════════════════════════════════════════════════════

def StartSentinel(contentScriptQuery: str = "") -> str:
    """Start LuaTools Sentinel background daemon."""
    return _sentinel_start()


def StopSentinel(contentScriptQuery: str = "") -> str:
    """Stop LuaTools Sentinel background daemon."""
    return _sentinel_stop()


def GetSentinelStatus(contentScriptQuery: str = "") -> str:
    """Get Sentinel daemon status and configuration."""
    return _sentinel_status()


def SetSentinelConfig(config_json: str = "{}", contentScriptQuery: str = "") -> str:
    """Update Sentinel configuration (enable/disable, poll interval, etc.)."""
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
        return _sentinel_config(config)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def IgnoreGameNotifications(appid: int, contentScriptQuery: str = "") -> str:
    """Add game to Sentinel ignore list (don't notify about it)."""
    return _sentinel_ignore(int(appid))


def UnignoreGameNotifications(appid: int, contentScriptQuery: str = "") -> str:
    """Remove game from Sentinel ignore list."""
    return _sentinel_unignore(int(appid))


# ═══════════════════════════════════════════════════════════════════════════
# PLUGIN LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════

class Plugin:
    def _front_end_loaded(self):
        _copy_webkit_files()

    def _deferred_bootstrap(self):
        """Network-heavy startup work, executed off the load thread.

        Millennium 2.36+/3.0 flags a plugin as "failed to load" if _load()
        blocks the main thread (e.g. the applist/GitHub/API-manifest network
        fetches, which can hang for minutes on a slow connection). All such
        I/O must run *after* Millennium.ready().
        """
        try:
            message = apply_pending_update_if_any()
            if message:
                store_last_message(message)
        except Exception as exc:
            logger.warn(f"AutoUpdate: apply pending failed: {exc}")

        try:
            init_applist()
        except Exception as exc:
            logger.warn(f"LuaTools: Applist initialization failed: {exc}")

        try:
            result = InitApis("boot")
            logger.log(f"InitApis (boot) return: {result}")
        except Exception as exc:
            logger.error(f"InitApis (boot) failed: {exc}")

        try:
            start_auto_update_background_check()
        except Exception as exc:
            logger.warn(f"AutoUpdate: start background check failed: {exc}")

        # ── Start Sentinel daemon (v9.0) when enabled in settings ─────────
        try:
            settings = get_steamtools_settings()
            if settings.get("sentinelEnabled"):
                StartSentinel()
                logger.log("LuaTools: Sentinel daemon started")
            else:
                logger.log("LuaTools: Sentinel disabled by settings")
        except Exception as exc:
            logger.warn(f"LuaTools: Sentinel startup failed: {exc}")

    def _load(self):
        logger.log(
            f"bootstrapping LuaTools Ultimate v8.3-fixed, millennium {_millennium_version()}"
        )

        # ── Fast, local-only setup (must complete before ready()) ──────────
        try:
            detect_steam_install_path()
        except Exception as exc:
            logger.warn(f"LuaTools: steam path detection failed: {exc}")

        ensure_http_client("InitApis")
        ensure_temp_download_dir()

        try:
            init_settings()
        except Exception as exc:
            logger.warn(f"LuaTools: settings initialization failed: {exc}")

        _copy_webkit_files()
        _inject_webkit_files()

        # ── Defer all network I/O so ready() is reached immediately ────────
        try:
            threading.Thread(
                target=self._deferred_bootstrap,
                name="LuaToolsDeferredBootstrap",
                daemon=True,
            ).start()
        except Exception as exc:
            logger.error(f"LuaTools: failed to start deferred bootstrap: {exc}")
            self._deferred_bootstrap()

        Millennium.ready()

    def _unload(self):
        # ── Stop Sentinel daemon gracefully ───────────────────────────────
        try:
            StopSentinel()
        except Exception:
            pass

        logger.log("unloading")
        close_http_client("InitApis")


plugin = Plugin()
