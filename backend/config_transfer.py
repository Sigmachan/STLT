"""LuaTools Config Export/Import — full settings dump and restore.

Exports:
  - All plugin settings (keys, cookies, paths, preferences)
  - Source chain configuration
  - Custom API sources
  - Hook configuration
  - Free API manifest list

Does NOT export (security):
  - Download history (separate export available)
  - Backup files
  - Cached manifests
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

from logger import logger
from paths import data_path

_VERSION = "1.0"


def export_config() -> str:
    """Export full plugin configuration as JSON string."""
    try:
        config: Dict[str, Any] = {
            "_meta": {
                "version": _VERSION,
                "exported_at": time.time(),
                "plugin": "LuaTools Ultimate",
            },
        }

        # 1. Plugin settings
        try:
            from settings.manager import get_all_settings
            config["settings"] = get_all_settings()
        except Exception:
            config["settings"] = {}

        # 2. Source chain
        try:
            from source_chain import load_chain, load_blacklist
            config["source_chain"] = load_chain()
            config["source_blacklist"] = load_blacklist()
        except Exception:
            pass

        # 3. Custom APIs
        try:
            from custom_apis import get_custom_apis
            raw = get_custom_apis()
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            config["custom_apis"] = parsed.get("apis", []) if isinstance(parsed, dict) else []
        except Exception:
            pass

        # 4. Hooks
        try:
            from events import _load_hooks_config
            config["hooks"] = _load_hooks_config()
        except Exception:
            pass

        # 5. API manifest
        try:
            manifest_path = data_path("api_manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f:
                    config["api_manifest"] = json.load(f)
        except Exception:
            pass

        return json.dumps({"success": True, "config": config}, indent=2)

    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def import_config(config_json: str) -> str:
    """Import configuration from JSON string. Merges, doesn't overwrite unknowns."""
    try:
        data = json.loads(config_json) if isinstance(config_json, str) else config_json
        if isinstance(data, dict) and "config" in data:
            data = data["config"]

        imported = []
        errors = []

        # 1. Settings
        if "settings" in data and data["settings"]:
            try:
                from settings.manager import apply_settings_bulk
                apply_settings_bulk(data["settings"])
                imported.append("settings")
            except Exception as exc:
                errors.append(f"settings: {exc}")

        # 2. Source chain
        if "source_chain" in data:
            try:
                from source_chain import save_chain, save_blacklist
                save_chain(data["source_chain"])
                if "source_blacklist" in data:
                    save_blacklist(data["source_blacklist"])
                imported.append("source_chain")
            except Exception as exc:
                errors.append(f"source_chain: {exc}")

        # 3. Custom APIs
        if "custom_apis" in data:
            try:
                from custom_apis import save_custom_apis
                save_custom_apis(json.dumps(data["custom_apis"]))
                imported.append("custom_apis")
            except Exception as exc:
                errors.append(f"custom_apis: {exc}")

        # 4. Hooks
        if "hooks" in data:
            try:
                from events import save_hooks_config
                save_hooks_config(data["hooks"])
                imported.append("hooks")
            except Exception as exc:
                errors.append(f"hooks: {exc}")

        # 5. API manifest
        if "api_manifest" in data:
            try:
                manifest_path = data_path("api_manifest.json")
                os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(data["api_manifest"], f, indent=2)
                imported.append("api_manifest")
            except Exception as exc:
                errors.append(f"api_manifest: {exc}")

        return json.dumps({
            "success": len(errors) == 0,
            "imported": imported,
            "errors": errors,
        })

    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
