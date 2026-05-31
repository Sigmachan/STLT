"""Steam Workshop content manager for .lua-activated games (v9.0).

Steam Workshop subscriptions are broken for many cracked games: Steam recognizes
the subscription but won't actually download the content because the API checks
that you own the base game. This module works around that by:

  1. Reading the user's subscribed Workshop items from localconfig.vdf
  2. Cross-referencing what's actually downloaded on disk
  3. For missing items, fetching the public download URL via the Web API
     and downloading directly via httpx (no Steam client required)

Workshop items live at:
    <Steam>/steamapps/workshop/content/<appid>/<workshopId>/

Each item is either:
  - A single file (rare — typically images / configs)
  - A folder with extracted content (most common — mods, maps)

Steam Web API used:
  ISteamRemoteStorage/GetPublishedFileDetails  (POST, public, no auth needed)

Source: ValveSoftware/steam-for-linux docs + community reverse engineering.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from logger import logger
from paths import data_path
from steam_utils import detect_steam_install_path


_PUBLISHED_FILE_DETAILS_URL = (
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
)


# ── Storage paths ──────────────────────────────────────────────────────

def _workshop_content_dir(appid: int) -> str:
    base = detect_steam_install_path()
    if not base:
        return ""
    return os.path.join(base, "steamapps", "workshop", "content", str(int(appid)))


def _localconfig_path(account_id32: int) -> str:
    base = detect_steam_install_path()
    if not base:
        return ""
    return os.path.join(
        base, "userdata", str(int(account_id32)), "config", "localconfig.vdf"
    )


# ── Parsing subscribed items from localconfig.vdf ──────────────────────

def _parse_subscribed_items(account_id32: int, appid: int) -> List[Dict[str, Any]]:
    """Walk localconfig.vdf for an account, return all Workshop subscriptions
    for the given appid.

    The structure looks like:
      "UserLocalConfigStore"
      {
          "Software" { "Valve" { "Steam" { "apps" {
              "<appid>" {
                  "Workshop" {
                      "Subscriptions" {
                          "<workshopId>" { ... }
                      }
                  }
              }
          } } } }
      }
    """
    p = _localconfig_path(account_id32)
    if not p or not os.path.isfile(p):
        return []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return []

    # Find the appid block
    appid_str = str(int(appid))
    appid_match = re.search(
        rf'"\s*{appid_str}\s*"\s*\{{(.+?)(?=\n\s*"\d+"\s*\{{|\n\s*\}}\s*\}})',
        text, re.DOTALL,
    )
    if not appid_match:
        return []

    app_body = appid_match.group(1)
    sub_match = re.search(
        r'"Subscriptions"\s*\{(.+?)\n\s*\}', app_body, re.DOTALL
    )
    if not sub_match:
        return []

    sub_body = sub_match.group(1)
    items = []
    for m in re.finditer(
        r'"(\d{6,})"\s*\{([^}]*)\}', sub_body, re.DOTALL
    ):
        workshop_id = m.group(1)
        body = m.group(2)
        ts_m = re.search(r'"TimeSubscribed"\s*"(\d+)"', body)
        items.append({
            "workshopId": workshop_id,
            "timeSubscribed": int(ts_m.group(1)) if ts_m else 0,
        })
    return items


# ── Local download status ──────────────────────────────────────────────

def _is_item_downloaded(appid: int, workshop_id: str) -> Tuple[bool, int]:
    """Return (downloaded?, total_bytes)."""
    content = _workshop_content_dir(appid)
    if not content:
        return False, 0
    item_path = os.path.join(content, str(workshop_id))
    if not os.path.exists(item_path):
        return False, 0
    # Folder or file?
    if os.path.isfile(item_path):
        return True, os.path.getsize(item_path)
    if os.path.isdir(item_path):
        total = 0
        for root, _dirs, files in os.walk(item_path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
        return total > 0, total
    return False, 0


# ── Steam Web API: get published file details ──────────────────────────

def _fetch_published_file_details(workshop_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch-fetch metadata + download URL for one or more Workshop items.

    POST to ISteamRemoteStorage/GetPublishedFileDetails with form fields:
        itemcount=N
        publishedfileids[0]=<id1>
        publishedfileids[1]=<id2>
        ...
    """
    if not workshop_ids:
        return {}

    try:
        from http_client import ensure_http_client
        client = ensure_http_client("workshop_manager")

        form = {"itemcount": str(len(workshop_ids))}
        for i, wid in enumerate(workshop_ids):
            form[f"publishedfileids[{i}]"] = wid

        resp = client.post(
            _PUBLISHED_FILE_DETAILS_URL,
            data=form,
            timeout=15,
        )
        if not resp.is_success:
            logger.warn(f"workshop: API HTTP {resp.status_code}")
            return {}

        data = resp.json()
        details = data.get("response", {}).get("publishedfiledetails", [])
        out: Dict[str, Dict[str, Any]] = {}
        for d in details:
            wid = str(d.get("publishedfileid", ""))
            if not wid:
                continue
            out[wid] = {
                "title": d.get("title", ""),
                "description": (d.get("description", "") or "")[:200],
                "creator": d.get("creator", ""),
                "appid": int(d.get("consumer_app_id", 0)),
                "fileUrl": d.get("file_url", ""),
                "fileSize": int(d.get("file_size", 0)),
                "previewUrl": d.get("preview_url", ""),
                "fileName": d.get("filename", ""),
                "timeUpdated": int(d.get("time_updated", 0)),
                "result": int(d.get("result", 0)),  # 1=OK, 9=not found
                "banned": bool(d.get("banned", False)),
            }
        return out
    except Exception as exc:
        logger.warn(f"workshop: fetch details failed: {exc}")
        return {}


