"""API key vault — backup, restore and switch between sets of premium keys.

Stores named profiles of API credentials (Ryuu / DepotBox / Morrenus /
ManifestHub / SteamGridDB / GitHub) so switching machines or sharing a
known-good set across PCs takes one click instead of re-pasting six keys.

Storage layout:
    <plugin>/backend/data/key_vault.json
        {
          "profiles": {
            "main":  {"ryuuSession": "...", "depotboxSid": "...", ...},
            "spare": {...}
          },
          "active": "main",
          "updated_at": 1715900000
        }

The vault file is plain JSON (no encryption) -- if you share it, share with
the same caution as the keys themselves. Export to .ltkeys archives that can
be saved off-machine.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Dict, List, Optional

from logger import logger
from paths import get_plugin_dir
from settings.manager import (
    get_morrenus_api_key, get_ryuu_session, get_depotbox_sid,
    get_manifesthub_api_key, get_steamgriddb_key, get_github_token,
    apply_settings_bulk,
)

# Map each vault field to its settings group (general/steamtools)
_FIELD_GROUPS = {
    "morrenusApiKey":   "general",
    "ryuuSession":      "general",
    "depotboxSid":      "general",
    "manifestHubApiKey": "steamtools",
    "steamGridDbKey":   "steamtools",
    "githubToken":      "steamtools",
}

# All managed credentials (key name in settings -> human label)
VAULT_FIELDS = [
    ("morrenusApiKey",   "Morrenus API Key"),
    ("ryuuSession",      "Ryuu Session"),
    ("depotboxSid",      "DepotBox SID"),
    ("manifestHubApiKey", "ManifestHub API Key"),
    ("steamGridDbKey",   "SteamGridDB Key"),
    ("githubToken",      "GitHub Token"),
]


def _vault_path() -> str:
    base = get_plugin_dir()
    data_dir = os.path.join(base, "backend", "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "key_vault.json")


def _read_vault() -> Dict[str, Any]:
    path = _vault_path()
    if not os.path.isfile(path):
        return {"profiles": {}, "active": "", "updated_at": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("profiles"), dict):
            data["profiles"] = {}
        return data
    except Exception as exc:
        logger.warn(f"LuaTools: key_vault read failed: {exc}")
        return {"profiles": {}, "active": "", "updated_at": 0}


def _write_vault(data: Dict[str, Any]) -> None:
    data["updated_at"] = int(time.time())
    path = _vault_path()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def _current_keys() -> Dict[str, str]:
    """Read currently active keys from settings."""
    getters = {
        "morrenusApiKey":   get_morrenus_api_key,
        "ryuuSession":      get_ryuu_session,
        "depotboxSid":      get_depotbox_sid,
        "manifestHubApiKey": get_manifesthub_api_key,
        "steamGridDbKey":   get_steamgriddb_key,
        "githubToken":      get_github_token,
    }
    result: Dict[str, str] = {}
    for key, fn in getters.items():
        try:
            result[key] = fn() or ""
        except Exception:
            result[key] = ""
    return result


def _mask(value: str) -> str:
    """Show first 4 + last 4 chars; everything else masked."""
    if not value:
        return ""
    if len(value) <= 10:
        return value[:2] + "***"
    return f"{value[:4]}***{value[-4:]} ({len(value)} chars)"


def list_profiles(contentScriptQuery: str = "") -> str:
    """List vault profiles with masked credentials and metadata."""
    try:
        vault = _read_vault()
        profiles_summary = []
        for name, keys in vault.get("profiles", {}).items():
            non_empty = sum(1 for v in keys.values() if v)
            profiles_summary.append({
                "name": name,
                "fieldsSet": non_empty,
                "totalFields": len(VAULT_FIELDS),
                "savedAt": keys.get("_savedAt", 0),
                "masked": {k: _mask(keys.get(k, ""))
                           for k, _ in VAULT_FIELDS},
            })
        return json.dumps({
            "success": True,
            "profiles": profiles_summary,
            "active": vault.get("active", ""),
            "fields": [{"key": k, "label": label} for k, label in VAULT_FIELDS],
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def save_profile(name: str = "main", contentScriptQuery: str = "") -> str:
    """Snapshot the currently active keys into a named profile."""
    name = (name or "main").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return json.dumps({"success": False, "error": "Invalid profile name"})

    try:
        vault = _read_vault()
        keys = _current_keys()
        keys["_savedAt"] = int(time.time())
        vault["profiles"][name] = keys
        if not vault.get("active"):
            vault["active"] = name
        _write_vault(vault)
        non_empty_count = sum(1 for v in keys.values() if v and not isinstance(v, int))
        logger.log(f"LuaTools: Saved key vault profile '{name}' "
                   f"({non_empty_count} fields)")
        return json.dumps({"success": True, "name": name,
                            "fieldsSet": non_empty_count})
    except Exception as exc:
        logger.error(f"LuaTools: save_profile failed: {exc}")
        return json.dumps({"success": False, "error": str(exc)})


def load_profile(name: str = "main", contentScriptQuery: str = "") -> str:
    """Apply the named profile's keys to current settings."""
    try:
        vault = _read_vault()
        keys = vault.get("profiles", {}).get(name)
        if not keys:
            return json.dumps({"success": False, "error": f"Profile '{name}' not found"})

        # Build group -> {key: value} mapping for apply_settings_bulk
        bulk: Dict[str, Dict[str, Any]] = {}
        applied: List[str] = []
        for field_key, _ in VAULT_FIELDS:
            value = keys.get(field_key, "")
            if value:
                group = _FIELD_GROUPS.get(field_key, "general")
                bulk.setdefault(group, {})[field_key] = value
                applied.append(field_key)
        if bulk:
            apply_settings_bulk(bulk)

        vault["active"] = name
        _write_vault(vault)
        logger.log(f"LuaTools: Loaded key vault profile '{name}' "
                   f"({len(applied)} fields applied)")
        return json.dumps({"success": True, "name": name, "applied": applied})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def delete_profile(name: str = "", contentScriptQuery: str = "") -> str:
    """Remove a profile from the vault (not the active settings)."""
    try:
        vault = _read_vault()
        if name not in vault.get("profiles", {}):
            return json.dumps({"success": False, "error": f"Profile '{name}' not found"})
        del vault["profiles"][name]
        if vault.get("active") == name:
            vault["active"] = next(iter(vault["profiles"]), "")
        _write_vault(vault)
        return json.dumps({"success": True, "deleted": name})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def export_profile(name: str = "", contentScriptQuery: str = "") -> str:
    """Export profile as a portable base64-encoded JSON blob.

    The blob can be saved to a .ltkeys file or pasted into another machine.
    The encoding is NOT encryption -- treat the export as sensitive.
    """
    try:
        vault = _read_vault()
        keys = vault.get("profiles", {}).get(name)
        if not keys:
            return json.dumps({"success": False, "error": f"Profile '{name}' not found"})

        payload = {
            "format": "ltkeys-v1",
            "name": name,
            "exportedAt": int(time.time()),
            "keys": {k: keys.get(k, "") for k, _ in VAULT_FIELDS},
        }
        blob_json = json.dumps(payload, separators=(",", ":"))
        encoded = base64.b64encode(blob_json.encode("utf-8")).decode("ascii")
        return json.dumps({
            "success": True,
            "name": name,
            "blob": encoded,
            "preview": _mask_payload_preview(payload),
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def _mask_payload_preview(payload: Dict[str, Any]) -> Dict[str, str]:
    return {k: _mask(payload["keys"].get(k, "")) for k, _ in VAULT_FIELDS}


def import_profile(blob: str = "", name_override: str = "",
                   activate: bool = False, contentScriptQuery: str = "") -> str:
    """Import a profile from a base64 blob produced by export_profile."""
    try:
        decoded = base64.b64decode(blob.strip()).decode("utf-8")
        payload = json.loads(decoded)
        if payload.get("format") != "ltkeys-v1":
            return json.dumps({"success": False, "error": "Invalid or unsupported format"})

        keys = payload.get("keys", {})
        if not isinstance(keys, dict):
            return json.dumps({"success": False, "error": "Malformed keys"})

        target_name = name_override.strip() or payload.get("name", "imported")
        if not target_name or "/" in target_name or ".." in target_name:
            target_name = "imported"

        vault = _read_vault()
        keys["_savedAt"] = int(time.time())
        vault["profiles"][target_name] = keys
        _write_vault(vault)

        if activate:
            return load_profile(target_name)

        return json.dumps({
            "success": True,
            "name": target_name,
            "fieldsSet": sum(1 for k, _ in VAULT_FIELDS if keys.get(k)),
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": f"Import failed: {exc}"})
