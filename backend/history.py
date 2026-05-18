"""LuaTools Download History  --  persistent log of all download operations.

Stores per-download: appid, source, status, sha256, bytes, duration, timestamp.
Queryable by appid, source, status, date range.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from logger import logger
from paths import data_path

_DB_PATH = None
_db_lock = threading.Lock()


def _db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = data_path("download_history.db")
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    return _DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            appid       INTEGER NOT NULL,
            game_name   TEXT DEFAULT '',
            source      TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'started',
            sha256      TEXT DEFAULT '',
            bytes_total INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            error_msg   TEXT DEFAULT '',
            created_at  REAL NOT NULL,
            finished_at REAL DEFAULT 0,
            manifest_version TEXT DEFAULT '',
            metadata    TEXT DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_appid ON history(appid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at)")
    conn.commit()
    return conn


def record_start(appid: int, source: str, game_name: str = "") -> int:
    """Record download start. Returns history row ID."""
    with _db_lock:
        conn = _get_conn()
        try:
            cur = conn.execute(
                "INSERT INTO history (appid, game_name, source, status, created_at) VALUES (?, ?, ?, 'downloading', ?)",
                (appid, game_name, source, time.time()),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def record_complete(row_id: int, sha256: str = "", bytes_total: int = 0, manifest_version: str = "") -> None:
    """Mark download as completed."""
    now = time.time()
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE history SET status='complete', sha256=?, bytes_total=?, finished_at=?, "
                "duration_ms=CAST((? - created_at) * 1000 AS INTEGER), manifest_version=? WHERE id=?",
                (sha256, bytes_total, now, now, manifest_version, row_id),
            )
            conn.commit()
        finally:
            conn.close()


def record_failure(row_id: int, error: str = "") -> None:
    """Mark download as failed."""
    now = time.time()
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE history SET status='failed', error_msg=?, finished_at=?, "
                "duration_ms=CAST((? - created_at) * 1000 AS INTEGER) WHERE id=?",
                (error[:500], now, now, row_id),
            )
            conn.commit()
        finally:
            conn.close()


def file_sha256(filepath: str) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def get_history(appid: int = 0, limit: int = 50, offset: int = 0,
                status: str = "", source: str = "",
                date_from: float = 0.0, date_to: float = 0.0) -> List[Dict[str, Any]]:
    """Query download history. appid=0 returns all.

    Args:
        appid: Filter by Steam AppID (0 = all)
        limit: Max rows to return
        offset: Pagination offset
        status: Filter by status ('complete', 'failed', 'downloading')
        source: Partial match on source name
        date_from: Unix timestamp  --  only rows created after this
        date_to: Unix timestamp  --  only rows created before this
    """
    with _db_lock:
        conn = _get_conn()
        try:
            query = "SELECT * FROM history WHERE 1=1"
            params: list = []
            if appid:
                query += " AND appid=?"
                params.append(appid)
            if status:
                query += " AND status=?"
                params.append(status)
            if source:
                query += " AND source LIKE ?"
                params.append(f"%{source}%")
            if date_from:
                query += " AND created_at >= ?"
                params.append(float(date_from))
            if date_to:
                query += " AND created_at <= ?"
                params.append(float(date_to))
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_stats() -> Dict[str, Any]:
    """Aggregate stats: total downloads, by source, by status, avg duration."""
    with _db_lock:
        conn = _get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            by_status = {r[0]: r[1] for r in conn.execute(
                "SELECT status, COUNT(*) FROM history GROUP BY status").fetchall()}
            by_source = {r[0]: r[1] for r in conn.execute(
                "SELECT source, COUNT(*) FROM history WHERE status='complete' GROUP BY source ORDER BY COUNT(*) DESC"
            ).fetchall()}
            avg_dur = conn.execute(
                "SELECT AVG(duration_ms) FROM history WHERE status='complete' AND duration_ms > 0"
            ).fetchone()[0] or 0
            total_bytes = conn.execute(
                "SELECT SUM(bytes_total) FROM history WHERE status='complete'"
            ).fetchone()[0] or 0
            return {
                "total_downloads": total,
                "by_status": by_status,
                "by_source": by_source,
                "avg_duration_ms": int(avg_dur),
                "total_bytes": total_bytes,
                "unique_games": conn.execute(
                    "SELECT COUNT(DISTINCT appid) FROM history WHERE status='complete'"
                ).fetchone()[0],
            }
        finally:
            conn.close()


def get_last_download(appid: int) -> Optional[Dict[str, Any]]:
    """Get most recent download record for an appid."""
    rows = get_history(appid=appid, limit=1)
    return rows[0] if rows else None




def get_stats_by_source() -> Dict[str, Any]:
    """Per-source aggregate stats for the source chain widget.

    Returns a dict keyed by source name with:
      total, success, failed, success_rate (0-1),
      avg_speed_kbps, last_success_at (Unix timestamp).
    """
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("""
                SELECT
                    source,
                    COUNT(*)                                        AS total,
                    SUM(status = 'complete')                        AS success,
                    SUM(status = 'failed')                          AS failed,
                    AVG(CASE WHEN status='complete' AND duration_ms > 0
                             AND bytes_total > 0
                             THEN CAST(bytes_total AS REAL) / duration_ms
                             ELSE NULL END)                         AS avg_kbps,
                    MAX(CASE WHEN status='complete' THEN finished_at ELSE NULL END) AS last_success_at
                FROM history
                GROUP BY source
            """).fetchall()
            result: Dict[str, Any] = {}
            for r in rows:
                total = r["total"] or 0
                success = r["success"] or 0
                result[r["source"]] = {
                    "total": total,
                    "success": success,
                    "failed": r["failed"] or 0,
                    "success_rate": round(success / total, 3) if total else None,
                    "avg_speed_kbps": round((r["avg_kbps"] or 0), 1) or None,
                    "last_success_at": r["last_success_at"],
                }
            return result
        finally:
            conn.close()


def prune_history(days: int = 30) -> Dict[str, Any]:
    """Delete history records older than `days` days.

    Keeps the most recent record for each appid regardless of age
    so the UI always has something to show per game.

    Returns {deleted, kept, oldest_kept_at}.
    """
    days = max(1, int(days))
    cutoff = time.time() - days * 86400
    with _db_lock:
        conn = _get_conn()
        try:
            # Count before
            total_before = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]

            # Find the most recent row id per appid  --  these are never deleted
            conn.execute("""
                DELETE FROM history
                WHERE created_at < ?
                AND id NOT IN (
                    SELECT MAX(id) FROM history GROUP BY appid
                )
            """, (cutoff,))
            conn.commit()

            total_after = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            oldest = conn.execute(
                "SELECT MIN(created_at) FROM history"
            ).fetchone()[0]

            return {
                "success": True,
                "deleted": total_before - total_after,
                "kept": total_after,
                "oldest_kept_at": oldest,
            }
        finally:
            conn.close()

# ── IPC wrappers ──────────────────────────────────────────────────────

def get_download_history_json(appid: int = 0, limit: int = 50, status: str = "",
                              source: str = "", date_from: float = 0.0, date_to: float = 0.0) -> str:
    try:
        rows = get_history(appid=appid, limit=limit, status=status, source=source,
                           date_from=date_from, date_to=date_to)
        return json.dumps({"success": True, "history": rows, "count": len(rows)})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def prune_history_json(days: int = 30) -> str:
    """IPC wrapper for prune_history."""
    try:
        return json.dumps(prune_history(days=days))
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def get_download_stats_json() -> str:
    try:
        return json.dumps({"success": True, "stats": get_stats()})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
