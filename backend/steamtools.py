"""SteamTools integration module for LuaTools Ultimate.

All operations are Windows 11 native  --  no WSL, no bash, no background daemons.
Every function runs on-demand (zero-bloat, trigger-only).

Features:
  1. Collection sync     --  scan stplug-in, return appid list for frontend
  2. Lua content audit    --  verify depots, DLC, workshop presence in .lua files
  3. Lua syntax validator  --  port of clemdotla/cleanluas.ps1 line-level checker
  4. Manifest updater      --  download missing/outdated manifests from ManifestHub mirror
  5. Smart cache clean     --  targeted removal with achievement/playtime preservation
  6. Backup / restore      --  snapshot stplug-in + depotcache to timestamped zip
  7. Folder stats          --  disk usage per Steam subdirectory
  8. Toggle scripts        --  enable/disable lua without deleting
  9. Diagnostic report     --  per-app health check (Goldberg, install, lua, updates)
"""

from __future__ import annotations

import datetime
import sys
import json
import os
import re
import shutil
import threading
import zipfile
from typing import Any, Dict, List, Optional, Set, Tuple

import Millennium  # type: ignore

from http_client import ensure_http_client
from logger import logger
from paths import data_path, steam_localappdata_dir
try:
    from config import USER_AGENT
except Exception:  # pragma: no cover - defensive fallback for standalone use
    USER_AGENT = "LuaTools/1.0"
from steam_utils import detect_steam_install_path, _parse_vdf_simple
from steam_version import _steam_is_running


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _steam_path() -> str:
    return detect_steam_install_path() or Millennium.steam_path() or ""

def _stplug_dir() -> str:
    base = _steam_path()
    return os.path.join(base, "config", "stplug-in") if base else ""

def _dir_size(path: str) -> int:
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                try: total += os.path.getsize(os.path.join(dirpath, f))
                except OSError: pass
    except Exception: pass
    return total

def _read_lua_file(appid: int) -> Tuple[Optional[str], str]:
    stplug = _stplug_dir()
    if not stplug: return None, "Steam path not found"
    for ext in (".lua", ".lua.disabled"):
        p = os.path.join(stplug, f"{appid}{ext}")
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read(), p
            except Exception as exc: return None, str(exc)
    return None, "Lua file not found"

# Manifest magic bytes (ported from SFF/integrity.py)
_MANIFEST_MAGIC = b'\x27\x44\x56\x01'

def _verify_manifest_magic(filepath: str) -> bool:
    """Check if a .manifest file starts with Steam's magic bytes."""
    try:
        with open(filepath, "rb") as fh:
            magic = fh.read(4)
            return magic == _MANIFEST_MAGIC
    except Exception:
        return False

def _find_manifest_file(base: str, depot_id: str, manifest_id: str) -> Optional[str]:
    """Search for a manifest in both depotcache locations (ported from SFF/steam_tools_compat.py).

    Steam uses two paths: depotcache/ (primary) and config/depotcache/ (alternate).
    """
    fname = f"{depot_id}_{manifest_id}.manifest"
    for subdir in ("depotcache", os.path.join("config", "depotcache")):
        fp = os.path.join(base, subdir, fname)
        if os.path.isfile(fp) and os.path.getsize(fp) > 0:
            return fp
    return None

def _scan_all_steam_libraries(base: str) -> List[str]:
    """Find all Steam library paths across all drives (ported from SFF/library_scanner.py).

    Reads libraryfolders.vdf + scans common locations on every drive letter.
    """
    paths: List[str] = [base]

    # 1. Parse libraryfolders.vdf
    vdf_path = os.path.join(base, "config", "libraryfolders.vdf")
    if os.path.isfile(vdf_path):
        try:
            with open(vdf_path, "r", encoding="utf-8") as fh:
                data = _parse_vdf_simple(fh.read())
            for v in data.get("libraryfolders", {}).values():
                if isinstance(v, dict):
                    p = v.get("path", "").replace("\\\\", "\\")
                    if p and os.path.isdir(p) and p not in paths:
                        paths.append(p)
        except Exception:
            pass

    # 2. Scan all drive letters for common Steam library locations (Windows only)
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\"
            if not os.path.isdir(drive):
                continue
            for candidate in (
                os.path.join(drive, "SteamLibrary"),
                os.path.join(drive, "Steam"),
                os.path.join(drive, "Games", "Steam"),
            ):
                steamapps = os.path.join(candidate, "steamapps")
                if os.path.isdir(steamapps) and candidate not in paths:
                    paths.append(candidate)

    return paths


def _find_game_install_by_folder(folder_name: str, main_exe: str = "") -> str:
    """Find a Steam library game folder by folder name, optionally verifying an exe."""
    folder_name = str(folder_name or "").strip()
    main_exe = str(main_exe or "").strip()
    if not folder_name or any(sep in folder_name for sep in ("/", "\\")) or ".." in folder_name:
        return ""
    if main_exe and ("/" in main_exe or "\\" in main_exe or ".." in main_exe):
        return ""

    base = _steam_path()
    if not base:
        return ""

    for lib_path in _scan_all_steam_libraries(base):
        common = os.path.join(lib_path, "steamapps", "common")
        if not os.path.isdir(common):
            continue

        candidates = [os.path.join(common, folder_name)]
        try:
            for entry in os.listdir(common):
                if entry.lower() == folder_name.lower():
                    candidate = os.path.join(common, entry)
                    if candidate not in candidates:
                        candidates.append(candidate)
        except Exception:
            pass

        for candidate in candidates:
            if not os.path.isdir(candidate):
                continue
            if main_exe and not os.path.isfile(os.path.join(candidate, main_exe)):
                continue
            return candidate

    return ""


# ═══════════════════════════════════════════════════════════════════════════
# 1. COLLECTION SYNC
# ═══════════════════════════════════════════════════════════════════════════

def get_steamtools_ids(include_disabled: bool = False) -> str:
    try:
        stplug = _stplug_dir()
        if not stplug or not os.path.isdir(stplug):
            return json.dumps({"success": True, "ids": [], "csv": "", "count": 0})
        ids: List[int] = []
        for entry in os.listdir(stplug):
            if not entry.endswith(".lua") and not entry.endswith(".lua.disabled"): continue
            if not include_disabled and entry.endswith(".lua.disabled"): continue
            m = re.match(r"^(\d+)\.lua", entry)
            if m: ids.append(int(m.group(1)))
        ids.sort()
        return json.dumps({"success": True, "ids": ids, "csv": ",".join(str(i) for i in ids), "count": len(ids)})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


# ═══════════════════════════════════════════════════════════════════════════
# 2. LUA CONTENT AUDIT
# ═══════════════════════════════════════════════════════════════════════════

_APP_INFO_CACHE: Dict[int, Dict] = {}
_APP_INFO_LOCK = threading.Lock()