# ── Direct download (bypasses Steam client) ────────────────────────────

def _download_to_workshop_dir(appid: int, workshop_id: str, file_url: str,
                              file_name: str) -> Dict[str, Any]:
    """Download a workshop item directly via httpx, unpack to workshop dir."""
    if not file_url:
        return {"success": False, "error": "no file_url — item may be private"}

    content_dir = _workshop_content_dir(appid)
    if not content_dir:
        return {"success": False, "error": "Steam install path not found"}

    try:
        os.makedirs(content_dir, exist_ok=True)
    except Exception as exc:
        return {"success": False, "error": f"mkdir failed: {exc}"}

    item_dir = os.path.join(content_dir, str(workshop_id))

    # If item dir already exists with content, refuse without explicit overwrite
    if os.path.isdir(item_dir):
        existing_files = sum(1 for _r, _d, fs in os.walk(item_dir) for _ in fs)
        if existing_files > 0:
            return {
                "success": False,
                "error": f"Item already downloaded ({existing_files} files). "
                         "Remove the folder manually if you want to re-download.",
                "itemDir": item_dir,
            }

    # Download into a temp file first, then unpack
    from utils import ensure_temp_download_dir
    tmp_dir = ensure_temp_download_dir()
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", file_name or "workshop_item")
    tmp_path = os.path.join(tmp_dir, f"wsdl_{workshop_id}_{safe_name}")

    try:
        from http_client import ensure_http_client
        client = ensure_http_client("workshop_manager")
        with client.stream("GET", file_url, follow_redirects=True, timeout=120) as resp:
            if not resp.is_success:
                return {"success": False,
                        "error": f"HTTP {resp.status_code} downloading {file_url}"}
            with open(tmp_path, "wb") as out:
                for chunk in resp.iter_bytes(65536):
                    out.write(chunk)
    except Exception as exc:
        try: os.remove(tmp_path)
        except Exception: pass
        return {"success": False, "error": f"download failed: {exc}"}

    file_size = os.path.getsize(tmp_path) if os.path.isfile(tmp_path) else 0
    if file_size < 16:
        try: os.remove(tmp_path)
        except Exception: pass
        return {"success": False, "error": "downloaded file too small (network error?)"}

    # Detect if it's a ZIP — extract; otherwise just move
    try:
        os.makedirs(item_dir, exist_ok=True)
    except Exception as exc:
        return {"success": False, "error": f"item dir create: {exc}"}

    extracted = False
    try:
        # ZIP magic: PK\x03\x04
        with open(tmp_path, "rb") as f:
            magic = f.read(4)
        if magic == b"PK\x03\x04":
            with zipfile.ZipFile(tmp_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith("/") or ".." in member:
                        continue
                    zf.extract(member, item_dir)
            extracted = True
    except Exception as exc:
        logger.warn(f"workshop: extract failed for {workshop_id}: {exc}")

    if not extracted:
        # Not a ZIP — just move the file into the item dir under its original name
        dest = os.path.join(item_dir, file_name or "workshop_item")
        try:
            shutil.move(tmp_path, dest)
        except Exception as exc:
            return {"success": False, "error": f"move failed: {exc}"}
    else:
        try: os.remove(tmp_path)
        except Exception: pass

    # Final sanity check
    final_size = 0
    final_count = 0
    for r, _d, fs in os.walk(item_dir):
        for f in fs:
            try:
                final_size += os.path.getsize(os.path.join(r, f))
                final_count += 1
            except Exception:
                pass

    logger.log(
        f"workshop: downloaded {workshop_id} -> {item_dir} "
        f"({final_count} files, {final_size:,} bytes)"
    )
    return {
        "success": True,
        "workshopId": workshop_id,
        "itemDir": item_dir,
        "extracted": extracted,
        "fileCount": final_count,
        "totalBytes": final_size,
    }


# ── Public IPC ─────────────────────────────────────────────────────────

def list_subscribed(appid: int, accountId32: int,
                    contentScriptQuery: str = "") -> str:
    """All Workshop subscriptions for an appid/account, with download status."""
    try:
        appid = int(appid)
        account_id32 = int(accountId32)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid or accountId32"})

    subs = _parse_subscribed_items(account_id32, appid)
    if not subs:
        return json.dumps({
            "success": True,
            "appid": appid,
            "accountId32": account_id32,
            "items": [],
            "message": "No Workshop subscriptions found in localconfig.vdf for this game/account",
        })

    # Batch-fetch metadata
    ids = [s["workshopId"] for s in subs]
    details = _fetch_published_file_details(ids)

    items: List[Dict[str, Any]] = []
    for s in subs:
        wid = s["workshopId"]
        det = details.get(wid, {})
        downloaded, size_local = _is_item_downloaded(appid, wid)
        items.append({
            "workshopId": wid,
            "title": det.get("title", "(metadata unavailable)"),
            "creator": det.get("creator", ""),
            "downloaded": downloaded,
            "localBytes": size_local,
            "remoteBytes": det.get("fileSize", 0),
            "hasFileUrl": bool(det.get("fileUrl")),
            "fileName": det.get("fileName", ""),
            "timeSubscribed": s.get("timeSubscribed", 0),
            "timeUpdated": det.get("timeUpdated", 0),
            "banned": det.get("banned", False),
            "previewUrl": det.get("previewUrl", ""),
            "result": det.get("result", 0),  # 1=OK, 9=not found
        })

    downloaded_count = sum(1 for i in items if i["downloaded"])
    missing_count = len(items) - downloaded_count

    return json.dumps({
        "success": True,
        "appid": appid,
        "accountId32": account_id32,
        "totalSubscribed": len(items),
        "downloadedCount": downloaded_count,
        "missingCount": missing_count,
        "items": items,
    })


def list_local_items(appid: int, contentScriptQuery: str = "") -> str:
    """All Workshop items currently on disk for an appid (regardless of subscription).

    Useful for finding orphaned downloads (item present but no subscription)."""
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid"})

    content = _workshop_content_dir(appid)
    if not content or not os.path.isdir(content):
        return json.dumps({"success": True, "appid": appid, "items": []})

    items = []
    for name in os.listdir(content):
        full = os.path.join(content, name)
        if not name.isdigit():
            continue
        if os.path.isdir(full):
            file_count = sum(1 for _r, _d, fs in os.walk(full) for _ in fs)
            size = sum(
                os.path.getsize(os.path.join(r, f))
                for r, _d, fs in os.walk(full)
                for f in fs
            )
            items.append({
                "workshopId": name,
                "isDir": True,
                "fileCount": file_count,
                "totalBytes": size,
            })
        elif os.path.isfile(full):
            items.append({
                "workshopId": name,
                "isDir": False,
                "fileCount": 1,
                "totalBytes": os.path.getsize(full),
            })

    return json.dumps({
        "success": True,
        "appid": appid,
        "items": items,
        "total": len(items),
    })


def download_item(appid: int, workshopId: str = "",
                  contentScriptQuery: str = "") -> str:
    """Download a Workshop item directly via the public Web API.

    Bypasses Steam client — fetches the file_url from
    ISteamRemoteStorage/GetPublishedFileDetails and downloads/unpacks it
    into the right workshop folder.
    """
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid"})

    workshop_id = (workshopId or "").strip()
    if not workshop_id or not workshop_id.isdigit():
        return json.dumps({"success": False, "error": "valid workshopId required"})

    details = _fetch_published_file_details([workshop_id])
    item = details.get(workshop_id)
    if not item:
        return json.dumps({
            "success": False,
            "error": "Could not fetch item details from Steam Web API",
        })

    if item.get("result") == 9:
        return json.dumps({"success": False, "error": "Item not found on Steam"})
    if item.get("banned"):
        return json.dumps({"success": False, "error": "Item is banned"})

    if not item.get("fileUrl"):
        return json.dumps({
            "success": False,
            "error": (
                "Item has no direct download URL — typical for hidden, friends-only, "
                "or in-game-only Workshop items. Cannot bypass."
            ),
            "title": item.get("title", ""),
        })

    result = _download_to_workshop_dir(
        appid, workshop_id, item["fileUrl"], item.get("fileName", "")
    )
    result["title"] = item.get("title", "")
    return json.dumps(result)


def delete_item(appid: int, workshopId: str = "",
                contentScriptQuery: str = "") -> str:
    """Remove a downloaded Workshop item's folder."""
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({"success": False, "error": "invalid appid"})

    workshop_id = (workshopId or "").strip()
    if not workshop_id or not workshop_id.isdigit():
        return json.dumps({"success": False, "error": "valid workshopId required"})

    content = _workshop_content_dir(appid)
    if not content:
        return json.dumps({"success": False, "error": "Steam install not found"})
    item_path = os.path.join(content, workshop_id)
    if not os.path.exists(item_path):
        return json.dumps({"success": False, "error": "Item not found locally"})

    try:
        if os.path.isfile(item_path):
            os.remove(item_path)
        else:
            shutil.rmtree(item_path)
    except Exception as exc:
        return json.dumps({"success": False, "error": f"delete failed: {exc}"})

    logger.log(f"workshop: deleted local copy of item {workshop_id} (appid {appid})")
    return json.dumps({"success": True, "workshopId": workshop_id})
