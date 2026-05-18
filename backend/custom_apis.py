"""Custom API endpoint manager — lets users add/remove download sources from the UI.

Ported from Cyberia's dynamic api_list pattern. Each API has:
  name     — display name
  url      — template with <appid> placeholder (e.g. https://example.com/manifest/<appid>)
  api_key  — optional Bearer token
  enabled  — toggle
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from logger import logger
from paths import data_path


_CUSTOM_APIS_FILE = "custom_apis.json"


def _apis_path() -> str:
    return data_path(_CUSTOM_APIS_FILE)


def get_custom_apis() -> str:
    """Return all custom API endpoints as JSON."""
    fp = _apis_path()
    if not os.path.isfile(fp):
        return json.dumps({"success": True, "apis": []})
    try:
        with open(fp, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        apis = data if isinstance(data, list) else data.get("apis", [])
        return json.dumps({"success": True, "apis": apis})
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to load custom APIs: {exc}")
        return json.dumps({"success": True, "apis": []})


def save_custom_apis(apis_json: str) -> str:
    """Save custom API endpoints from frontend JSON."""
    try:
        apis = json.loads(apis_json)
        if not isinstance(apis, list):
            return json.dumps({"success": False, "error": "Expected a JSON array"})

        # Validate each entry
        cleaned: List[Dict[str, Any]] = []
        for i, api in enumerate(apis):
            if not isinstance(api, dict):
                continue
            name = str(api.get("name", "")).strip()
            url = str(api.get("url", "")).strip()
            if not name or not url:
                continue
            if "<appid>" not in url:
                return json.dumps({"success": False, "error": f"API '{name}' URL must contain <appid> placeholder"})
            cleaned.append({
                "name": name,
                "url": url,
                "api_key": str(api.get("api_key", "")).strip(),
                "enabled": bool(api.get("enabled", True)),
            })

        fp = _apis_path()
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump({"apis": cleaned}, fh, indent=2, ensure_ascii=False)

        logger.log(f"LuaTools: Saved {len(cleaned)} custom API endpoint(s)")
        return json.dumps({"success": True, "count": len(cleaned)})
    except json.JSONDecodeError:
        return json.dumps({"success": False, "error": "Invalid JSON"})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def get_enabled_custom_apis() -> List[Dict[str, Any]]:
    """Return only enabled custom APIs (for use by download pipeline)."""
    try:
        result = json.loads(get_custom_apis())
        return [a for a in result.get("apis", []) if a.get("enabled", False)]
    except Exception:
        return []


__all__ = ["get_custom_apis", "get_enabled_custom_apis", "save_custom_apis"]