def _fetch_app_info_from_steamcmd(appid: int) -> Dict[str, Any]:
    with _APP_INFO_LOCK:
        if appid in _APP_INFO_CACHE and _APP_INFO_CACHE[appid]:
            return _APP_INFO_CACHE[appid]
    client = ensure_http_client("SteamTools: app_info")
    try:
        resp = client.get(f"https://api.steamcmd.net/v1/info/{appid}", follow_redirects=True, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        if isinstance(data, dict):
            root = data.get(str(appid), {})
            output = {
                "workshop_depot": root.get("depots", {}).get("workshopdepot", 0),
                "dlc_list": root.get("extended", {}).get("listofdlc", ""),
                "depots": root.get("depots", {}),
                "name": root.get("common", {}).get("name", ""),
            }
            with _APP_INFO_LOCK: _APP_INFO_CACHE[appid] = output
            return output
    except Exception as exc:
        logger.warn(f"SteamTools: _fetch_app_info failed for {appid}: {exc}")
    with _APP_INFO_LOCK: _APP_INFO_CACHE[appid] = {}
    return {}

def audit_lua_content(appid: int) -> str:
    try: appid = int(appid)
    except Exception: return json.dumps({"success": False, "error": "Invalid appid"})
    content, lua_path = _read_lua_file(appid)
    if content is None: return json.dumps({"success": False, "error": lua_path})

    # Collect depot IDs + their line text (upstream improvement: dict with ids + lines)
    depot_ids: List[int] = []
    depot_lines: Dict[str, str] = {}
    for line in content.splitlines():
        if re.match(r"^\s*--", line): continue
        m = re.search(r"addappid\(\s*(\d+)", line)
        if m:
            did = m.group(1)
            depot_ids.append(int(did))
            depot_lines[did] = line

    info = _fetch_app_info_from_steamcmd(appid)
    ws_depot = str(info.get("workshop_depot", 0))
    if ws_depot == "0" or not ws_depot:
        ws_status, ws_label = "no_workshop", "No workshop for this game ✅"
    else:
        # Upstream improved check: workshop depot must be in depot IDs
        # AND its line must contain a decryption key (pattern: ,digit,"key")
        if ws_depot in depot_lines and re.search(r',\d+,["\']', depot_lines[ws_depot].replace(" ", "")):
            ws_status, ws_label = "included", "Workshop included 🎉"
        elif ws_depot in [str(d) for d in depot_ids]:
            ws_status, ws_label = "partial", "Workshop depot present but no key ⚠️"
        else:
            ws_status, ws_label = "missing", "Workshop missing ❌"

    dlc_inc, dlc_miss = [], []
    raw_dlc = str(info.get("dlc_list", "")).strip()
    if raw_dlc:
        for piece in raw_dlc.split(","):
            piece = piece.strip()
            if piece.isdigit():
                (dlc_inc if int(piece) in depot_ids else dlc_miss).append(int(piece))

    return json.dumps({"success": True, "appid": appid,
        "workshop": {"status": ws_status, "label": ws_label},
        "dlc": {"included": dlc_inc, "missing": dlc_miss, "total": len(dlc_inc)+len(dlc_miss)},
        "depotCount": len(depot_ids)})


# ═══════════════════════════════════════════════════════════════════════════
# 3. LUA SYNTAX VALIDATOR  (ported from cleanluas.ps1)
# ═══════════════════════════════════════════════════════════════════════════

def _is_valid_lua_line(line: str) -> Tuple[bool, str]:
    trimmed = line.strip()
    if not trimmed or trimmed.startswith("-"): return True, ""
    if re.match(r"(?i)^addtoken", trimmed): return True, ""

    func_match = re.match(r"(?i)^(addappid|setManifestid)\s*(\(.*)", trimmed)
    if func_match:
        func_name, rest = func_match.group(1), func_match.group(2)
        before_comment = rest.split("--")[0] if "--" in rest else rest
        depth, close_pos = 0, -1
        for i, ch in enumerate(before_comment):
            if ch == "(": depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0: close_pos = i; break
        if close_pos < 0: return False, f"Unmatched parenthesis in {func_name}()"
        after = before_comment[close_pos+1:].strip()
        if after and not after.startswith("--"):
            return False, f"Content after {func_name}() closing paren"
        paren_content = before_comment[1:close_pos]
        without_quotes = re.sub(r'"[^"]*"', "", paren_content)
        if re.search(r"[a-fA-F0-9]{40,}", without_quotes):
            return False, f"Unquoted hex hash in {func_name}()"
        return True, ""
    return False, f"Unrecognized statement: {trimmed[:60]}"

def validate_lua_syntax(appid: int = 0) -> str:
    stplug = _stplug_dir()
    if not stplug or not os.path.isdir(stplug):
        return json.dumps({"success": False, "error": "stplug-in not found"})
    targets: List[str] = []
    if appid:
        for ext in (".lua", ".lua.disabled"):
            p = os.path.join(stplug, f"{appid}{ext}")
            if os.path.isfile(p): targets.append(p); break
        if not targets: return json.dumps({"success": False, "error": f"Lua not found for {appid}"})
    else:
        targets = [os.path.join(stplug, f) for f in os.listdir(stplug) if f.endswith(".lua") or f.endswith(".lua.disabled")]
    non_lua = [f for f in os.listdir(stplug) if os.path.isfile(os.path.join(stplug,f)) and not f.endswith(".lua") and not f.endswith(".lua.disabled")]
    results: List[Dict[str,Any]] = []
    total_bad = 0
    for fp in sorted(targets):
        fn = os.path.basename(fp)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as fh: lines = fh.readlines()
        except Exception as exc:
            results.append({"filename": fn, "valid": False, "error": str(exc), "badLines": []}); total_bad += 1; continue
        bad = [{"line": i, "content": l.rstrip()[:120], "reason": r} for i, l in enumerate(lines, 1) for ok, r in [_is_valid_lua_line(l)] if not ok]
        if bad: total_bad += 1
        results.append({"filename": fn, "valid": len(bad)==0, "lineCount": len(lines), "badLines": bad})
    return json.dumps({"success": True, "filesChecked": len(results), "filesWithErrors": total_bad, "nonLuaFiles": non_lua, "results": results})


# ═══════════════════════════════════════════════════════════════════════════
# 4. MANIFEST UPDATER  (ported from manifests.ps1 backup mode)
# ═══════════════════════════════════════════════════════════════════════════

_MH_BACKUP_URL = "https://raw.githubusercontent.com/qwe213312/k25FCdfEOoEJ42S6/main"
_MORRENUS_MANIFEST_URL = "https://manifest.morrenus.xyz/api/v1/generate/manifest"
_MANIFESTHUB_API_URL = "https://api.manifesthub1.filegear-sg.me/manifest"

def _get_depot_ids_from_lua(content: str) -> List[str]:
    depots: Set[str] = set()
    for line in content.splitlines():
        m = re.search(r'addappid\s*\(\s*(\d+)\s*,\s*\d+\s*,\s*"[a-fA-F0-9]+"', line)
        if m: depots.add(m.group(1))
    return sorted(depots)

def _get_manifest_id(depots_data: Dict, depot_id: str) -> Optional[str]:
    d = depots_data.get(depot_id, {})
    if not isinstance(d, dict): return None
    m = d.get("manifests", {})
    if not isinstance(m, dict): return None
    pub = m.get("public")
    if isinstance(pub, dict): return str(pub.get("gid", ""))
    if isinstance(pub, str) and pub.strip(): return pub.strip()
    return None

def update_manifests(appid: int) -> str:
    try: appid = int(appid)
    except Exception: return json.dumps({"success": False, "error": "Invalid appid"})
    content, err = _read_lua_file(appid)
    if content is None: return json.dumps({"success": False, "error": err})
    depot_ids = _get_depot_ids_from_lua(content)
    if not depot_ids: return json.dumps({"success": False, "error": "No depot IDs in lua"})
    info = _fetch_app_info_from_steamcmd(appid)
    depots_data = info.get("depots", {})
    if not depots_data: return json.dumps({"success": False, "error": "No depot info from steamcmd"})
    base = _steam_path()
    dc = os.path.join(base, "depotcache"); os.makedirs(dc, exist_ok=True)
    client = ensure_http_client("SteamTools: manifests")
    dl, sk, fl = [], [], []
    for did in depot_ids:
        mid = _get_manifest_id(depots_data, did)
        if not mid: fl.append({"depotId": did, "reason": "No public manifest"}); continue
        dest = os.path.join(dc, f"{did}_{mid}.manifest")
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            sk.append({"depotId": did, "manifestId": mid}); continue
        # Multi-source fallback: GitHub mirror -> Morrenus API -> ManifestHub API
        # (mirrors manifests.ps1 logic from lt_api_links)
        downloaded = False
        fail_reason = ""

        def _try_fetch(url: str, extra_headers: Optional[Dict] = None) -> Optional[bytes]:
            try:
                h = {"User-Agent": USER_AGENT}
                if extra_headers:
                    h.update(extra_headers)
                r = client.get(url, headers=h, follow_redirects=True, timeout=30)
                if r.status_code == 200 and len(r.content) > 0:
                    return r.content
            except Exception:
                pass
            return None

        # Source 1: GitHub mirror
        data = _try_fetch(f"{_MH_BACKUP_URL}/{did}_{mid}.manifest")

        # Source 2: Morrenus API (if key configured)
        if data is None:
            from settings.manager import get_morrenus_api_key
            mo_key = get_morrenus_api_key()
            if mo_key:
                data = _try_fetch(
                    f"{_MORRENUS_MANIFEST_URL}?depot_id={did}&manifest_id={mid}&api_key={mo_key}"
                )

        # Source 3: ManifestHub API (if key configured)
        if data is None:
            from settings.manager import get_manifesthub_api_key
            mh_key = get_manifesthub_api_key()
            if mh_key:
                data = _try_fetch(
                    f"{_MANIFESTHUB_API_URL}?apikey={mh_key}&depotid={did}&manifestid={mid}"
                )

        if data is not None:
            with open(dest, "wb") as fh:
                fh.write(data)
            dl.append({"depotId": did, "manifestId": mid, "sizeBytes": len(data)})
        else:
            fl.append({"depotId": did, "manifestId": mid, "reason": "All sources failed (GitHub / Morrenus / ManifestHub)"})
    return json.dumps({"success": True, "appid": appid, "downloaded": dl, "skipped": sk, "failed": fl,
        "summary": {"total": len(depot_ids), "downloaded": len(dl), "skipped": len(sk), "failed": len(fl)}})


# ═══════════════════════════════════════════════════════════════════════════
# 5. SMART CACHE CLEAN  (preserves achievements + playtime per fix-st.ps1)
# ═══════════════════════════════════════════════════════════════════════════

_CACHE_TARGETS: Dict[str, Dict[str, Any]] = {
    "htmlcache": {"paths": [("steam","htmlcache"),("localappdata","htmlcache")],
        "label": "CEF / HTML Cache", "description": "Browser cache"},
    "shadercache": {"paths": [("steam",os.path.join("steamapps","shadercache")),("localappdata","shadercache")],
        "label": "Shader Pre-cache", "description": "Vulkan / DX shader cache"},
    "downloadcache": {"paths": [("steam",os.path.join("steamapps","downloading")),("steam",os.path.join("steamapps","temp"))],
        "label": "Download Staging", "description": "Incomplete downloads and temp"},
    "appcache": {"paths": [("steam","appcache")],
        "label": "App Cache", "description": "Metadata cache (rebuilds on launch)",
        "preserve": ["stats"]},
    "depotcache": {"paths": [("steam","depotcache")],
        "label": "Depot Cache", "description": "Manifest cache files"},
    "logs": {"paths": [("steam","logs")],
        "label": "Steam Logs", "description": "Client log files"},
    "usercache": {"paths": [("steam","userdata")],
        "label": "User Config Cache", "description": "Per-user config (preserves playtime)",
        "preserve_files": ["localconfig.vdf"], "target_subdir": "config"},
}

def _resolve_cache_path(root_type: str, rel: str) -> str:
    if root_type == "steam": base = _steam_path()
    elif root_type == "localappdata": base = steam_localappdata_dir()
    else: return ""
    return os.path.join(base, rel) if base else ""

def _safe_remove_contents(path: str, preserve_dirs=None, preserve_files=None, target_subdir=None) -> int:
    if not os.path.isdir(path): return 0
    pd = set(d.lower() for d in (preserve_dirs or []))
    pf = set(f.lower() for f in (preserve_files or []))
    before = _dir_size(path)
    if target_subdir:
        for uid in os.listdir(path):
            up = os.path.join(path, uid)
            if not os.path.isdir(up): continue
            st = os.path.join(up, target_subdir)
            if not os.path.isdir(st): continue
            saved = {}
            for fn in pf:
                fp = os.path.join(st, fn)
                if os.path.isfile(fp):
                    try:
                        with open(fp, "rb") as fh: saved[fn] = fh.read()
                    except Exception: pass
            try: shutil.rmtree(st, ignore_errors=True)
            except Exception: pass
            if saved:
                os.makedirs(st, exist_ok=True)
                for fn, data in saved.items():
                    try:
                        with open(os.path.join(st, fn), "wb") as fh: fh.write(data)
                    except Exception: pass
    else:
        for item in os.listdir(path):
            ip = os.path.join(path, item); il = item.lower()
            if il in pd and os.path.isdir(ip): continue
            if il in pf and os.path.isfile(ip): continue
            try:
                if os.path.isfile(ip) or os.path.islink(ip): os.remove(ip)
                elif os.path.isdir(ip): shutil.rmtree(ip, ignore_errors=True)
            except Exception: pass
    return max(0, before - _dir_size(path))

def get_cache_info() -> str:
    result: Dict[str, Any] = {}; total = 0
    for key, cfg in _CACHE_TARGETS.items():
        cs = 0; resolved = []
        for rt, rel in cfg["paths"]:
            p = _resolve_cache_path(rt, rel)
            if p and os.path.isdir(p): cs += _dir_size(p); resolved.append(p)
        result[key] = {"label": cfg["label"], "description": cfg["description"],
            "sizeBytes": cs, "sizeMB": round(cs/(1024*1024),2), "paths": resolved}
        total += cs
    return json.dumps({"success": True, "categories": result, "totalBytes": total, "totalMB": round(total/(1024*1024),2)})

def clean_cache(categories: str = "") -> str:
    requested = [c.strip() for c in str(categories).split(",") if c.strip()] or list(_CACHE_TARGETS.keys())
    freed = 0; errors = {}; cleaned = {}; preserved_info = {}
    for key in requested:
        cfg = _CACHE_TARGETS.get(key)
        if not cfg: errors[key] = "Unknown category"; continue
        pd = cfg.get("preserve",[]); pf = cfg.get("preserve_files",[]); ts = cfg.get("target_subdir")
        if pd or pf: preserved_info[key] = pd + pf
        cf = 0
        for rt, rel in cfg["paths"]:
            p = _resolve_cache_path(rt, rel)
            if p and os.path.isdir(p):
                try: cf += _safe_remove_contents(p, preserve_dirs=pd, preserve_files=pf, target_subdir=ts)
                except Exception as exc: errors[key] = str(exc)
        cleaned[key] = cf; freed += cf
    return json.dumps({"success": True, "freedBytes": freed, "freedMB": round(freed/(1024*1024),2),
        "cleaned": cleaned, "preserved": preserved_info or None, "errors": errors or None})


# ═══════════════════════════════════════════════════════════════════════════
# 6. BACKUP / RESTORE
# ═══════════════════════════════════════════════════════════════════════════

def _backup_dir() -> str: return data_path("luatools_backups")

def create_backup(label: str = "") -> str:
    base = _steam_path()
    if not base: return json.dumps({"success": False, "error": "Steam path not found"})
    stplug = os.path.join(base,"config","stplug-in"); depot = os.path.join(base,"depotcache")
    if not os.path.isdir(stplug) and not os.path.isdir(depot): return json.dumps({"success": False, "error": "Nothing to backup"})
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sl = re.sub(r"[^\w\-]","_",str(label).strip())[:32] if label else ""
    fname = f"backup_{stamp}{'_'+sl if sl else ''}.zip"
    bd = _backup_dir(); os.makedirs(bd, exist_ok=True); zp = os.path.join(bd, fname)
    fc = 0
    try:
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for sd, ap in [(stplug,"stplug-in"),(depot,"depotcache")]:
                if not os.path.isdir(sd): continue
                for dp, _d, fs in os.walk(sd):
                    for f in fs: full=os.path.join(dp,f); zf.write(full, os.path.join(ap, os.path.relpath(full,sd))); fc+=1
        sz = os.path.getsize(zp)
        return json.dumps({"success": True, "path": zp, "filename": fname, "fileCount": fc, "sizeBytes": sz, "sizeMB": round(sz/(1024*1024),2)})
    except Exception as exc: return json.dumps({"success": False, "error": str(exc)})

def list_backups() -> str:
    bd = _backup_dir()
    if not os.path.isdir(bd): return json.dumps({"success": True, "backups": [], "count": 0})
    bk = []
    for e in sorted(os.listdir(bd), reverse=True):
        if not e.endswith(".zip"): continue
        fp = os.path.join(bd,e)
        try:
            st = os.stat(fp)
            bk.append({"filename":e,"path":fp,"sizeBytes":st.st_size,"sizeMB":round(st.st_size/(1024*1024),2),
                "created":datetime.datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")})
        except Exception: pass
    return json.dumps({"success": True, "backups": bk, "count": len(bk)})

def restore_backup(filename: str) -> str:
    zp = os.path.join(_backup_dir(), filename)
    if not os.path.isfile(zp): return json.dumps({"success": False, "error": "Not found"})
    base = _steam_path()
    if not base: return json.dumps({"success": False, "error": "Steam path not found"})
    try:
        rc = 0
        with zipfile.ZipFile(zp, "r") as zf:
            for info in zf.infolist():
                if info.is_dir(): continue
                parts = info.filename.split("/", 1)
                if len(parts) < 2: continue
                pfx, rel = parts
                if pfx == "stplug-in": dd = os.path.join(base,"config","stplug-in")
                elif pfx == "depotcache": dd = os.path.join(base,"depotcache")
                else: continue
                dest = os.path.join(dd, rel); os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(info) as s, open(dest,"wb") as d: d.write(s.read()); rc+=1
        return json.dumps({"success": True, "restoredFiles": rc})
    except Exception as exc: return json.dumps({"success": False, "error": str(exc)})

def delete_backup(filename: str) -> str:
    zp = os.path.join(_backup_dir(), filename)
    if not os.path.isfile(zp): return json.dumps({"success": False, "error": "Not found"})
    try: os.remove(zp); return json.dumps({"success": True})
    except Exception as exc: return json.dumps({"success": False, "error": str(exc)})


# ═══════════════════════════════════════════════════════════════════════════
# 7. FOLDER STATS
# ═══════════════════════════════════════════════════════════════════════════

def get_steam_folder_stats() -> str:
    base = _steam_path()
    if not base: return json.dumps({"success": False, "error": "Steam path not found"})
    tgts = {k: os.path.join(base,k) for k in ("steamapps","config","depotcache","appcache","htmlcache","logs","userdata")}
    la = steam_localappdata_dir()
    if la and os.path.isdir(la): tgts["localappdata_steam"] = la
    stats = {}; total = 0
    for k,p in tgts.items():
        if os.path.isdir(p):
            s = _dir_size(p); stats[k] = {"path":p,"sizeBytes":s,"sizeMB":round(s/(1024*1024),2),"sizeGB":round(s/(1024**3),2)}; total+=s
        else: stats[k] = {"path":p,"sizeBytes":0,"sizeMB":0,"sizeGB":0,"exists":False}
    return json.dumps({"success":True,"steamPath":base,"folders":stats,"totalBytes":total,"totalGB":round(total/(1024**3),2)})


# ═══════════════════════════════════════════════════════════════════════════
# 8. TOGGLE LUA SCRIPTS
# ═══════════════════════════════════════════════════════════════════════════

def toggle_lua_script(appid: int, enable: bool = True) -> str:
    try: appid = int(appid)
    except Exception: return json.dumps({"success": False, "error": "Invalid appid"})
    stplug = _stplug_dir()
    if not stplug: return json.dumps({"success": False, "error": "Steam path not found"})
    lp = os.path.join(stplug, f"{appid}.lua"); dp = lp + ".disabled"
    if enable:
        if os.path.isfile(dp): os.rename(dp, lp); return json.dumps({"success": True, "state": "enabled"})
        elif os.path.isfile(lp): return json.dumps({"success": True, "state": "already_enabled"})
        return json.dumps({"success": False, "error": "Lua file not found"})
    else:
        if os.path.isfile(lp): os.rename(lp, dp); return json.dumps({"success": True, "state": "disabled"})
        elif os.path.isfile(dp): return json.dumps({"success": True, "state": "already_disabled"})
        return json.dumps({"success": False, "error": "Lua file not found"})


# ═══════════════════════════════════════════════════════════════════════════
# 9. DIAGNOSTIC REPORT  (ported from Devuvo.ps1)
# ═══════════════════════════════════════════════════════════════════════════

_GB_SIGS = [
    # Config / indicator files (from Devuvo.ps1)
    "steam_settings", "steam_interfaces.txt", "coldclientloader.ini",
    "ColdClientLoader.ini", "local_save.txt", "configs.user.ini",
    # Backup DLLs left by patchers
    "steam_api.dll.bak", "steam_api64.dll.bak",
]

# Files that conflict with SteamTools activation (other cracks / emulators)
# Source: Devuvo.ps1 § 5b  --  conflicting files scan
_CONFLICTING_FILES = [
    "winmm.dll", "xinput1_3.dll", "xinput1_4.dll", "xinput9_1_0.dll",
    "dinput8.dll", "winhttp.dll", "iphlpapi.dll", "dsound.dll",
    "cream_api.ini", "steam_api_o.dll", "steam_api64_o.dll",
    "steamclient_loader.exe", "codex.cfg", "codex64.dll",
    "3dmgame.dll", "ali213.ini", "valve.ini", "hlm.ini",
    "denuvo.dll", "unsteam.ini", "unsteam.dll",
]

# ── Achievement schema infrastructure (ported from SLScheevo) ─────────────
# Public Steam accounts with large libraries used to fetch stats schemas.
# These accounts have opted into public profiles — SLScheevo project, MIT license.
_STEAMID64_BASE = 76561197960265728  # Valve's public SteamID64 offset

_TOP_OWNER_IDS: List[int] = [
    76561198028121353, 76561197979911851, 76561198017975643, 76561197993544755,
    76561198355953202, 76561198001237877, 76561198237402290, 76561198152618007,
    76561198355625888, 76561198213148949, 76561197969050296, 76561198217186687,
    76561198037867621, 76561198094227663, 76561198019712127, 76561197963550511,
    76561198134044398, 76561198001678750, 76561197973009892, 76561198044596404,
    76561197976597747, 76561197969810632, 76561198095049646, 76561198085065107,
    76561198864213876, 76561197962473290, 76561198388522904, 76561198033715344,
    76561197995070100, 76561198313790296, 76561198063574735, 76561197996432822,
    76561197976968076, 76561198281128349, 76561198154462478, 76561198027233260,
    76561198842864763, 76561198010615256, 76561198035900006, 76561198122859224,
    76561198235911884, 76561198027214426, 76561197970825215, 76561197968410781,
    76561198104323854, 76561198001221571, 76561198256917957, 76561198008181611,
    76561198407953371, 76561198062901118,
]

# Minimal valid Steam UserGameStats binary (38-byte template — empty stats record).
# Steam accepts this as "user has no stats recorded yet" for any game.
# Reverse-engineered from SLScheevo's UserGameStats_TEMPLATE.bin.
_USERGAMESTATS_TEMPLATE = bytes([
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
])

# ── Unreleased games registry (ported from Devuvo.ps1 2026-04-16) ─────────────
# Games not yet on Steam -- no appmanifest exists. Detected by folder name + exe.
# Add new entries as pre-release titles become available.
_UNRELEASED_GAMES: Dict[int, Dict[str, str]] = {
    3357650: {
        "folderName": "PRAGMATA",
        "gameName":   "PRAGMATA",
        "mainExe":    "PRAGMATA.exe",
    },
}

def diagnose_app(appid: int) -> str:
    try: appid = int(appid)
    except Exception: return json.dumps({"success": False, "error": "Invalid appid"})
    base = _steam_path()
    if not base: return json.dumps({"success": False, "error": "Steam path not found"})

    report: Dict[str, Any] = {"appid": appid, "gameName": "", "installed": False,
        "installPath": "", "folderSizeMB": 0,
        "luaFile": {"found": False, "path": "", "syntaxValid": None, "disabled": False},
        "goldberg": {"detected": False, "files": []},
        "conflictingFiles": [],
        "updatesDisabled": False,
        "manifestStatus": {"total": 0, "present": 0, "missing": 0, "corrupt": 0},
        "contentAudit": None,
        "fixesAvailable": {"generic": False, "online": False},
    }
    ip = ""

    # Game install -- check for unreleased game first
    unreleased_meta = _UNRELEASED_GAMES.get(appid)
    if unreleased_meta:
        report["gameName"] = unreleased_meta["gameName"]
        report["isUnreleased"] = True
        ip = _find_game_install_by_folder(
            unreleased_meta["folderName"], unreleased_meta["mainExe"]
        )
        if ip:
            report["installed"] = True
            report["installPath"] = ip
            logger.log(f"LuaTools: Unreleased game {appid} found at {ip}")
        else:
            logger.log(
                f"LuaTools: Unreleased game {appid} folder '{unreleased_meta['folderName']}' "
                "not found in any Steam library"
            )
    else:
        from steam_utils import get_game_install_path_response
        pr = get_game_install_path_response(appid)
        if pr.get("success"):
            ip = pr.get("installPath", "")
            report["installed"] = True; report["installPath"] = ip
        if ip and os.path.isdir(ip):
            report["folderSizeMB"] = round(_dir_size(ip)/(1024*1024), 2)
            gb_found: List[str] = []
            cf_found: List[str] = []
            for dp, _ds, fs in os.walk(ip):
                depth = dp.count(os.sep) - ip.count(os.sep)
                fl_lower = {f.lower(): f for f in fs}
                # Goldberg: indicator files + folder names
                for sig in _GB_SIGS:
                    if sig.lower() in fl_lower:
                        gb_found.append(os.path.relpath(os.path.join(dp, fl_lower[sig.lower()]), ip))
                    if os.path.basename(dp).lower() == sig.lower():
                        gb_found.append(os.path.relpath(dp, ip) + os.sep)
                # Goldberg: check steam_api.dll / steam_api64.dll for patched DLL signature
                for dll_name in ("steam_api.dll", "steam_api64.dll"):
                    if dll_name in fl_lower:
                        dll_path = os.path.join(dp, fl_lower[dll_name])
                        try:
                            # Read PE version strings (minimal  --  look for "Goldberg" in first 64KB)
                            with open(dll_path, "rb") as fh:
                                header = fh.read(65536)
                            if b"Goldberg" in header or b"goldberg" in header:
                                rel = os.path.relpath(dll_path, ip)
                                if rel not in gb_found:
                                    gb_found.append(f"{rel} (patched DLL)")
                        except Exception:
                            pass
                # Conflicting files: other crack DLLs / configs
                for cf in _CONFLICTING_FILES:
                    if cf.lower() in fl_lower:
                        cf_found.append(os.path.relpath(os.path.join(dp, fl_lower[cf.lower()]), ip))
                # Also catch any file with "unsteam" in name
                for fname in fs:
                    if "unsteam" in fname.lower():
                        rel = os.path.relpath(os.path.join(dp, fname), ip)
                        if rel not in cf_found:
                            cf_found.append(rel)
                if depth > 3:
                    break
            if gb_found:
                report["goldberg"] = {"detected": True, "files": gb_found[:20]}
            if cf_found:
                report["conflictingFiles"] = cf_found[:20]

    # AutoUpdate check
    try:
        _pr = locals().get("pr") or {}
        lp = _pr.get("libraryPath","")
        if lp:
            mf = os.path.join(lp,"steamapps",f"appmanifest_{appid}.acf")
            if os.path.isfile(mf):
                with open(mf,"r",encoding="utf-8") as fh: md = _parse_vdf_simple(fh.read())
                report["updatesDisabled"] = str(md.get("AppState",{}).get("AutoUpdateBehavior","0")) == "2"
    except Exception: pass

    # Lua file
    stplug = _stplug_dir()
    for ext, dis in [(".lua", False), (".lua.disabled", True)]:
        p = os.path.join(stplug, f"{appid}{ext}") if stplug else ""
        if p and os.path.isfile(p):
            report["luaFile"] = {"found": True, "path": p, "syntaxValid": None, "disabled": dis}; break

    if report["luaFile"]["found"]:
        try:
            sr = json.loads(validate_lua_syntax(appid))
            if sr.get("success"):
                report["luaFile"]["syntaxValid"] = all(r.get("valid",False) for r in sr.get("results",[]))
        except Exception: pass
        try:
            ar = json.loads(audit_lua_content(appid))
            if ar.get("success"):
                report["contentAudit"] = {"workshop":ar.get("workshop",{}),"dlc":ar.get("dlc",{}),"depotCount":ar.get("depotCount",0)}
                info = _APP_INFO_CACHE.get(appid,{})
                if info.get("name"): report["gameName"] = info["name"]
        except Exception: pass

        # Manifest status (dual depotcache + magic bytes from SFF)
        content, _ = _read_lua_file(appid)
        if content:
            dids = _get_depot_ids_from_lua(content)
            info = _fetch_app_info_from_steamcmd(appid); dd = info.get("depots",{})
            t=p2=mi=corrupt=0
            for did in dids:
                mid = _get_manifest_id(dd, did)
                if mid:
                    t += 1
                    fp = _find_manifest_file(base, str(did), str(mid))
                    if fp:
                        if _verify_manifest_magic(fp):
                            p2 += 1
                        else:
                            corrupt += 1
                    else:
                        mi += 1
            report["manifestStatus"] = {"total":t,"present":p2,"missing":mi,"corrupt":corrupt}

    # Fix availability check
    try:
        from fixes import _fetch_fixes_index
        index = _fetch_fixes_index()
        if index:
            report["fixesAvailable"]["generic"] = appid in index.get("generic", set())
            report["fixesAvailable"]["online"] = appid in index.get("online", set())
    except Exception:
        pass

    return json.dumps({"success": True, "report": report})


# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# 10. LUA CONTENT CLEANER  (ported from SteamAppInserter clean_lua_content)
# ═══════════════════════════════════════════════════════════════════════════

_REMOVE_PATTERNS = [
    r'--\s*manifest\s*(&|and)\s*lua\s*provided\s*by',
    r'--\s*via\s+manilua', r'--\s*https?://',
    r'--\s*provided\s+by', r'--\s*source:',
    r'^--\s*dlc\s*$', r'^--\s*={3,}',
    r'--\s*credits:', r'--\s*discord:', r'--\s*website:',
    r'--\s*k3rn', r'--\s*kernelos',
]

def clean_lua_content(appid: int) -> str:
    """Strip branding/credit comments from a .lua file. Writes cleaned version back.

    Ported from SteamAppInserter's clean_lua_content().
    """
    try: appid = int(appid)
    except Exception: return json.dumps({"success": False, "error": "Invalid appid"})
    content, err = _read_lua_file(appid)
    if content is None: return json.dumps({"success": False, "error": err})

    lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    cleaned, removed_count = [], 0
    for line in lines:
        stripped = line.strip()
        if not stripped: continue
        skip = False
        if stripped.startswith('--'):
            for pat in _REMOVE_PATTERNS:
                if re.search(pat, stripped, re.IGNORECASE):
                    skip = True; removed_count += 1; break
        if not skip: cleaned.append(line)

    if removed_count == 0:
        return json.dumps({"success": True, "removedLines": 0, "message": "Already clean"})

    # Write back
    stplug = _stplug_dir()
    for ext in (".lua", ".lua.disabled"):
        p = os.path.join(stplug, f"{appid}{ext}")
        if os.path.isfile(p):
            try:
                result = '\n'.join(cleaned).rstrip('\r\n')
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(result + '\n' if result else '')
                return json.dumps({"success": True, "removedLines": removed_count, "path": p})
            except Exception as exc:
                return json.dumps({"success": False, "error": str(exc)})
    return json.dumps({"success": False, "error": "File not found for write-back"})


# ═══════════════════════════════════════════════════════════════════════════
# 11. DLC KEY EXTRACTION  (ported from SteamAppInserter)
# ═══════════════════════════════════════════════════════════════════════════

def extract_lua_keys(appid: int) -> str:
    """Extract all decryption keys and manifest IDs from a .lua file.

    Returns structured JSON with depot keys, manifest IDs, and all referenced appids.
    Ported from SteamAppInserter's extract_keys_from_lua_content / extract_manifest_ids_from_lua.
    """
    try: appid = int(appid)
    except Exception: return json.dumps({"success": False, "error": "Invalid appid"})
    content, err = _read_lua_file(appid)
    if content is None: return json.dumps({"success": False, "error": err})

    # Depot keys: addappid(id, 0, "key")
    keys: Dict[str, str] = {}
    for m in re.finditer(r'addappid\(\s*(\d+)\s*,\s*\d+\s*,\s*"([^"]+)"\s*\)', content):
        keys[m.group(1)] = m.group(2).strip()

    # Manifest IDs: setManifestid(id, "manifestid")
    manifests: Dict[str, str] = {}
    for m in re.finditer(r'setManifestid\(\s*(\d+)\s*,\s*"([^"]+)"\s*\)', content):
        manifests[m.group(1)] = m.group(2).strip()

    # All referenced appids (excluding main)
    all_ids = []
    for m in re.finditer(r'addappid\(\s*(\d+)', content):
        aid = m.group(1)
        if aid != str(appid) and aid not in all_ids:
            all_ids.append(aid)

    # Tokens: addtoken(id, "value")
    tokens: Dict[str, str] = {}
    for m in re.finditer(r'addtoken\(\s*(\d+)\s*,\s*"([^"]+)"\s*\)', content):
        tokens[m.group(1)] = m.group(2).strip()

    return json.dumps({
        "success": True, "appid": appid,
        "depotKeys": keys,
        "manifestIds": manifests,
        "tokens": tokens,
        "referencedAppIds": all_ids,
        "summary": {
            "totalDepots": len(keys),
            "totalManifests": len(manifests),
            "totalTokens": len(tokens),
            "totalReferenced": len(all_ids),
        },
    })


# ═══════════════════════════════════════════════════════════════════════════
# 12. BATCH HEALTH SCAN  (one-click full audit of every installed lua)
# ═══════════════════════════════════════════════════════════════════════════

def batch_health_scan() -> str:
    """Run a comprehensive health check on ALL installed .lua scripts.

    For each file: syntax validation + content audit + manifest presence.
    Returns a single dashboard-ready JSON report.
    """
    stplug = _stplug_dir()
    if not stplug or not os.path.isdir(stplug):
        return json.dumps({"success": False, "error": "stplug-in not found"})

    base = _steam_path()

    # Collect all appids
    appids: List[int] = []
    for f in os.listdir(stplug):
        m = re.match(r"^(\d+)\.lua", f)
        if m:
            appids.append(int(m.group(1)))
    appids.sort()

    # Run syntax validation (batch)
    syntax_map: Dict[int, Dict] = {}
    try:
        sr = json.loads(validate_lua_syntax(0))
        if sr.get("success"):
            for r in sr.get("results", []):
                fn = r.get("filename", "")
                m2 = re.match(r"^(\d+)\.lua", fn)
                if m2:
                    syntax_map[int(m2.group(1))] = r
    except Exception:
        pass

    results: List[Dict[str, Any]] = []
    totals = {"total": len(appids), "healthy": 0, "warnings": 0, "errors": 0}

    for appid in appids:
        entry: Dict[str, Any] = {"appid": appid, "status": "healthy", "issues": []}

        # Syntax
        syn = syntax_map.get(appid, {})
        if not syn.get("valid", True):
            bad_count = len(syn.get("badLines", []))
            entry["issues"].append(f"Syntax errors: {bad_count} bad line(s)")
            entry["status"] = "error"

        # Content audit
        try:
            ar = json.loads(audit_lua_content(appid))
            if ar.get("success"):
                ws = ar.get("workshop", {})
                dlc = ar.get("dlc", {})
                entry["depotCount"] = ar.get("depotCount", 0)
                entry["gameName"] = _APP_INFO_CACHE.get(appid, {}).get("name", "")
                if ws.get("status") == "missing":
                    entry["issues"].append("Workshop depot missing")
                    if entry["status"] == "healthy":
                        entry["status"] = "warning"
                missing_dlc = len(dlc.get("missing", []))
                if missing_dlc > 0:
                    entry["issues"].append(f"{missing_dlc} DLC missing")
                    if entry["status"] == "healthy":
                        entry["status"] = "warning"
        except Exception:
            pass

        # Manifest check
        # Manifest check (dual depotcache + magic bytes from SFF)
        if base:
            content, _ = _read_lua_file(appid)
            if content:
                dids = _get_depot_ids_from_lua(content)
                info = _fetch_app_info_from_steamcmd(appid)
                dd = info.get("depots", {})
                manifest_missing = 0
                manifest_corrupt = 0
                for did in dids:
                    mid = _get_manifest_id(dd, did)
                    if mid:
                        fp = _find_manifest_file(base, str(did), str(mid))
                        if not fp:
                            manifest_missing += 1
                        elif not _verify_manifest_magic(fp):
                            manifest_corrupt += 1
                if manifest_missing > 0:
                    entry["issues"].append(f"{manifest_missing} manifest(s) missing")
                    if entry["status"] == "healthy":
                        entry["status"] = "warning"
                if manifest_corrupt > 0:
                    entry["issues"].append(f"{manifest_corrupt} manifest(s) corrupt (bad magic bytes)")
                    entry["status"] = "error"

        if entry["status"] == "healthy":
            totals["healthy"] += 1
        elif entry["status"] == "warning":
            totals["warnings"] += 1
        else:
            totals["errors"] += 1

        results.append(entry)

    return json.dumps({"success": True, "results": results, "totals": totals})


# ═══════════════════════════════════════════════════════════════════════════
# 13. SMART STEAM RESTART  (safe restart with -clearbeta option)
# ═══════════════════════════════════════════════════════════════════════════

def smart_restart_steam(clear_beta: bool = True) -> str:
    """Check if Steam is running, kill it, restart with optional -clearbeta.

    Ported from multiple clemdotla/madoiscool PS1 scripts into Python.
    Windows-only, no WSL.
    """
    if not sys.platform.startswith("win"):
        return json.dumps({
            "success": False,
            "error": ("Smart Steam restart uses Windows taskkill / detached "
                      "process spawn; Linux uses different process management. "
                      "Please restart Steam manually for now."),
            "platform": "linux", "shelved": True,
        })
    import subprocess

    base = _steam_path()
    if not base:
        return json.dumps({"success": False, "error": "Steam path not found"})

    steam_exe = os.path.join(base, "steam.exe")
    if not os.path.isfile(steam_exe):
        return json.dumps({"success": False, "error": "steam.exe not found"})

    # Check if Steam is running
    was_running = False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        was_running = "steam.exe" in result.stdout.lower()
    except Exception:
        pass

    # Kill Steam processes
    killed = False
    if was_running:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "steam.exe"],
                capture_output=True, timeout=10,
                creationflags=0x08000000,
            )
            killed = True
            import time as _time
            _time.sleep(3)  # Wait for processes to fully terminate
        except Exception as exc:
            return json.dumps({"success": False, "error": f"Failed to kill Steam: {exc}"})

    # Restart
    args = [steam_exe]
    if clear_beta:
        args.append("-clearbeta")

    try:
        subprocess.Popen(
            args,
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
        return json.dumps({
            "success": True,
            "wasRunning": was_running,
            "killed": killed,
            "clearBeta": clear_beta,
            "message": "Steam restarted" + (" with -clearbeta" if clear_beta else ""),
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": f"Failed to start Steam: {exc}"})


# ═══════════════════════════════════════════════════════════════════════════
# 14. EXPORT DIAGNOSTIC REPORT  (shareable text for discord/support)
# ═══════════════════════════════════════════════════════════════════════════

def export_diagnostic_report(appid: int) -> str:
    """Generate a formatted text report suitable for pasting into Discord.

    Runs DiagnoseApp internally and formats the output as a code block.
    """
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})

    try:
        raw = json.loads(diagnose_app(appid))
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})

    if not raw.get("success"):
        return json.dumps(raw)

    r = raw.get("report", {})
    lines = [
        f"=== LuaTools Diagnostic Report ===",
        f"AppID:        {r.get('appid', '?')}",
        f"Game:         {r.get('gameName', 'Unknown')}",
        f"Installed:    {'Yes' if r.get('installed') else 'No'}",
    ]
    if r.get("installed"):
        lines.append(f"Path:         {r.get('installPath', '?')}")
        lines.append(f"Folder Size:  {r.get('folderSizeMB', 0)} MB")

    lua = r.get("luaFile", {})
    lines.append(f"Lua File:     {'Found' if lua.get('found') else 'Missing'}"
                 + (" (DISABLED)" if lua.get("disabled") else ""))
    if lua.get("found"):
        sv = lua.get("syntaxValid")
        lines.append(f"Syntax:       {'Valid ✓' if sv else ('Errors ✗' if sv is False else 'Not checked')}")

    ca = r.get("contentAudit")
    if ca:
        ws = ca.get("workshop", {})
        dlc = ca.get("dlc", {})
        lines.append(f"Depots:       {ca.get('depotCount', 0)}")
        lines.append(f"Workshop:     {ws.get('label', '?')}")
        lines.append(f"DLC Included: {len(dlc.get('included', []))}")
        lines.append(f"DLC Missing:  {len(dlc.get('missing', []))}")

    ms = r.get("manifestStatus", {})
    if ms.get("total", 0) > 0:
        issues_parts = []
        if ms.get("missing", 0): issues_parts.append(f"{ms['missing']} missing")
        if ms.get("corrupt", 0): issues_parts.append(f"{ms['corrupt']} corrupt")
        suffix = " (" + ", ".join(issues_parts) + ")" if issues_parts else " ✓"
        lines.append(f"Manifests:    {ms.get('present', 0)}/{ms.get('total', 0)} present" + suffix)

    gb = r.get("goldberg", {})
    lines.append(f"Goldberg:     {'Detected ⚠' if gb.get('detected') else 'Not found'}")
    lines.append(f"Updates Off:  {'Yes' if r.get('updatesDisabled') else 'No'}")

    fx = r.get("fixesAvailable", {})
    fixes_parts = []
    if fx.get("generic"): fixes_parts.append("Generic ✓")
    if fx.get("online"): fixes_parts.append("Online ✓")
    lines.append(f"Fixes Avail:  {', '.join(fixes_parts) if fixes_parts else 'None'}")
    lines.append(f"================================")
    lines.append(f"LuaTools Ultimate v{_plugin_version()}")

    text = "\n".join(lines)
    return json.dumps({"success": True, "text": text, "appid": appid})


