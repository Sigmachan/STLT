"""Per-game configuration profiles (v9.0).

Some games benefit from multiple configurations:
  - "Pragmata + Tokeer" vs "Pragmata vanilla"
  - "Persona 5 with Cheat Engine launch options" vs "Persona 5 clean"
  - "Hogwarts Legacy English manifest" vs "Hogwarts Legacy Russian manifest"

A profile is a named snapshot of:
  - the .lua activation script (full content)
  - launch options from localconfig.vdf (per-account, optional)
  - timestamp + user description

Storage:
    <plugin>/backend/data/profiles/<appid>/<slug>.json   -- profile contents
    <plugin>/backend/data/profiles/active.json           -- {appid: slug} pointer

Activating a profile rewrites the .lua (with .pre-activate-* backup) and
optionally writes launch options. Safe to roundtrip — every activation
creates a backup of the previous state.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional

from logger import logger
from paths import data_path
from steam_utils import detect_steam_install_path


# ── Storage paths ──────────────────────────────────────────────────────

def _profiles_root() -> str:
    p = os.path.join(data_path(), "profiles")
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass
    return p


def _profile_dir(appid: int) -> str:
    p = os.path.join(_profiles_root(), str(int(appid)))
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass
    return p


def _active_path() -> str:
    return os.path.join(_profiles_root(), "active.json")


def _slugify(name: str) -> str:
    """Convert profile name into a filesystem-safe slug."""
    s = re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip()).strip("_")
    return s[:64] if s else "profile"


# ── Lua + launch-options snapshot helpers ──────────────────────────────

def _lua_path(appid: int) -> str:
    base = detect_steam_install_path()
    if not base:
        return ""
    return os.path.join(base, "config", "stplug-in", f"{appid}.lua")


def _read_lua_snapshot(appid: int) -> Optional[str]:
    p = _lua_path(appid)
    if not p or not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as exc:
        logger.warn(f"profiles: read lua {appid} failed: {exc}")
        return None


def _write_lua_snapshot(appid: int, content: str) -> bool:
    p = _lua_path(appid)
    if not p:
        return False
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, p)
        return True
    except Exception as exc:
        logger.warn(f"profiles: write lua {appid} failed: {exc}")
        return False


def _localconfig_path(account_id32: int) -> str:
    base = detect_steam_install_path()
    if not base:
        return ""
    return os.path.join(
        base, "userdata", str(int(account_id32)), "config", "localconfig.vdf"
    )


def _read_launch_options(appid: int, account_id32: int) -> str:
    """Pull LaunchOptions for an appid from localconfig.vdf."""
    p = _localconfig_path(account_id32)
    if not p or not os.path.isfile(p):
        return ""
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return ""
    apps_match = re.search(r'"apps"\s*\{(.+?)\n\s*\}\s*\n', text, re.DOTALL)
    if not apps_match:
        return ""
    body = apps_match.group(1)
    appid_match = re.search(
        rf'"\s*{int(appid)}\s*"\s*\{{(.+?)\n\s*\}}\s*\n', body, re.DOTALL
    )
    if not appid_match:
        return ""
    lo = re.search(r'"LaunchOptions"\s*"([^"]*)"', appid_match.group(1))
    return lo.group(1) if lo else ""


# ── Active-profile tracking ────────────────────────────────────────────

def _read_active() -> Dict[str, str]:
    p = _active_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_active(data: Dict[str, str]) -> bool:
    p = _active_path()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, p)
        return True
    except Exception as exc:
        logger.warn(f"profiles: write active.json failed: {exc}")
        try: os.remove(tmp)
        except Exception: pass
        return False


# ── Public IPC ─────────────────────────────────────────────────────────

def list_profiles_for(appid: int, contentScriptQuery: str = "") -> str:
    """All saved profiles for one appid. Marks the active one."""
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid"})

    pdir = _profile_dir(appid)
    if not os.path.isdir(pdir):
        return json.dumps({"success": True, "appid": appid, "profiles": [], "active": None})

    active_map = _read_active()
    active_slug = active_map.get(str(appid))

    profiles: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(pdir)):
        if not fname.endswith(".json"):
            continue
        slug = fname[:-5]
        try:
            with open(os.path.join(pdir, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        profiles.append({
            "slug": slug,
            "name": data.get("name", slug),
            "description": data.get("description", ""),
            "createdAt": data.get("createdAt", 0),
            "luaLength": len(data.get("luaContent", "") or ""),
            "hasLaunchOptions": bool(data.get("launchOptions")),
            "launchOptionsPreview": (data.get("launchOptions", "") or "")[:80],
            "active": (slug == active_slug),
        })

    profiles.sort(key=lambda x: (not x["active"], -x["createdAt"]))

    return json.dumps({
        "success": True,
        "appid": appid,
        "profiles": profiles,
        "active": active_slug,
    })


def save_profile(appid: int, name: str = "", description: str = "",
                 accountId32: int = 0,
                 contentScriptQuery: str = "") -> str:
    """Snapshot current state (lua + launch options) as a named profile."""
    try:
        appid = int(appid)
        account_id32 = int(accountId32)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid or accountId32"})

    name = (name or "").strip()
    if not name:
        return json.dumps({"success": False, "error": "name required"})

    slug = _slugify(name)
    lua_content = _read_lua_snapshot(appid)
    if lua_content is None:
        return json.dumps({
            "success": False,
            "error": f".lua file for AppID {appid} not found",
        })

    launch_options = _read_launch_options(appid, account_id32) if account_id32 else ""

    data = {
        "appid": appid,
        "slug": slug,
        "name": name,
        "description": description,
        "createdAt": int(time.time()),
        "luaContent": lua_content,
        "launchOptions": launch_options,
        "snapshotAccountId32": account_id32,
    }

    pdir = _profile_dir(appid)
    path = os.path.join(pdir, f"{slug}.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        return json.dumps({"success": False, "error": f"write failed: {exc}"})

    logger.log(f"profiles: saved '{name}' for appid {appid} ({len(lua_content)} bytes lua)")
    return json.dumps({
        "success": True,
        "appid": appid,
        "slug": slug,
        "name": name,
        "luaLength": len(lua_content),
        "hasLaunchOptions": bool(launch_options),
    })


def activate_profile(appid: int, slug: str = "",
                     applyLaunchOptions: bool = True,
                     accountId32: int = 0,
                     contentScriptQuery: str = "") -> str:
    """Restore a profile: rewrite the .lua + optionally launch options.

    Pre-activate backup of current state goes to:
        <plugin>/data/profiles/<appid>/.pre-activate-<timestamp>.json
    """
    try:
        appid = int(appid)
        account_id32 = int(accountId32)
        apply_lo = bool(applyLaunchOptions)
    except Exception:
        return json.dumps({"success": False, "error": "invalid args"})

    slug = (slug or "").strip()
    if not slug:
        return json.dumps({"success": False, "error": "slug required"})

    profile_path = os.path.join(_profile_dir(appid), f"{slug}.json")
    if not os.path.isfile(profile_path):
        return json.dumps({"success": False, "error": "profile not found"})

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception as exc:
        return json.dumps({"success": False, "error": f"profile read: {exc}"})

    # Backup current state as a synthetic profile
    backup_name = f".pre-activate-{int(time.time())}"
    backup_path = os.path.join(_profile_dir(appid), f"{backup_name}.json")
    current_lua = _read_lua_snapshot(appid) or ""
    current_lo = _read_launch_options(appid, account_id32) if account_id32 else ""
    try:
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump({
                "appid": appid,
                "slug": backup_name,
                "name": "(pre-activate backup)",
                "description": f"Auto-backup before activating '{profile.get('name', slug)}'",
                "createdAt": int(time.time()),
                "luaContent": current_lua,
                "launchOptions": current_lo,
                "snapshotAccountId32": account_id32,
            }, f, indent=2)
    except Exception as exc:
        logger.warn(f"profiles: backup failed: {exc}")

    # Apply lua
    lua_content = profile.get("luaContent", "")
    if not _write_lua_snapshot(appid, lua_content):
        return json.dumps({"success": False, "error": "lua write failed"})

    # Apply launch options (if requested + accountId32 provided + Steam closed)
    lo_applied = False
    lo_skipped_reason = ""
    if apply_lo and account_id32 and profile.get("launchOptions"):
        from steam_version import _steam_is_running
        if _steam_is_running():
            lo_skipped_reason = "Steam is running — launch options will be overwritten on exit, skipped"
        else:
            try:
                from tokeer_launcher import _set_launch_options  # reuse the proven logic
                lc_path = _localconfig_path(account_id32)
                if lc_path and os.path.isfile(lc_path):
                    with open(lc_path, "r", encoding="utf-8", errors="replace") as f:
                        lc_text = f.read()
                    new_text, action = _set_launch_options(
                        lc_text, appid, profile["launchOptions"]
                    )
                    if action not in ("no_file", "no_apps_section"):
                        # Backup before write
                        bak = lc_path + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
                        shutil.copy2(lc_path, bak)
                        tmp = lc_path + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            f.write(new_text)
                        os.replace(tmp, lc_path)
                        lo_applied = True
            except Exception as exc:
                lo_skipped_reason = f"launch options write failed: {exc}"

    # Update active pointer
    active = _read_active()
    active[str(appid)] = slug
    _write_active(active)

    logger.log(
        f"profiles: activated '{profile.get('name', slug)}' for appid {appid}"
    )
    return json.dumps({
        "success": True,
        "appid": appid,
        "slug": slug,
        "name": profile.get("name", slug),
        "luaApplied": True,
        "launchOptionsApplied": lo_applied,
        "launchOptionsSkippedReason": lo_skipped_reason,
        "backupPath": backup_path,
    })


def delete_profile(appid: int, slug: str = "",
                   contentScriptQuery: str = "") -> str:
    """Remove a profile. Does not affect current active state."""
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid"})

    slug = (slug or "").strip()
    if not slug:
        return json.dumps({"success": False, "error": "slug required"})

    path = os.path.join(_profile_dir(appid), f"{slug}.json")
    if not os.path.isfile(path):
        return json.dumps({"success": False, "error": "profile not found"})

    try:
        os.remove(path)
    except Exception as exc:
        return json.dumps({"success": False, "error": f"delete failed: {exc}"})

    # If this was the active profile, clear the pointer
    active = _read_active()
    if active.get(str(appid)) == slug:
        active.pop(str(appid), None)
        _write_active(active)

    return json.dumps({"success": True, "slug": slug})


def list_all_profiles(contentScriptQuery: str = "") -> str:
    """Cross-game profile list (for dashboards)."""
    root = _profiles_root()
    if not os.path.isdir(root):
        return json.dumps({"success": True, "appids": [], "totalProfiles": 0})

    active_map = _read_active()
    out: List[Dict[str, Any]] = []
    total = 0
    for entry in sorted(os.listdir(root)):
        full = os.path.join(root, entry)
        if not (os.path.isdir(full) and entry.isdigit()):
            continue
        appid = int(entry)
        profiles = [
            f[:-5] for f in os.listdir(full)
            if f.endswith(".json") and not f.startswith(".pre-activate-")
        ]
        if not profiles:
            continue
        total += len(profiles)
        out.append({
            "appid": appid,
            "profileCount": len(profiles),
            "activeSlug": active_map.get(str(appid)),
            "slugs": sorted(profiles),
        })
    return json.dumps({"success": True, "appids": out, "totalProfiles": total})
