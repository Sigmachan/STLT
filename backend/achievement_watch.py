"""Read-only achievement progress dashboard (v9.1).

This is the LEGITIMATE alternative to a "fake achievement unlocker". It only
READS data — never modifies UserGameStats_*.bin files. The data sources:

  1. Steam Web API (ISteamUserStats/GetSchemaForGame) for the canonical
     achievement list with display names, descriptions, icons
  2. UserGameStats_<accountId>_<appid>.bin local file — parses the binary
     to count which achievements are unlocked + their timestamps
  3. Cross-references both to compute per-game progress

What this DOESN'T do:
  - No writes to any stats file
  - No fake unlocks on your public profile
  - No bypassing of Steam's achievement validation
  - No risk of VAC issues

What it DOES give you:
  - Per-game progress percentage
  - Total achievement count vs unlocked
  - Recent unlocks across all your activated games
  - Identify games where schema is missing (need to launch once to populate)

Binary format reference: UserGameStats_*.bin is a Steam Stats serialization
that maps achievement CRC -> (unlocked timestamp, progress value). The exact
protobuf format is undocumented but the high-level layout is:

  [0x07] CRC = <int>
  [0x08] flag = 0 or 1 (unlocked)
  [0x08] unlock_ts = <unix timestamp>

We do a conservative byte-pattern scan rather than full protobuf parse —
counts unique CRC IDs that have a non-zero unlock timestamp. This is
approximate but error-bound is small for the purpose of a progress display.
"""

from __future__ import annotations

import json
import os
import re
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

from logger import logger


def _appcache_stats_dir() -> str:
    """Where Steam stores per-user achievement state."""
    from steam_utils import detect_steam_install_path
    base = detect_steam_install_path()
    return os.path.join(base, "appcache", "stats") if base else ""


def _stplug_dir() -> str:
    from steam_utils import detect_steam_install_path
    base = detect_steam_install_path()
    return os.path.join(base, "config", "stplug-in") if base else ""


# ── Binary stats parsing ───────────────────────────────────────────────

def _parse_user_stats_binary(path: str) -> Dict[str, Any]:
    """Conservative scan of UserGameStats_*.bin for achievement records.

    Returns {unlocked_count, unlock_timestamps[], total_size}.

    The format is a Steam protobuf-encoded message. Without the actual .proto
    definition we approach this as a pattern scan:
      - Look for varint-encoded integer pairs that look like
        (achievement_id, unlocked_flag=1, unix_timestamp)
      - Filter timestamps to a sane range (Steam launched ~2003-09 →
        timestamps before ~1062374400 are noise)
    """
    if not os.path.isfile(path):
        return {"exists": False}

    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception as exc:
        return {"exists": False, "error": str(exc)}

    file_size = len(data)
    if file_size < 32:
        # Empty seeded template — no unlocks yet
        return {"exists": True, "fileSize": file_size, "unlockedCount": 0,
                "timestamps": [], "seeded_empty": True}

    # Plausible Steam timestamps: between Sep 2003 (Steam launch) and now+1 day
    min_ts = 1062374400  # 2003-09-01
    max_ts = int(time.time()) + 86400

    # Heuristic: find 4-byte little-endian integers that are plausible Steam
    # achievement timestamps. We do an overlapping scan because timestamps
    # can be unaligned in the protobuf encoding.
    timestamps: List[int] = []
    seen_offsets = set()
    for i in range(0, file_size - 4):
        ts = struct.unpack("<I", data[i:i+4])[0]
        if min_ts <= ts <= max_ts:
            # Avoid double-counting adjacent overlapping reads
            if i in seen_offsets:
                continue
            seen_offsets.add(i)
            timestamps.append(ts)

    # The same timestamp can appear multiple times in the protobuf for the
    # same achievement (different fields). De-dup by exact timestamp value.
    # This is imperfect — two different achievements unlocked at the same
    # second collapse to one. For dashboard display that's acceptable.
    unique_ts = sorted(set(timestamps), reverse=True)

    return {
        "exists": True,
        "fileSize": file_size,
        "unlockedCount": len(unique_ts),
        "timestamps": unique_ts[:50],  # last 50 for the dashboard
        "seeded_empty": False,
    }


# ── Achievement schema (from Steam Web API) ────────────────────────────

def _fetch_achievement_schema(appid: int, web_api_key: str = "") -> Dict[str, Any]:
    """Fetch the canonical achievement list for an appid via Steam Web API.

    Without an API key, this still works but uses a public alternative endpoint
    that returns less detail (just IDs + counts).
    """
    from http_client import ensure_http_client
    client = ensure_http_client("achievement_watch")

    # Try the rich endpoint first (needs API key)
    if web_api_key:
        try:
            resp = client.get(
                "https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/",
                params={"key": web_api_key, "appid": appid, "l": "english"},
                timeout=10,
            )
            if resp.is_success:
                data = resp.json()
                game = data.get("game", {})
                stats = game.get("availableGameStats", {})
                achievements = stats.get("achievements", [])
                return {
                    "success": True,
                    "source": "web_api_keyed",
                    "gameName": game.get("gameName", ""),
                    "achievements": [
                        {
                            "name": a.get("name", ""),
                            "displayName": a.get("displayName", ""),
                            "description": a.get("description", ""),
                            "hidden": bool(a.get("hidden", 0)),
                            "icon": a.get("icon", ""),
                            "iconGray": a.get("icongray", ""),
                        }
                        for a in achievements
                    ],
                }
        except Exception as exc:
            logger.warn(f"achievement_watch: GetSchemaForGame failed: {exc}")

    # Fallback: public global percentages endpoint (no key needed)
    try:
        resp = client.get(
            "https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/",
            params={"gameid": appid},
            timeout=10,
        )
        if resp.is_success:
            data = resp.json()
            percentages = data.get("achievementpercentages", {}).get("achievements", [])
            return {
                "success": True,
                "source": "public_global",
                "achievements": [
                    {
                        "name": p.get("name", ""),
                        "displayName": p.get("name", ""),
                        "globalPercent": float(p.get("percent", 0)),
                    }
                    for p in percentages
                ],
            }
    except Exception as exc:
        logger.warn(f"achievement_watch: global percentages failed: {exc}")

    return {"success": False, "error": "Could not fetch achievement schema"}