# ═══════════════════════════════════════════════════════════════════════════
# 15. DEPOT CONFLICT DETECTOR
# ═══════════════════════════════════════════════════════════════════════════

def detect_depot_conflicts() -> str:
    """Scan all .lua files and find depot IDs referenced by multiple files.

    Conflicts indicate potential issues  --  e.g. two games claiming the same depot.
    """
    stplug = _stplug_dir()
    if not stplug or not os.path.isdir(stplug):
        return json.dumps({"success": False, "error": "stplug-in not found"})

    # Map: depot_id -> list of appids that reference it
    depot_map: Dict[str, List[int]] = {}
    file_count = 0

    for f in os.listdir(stplug):
        if not f.endswith(".lua") and not f.endswith(".lua.disabled"):
            continue
        m = re.match(r"^(\d+)\.lua", f)
        if not m:
            continue
        appid = int(m.group(1))
        file_count += 1
        fp = os.path.join(stplug, f)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if re.match(r"^\s*--", line):
                        continue
                    dm = re.search(r'addappid\(\s*(\d+)\s*,\s*\d+\s*,\s*"', line)
                    if dm:
                        did = dm.group(1)
                        if did != str(appid):  # skip self-references
                            depot_map.setdefault(did, []).append(appid)
        except Exception:
            pass

    conflicts: List[Dict[str, Any]] = []
    for depot_id, owners in sorted(depot_map.items()):
        if len(owners) > 1:
            conflicts.append({"depotId": depot_id, "referencedBy": sorted(set(owners))})

    return json.dumps({
        "success": True,
        "filesScanned": file_count,
        "conflictsFound": len(conflicts),
        "conflicts": conflicts,
    })


