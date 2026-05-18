"""LuaTools Source Chain Config  --  customizable download priority pipeline.

Users can:
  - Reorder download sources
  - Enable/disable individual sources
  - Set per-source timeout, retry count
  - Blacklist specific free APIs
  - View source success rate stats
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from logger import logger
from paths import data_path

_CONFIG_FILE = None

# Default chain  --  matches original hardcoded order
DEFAULT_CHAIN = [
    {"id": "local",           "name": "Local Folder",          "enabled": True,  "timeout": 10,  "retries": 0},
    {"id": "twentytwo",       "name": "TwentyTwo Cloud",       "enabled": True,  "timeout": 15,  "retries": 1},
    {"id": "ryuu",            "name": "Ryuu Premium",          "enabled": True,  "timeout": 20,  "retries": 1},
    {"id": "depotbox",        "name": "DepotBox Premium",      "enabled": True,  "timeout": 120, "retries": 0},
    {"id": "manifesthub_api", "name": "ManifestHub API",       "enabled": True,  "timeout": 30,  "retries": 1},
    {"id": "custom_apis",     "name": "Custom APIs",           "enabled": True,  "timeout": 20,  "retries": 0},
    {"id": "free_apis",       "name": "Free APIs",             "enabled": True,  "timeout": 20,  "retries": 0},
    {"id": "fallbacks",       "name": "SLStools Fallbacks",    "enabled": True,  "timeout": 15,  "retries": 1},
    {"id": "github_repos",    "name": "GitHub Repos (SDO)",    "enabled": True,  "timeout": 30,  "retries": 0},
]

# Built-in free API blacklist (user-extendable)
DEFAULT_BLACKLIST: List[str] = []


def _config_path() -> str:
    global _CONFIG_FILE
    if _CONFIG_FILE is None:
        _CONFIG_FILE = data_path("source_chain.json")
    return _CONFIG_FILE


def load_chain() -> List[Dict[str, Any]]:
    """Load source chain config. Returns default if not customized."""
    path = _config_path()
    if not os.path.exists(path):
        return [dict(s) for s in DEFAULT_CHAIN]
    try:
        with open(path, "r", encoding="utf-8") as f:
            chain = json.load(f).get("chain", DEFAULT_CHAIN)
        # Merge any missing default sources (in case new sources added in update)
        known_ids = {s["id"] for s in chain}
        for default in DEFAULT_CHAIN:
            if default["id"] not in known_ids:
                chain.append(dict(default))
        return chain
    except Exception:
        return [dict(s) for s in DEFAULT_CHAIN]


def save_chain(chain: List[Dict[str, Any]]) -> None:
    """Save customized source chain."""
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    config = {"chain": chain, "blacklist": load_blacklist()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def load_blacklist() -> List[str]:
    """Load blacklisted free API names."""
    path = _config_path()
    if not os.path.exists(path):
        return list(DEFAULT_BLACKLIST)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("blacklist", DEFAULT_BLACKLIST)
    except Exception:
        return list(DEFAULT_BLACKLIST)


def save_blacklist(blacklist: List[str]) -> None:
    """Save free API blacklist."""
    path = _config_path()
    config = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass
    config["blacklist"] = blacklist
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_enabled_chain() -> List[Dict[str, Any]]:
    """Get only enabled sources in priority order."""
    return [s for s in load_chain() if s.get("enabled", True)]


def is_source_enabled(source_id: str) -> bool:
    """Check if a specific source is enabled."""
    for s in load_chain():
        if s["id"] == source_id:
            return s.get("enabled", True)
    return True


def get_source_timeout(source_id: str) -> int:
    """Get timeout for a source."""
    for s in load_chain():
        if s["id"] == source_id:
            return s.get("timeout", 20)
    return 20


def is_api_blacklisted(api_name: str) -> bool:
    """Check if a free API is blacklisted."""
    bl = load_blacklist()
    return api_name.lower() in [b.lower() for b in bl]




def get_source_stats() -> Dict[str, Any]:
    """Query download history and compute per-source stats.

    Returns success rate, avg speed (KB/s), last success timestamp
    and total count for each source in the chain.
    """
    try:
        from history import get_stats_by_source
        return get_stats_by_source()
    except Exception as exc:
        logger.warn(f"LuaTools: source_stats query failed: {exc}")
        return {}

# ── IPC wrappers ──────────────────────────────────────────────────────

def get_source_chain_json() -> str:
    try:
        chain = load_chain()
        stats = get_source_stats()
        # Attach live stats to each chain entry
        for entry in chain:
            src_stats = stats.get(entry["id"]) or stats.get(entry["name"]) or {}
            entry["stats"] = {
                "total": src_stats.get("total", 0),
                "success": src_stats.get("success", 0),
                "failed": src_stats.get("failed", 0),
                "success_rate": src_stats.get("success_rate", None),
                "avg_speed_kbps": src_stats.get("avg_speed_kbps", None),
                "last_success_at": src_stats.get("last_success_at", None),
            }
        return json.dumps({
            "success": True,
            "chain": chain,
            "blacklist": load_blacklist(),
            "defaults": DEFAULT_CHAIN,
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def save_source_chain_json(chain_json: str) -> str:
    try:
        data = json.loads(chain_json) if isinstance(chain_json, str) else chain_json
        if "chain" in data:
            save_chain(data["chain"])
        if "blacklist" in data:
            save_blacklist(data["blacklist"])
        return json.dumps({"success": True})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
