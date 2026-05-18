"""LuaTools Event Bus  --  hook system for download lifecycle events.

Supports:
  - webhook: POST JSON to URL (Discord, ntfy, Telegram, etc.)
  - exec: run shell command with {appid}, {source}, {status} placeholders
  - internal: Python callables registered at runtime

Events emitted:
  download.start, download.complete, download.fail,
  batch.start, batch.complete, batch.progress,
  install.complete, install.fail,
  health.warning, health.error
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional

from logger import logger

# ── Internal subscriber registry ──────────────────────────────────────

_listeners: Dict[str, List[Callable]] = {}
_listener_lock = threading.Lock()


def on(event: str, callback: Callable[[Dict[str, Any]], None]) -> None:
    """Register an internal listener for an event."""
    with _listener_lock:
        _listeners.setdefault(event, []).append(callback)


def off(event: str, callback: Optional[Callable] = None) -> None:
    """Remove listener(s). If callback is None, remove all for event."""
    with _listener_lock:
        if callback is None:
            _listeners.pop(event, None)
        elif event in _listeners:
            _listeners[event] = [cb for cb in _listeners[event] if cb is not callback]


def emit(event: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Emit an event  --  runs all hooks in a background thread to avoid blocking."""
    payload = {"event": event, **(data or {})}
    thread = threading.Thread(target=_dispatch, args=(event, payload), daemon=True)
    thread.start()


def _dispatch(event: str, payload: Dict[str, Any]) -> None:
    """Internal: run all hooks for an event."""
    # 1. Internal Python callbacks
    with _listener_lock:
        callbacks = list(_listeners.get(event, []))
        # Also fire wildcard listeners
        callbacks += list(_listeners.get("*", []))
    for cb in callbacks:
        try:
            cb(payload)
        except Exception as exc:
            logger.warn(f"LuaTools: Event hook error ({event}): {exc}")

    # 2. External hooks from config
    hooks = _load_hooks_config()
    for hook in hooks.get(event, []):
        hook_type = hook.get("type", "")
        try:
            if hook_type == "webhook":
                _fire_webhook(hook["url"], payload, hook.get("headers"))
            elif hook_type == "exec":
                _fire_exec(hook["command"], payload, shell=bool(hook.get("shell", False)))
        except Exception as exc:
            logger.warn(f"LuaTools: Hook {hook_type} failed for {event}: {exc}")


# ── Webhook handler ───────────────────────────────────────────────────

def _fire_webhook(url: str, payload: Dict[str, Any], extra_headers: Optional[Dict] = None) -> None:
    """POST JSON payload to a webhook URL (uses shared HTTP client)."""
    try:
        from http_client import ensure_http_client
        client = ensure_http_client("LuaTools: Webhook")
    except Exception:
        logger.warn("LuaTools: Webhook  --  HTTP client unavailable")
        return

    headers = {"Content-Type": "application/json", "User-Agent": "LuaTools-Hooks/1.0"}
    if extra_headers:
        headers.update(extra_headers)

    try:
        # Discord webhook format  --  embed with colour coding
        if "discord.com/api/webhooks" in url:
            body = {
                "content": None,
                "embeds": [{
                    "title": f"LuaTools: {payload.get('event', 'unknown')}",
                    "description": _format_payload(payload),
                    "color": 0x66c0f4 if "fail" not in payload.get("event", "") else 0xf44336,
                }],
            }
            client.post(url, json=body, headers=headers, timeout=10)

        # ntfy.sh format  --  plain text with priority header
        elif "ntfy.sh" in url or "/ntfy." in url:
            headers["Title"] = f"LuaTools: {payload.get('event', 'unknown')}"
            headers["Priority"] = "high" if "fail" in payload.get("event", "") else "default"
            headers.pop("Content-Type", None)  # ntfy wants text/plain
            client.post(url, content=_format_payload(payload).encode(), headers=headers, timeout=10)

        # Generic JSON webhook
        else:
            client.post(url, json=payload, headers=headers, timeout=10)

    except Exception as exc:
        logger.warn(f"LuaTools: Webhook POST to {url!r} failed: {exc}")


def _format_payload(payload: Dict[str, Any]) -> str:
    """Human-readable payload summary."""
    parts = []
    if "appid" in payload:
        parts.append(f"AppID: {payload['appid']}")
    if "name" in payload:
        parts.append(f"Game: {payload['name']}")
    if "source" in payload:
        parts.append(f"Source: {payload['source']}")
    if "error" in payload:
        parts.append(f"Error: {payload['error']}")
    if "success" in payload:
        parts.append(f"Success: {payload['success']}/{payload.get('total', '?')}")
    if "failed" in payload:
        parts.append(f"Failed: {payload['failed']}")
    if "duration_s" in payload:
        parts.append(f"Duration: {payload['duration_s']:.1f}s")
    return " | ".join(parts) if parts else json.dumps(payload, indent=2)


# ── Exec handler ──────────────────────────────────────────────────────

def _fire_exec(command_template: str, payload: Dict[str, Any], shell: bool = False) -> None:
    """Run an exec hook with placeholder substitution.

    shell=False is the safe default: payload values cannot inject shell metacharacters.
    Set {"shell": true} explicitly in hooks.json only when shell features are required.
    """
    cmd = str(command_template or "")
    for key, val in payload.items():
        cmd = cmd.replace(f"{{{key}}}", str(val))
    if not cmd.strip():
        return

    try:
        if shell:
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            args = shlex.split(cmd, posix=(os.name != "nt"))
            if not args:
                return
            subprocess.Popen(args, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.warn(f"LuaTools: Exec hook failed: {exc}")


# ── Config loading ────────────────────────────────────────────────────

_hooks_cache: Optional[Dict] = None
_hooks_mtime: float = 0


def _hooks_config_path() -> str:
    from paths import data_path
    return data_path("hooks.json")


def _load_hooks_config() -> Dict[str, List[Dict]]:
    """Load hooks.json  --  cached, reloaded on mtime change."""
    global _hooks_cache, _hooks_mtime
    path = _hooks_config_path()
    if not os.path.exists(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
        if _hooks_cache is not None and mtime == _hooks_mtime:
            return _hooks_cache
        with open(path, "r", encoding="utf-8") as f:
            _hooks_cache = json.load(f)
            _hooks_mtime = mtime
            return _hooks_cache
    except Exception:
        return {}


def save_hooks_config(config: Dict[str, List[Dict]]) -> None:
    """Save hooks configuration."""
    path = _hooks_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    global _hooks_cache, _hooks_mtime
    _hooks_cache = config
    _hooks_mtime = os.path.getmtime(path)


def get_hooks_config() -> str:
    """Return hooks config as JSON string (for IPC)."""
    return json.dumps({"success": True, "hooks": _load_hooks_config()})