# ═══════════════════════════════════════════════════════════════════════════
# 16. STEAM PROCESS INFO  (read-only diagnostic)
# ═══════════════════════════════════════════════════════════════════════════

def get_steam_process_info() -> str:
    """Check if Steam is running, show PID, exe path, memory usage."""
    import subprocess

    result: Dict[str, Any] = {"running": False, "processes": []}
    if not sys.platform.startswith("win"):
        # Linux: detect via /proc, skip Windows-only memory accounting
        try:
            result["running"] = _steam_is_running()
        except Exception:
            pass
        result["platform"] = "linux"
        return json.dumps(result)
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,
        )
        for line in out.stdout.strip().splitlines():
            parts = line.strip('"').split('","')
            if len(parts) >= 5 and "steam" in parts[0].lower():
                mem_str = parts[4].replace('"', '').replace(' K', '').replace(',', '').strip()
                try:
                    mem_kb = int(mem_str)
                except ValueError:
                    mem_kb = 0
                result["processes"].append({
                    "name": parts[0],
                    "pid": int(parts[1]) if parts[1].isdigit() else 0,
                    "memoryKB": mem_kb,
                    "memoryMB": round(mem_kb / 1024, 1),
                })
        result["running"] = len(result["processes"]) > 0
        result["totalMemoryMB"] = round(sum(p["memoryMB"] for p in result["processes"]), 1)
    except Exception as exc:
        result["error"] = str(exc)

    # Also check SteamService
    try:
        out2 = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steamservice.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,
        )
        result["serviceRunning"] = "steamservice" in out2.stdout.lower()
    except Exception:
        result["serviceRunning"] = False

    return json.dumps({"success": True, **result})