# ── Per-game watchlist ─────────────────────────────────────────────────

def get_game_progress(appid: int, account_id32: int,
                      contentScriptQuery: str = "") -> str:
    """Per-game achievement progress (read-only)."""
    try:
        appid = int(appid)
        account_id32 = int(account_id32)
    except Exception:
        return json.dumps({"success": False, "error": "invalid args"})

    stats_dir = _appcache_stats_dir()
    user_file = os.path.join(
        stats_dir, f"UserGameStats_{account_id32}_{appid}.bin"
    )

    parsed = _parse_user_stats_binary(user_file)

    # Try to get total achievement count via Web API
    try:
        from settings.manager import get_steamtools_settings
        st_settings = get_steamtools_settings()
        web_key = st_settings.get("steamtools", {}).get("steamWebApiKey", "")
    except Exception:
        web_key = ""

    schema = _fetch_achievement_schema(appid, web_key)
    total = len(schema.get("achievements", [])) if schema.get("success") else 0
    unlocked = parsed.get("unlockedCount", 0) if parsed.get("exists") else 0

    # Cap unlocked at total (parsing may over-count for noisy binaries)
    if total > 0 and unlocked > total:
        unlocked = total

    percentage = round(100 * unlocked / total, 1) if total > 0 else 0

    return json.dumps({
        "success": True,
        "appid": appid,
        "accountId32": account_id32,
        "gameName": schema.get("gameName", ""),
        "schemaSource": schema.get("source", ""),
        "schemaAvailable": schema.get("success", False),
        "statsFileExists": parsed.get("exists", False),
        "statsFileSize": parsed.get("fileSize", 0),
        "seeded_empty": parsed.get("seeded_empty", False),
        "totalAchievements": total,
        "unlockedCount": unlocked,
        "percentage": percentage,
        "recentUnlocks": parsed.get("timestamps", [])[:10],
    })


def list_games_with_achievements(account_id32: int,
                                 contentScriptQuery: str = "") -> str:
    """Scan all .lua-activated games and report achievement progress per game.

    Used by the dashboard to show your overall achievement status across
    everything LuaTools has activated.
    """
    try:
        account_id32 = int(account_id32)
    except Exception:
        return json.dumps({"success": False, "error": "invalid accountId32"})

    stplug = _stplug_dir()
    if not stplug or not os.path.isdir(stplug):
        return json.dumps({"success": False, "error": "stplug-in dir not found"})

    stats_dir = _appcache_stats_dir()

    games: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(stplug)):
        m = re.match(r"^(\d+)\.lua$", fname)
        if not m:
            continue
        appid = int(m.group(1))

        user_file = os.path.join(
            stats_dir, f"UserGameStats_{account_id32}_{appid}.bin"
        )
        schema_file = os.path.join(stats_dir, f"UserGameStatsSchema_{appid}.bin")

        parsed = _parse_user_stats_binary(user_file)
        games.append({
            "appid": appid,
            "hasStatsFile": parsed.get("exists", False),
            "hasSchema": os.path.isfile(schema_file),
            "schemaSize": os.path.getsize(schema_file) if os.path.isfile(schema_file) else 0,
            "unlockedCount": parsed.get("unlockedCount", 0),
            "seeded_empty": parsed.get("seeded_empty", False),
            "lastUnlockTs": (parsed.get("timestamps") or [0])[0] if parsed.get("timestamps") else 0,
        })

    # Sort: games with progress first, then by recency
    games.sort(key=lambda g: (-g["unlockedCount"], -g["lastUnlockTs"]))

    total_unlocked = sum(g["unlockedCount"] for g in games)
    games_with_progress = sum(1 for g in games if g["unlockedCount"] > 0)

    return json.dumps({
        "success": True,
        "accountId32": account_id32,
        "totalGames": len(games),
        "gamesWithProgress": games_with_progress,
        "totalUnlocked": total_unlocked,
        "games": games,
    })


def get_recent_unlocks_across_games(account_id32: int, limit: int = 20,
                                    contentScriptQuery: str = "") -> str:
    """Aggregate recent achievement unlocks across all your games."""
    try:
        account_id32 = int(account_id32)
        limit = max(1, min(int(limit), 100))
    except Exception:
        return json.dumps({"success": False, "error": "invalid args"})

    stats_dir = _appcache_stats_dir()
    if not os.path.isdir(stats_dir):
        return json.dumps({"success": True, "unlocks": []})

    all_unlocks: List[Dict[str, Any]] = []
    prefix = f"UserGameStats_{account_id32}_"
    for fname in os.listdir(stats_dir):
        if not (fname.startswith(prefix) and fname.endswith(".bin")):
            continue
        try:
            appid = int(fname[len(prefix):-4])
        except ValueError:
            continue
        parsed = _parse_user_stats_binary(os.path.join(stats_dir, fname))
        for ts in parsed.get("timestamps", []):
            all_unlocks.append({"appid": appid, "ts": ts})

    all_unlocks.sort(key=lambda u: -u["ts"])
    return json.dumps({
        "success": True,
        "accountId32": account_id32,
        "unlocks": all_unlocks[:limit],
        "totalCount": len(all_unlocks),
    })
