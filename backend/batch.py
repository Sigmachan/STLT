"""LuaTools Batch Pipeline  --  concurrent download queue with persistence and progress.

Features:
  - Concurrent downloads with configurable parallelism (default: 3)
  - Persistent queue (survives plugin restart)
  - Per-app retry with configurable count
  - Aggregate progress: total/active/done/failed/ETA
  - Priority ordering
  - Event emission for batch lifecycle
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from typing import Any, Dict, List, Optional

from logger import logger
from paths import data_path

# Lazy import to avoid circular deps
_downloads_mod = None


def _get_downloads():
    global _downloads_mod
    if _downloads_mod is None:
        import downloads as _dm
        _downloads_mod = _dm
    return _downloads_mod


# ── Batch state ───────────────────────────────────────────────────────

_batch_lock = threading.Lock()
_batch_state: Dict[str, Any] = {
    "active": False,
    "batch_id": "",
    "queue": [],           # [{appid, priority, retries_left, status}]
    "results": {},         # {appid: {status, source, duration_s, error}}
    "config": {
        "parallel": 3,
        "max_retries": 2,
        "delay_between_s": 1.0,
    },
    "started_at": 0,
    "finished_at": 0,
    "cancelled": False,
    "paused": False,
    "skipped": [],         # appids skipped (already installed)
}


def _queue_path() -> str:
    return data_path("batch_queue.json")


def _save_queue() -> None:
    """Persist queue to disk for crash recovery."""
    try:
        path = _queue_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        snapshot = {
            "batch_id": _batch_state["batch_id"],
            "queue": _batch_state["queue"],
            "config": _batch_state["config"],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f)
    except Exception as exc:
        logger.warn(f"LuaTools: Failed to persist batch queue: {exc}")


def _load_queue() -> Optional[Dict]:
    """Load persisted queue if exists."""
    path = _queue_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _clear_queue_file() -> None:
    try:
        os.remove(_queue_path())
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────

def start_batch(appids: List[int], parallel: int = 3, max_retries: int = 2,
                delay: float = 1.0, priority_appids: Optional[List[int]] = None,
                skip_installed: bool = True, force: bool = False) -> str:
    """Start a batch download.

    Args:
        appids: List of Steam AppIDs to download
        parallel: Max concurrent downloads (1-8)
        max_retries: Retry count per failed app
        delay: Seconds between starting new downloads
        priority_appids: These appids go first in queue
        skip_installed: Skip appids that already have a .lua file (default: True)
        force: Override skip_installed (re-download even if already installed)

    Returns: JSON {success, batch_id, queued, skipped_installed}
    """
    with _batch_lock:
        if _batch_state["active"]:
            return json.dumps({"success": False, "error": "Batch already running",
                               "batch_id": _batch_state["batch_id"]})

        parallel = max(1, min(8, parallel))

        # Dedup preserving order
        original_count = len(appids)
        seen: set = set()
        unique_appids: List[int] = []
        for a in appids:
            a = int(a)
            if a not in seen:
                seen.add(a)
                unique_appids.append(a)

        # Skip already-installed if requested
        skipped_installed: List[int] = []
        if skip_installed and not force:
            dl = _get_downloads()
            to_queue: List[int] = []
            for a in unique_appids:
                try:
                    import json as _j
                    result = _j.loads(dl.has_luatools_for_app(a))
                    if result.get("hasLuaTools"):
                        skipped_installed.append(a)
                    else:
                        to_queue.append(a)
                except Exception:
                    to_queue.append(a)
            unique_appids = to_queue

        batch_id = f"batch_{int(time.time())}_{len(unique_appids)}"

        # Build priority-sorted queue
        priority_set = set(priority_appids or [])
        queue = []
        for appid in unique_appids:
            queue.append({
                "appid": appid,
                "priority": 0 if appid in priority_set else 1,
                "retries_left": max_retries,
                "status": "queued",
            })
        queue.sort(key=lambda x: x["priority"])

        _batch_state.update({
            "active": True,
            "batch_id": batch_id,
            "queue": queue,
            "results": {},
            "config": {"parallel": parallel, "max_retries": max_retries, "delay_between_s": delay},
            "started_at": time.time(),
            "finished_at": 0,
            "cancelled": False,
            "paused": False,
            "skipped": skipped_installed,
        })
        _save_queue()

    # Fire event
    try:
        from events import emit
        emit("batch.start", {"batch_id": batch_id, "total": len(appids), "parallel": parallel})
    except Exception:
        pass

    # Start worker thread
    thread = threading.Thread(target=_batch_worker, daemon=True)
    thread.start()

    return json.dumps({
        "success": True,
        "batch_id": batch_id,
        "queued": len(queue),
        "skipped_installed": len(skipped_installed),
        "deduplicated": original_count - len(seen),
    })


def get_batch_status() -> str:
    """Get aggregate batch progress."""
    with _batch_lock:
        if not _batch_state["active"] and not _batch_state["results"]:
            return json.dumps({"success": True, "active": False})

        q = _batch_state["queue"]
        r = _batch_state["results"]
        total = len(q)
        done = sum(1 for v in r.values() if v.get("status") == "done")
        failed = sum(1 for v in r.values() if v.get("status") == "failed")
        active = sum(1 for item in q if item["status"] == "downloading")
        queued = sum(1 for item in q if item["status"] == "queued")

        # ETA calculation
        elapsed = time.time() - _batch_state["started_at"] if _batch_state["started_at"] else 0
        completed = done + failed
        eta_s = 0
        if completed > 0 and (queued + active) > 0:
            rate = elapsed / completed
            eta_s = int(rate * (queued + active))

        skipped_ui = sum(1 for v in r.values() if v.get("status") == "skipped")
        return json.dumps({
            "success": True,
            "active": _batch_state["active"],
            "paused": _batch_state.get("paused", False),
            "batch_id": _batch_state["batch_id"],
            "total": total,
            "done": done,
            "failed": failed,
            "skipped": skipped_ui,
            "active_downloads": active,
            "queued": queued,
            "elapsed_s": int(elapsed),
            "eta_s": eta_s,
            "cancelled": _batch_state["cancelled"],
            "skipped_installed": _batch_state.get("skipped", []),
            "results": r,
        })


def cancel_batch() -> str:
    """Cancel the running batch."""
    with _batch_lock:
        if not _batch_state["active"]:
            return json.dumps({"success": False, "error": "No batch running"})
        _batch_state["cancelled"] = True
    return json.dumps({"success": True})


def pause_batch() -> str:
    """Pause the batch  --  in-flight downloads finish, no new ones start."""
    with _batch_lock:
        if not _batch_state["active"]:
            return json.dumps({"success": False, "error": "No batch running"})
        if _batch_state["paused"]:
            return json.dumps({"success": False, "error": "Batch already paused"})
        _batch_state["paused"] = True
    return json.dumps({"success": True, "message": "Batch paused  --  active downloads will complete"})


def unpause_batch() -> str:
    """Resume a paused batch."""
    with _batch_lock:
        if not _batch_state["active"]:
            return json.dumps({"success": False, "error": "No batch running"})
        if not _batch_state["paused"]:
            return json.dumps({"success": False, "error": "Batch is not paused"})
        _batch_state["paused"] = False
    return json.dumps({"success": True, "message": "Batch resumed"})


def skip_batch_item(appid: int) -> str:
    """Skip a specific queued item in the running batch."""
    appid = int(appid)
    with _batch_lock:
        if not _batch_state["active"]:
            return json.dumps({"success": False, "error": "No batch running"})
        for item in _batch_state["queue"]:
            if item["appid"] == appid and item["status"] == "queued":
                item["status"] = "skipped"
                _batch_state["results"][appid] = {"status": "skipped", "error": "Skipped by user"}
                return json.dumps({"success": True, "appid": appid})
        return json.dumps({"success": False, "error": f"AppID {appid} not in queue or not queued"})


def resume_batch() -> str:
    """Resume a persisted batch queue after restart."""
    saved = _load_queue()
    if not saved or not saved.get("queue"):
        return json.dumps({"success": False, "error": "No saved queue found"})

    remaining = [item for item in saved["queue"] if item.get("status") in ("queued", "downloading")]
    if not remaining:
        _clear_queue_file()
        return json.dumps({"success": False, "error": "All items already processed"})

    # Reset downloading items back to queued
    for item in remaining:
        item["status"] = "queued"

    appids = [item["appid"] for item in remaining]
    cfg = saved.get("config", {})
    return start_batch(appids, parallel=cfg.get("parallel", 3),
                       max_retries=cfg.get("max_retries", 2),
                       delay=cfg.get("delay_between_s", 1.0))


# ── Worker ────────────────────────────────────────────────────────────

def _batch_worker() -> None:
    """Main batch executor  --  runs in background thread."""
    cfg = _batch_state["config"]
    parallel = cfg["parallel"]
    delay = cfg["delay_between_s"]

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures: Dict[Future, Dict] = {}

        while True:
            with _batch_lock:
                if _batch_state["cancelled"]:
                    # Cancel all pending
                    for item in _batch_state["queue"]:
                        if item["status"] == "queued":
                            item["status"] = "cancelled"
                            _batch_state["results"][item["appid"]] = {"status": "cancelled"}
                    break

                # Respect pause  --  don't pick up new items while paused
                paused = _batch_state.get("paused", False)
                active_count = sum(1 for item in _batch_state["queue"] if item["status"] == "downloading")
                slots = 0 if paused else (parallel - active_count)

            if slots > 0:
                to_submit = []
                with _batch_lock:
                    for item in _batch_state["queue"]:
                        if item["status"] == "queued" and len(to_submit) < slots:
                            item["status"] = "downloading"
                            to_submit.append(item)

                for item in to_submit:
                    future = pool.submit(_download_single, item["appid"])
                    futures[future] = item
                    time.sleep(delay)

            # Check completed futures
            done_futures = [f for f in futures if f.done()]
            for future in done_futures:
                item = futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"status": "failed", "error": str(exc)}

                with _batch_lock:
                    if result.get("status") == "failed" and item["retries_left"] > 0:
                        item["retries_left"] -= 1
                        item["status"] = "queued"
                        logger.log(f"LuaTools: Batch retry for {item['appid']} ({item['retries_left']} left)")
                    else:
                        item["status"] = result.get("status", "failed")
                        _batch_state["results"][item["appid"]] = result
                    _save_queue()

                    # Emit progress
                    try:
                        from events import emit
                        total = len(_batch_state["queue"])
                        done = sum(1 for v in _batch_state["results"].values() if v.get("status") == "done")
                        failed = sum(1 for v in _batch_state["results"].values() if v.get("status") == "failed")
                        emit("batch.progress", {"appid": item["appid"], "done": done, "failed": failed, "total": total})
                    except Exception:
                        pass

            # Check if all done
            with _batch_lock:
                all_terminal = all(
                    item["status"] in ("done", "failed", "cancelled", "skipped")
                    for item in _batch_state["queue"]
                )
            if all_terminal and not futures:
                break

            time.sleep(0.5)

    # Batch finished
    with _batch_lock:
        _batch_state["active"] = False
        _batch_state["finished_at"] = time.time()
        _clear_queue_file()

        total = len(_batch_state["queue"])
        done = sum(1 for v in _batch_state["results"].values() if v.get("status") == "done")
        failed = sum(1 for v in _batch_state["results"].values() if v.get("status") == "failed")
        duration = _batch_state["finished_at"] - _batch_state["started_at"]

    try:
        from events import emit
        emit("batch.complete", {
            "batch_id": _batch_state["batch_id"],
            "total": total, "success": done, "failed": failed,
            "duration_s": round(duration, 1),
        })
    except Exception:
        pass

    logger.log(f"LuaTools: Batch complete  --  {done}/{total} success, {failed} failed, {duration:.1f}s")


def _download_single(appid: int) -> Dict[str, Any]:
    """Download a single app (runs in thread pool). Returns result dict."""
    start = time.time()
    try:
        dl = _get_downloads()
        # Use the existing download function
        dl._download_zip_for_app(appid)
        # Check result from download state
        state = dl._get_download_state(appid)
        status = state.get("status", "failed")
        if status == "done" and state.get("success"):
            duration = time.time() - start
            return {
                "status": "done",
                "source": state.get("api", "unknown"),
                "duration_s": round(duration, 1),
            }
        else:
            return {
                "status": "failed",
                "error": state.get("error", "Unknown failure"),
                "duration_s": round(time.time() - start, 1),
            }
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "duration_s": round(time.time() - start, 1)}