# ═══════════════════════════════════════════════════════════════════════════
# 17. QUICK DASHBOARD  (combined stats overview)
# ═══════════════════════════════════════════════════════════════════════════

def get_quick_dashboard() -> str:
    """Return a combined stats snapshot for a quick dashboard view."""
    base = _steam_path()
    stplug = _stplug_dir()

    stats: Dict[str, Any] = {
        "luaFiles": 0, "disabledFiles": 0,
        "manifestFiles": 0, "manifestSizeMB": 0,
        "cacheSizeMB": 0, "backupCount": 0,
        "steamRunning": False,
        "fixesAvailable": 0,
    }

    # Lua count
    if stplug and os.path.isdir(stplug):
        for f in os.listdir(stplug):
            if f.endswith(".lua"):
                stats["luaFiles"] += 1
            elif f.endswith(".lua.disabled"):
                stats["disabledFiles"] += 1

    # Manifest count & size
    if base:
        dc = os.path.join(base, "depotcache")
        if os.path.isdir(dc):
            for f in os.listdir(dc):
                if f.endswith(".manifest"):
                    stats["manifestFiles"] += 1
            stats["manifestSizeMB"] = round(_dir_size(dc) / (1024 * 1024), 1)

    # Total cache size (quick estimate  --  htmlcache + shadercache + appcache)
    cache_total = 0
    for key in ("htmlcache", "shadercache", "appcache"):
        cfg = _CACHE_TARGETS.get(key, {})
        for rt, rel in cfg.get("paths", []):
            p = _resolve_cache_path(rt, rel)
            if p and os.path.isdir(p):
                cache_total += _dir_size(p)
    stats["cacheSizeMB"] = round(cache_total / (1024 * 1024), 1)

    # Backup count
    bd = data_path("luatools_backups")
    if os.path.isdir(bd):
        stats["backupCount"] = len([f for f in os.listdir(bd) if f.endswith(".zip")])

    # Steam running — cross-platform via steam_version helper
    try:
        stats["steamRunning"] = _steam_is_running()
    except Exception:
        pass

    # Fixes available for installed lua scripts
    try:
        from fixes import _fetch_fixes_index
        index = _fetch_fixes_index()
        if index and stplug and os.path.isdir(stplug):
            lua_appids = set()
            for f in os.listdir(stplug):
                m = re.match(r"^(\d+)\.lua", f)
                if m: lua_appids.add(int(m.group(1)))
            generic_set = index.get("generic", set())
            online_set = index.get("online", set())
            stats["fixesAvailable"] = len(lua_appids & (generic_set | online_set))
    except Exception:
        pass

    return json.dumps({"success": True, **stats})


# ═══════════════════════════════════════════════════════════════════════════
# 18. LIBRARY SCANNER  (ported from SFF/library_scanner.py)
# ═══════════════════════════════════════════════════════════════════════════

def scan_steam_libraries() -> str:
    """Scan all drives for Steam libraries. For each, report path, game count, size.

    Uses _scan_all_steam_libraries() from SFF to find libraries on all drives.
    """
    base = _steam_path()
    if not base:
        return json.dumps({"success": False, "error": "Steam path not found"})

    all_libs = _scan_all_steam_libraries(base)
    libraries: List[Dict[str, Any]] = []

    for lib_path in all_libs:
        sa = os.path.join(lib_path, "steamapps")
        entry: Dict[str, Any] = {
            "path": lib_path,
            "isPrimary": os.path.normcase(lib_path) == os.path.normcase(base),
            "exists": os.path.isdir(sa),
            "gameCount": 0,
            "sizeGB": 0,
            "games": [],
        }
        if os.path.isdir(sa):
            # Count ACF files = installed games
            acfs = [f for f in os.listdir(sa) if f.startswith("appmanifest_") and f.endswith(".acf")]
            entry["gameCount"] = len(acfs)
            # Quick size of steamapps/common
            common = os.path.join(sa, "common")
            if os.path.isdir(common):
                try:
                    total = sum(
                        os.path.getsize(os.path.join(dp, fn))
                        for dp, _, fns in os.walk(common) for fn in fns
                        if dp.count(os.sep) - common.count(os.sep) < 3  # limit depth
                    )
                    entry["sizeGB"] = round(total / (1024**3), 1)
                except Exception:
                    pass
            # First 20 game names
            for acf in sorted(acfs)[:20]:
                try:
                    with open(os.path.join(sa, acf), "r", encoding="utf-8", errors="replace") as fh:
                        data = _parse_vdf_simple(fh.read())
                    a = data.get("AppState", {})
                    entry["games"].append({
                        "appid": int(a.get("appid", 0)),
                        "name": a.get("name", "?"),
                    })
                except Exception:
                    pass

        libraries.append(entry)

    return json.dumps({
        "success": True,
        "libraryCount": len(libraries),
        "libraries": libraries,
    })


# ═══════════════════════════════════════════════════════════════════════════
# KILLER FEATURES (v8.2+)
# ═══════════════════════════════════════════════════════════════════════════


def check_manifest_staleness(appid: int = 0) -> str:
    """Check if installed manifests are outdated vs SteamCMD public manifests.

    Compares depot manifest IDs in .lua files against api.steamcmd.net.
    appid=0 checks ALL installed scripts.
    Returns per-depot: {depot_id, local_manifest, remote_manifest, stale: bool}
    """
    try:
        from http_client import ensure_http_client
        client = ensure_http_client("staleness")
        stplug = _stplug_dir()
        if not stplug or not os.path.isdir(stplug):
            return json.dumps({"success": False, "error": "stplug-in not found"})

        targets = []
        if appid:
            targets = [appid]
        else:
            for f in os.listdir(stplug):
                if f.endswith(".lua") and f.replace(".lua", "").isdigit():
                    targets.append(int(f.replace(".lua", "")))

        results = []
        for aid in targets[:50]:  # cap at 50 to avoid hammering API
            content, _ = _read_lua_file(aid)
            if not content:
                continue

            # Extract depot->manifest from lua
            local_depots = {}
            for m in re.findall(r'addappid\s*\(\s*(\d+)\s*,\s*(\d+)\s*,', content):
                local_depots[m[0]] = m[1]

            if not local_depots:
                continue

            # Query SteamCMD
            try:
                resp = client.get(f"https://api.steamcmd.net/v1/info/{aid}", timeout=10)
                if not resp.is_success:
                    continue
                data = resp.json()
                if data.get("status") != "success":
                    continue
                remote_depots = data.get("data", {}).get(str(aid), {}).get("depots", {})
            except Exception:
                continue

            app_stale = False
            depot_checks = []
            for depot_id, local_manifest in local_depots.items():
                remote_info = remote_depots.get(depot_id, {})
                remote_manifests = remote_info.get("manifests", {})
                remote_public = remote_manifests.get("public", {})
                remote_gid = remote_public.get("gid") if isinstance(remote_public, dict) else str(remote_public) if remote_public else ""

                is_stale = bool(remote_gid and str(remote_gid) != str(local_manifest))
                if is_stale:
                    app_stale = True
                depot_checks.append({
                    "depot_id": depot_id,
                    "local": local_manifest,
                    "remote": remote_gid or "?",
                    "stale": is_stale,
                })

            results.append({
                "appid": aid,
                "stale": app_stale,
                "depots": depot_checks,
                "total_depots": len(depot_checks),
                "stale_count": sum(1 for d in depot_checks if d["stale"]),
            })

            # Rate limit: 250ms between API calls
            import time
            time.sleep(0.25)

        total_stale = sum(1 for r in results if r["stale"])
        return json.dumps({
            "success": True,
            "results": results,
            "total_checked": len(results),
            "total_stale": total_stale,
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def generate_dlc_config(appid: int, format: str = "creamapi") -> str:
    """Generate DLC unlock configs from installed .lua depot/DLC data.

    Supported formats: creamapi, smokeapi, greenluma, codex
    Based on Sak32009 GetDataFromSteam concept.
    """
    try:
        from http_client import ensure_http_client
        client = ensure_http_client("dlc_config")

        # Fetch DLC list from Steam Store API
        resp = client.get(
            f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic",
            timeout=10,
        )
        dlc_list = []
        if resp.is_success:
            app_data = resp.json().get(str(appid), {}).get("data", {})
            app_name = app_data.get("name", f"AppID {appid}")
            dlc_ids = app_data.get("dlc", [])
        else:
            app_name = f"AppID {appid}"
            dlc_ids = []

        # Fetch DLC names
        for dlc_id in dlc_ids[:200]:
            try:
                dr = client.get(
                    f"https://store.steampowered.com/api/appdetails?appids={dlc_id}&filters=basic",
                    timeout=5,
                )
                if dr.is_success:
                    dlc_data = dr.json().get(str(dlc_id), {}).get("data", {})
                    dlc_list.append({"id": dlc_id, "name": dlc_data.get("name", f"DLC {dlc_id}")})
                else:
                    dlc_list.append({"id": dlc_id, "name": f"DLC {dlc_id}"})
            except Exception:
                dlc_list.append({"id": dlc_id, "name": f"DLC {dlc_id}"})
            import time
            time.sleep(0.1)

        # Also extract depots from lua
        content, _ = _read_lua_file(appid)
        depot_ids = _get_depot_ids_from_lua(content) if content else []

        fmt = format.lower()
        config_text = ""
        filename = ""

        if fmt == "creamapi":
            # cream_api.ini format
            lines = [f"; {app_name}", f"; Generated by LuaTools Ultimate", "",
                     "[steam]", f"appid = {appid}", "unlockall = false",
                     "orgapi = steam_api_o.dll", "orgapi64 = steam_api64_o.dll", "",
                     "[steam_misc]", "disableoverlay = false", "",
                     "[dlc]"]
            for dlc in dlc_list:
                lines.append(f"{dlc['id']} = {dlc['name']}")
            config_text = "\n".join(lines)
            filename = "cream_api.ini"

        elif fmt == "smokeapi":
            # SmokeAPI config.json
            import json as _json
            cfg = {
                "enabled": True,
                "unlock_all": True,
                "app_id": appid,
                "dlc": {str(d["id"]): d["name"] for d in dlc_list},
            }
            config_text = _json.dumps(cfg, indent=2)
            filename = "config.json"

        elif fmt == "greenluma":
            # GreenLuma AppList format (one DLC ID per file)
            lines = [f"// {app_name}  --  GreenLuma DLC list", f"// {len(dlc_list)} DLCs"]
            for i, dlc in enumerate(dlc_list):
                lines.append(f"// {i+1}. {dlc['name']}")
                lines.append(str(dlc["id"]))
            config_text = "\n".join(lines)
            filename = "AppList.txt"

        elif fmt == "codex":
            # CODEX steam_emu.ini format
            lines = [f"; {app_name}", "[Settings]", f"AppId={appid}",
                     "Language=english", "LowViolence=0", "",
                     "[DLC]"]
            for dlc in dlc_list:
                lines.append(f"{dlc['id']} = {dlc['name']}")
            config_text = "\n".join(lines)
            filename = "steam_emu.ini"

        return json.dumps({
            "success": True,
            "appid": appid,
            "app_name": app_name,
            "format": fmt,
            "filename": filename,
            "config": config_text,
            "dlc_count": len(dlc_list),
            "depot_count": len(depot_ids),
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def get_dlc_overview(appid: int) -> str:
    """Per-game DLC status: which DLCs Steam knows about, which the lua has.

    For each DLC ID returned by store.steampowered.com:
      - id, name, fetched
      - inLua: True if there's an addappid() line for it in our .lua
      - hasManifest: True if there's a setManifestid() line for it
      - exists locally (DLC depot manifest exists on disk)

    Used by the DLC Overview UI panel — purely informational, no writes.
    """
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid"})

    # 1. DLC list from Steam store
    try:
        from http_client import ensure_http_client
        client = ensure_http_client("dlc_overview")
        resp = client.get(
            f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic",
            timeout=10,
        )
        if not resp.is_success:
            return json.dumps({"success": False, "error": f"Store API HTTP {resp.status_code}"})
        app_data = resp.json().get(str(appid), {}).get("data", {})
        app_name = app_data.get("name", f"AppID {appid}")
        dlc_ids = app_data.get("dlc", []) or []
    except Exception as exc:
        return json.dumps({"success": False, "error": f"Store API: {exc}"})

    # 2. Read this game's .lua to find what's already activated
    content_text, _ = _read_lua_file(appid)
    appids_in_lua: set = set()
    manifests_in_lua: dict = {}  # depot_id -> manifest_id
    if content_text:
        for m in re.finditer(r"addappid\s*\(\s*(\d+)", content_text):
            appids_in_lua.add(int(m.group(1)))
        for m in re.finditer(r"setManifestid\s*\(\s*(\d+)\s*,\s*\"?(\d+)", content_text):
            manifests_in_lua[int(m.group(1))] = m.group(2)

    # 3. For each DLC, fetch its name (parallel-ish via httpx is overkill — just sequential w/ short timeout)
    dlc_entries: List[Dict[str, Any]] = []
    fetched_names = 0
    for dlc_id in dlc_ids[:200]:
        name = f"DLC {dlc_id}"
        try:
            dr = client.get(
                f"https://store.steampowered.com/api/appdetails?appids={dlc_id}&filters=basic",
                timeout=5,
            )
            if dr.is_success:
                dd = dr.json().get(str(dlc_id), {}).get("data", {})
                if dd.get("name"):
                    name = dd["name"]
                    fetched_names += 1
        except Exception:
            pass
        import time as _t
        _t.sleep(0.05)

        in_lua = dlc_id in appids_in_lua
        has_manifest = dlc_id in manifests_in_lua

        dlc_entries.append({
            "id": dlc_id,
            "name": name,
            "inLua": in_lua,
            "hasManifest": has_manifest,
            "manifestId": manifests_in_lua.get(dlc_id, ""),
            "status": (
                "active" if (in_lua and has_manifest) else
                "added_no_manifest" if in_lua else
                "missing"
            ),
        })

    # 4. Also find DLCs in .lua that Steam Store DOESN'T know about (orphans / private DLCs)
    known_dlc_ids = set(dlc_ids)
    orphan_appids = appids_in_lua - known_dlc_ids - {appid}  # exclude the base game itself
    for orphan_id in orphan_appids:
        if orphan_id in known_dlc_ids:
            continue
        dlc_entries.append({
            "id": orphan_id,
            "name": f"(unknown depot/DLC {orphan_id})",
            "inLua": True,
            "hasManifest": orphan_id in manifests_in_lua,
            "manifestId": manifests_in_lua.get(orphan_id, ""),
            "status": "orphan",
        })

    active = sum(1 for d in dlc_entries if d["status"] == "active")
    missing = sum(1 for d in dlc_entries if d["status"] == "missing")

    return json.dumps({
        "success": True,
        "appid": appid,
        "gameName": app_name,
        "totalDlcs": len(dlc_entries),
        "active": active,
        "missing": missing,
        "orphans": sum(1 for d in dlc_entries if d["status"] == "orphan"),
        "namesFetched": fetched_names,
        "dlcs": dlc_entries,
    })


def sync_depotcache(appid: int = 0) -> str:
    """Verify and auto-download missing depot manifest files to depotcache/.

    For each depot referenced in .lua, checks if {depot}_{manifest}.manifest
    exists in both Steam/depotcache/ and Steam/config/depotcache/.
    Missing files are fetched via ManifestHub API (if key configured).
    """
    try:
        base = _steam_path()
        if not base:
            return json.dumps({"success": False, "error": "Steam path not found"})

        stplug = _stplug_dir()
        targets = []
        if appid:
            targets = [appid]
        else:
            if os.path.isdir(stplug):
                for f in os.listdir(stplug):
                    if f.endswith(".lua") and f.replace(".lua", "").isdigit():
                        targets.append(int(f.replace(".lua", "")))

        cache_dirs = [
            os.path.join(base, "depotcache"),
            os.path.join(base, "config", "depotcache"),
        ]
        for d in cache_dirs:
            os.makedirs(d, exist_ok=True)

        # Collect all existing manifests
        existing = set()
        for cd in cache_dirs:
            if os.path.isdir(cd):
                for f in os.listdir(cd):
                    if f.endswith(".manifest"):
                        existing.add(f)

        # Check what's referenced in luas
        missing = []
        present = []
        for aid in targets:
            content, _ = _read_lua_file(aid)
            if not content:
                continue
            for m in re.findall(r'addappid\s*\(\s*(\d+)\s*,\s*(\d+)\s*,', content):
                depot_id, manifest_id = m[0], m[1]
                fname = f"{depot_id}_{manifest_id}.manifest"
                if fname in existing:
                    present.append({"appid": aid, "depot": depot_id, "manifest": manifest_id})
                else:
                    missing.append({"appid": aid, "depot": depot_id, "manifest": manifest_id})

        # Try to fetch missing via ManifestHub
        fetched = 0
        failed = 0
        from settings.manager import get_manifesthub_api_key
        mh_key = get_manifesthub_api_key()
        if mh_key and missing:
            from http_client import ensure_http_client
            client = ensure_http_client("depotcache_sync")
            for item in missing[:100]:  # cap
                try:
                    url = f"https://api.manifesthub1.filegear-sg.me/manifest?apikey={mh_key}&depotid={item['depot']}&manifestid={item['manifest']}"
                    resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                    if resp.is_success and len(resp.content) > 50:
                        fname = f"{item['depot']}_{item['manifest']}.manifest"
                        for cd in cache_dirs:
                            with open(os.path.join(cd, fname), "wb") as fh:
                                fh.write(resp.content)
                        fetched += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                import time
                time.sleep(0.5)  # rate limit

        return json.dumps({
            "success": True,
            "total_depots": len(present) + len(missing),
            "present": len(present),
            "missing_before": len(missing),
            "fetched": fetched,
            "failed": failed,
            "still_missing": len(missing) - fetched,
            "manifesthub_available": bool(mh_key),
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})



# ═══════════════════════════════════════════════════════════════════════════
# 18. ACHIEVEMENT SCHEMA  (SLScheevo-inspired — local check + Steam Web API)
# ═══════════════════════════════════════════════════════════════════════════

def _get_active_account_ids() -> List[Dict[str, Any]]:
    """Parse loginusers.vdf and return list of {accountId32, steamId64, name, mostRecent}."""
    base = _steam_path()
    if not base:
        return []
    vdf_path = os.path.join(base, "config", "loginusers.vdf")
    if not os.path.isfile(vdf_path):
        return []
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        # Each block: "76561198XXXXXXXXX" { "AccountName" "..." "MostRecent" "1" ... }
        accounts = []
        for m in re.finditer(
            r'"(\d{17,})"\s*\{([^}]+)\}', raw, re.DOTALL
        ):
            sid64 = int(m.group(1))
            body = m.group(2)
            name = re.search(r'"AccountName"\s*"([^"]+)"', body)
            recent = re.search(r'"MostRecent"\s*"([01])"', body)
            persona = re.search(r'"PersonaName"\s*"([^"]+)"', body)
            account_id32 = sid64 - _STEAMID64_BASE
            accounts.append({
                "accountId32": account_id32,
                "steamId64": sid64,
                "username": name.group(1) if name else "",
                "personaName": persona.group(1) if persona else "",
                "mostRecent": (recent.group(1) == "1") if recent else False,
            })
        # Sort: mostRecent first
        accounts.sort(key=lambda x: (not x["mostRecent"], x["username"]))
        return accounts
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to parse loginusers.vdf: {exc}")
        return []


def _appcache_stats_dir() -> str:
    """Return path to Steam/appcache/stats."""
    base = _steam_path()
    return os.path.join(base, "appcache", "stats") if base else ""


def _check_schema_files(appid: int, account_id32: int) -> Dict[str, Any]:
    """Check which achievement schema files exist in appcache/stats."""
    stats_dir = _appcache_stats_dir()
    schema_file = os.path.join(stats_dir, f"UserGameStatsSchema_{appid}.bin")
    user_file = os.path.join(stats_dir, f"UserGameStats_{account_id32}_{appid}.bin")
    return {
        "statsDir": stats_dir,
        "schemaFile": schema_file,
        "userStatsFile": user_file,
        "schemaExists": os.path.isfile(schema_file),
        "userStatsExists": os.path.isfile(user_file),
        "schemaSize": os.path.getsize(schema_file) if os.path.isfile(schema_file) else 0,
    }


def get_achievement_info(appid: int) -> str:
    """Fetch achievement info from Steam Web API and check local schema files.

    - Queries ISteamUserStats/GetSchemaForGame (no key needed for public games)
    - Checks Steam/appcache/stats/ for existing schema binary files
    - Reports which accounts are logged in and their schema file status

    Returns:
        success, count, achievements [{name, displayName, description, icon}],
        accounts [{accountId32, username, schemaExists, userStatsExists}]
    """
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})

    result: Dict[str, Any] = {
        "success": True,
        "appid": appid,
        "count": 0,
        "achievements": [],
        "accounts": [],
        "apiAvailable": False,
    }

    # 1. Steam Web API -- public achievement schema (no key needed)
    try:
        client = ensure_http_client("LuaTools: AchievementInfo")
        url = (
            f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/"
            f"?appid={appid}&l=english&format=json"
        )
        resp = client.get(url, headers={"User-Agent": "LuaTools/1.0"}, timeout=15, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            game = data.get("game", {})
            stats = game.get("availableGameStats", {})
            achievements = stats.get("achievements", [])
            result["count"] = len(achievements)
            result["apiAvailable"] = True
            # Return first 50 (display purposes)
            result["achievements"] = [
                {
                    "name": a.get("name", ""),
                    "displayName": a.get("displayName", ""),
                    "description": a.get("description", ""),
                    "hidden": a.get("hidden", 0) == 1,
                    "icon": a.get("icon", ""),
                }
                for a in achievements[:50]
            ]
            if len(achievements) > 50:
                result["truncated"] = len(achievements) - 50
        elif resp.status_code == 403:
            result["apiNote"] = "Game schema is private or requires a Steam API key"
        else:
            result["apiNote"] = f"Steam Web API returned HTTP {resp.status_code}"
    except Exception as exc:
        result["apiNote"] = f"Steam Web API unavailable: {exc}"

    # 2. Local schema file status per known account
    accounts = _get_active_account_ids()
    if not accounts:
        result["accountNote"] = "No accounts found in loginusers.vdf"
    for acc in accounts:
        file_info = _check_schema_files(appid, acc["accountId32"])
        result["accounts"].append({
            "accountId32": acc["accountId32"],
            "steamId64": acc["steamId64"],
            "username": acc["username"],
            "personaName": acc["personaName"],
            "mostRecent": acc["mostRecent"],
            "schemaExists": file_info["schemaExists"],
            "schemaSize": file_info["schemaSize"],
            "userStatsExists": file_info["userStatsExists"],
        })

    return json.dumps(result)


def seed_achievement_files(appid: int, account_id32: int = 0) -> str:
    """Create empty achievement stat files so Steam can populate them on first launch.

    For each logged-in account (or the specified one):
      - Creates UserGameStats_{accountId}_{appid}.bin if missing (empty stats template)
      - The UserGameStatsSchema_{appid}.bin is fetched by Steam automatically when
        the game is launched with a valid .lua activation.

    This mirrors SLScheevo's copy_bins_to_steam_stats() but without requiring
    a Steam protocol login -- just seeds the empty user stats file.
    """
    try:
        appid = int(appid)
        account_id32 = int(account_id32)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid or account_id"})

    stats_dir = _appcache_stats_dir()
    if not stats_dir:
        return json.dumps({"success": False, "error": "Steam path not found"})

    try:
        os.makedirs(stats_dir, exist_ok=True)
    except Exception as exc:
        return json.dumps({"success": False, "error": f"Cannot create stats dir: {exc}"})

    accounts = _get_active_account_ids() if account_id32 == 0 else [
        {"accountId32": account_id32, "username": f"id:{account_id32}", "mostRecent": True}
    ]

    if not accounts:
        return json.dumps({"success": False, "error": "No accounts found"})

    seeded = []
    skipped = []
    errors = []

    for acc in accounts:
        aid = acc["accountId32"]
        user_file = os.path.join(stats_dir, f"UserGameStats_{aid}_{appid}.bin")
        if os.path.isfile(user_file):
            skipped.append({"accountId32": aid, "username": acc.get("username", ""), "reason": "already exists"})
            continue
        try:
            with open(user_file, "wb") as fh:
                fh.write(_USERGAMESTATS_TEMPLATE)
            logger.log(f"LuaTools: Seeded {user_file} ({len(_USERGAMESTATS_TEMPLATE)} bytes)")
            seeded.append({"accountId32": aid, "username": acc.get("username", ""), "path": user_file})
        except Exception as exc:
            errors.append({"accountId32": aid, "error": str(exc)})

    # Check if schema binary also needs to come from somewhere
    schema_file = os.path.join(stats_dir, f"UserGameStatsSchema_{appid}.bin")
    schema_exists = os.path.isfile(schema_file)

    return json.dumps({
        "success": True,
        "appid": appid,
        "seeded": seeded,
        "skipped": skipped,
        "errors": errors,
        "schemaExists": schema_exists,
        "schemaNote": (
            "Schema binary already present." if schema_exists else
            "Schema binary not found. Steam will download it automatically "
            "the first time you launch the game with an active .lua script. "
            "If it doesn't appear, run the game once with Steam online."
        ),
        "statsDir": stats_dir,
    })


def get_active_accounts() -> str:
    """Return all Steam accounts from loginusers.vdf as JSON (for IPC)."""
    try:
        accounts = _get_active_account_ids()
        return json.dumps({"success": True, "accounts": accounts})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})

# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "audit_lua_content", "batch_health_scan",
    "check_manifest_staleness",
    "clean_cache", "clean_lua_content",
    "create_backup", "delete_backup",
    "detect_depot_conflicts",
    "diagnose_app", "export_diagnostic_report", "extract_lua_keys",
    "generate_dlc_config",
    "get_cache_info", "get_quick_dashboard",
    "get_steam_folder_stats", "get_steam_process_info",
    "get_steamtools_ids", "list_backups", "restore_backup",
    "scan_steam_libraries", "smart_restart_steam",
    "sync_depotcache",
    "toggle_lua_script", "update_manifests", "validate_lua_syntax",
    "get_achievement_info", "seed_achievement_files", "get_active_accounts",
    "repair_depot_cache",
]


# ═══════════════════════════════════════════════════════════════════════════
# 19. DEPOT CACHE REPAIR  (full fix pipeline — not just diagnose)
# ═══════════════════════════════════════════════════════════════════════════
#
# repair_depot_cache(appid=0) does everything in one pass:
#
#  Phase 1 — SCAN
#    - All .manifest files in both depotcache locations
#    - Classifies each as: valid / corrupt (bad magic) / orphaned (no lua refs it) / zero-byte
#
#  Phase 2 — LUA AUDIT
#    - For each .lua referencing depots: find missing manifests
#    - Try to re-download from GitHub mirror -> Morrenus API -> ManifestHub API
#
#  Phase 3 — CLEANUP
#    - Remove zero-byte manifests unconditionally
#    - Remove corrupt manifests (bad magic) — they make Steam complain
#    - Remove orphaned manifests older than --orphan_age_days (default 30)
#      that aren't referenced by any .lua (safe to delete)
#    - Remove non-.lua non-.lua.disabled files from stplug-in
#
#  Phase 4 — LUA SYNTAX FIX  (auto=False by default — destructive)
#    - Comment-out lines with unmatched parentheses or unrecognized statements
#    - Prepend "--LUATOOLS_AUTOFIXED: " to each bad line
#    - Never deletes lines — only comments them out (reversible)
#
# Returns a structured report: {phases: {scan, download, cleanup, lua_fix}, totals}


def _collect_all_manifests(base: str) -> List[Dict[str, Any]]:
    """Return info on every .manifest file found in both depotcache locations."""
    manifests: List[Dict[str, Any]] = []
    seen: set = set()
    dirs = [
        os.path.join(base, "depotcache"),
        os.path.join(base, "config", "depotcache"),
    ]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.endswith(".manifest"):
                continue
            fp = os.path.join(d, fname)
            if fp in seen:
                continue
            seen.add(fp)
            parts = fname[:-9].split("_", 1)  # strip ".manifest"
            depot_id = parts[0] if len(parts) == 2 and parts[0].isdigit() else None
            manifest_id = parts[1] if len(parts) == 2 and parts[1].isdigit() else None
            try:
                size = os.path.getsize(fp)
                mtime = os.path.getmtime(fp)
            except Exception:
                size, mtime = 0, 0
            valid_magic = False
            if size > 0:
                valid_magic = _verify_manifest_magic(fp)
            manifests.append({
                "path": fp,
                "filename": fname,
                "depotId": depot_id,
                "manifestId": manifest_id,
                "sizeBytes": size,
                "mtime": mtime,
                "validMagic": valid_magic,
                "zeroBytes": size == 0,
                "corrupt": size > 0 and not valid_magic,
            })
    return manifests


def _build_lua_depot_index(stplug: str) -> Dict[str, List[int]]:
    """Map each depot_id -> [appids] that reference it across all .lua files."""
    index: Dict[str, List[int]] = {}
    if not os.path.isdir(stplug):
        return index
    for fname in os.listdir(stplug):
        m = re.match(r"^(\d+)\.lua(?:\.disabled)?$", fname)
        if not m:
            continue
        appid = int(m.group(1))
        fp = os.path.join(stplug, fname)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except Exception:
            continue
        for depot_m in re.findall(r"addappid\s*\(\s*(\d+)\s*,\s*(\d+)\s*,", content):
            did = depot_m[0]
            index.setdefault(did, [])
            if appid not in index[did]:
                index[did].append(appid)
    return index


def _autofix_lua_bad_lines(fp: str, dry_run: bool = False) -> Dict[str, Any]:
    """Comment-out syntactically bad lines in a .lua file (reversible).

    Prepends '--LUATOOLS_AUTOFIXED: ' to each bad line.
    Never deletes lines. Returns {fixed, skipped_already_fixed, lines_touched, dry_run}.
    """
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except Exception as exc:
        return {"error": str(exc)}

    AUTOFIX_TAG = "--LUATOOLS_AUTOFIXED: "
    new_lines: List[str] = []
    fixed = 0
    skipped_already = 0

    for line in lines:
        stripped = line.rstrip("\r\n")
        # Already auto-fixed
        if stripped.lstrip().startswith(AUTOFIX_TAG):
            skipped_already += 1
            new_lines.append(line)
            continue
        ok, reason = _is_valid_lua_line(line)
        if ok:
            new_lines.append(line)
        else:
            # Comment it out with tag + reason
            indent = len(line) - len(line.lstrip())
            commented = " " * indent + AUTOFIX_TAG + stripped.lstrip() + f"  -- [{reason}]\n"
            new_lines.append(commented)
            fixed += 1

    result = {
        "fixed": fixed,
        "skipped_already_fixed": skipped_already,
        "lines_touched": fixed,
        "dry_run": dry_run,
    }

    if not dry_run and fixed > 0:
        try:
            # Atomic write via temp file
            import tempfile
            dir_ = os.path.dirname(fp)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                             dir=dir_, delete=False, suffix=".tmp") as tmp:
                tmp.writelines(new_lines)
                tmp_path = tmp.name
            os.replace(tmp_path, fp)
        except Exception as exc:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            result["error"] = str(exc)

    return result


def _try_fetch_manifest(depot_id: str, manifest_id: str,
                        dest_path: str, client: Any) -> Optional[str]:
    """Try to download a manifest from chain of sources.

    Returns source name on success, None on failure.
    Mirrors update_manifests() multi-source logic.
    """
    from settings.manager import get_morrenus_api_key, get_manifesthub_api_key, get_github_token

    gh_token = get_github_token()
    gh_headers: Dict[str, str] = {"User-Agent": "LuaTools/1.0"}
    if gh_token:
        gh_headers["Authorization"] = f"token {gh_token}"

    sources = [
        (
            "GitHub mirror",
            f"{_MH_BACKUP_URL}/{depot_id}_{manifest_id}.manifest",
            {"User-Agent": "LuaTools/1.0"},
        ),
    ]

    mo_key = get_morrenus_api_key()
    if mo_key:
        sources.append((
            "Morrenus API",
            f"{_MORRENUS_MANIFEST_URL}?depot_id={depot_id}&manifest_id={manifest_id}&api_key={mo_key}",
            {"User-Agent": "LuaTools/1.0"},
        ))

    mh_key = get_manifesthub_api_key()
    if mh_key:
        sources.append((
            "ManifestHub API",
            f"{_MANIFESTHUB_API_URL}?apikey={mh_key}&depotid={depot_id}&manifestid={manifest_id}",
            {"User-Agent": "Mozilla/5.0"},
        ))

    for source_name, url, headers in sources:
        try:
            resp = client.get(url, headers=headers, follow_redirects=True, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 10:
                # Verify magic before saving
                if resp.content[:4] == _MANIFEST_MAGIC or len(resp.content) > 50:
                    import tempfile
                    dir_ = os.path.dirname(dest_path)
                    os.makedirs(dir_, exist_ok=True)
                    with tempfile.NamedTemporaryFile("wb", dir=dir_,
                                                    delete=False, suffix=".tmp") as tmp:
                        tmp.write(resp.content)
                        tmp_path = tmp.name
                    os.replace(tmp_path, dest_path)
                    logger.log(
                        f"LuaTools: Fetched {depot_id}_{manifest_id}.manifest "
                        f"from {source_name} ({len(resp.content)} bytes)"
                    )
                    return source_name
        except Exception as exc:
            logger.warn(f"LuaTools: {source_name} failed for {depot_id}_{manifest_id}: {exc}")

    return None


def repair_depot_cache(
    appid: int = 0,
    fix_lua: bool = False,
    remove_orphans: bool = True,
    orphan_age_days: int = 30,
    dry_run: bool = False,
) -> str:
    """Full depot cache repair pipeline -- scan, re-download missing, clean junk.

    Phases:
      1. SCAN     -- classify every .manifest: valid / corrupt / zero-byte / orphaned
      2. DOWNLOAD -- re-fetch missing + corrupt manifests referenced by .lua files
      3. CLEANUP  -- delete zero-byte, corrupt, and orphaned manifests; stplug-in junk files
      4. LUA FIX  -- comment-out broken lines in .lua files (only if fix_lua=True)

    Args:
        appid:           0 = process all installed .lua scripts
        fix_lua:         Whether to auto-fix bad lines in .lua files (default False)
        remove_orphans:  Remove .manifest files not referenced by any .lua (default True)
        orphan_age_days: Only remove orphans older than N days (default 30)
        dry_run:         Report what WOULD be done without making changes

    Returns JSON with per-phase results and summary totals.
    """
    import time as _time

    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "Invalid appid"})

    base = _steam_path()
    if not base:
        return json.dumps({"success": False, "error": "Steam path not found"})

    stplug = _stplug_dir()
    client = ensure_http_client("LuaTools: RepairDepotCache")

    report: Dict[str, Any] = {
        "success": True,
        "dry_run": dry_run,
        "appid_filter": appid or "all",
        "phases": {
            "scan": {},
            "download": {},
            "cleanup": {},
            "lua_fix": {},
        },
        "totals": {},
    }

    # ── Phase 1: SCAN ─────────────────────────────────────────────────────
    logger.log(f"LuaTools: RepairDepotCache Phase 1 -- scanning manifests")

    all_manifests = _collect_all_manifests(base)
    depot_lua_index = _build_lua_depot_index(stplug) if stplug else {}

    now_ts = _time.time()
    orphan_cutoff = now_ts - orphan_age_days * 86400

    scan_valid = 0
    scan_corrupt: List[Dict] = []
    scan_zero: List[Dict] = []
    scan_orphan: List[Dict] = []

    # Which appids we're focusing on
    target_appids: Set[int] = set()
    if appid:
        target_appids = {appid}
    elif stplug and os.path.isdir(stplug):
        for f in os.listdir(stplug):
            m = re.match(r"^(\d+)\.lua(?:\.disabled)?$", f)
            if m:
                target_appids.add(int(m.group(1)))

    # Build set of referenced manifest filenames from all .lua files
    referenced_manifests: Set[str] = set()
    if stplug and os.path.isdir(stplug):
        for fname in os.listdir(stplug):
            m = re.match(r"^(\d+)\.lua(?:\.disabled)?$", fname)
            if not m:
                continue
            aid = int(m.group(1))
            if appid and aid != appid:
                continue
            try:
                with open(os.path.join(stplug, fname), "r",
                          encoding="utf-8", errors="replace") as fh:
                    lua_content = fh.read()
                for depot_m in re.findall(
                    r"addappid\s*\(\s*(\d+)\s*,\s*(\d+)\s*,", lua_content
                ):
                    referenced_manifests.add(f"{depot_m[0]}_{depot_m[1]}.manifest")
            except Exception:
                pass

    for mf in all_manifests:
        if mf["zeroBytes"]:
            scan_zero.append(mf)
        elif mf["corrupt"]:
            scan_corrupt.append(mf)
        elif mf["filename"] not in referenced_manifests:
            # Not referenced by any (targeted) lua
            age_ok = mf["mtime"] < orphan_cutoff
            scan_orphan.append({**mf, "old_enough": age_ok})
        else:
            scan_valid += 1

    report["phases"]["scan"] = {
        "total_manifests": len(all_manifests),
        "valid": scan_valid,
        "corrupt": len(scan_corrupt),
        "zero_byte": len(scan_zero),
        "orphaned": len(scan_orphan),
        "orphaned_old_enough": sum(1 for o in scan_orphan if o["old_enough"]),
    }
    logger.log(
        f"LuaTools: Scan -- {len(all_manifests)} total, "
        f"{scan_valid} OK, {len(scan_corrupt)} corrupt, "
        f"{len(scan_zero)} zero-byte, {len(scan_orphan)} orphaned"
    )

    # ── Phase 2: DOWNLOAD missing + corrupt manifests ─────────────────────
    logger.log(f"LuaTools: RepairDepotCache Phase 2 -- re-fetching missing/corrupt")

    dl_attempted: List[Dict] = []
    dl_success = 0
    dl_failed = 0

    # Collect what needs downloading:
    # a) manifests referenced by .lua but missing from disk
    # b) corrupt manifests (re-download to replace)
    corrupt_filenames = {mf["filename"] for mf in scan_corrupt}

    need_download: List[Tuple[str, str, str]] = []  # (depot_id, manifest_id, dest_path)
    for fname in referenced_manifests:
        parts = fname[:-9].split("_", 1)
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        depot_id, manifest_id = parts[0], parts[1]
        # Check if valid copy exists
        fp = _find_manifest_file(base, depot_id, manifest_id)
        if fp and os.path.getsize(fp) > 0 and _verify_manifest_magic(fp):
            if fname not in corrupt_filenames:
                continue  # already good
        # Primary dest: depotcache/
        dest = os.path.join(base, "depotcache", fname)
        need_download.append((depot_id, manifest_id, dest))

    logger.log(f"LuaTools: {len(need_download)} manifests need downloading")

    for depot_id, manifest_id, dest in need_download[:200]:  # cap
        item = {
            "depot": depot_id,
            "manifest": manifest_id,
            "dest": dest,
        }
        if dry_run:
            item["result"] = "dry_run"
            dl_attempted.append(item)
            continue

        source = _try_fetch_manifest(depot_id, manifest_id, dest, client)
        if source:
            item["result"] = "ok"
            item["source"] = source
            dl_success += 1
        else:
            item["result"] = "failed"
            dl_failed += 1
        dl_attempted.append(item)
        _time.sleep(0.3)  # gentle rate limit

    report["phases"]["download"] = {
        "needed": len(need_download),
        "attempted": len(dl_attempted),
        "success": dl_success,
        "failed": dl_failed,
        "capped": len(need_download) > 200,
    }

    # ── Phase 3: CLEANUP ──────────────────────────────────────────────────
    logger.log(f"LuaTools: RepairDepotCache Phase 3 -- cleaning up bad files")

    removed_corrupt = 0
    removed_zero = 0
    removed_orphan = 0
    removed_junk = 0
    removal_errors: List[str] = []

    def _safe_delete(path: str, reason: str) -> bool:
        if dry_run:
            logger.log(f"LuaTools: [DRY RUN] Would remove {path} ({reason})")
            return True
        try:
            os.remove(path)
            logger.log(f"LuaTools: Removed {os.path.basename(path)} ({reason})")
            return True
        except Exception as exc:
            removal_errors.append(f"{os.path.basename(path)}: {exc}")
            return False

    # Delete zero-byte manifests (always -- they're never valid)
    for mf in scan_zero:
        if _safe_delete(mf["path"], "zero-byte"):
            removed_zero += 1

    # Delete corrupt manifests that we successfully re-downloaded
    # (if download failed, keep the corrupt one as a placeholder)
    redownloaded = {
        f"{item['depot']}_{item['manifest']}.manifest"
        for item in dl_attempted
        if item.get("result") == "ok"
    }
    for mf in scan_corrupt:
        if mf["filename"] in redownloaded or dry_run:
            # Either replaced, or dry_run -- safe to remove the old corrupt copy
            if _safe_delete(mf["path"], "corrupt -- replaced with fresh download"):
                removed_corrupt += 1
        else:
            # Download failed -- leave corrupt file, just log it
            logger.warn(
                f"LuaTools: Keeping corrupt {mf['filename']} "
                "(download failed -- manual intervention needed)"
            )

    # Delete old enough orphaned manifests
    if remove_orphans:
        for mf in scan_orphan:
            if mf["old_enough"]:
                if _safe_delete(mf["path"], f"orphaned >={orphan_age_days}d"):
                    removed_orphan += 1

    # Clean non-.lua files from stplug-in dir
    if stplug and os.path.isdir(stplug):
        for fname in os.listdir(stplug):
            fp = os.path.join(stplug, fname)
            if not os.path.isfile(fp):
                continue
            if fname.endswith(".lua") or fname.endswith(".lua.disabled"):
                continue
            # Junk file -- log and remove
            logger.warn(f"LuaTools: Junk file in stplug-in: {fname}")
            if _safe_delete(fp, "non-lua file in stplug-in"):
                removed_junk += 1

    report["phases"]["cleanup"] = {
        "removed_zero_byte": removed_zero,
        "removed_corrupt": removed_corrupt,
        "removed_orphaned": removed_orphan,
        "removed_stplug_junk": removed_junk,
        "errors": removal_errors[:20],
    }

    # ── Phase 4: LUA SYNTAX FIX ───────────────────────────────────────────
    lua_fix_results: List[Dict] = []
    lua_fixed_total = 0

    if fix_lua and stplug and os.path.isdir(stplug):
        logger.log(f"LuaTools: RepairDepotCache Phase 4 -- auto-fixing lua syntax")

        for fname in sorted(os.listdir(stplug)):
            m = re.match(r"^(\d+)\.lua(?:\.disabled)?$", fname)
            if not m:
                continue
            aid = int(m.group(1))
            if appid and aid != appid:
                continue
            fp = os.path.join(stplug, fname)
            result = _autofix_lua_bad_lines(fp, dry_run=dry_run)
            result["appid"] = aid
            result["filename"] = fname
            if result.get("fixed", 0) > 0:
                lua_fixed_total += result["fixed"]
                lua_fix_results.append(result)

    report["phases"]["lua_fix"] = {
        "enabled": fix_lua,
        "files_fixed": len(lua_fix_results),
        "lines_commented_out": lua_fixed_total,
        "details": lua_fix_results,
    }

    # ── Totals ────────────────────────────────────────────────────────────
    report["totals"] = {
        "manifests_scanned": len(all_manifests),
        "manifests_downloaded": dl_success,
        "manifests_removed": removed_zero + removed_corrupt + removed_orphan,
        "junk_files_removed": removed_junk,
        "lua_lines_fixed": lua_fixed_total,
        "errors": len(removal_errors),
    }

    logger.log(
        f"LuaTools: RepairDepotCache done -- "
        f"dl:{dl_success} removed:{removed_zero + removed_corrupt + removed_orphan} "
        f"junk:{removed_junk} lua_lines:{lua_fixed_total}"
    )
    return json.dumps(report)

def _plugin_version() -> str:
    """Plugin version from plugin.json. Local copy to avoid circular import."""
    try:
        import json as _json
        from paths import get_plugin_dir as _gpd
        with open(os.path.join(_gpd(), "plugin.json"), encoding="utf-8") as _fh:
            return str(_json.load(_fh).get("version", "?"))
    except Exception:
        return "?"

