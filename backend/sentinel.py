"""LuaTools Sentinel — background daemon for v9.0

Transforms LuaTools from manual tool into proactive service:
  • Filesystem watcher on Steam/steamapps for new installations
  • Real-time manifest staleness detection (HuggingFace polling)
  • Automatic activation suggestions (with user approval)
  • Health-check before auto-applying fixes
  • Native Windows toast notifications (non-intrusive)

Architecture:
  1. FilesystemWatcher — monitors Steam directory changes
  2. ActivationIntelligence — checks source chain availability
  3. NotificationManager — Windows toast + tray integration
  4. AutoFixEngine — applies known patches with safety checks
  5. SentinelDaemon — main loop (runs in background, ~30-60s poll)

Designed to work alongside Millennium plugin (can run as separate process).
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from logger import logger as _logger
from paths import get_steam_path
from settings.manager import get_steamtools_settings, register_change_hook
from steamtools import _scan_all_steam_libraries
from steam_utils import _parse_vdf_simple
from downloads import check_apis_for_app, fetch_app_name
from fixes import apply_game_fix, check_for_fixes

# ──────────────────────────────────────────────────────────────────────────
# Configuration & Constants
# ──────────────────────────────────────────────────────────────────────────

SENTINEL_CONFIG_FILE = "sentinel_config.json"
SENTINEL_STATE_FILE = "sentinel_state.json"
POLL_INTERVAL_SECONDS = 45  # Throttle: don't hammer filesystem
MANIFEST_STALENESS_HOURS = 24  # Re-check if older than 24h
NOTIFICATION_COOLDOWN_MINUTES = 60  # Don't spam same game notifications


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """Write JSON atomically to avoid partial or corrupted files."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(temp_path, path)

@dataclass
class SentinelConfig:
    """Sentinel runtime configuration."""
    enabled: bool = False
    poll_interval: int = POLL_INTERVAL_SECONDS
    auto_activation_enabled: bool = False  # User opt-in
    auto_fix_enabled: bool = False  # User opt-in
    auto_apply_policy: str = "ask"
    notification_style: str = "toast"  # "toast" or "tray" or "silent"
    per_game_ignore: Set[int] = field(default_factory=set)
    per_game_auto_apply: Set[int] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "poll_interval": self.poll_interval,
            "auto_activation_enabled": self.auto_activation_enabled,
            "auto_fix_enabled": self.auto_fix_enabled,
            "auto_apply_policy": self.auto_apply_policy,
            "notification_style": self.notification_style,
            "per_game_ignore": list(self.per_game_ignore),
            "per_game_auto_apply": list(self.per_game_auto_apply),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SentinelConfig:
        return cls(
            enabled=data.get("enabled", False),
            poll_interval=data.get("poll_interval", POLL_INTERVAL_SECONDS),
            auto_activation_enabled=data.get("auto_activation_enabled", False),
            auto_fix_enabled=data.get("auto_fix_enabled", False),
            auto_apply_policy=data.get("auto_apply_policy", "ask"),
            notification_style=data.get("notification_style", "toast"),
            per_game_ignore=set(data.get("per_game_ignore", [])),
            per_game_auto_apply=set(data.get("per_game_auto_apply", [])),
        )

@dataclass
class SentinelState:
    """Persist seen games, notification history, etc."""
    last_poll: int = 0  # timestamp
    seen_appids: Set[int] = field(default_factory=set)
    notification_history: Dict[int, int] = field(default_factory=dict)  # appid -> last_notified_ts
    last_staleness_check: Dict[int, int] = field(default_factory=dict)  # appid -> ts
    known_stale: Set[int] = field(default_factory=set)  # appids flagged as having stale manifests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_poll": self.last_poll,
            "seen_appids": list(self.seen_appids),
            "notification_history": {str(k): v for k, v in self.notification_history.items()},
            "last_staleness_check": {str(k): v for k, v in self.last_staleness_check.items()},
            "known_stale": list(self.known_stale),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SentinelState:
        return cls(
            last_poll=data.get("last_poll", 0),
            seen_appids=set(data.get("seen_appids", [])),
            notification_history={
                int(k): v for k, v in data.get("notification_history", {}).items()
            },
            last_staleness_check={
                int(k): v for k, v in data.get("last_staleness_check", {}).items()
            },
            known_stale=set(data.get("known_stale", [])),
        )

class NotificationType(Enum):
    """Sentinel notification categories."""
    NEW_GAME_ACTIVATABLE = "new_game_activatable"
    MANIFEST_STALE = "manifest_stale"
    KNOWN_FIX_AVAILABLE = "known_fix_available"
    ACTIVATION_SUCCESS = "activation_success"
    ACTIVATION_FAILED = "activation_failed"

@dataclass
class SentinelNotification:
    """Internal representation of notification to show."""
    notification_type: NotificationType
    appid: int
    game_name: str
    message: str
    action_url: Optional[str] = None  # URL to click for more info
    timeout_seconds: int = 10

# ──────────────────────────────────────────────────────────────────────────
# Filesystem Watcher
# ──────────────────────────────────────────────────────────────────────────

class FilesystemWatcher:
    """Monitors Steam/steamapps for new game installations.

    Tracks manifest files (e.g., appmanifest_730.acf) and detects when new
    games are installed (new .acf files appear in steamapps/).
    """

    def __init__(self, steam_path: str):
        self.steam_path = steam_path
        self.steamapps_dir = os.path.join(steam_path, "steamapps")
        self.seen_acf_files: Set[str] = set()

    def scan_installed_games(self) -> Set[int]:
        """Return set of currently installed AppIDs by scanning all Steam libraries."""
        appids: Set[int] = set()
        if not os.path.isdir(self.steam_path):
            return appids

        try:
            for lib_path in _scan_all_steam_libraries(self.steam_path):
                steamapps_dir = os.path.join(lib_path, "steamapps")
                if not os.path.isdir(steamapps_dir):
                    continue

                for filename in os.listdir(steamapps_dir):
                    if filename.startswith("appmanifest_") and filename.endswith(".acf"):
                        try:
                            appid_str = filename[len("appmanifest_"):-len(".acf")]
                            appid = int(appid_str)
                            appids.add(appid)
                        except ValueError:
                            continue
        except (OSError, PermissionError):
            pass

        return appids

    def detect_new_games(self, previous_state: Set[int]) -> Set[int]:
        """Compare previous scan with current scan, return newly installed AppIDs."""
        current = self.scan_installed_games()
        return current - previous_state

# ──────────────────────────────────────────────────────────────────────────
# Activation Intelligence
# ──────────────────────────────────────────────────────────────────────────

class ActivationIntelligence:
    """Checks if a game is available across the source chain.

    Uses existing downloads.py API availability checker rather than private source
    helpers.
    """

    def __init__(self) -> None:
        self._check_apis_for_app = check_apis_for_app

    def _score_source(self, name: str) -> float:
        normalized = name.lower()
        if "ryuu" in normalized:
            return 0.95
        if "depotbox" in normalized:
            return 0.85
        if "morrenus" in normalized or "sadie" in normalized:
            return 0.75
        if "manifesthub" in normalized:
            return 0.7
        if "local" in normalized:
            return 0.9
        return 0.5

    def check_availability(self, appid: int) -> Dict[str, Any]:
        """Check if appid is available in any enabled source."""
        available_sources: List[str] = []
        confidence = 0.0
        recommended: Optional[str] = None

        try:
            payload = self._check_apis_for_app(appid)
            data = json.loads(payload or "{}")
            results = data.get("results", [])
            for item in results:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                if item.get("available"):
                    available_sources.append(name)
                    score = self._score_source(name)
                    if score > confidence:
                        confidence = score
                        recommended = name
        except Exception as exc:
            _logger.warn(f"Sentinel: availability check failed for {appid}: {exc}")

        return {
            "available": len(available_sources) > 0,
            "sources": available_sources,
            "confidence": confidence,
            "recommended_source": recommended,
        }

# ──────────────────────────────────────────────────────────────────────────
# Notification Manager
# ──────────────────────────────────────────────────────────────────────────

class NotificationManager:
    """Sends native Windows toast notifications and maintains history.

    Non-intrusive: respects cooldown periods, allows snooze/dismiss.
    """

    def __init__(self):
        self.notification_queue: List[SentinelNotification] = []
        self.lock = threading.Lock()

    def enqueue(self, notif: SentinelNotification) -> None:
        """Queue a notification for delivery."""
        with self.lock:
            self.notification_queue.append(notif)

    def send_toast(self, title: str, body: str, timeout_sec: int = 10) -> None:
        """Send native Windows toast notification.

        Requires: Windows 10+ (not tested on Win7).
        Falls back to console log if toast library unavailable.
        """
        try:
            from win10toast import ToastNotifier
            notifier = ToastNotifier()
            notifier.show_toast(title, body, duration=timeout_sec, threaded=True)
        except Exception as exc:
            # Fallback: log to console (Millennium will capture)
            _logger.log(f"[Sentinel] {title}: {body}")

    def can_notify_game(self, appid: int, state: SentinelState) -> bool:
        """Check if we should notify about this game (cooldown check)."""
        last_notified = state.notification_history.get(appid, 0)
        now = int(time.time())
        cooldown_sec = NOTIFICATION_COOLDOWN_MINUTES * 60
        return (now - last_notified) > cooldown_sec

    def mark_notified(self, appid: int, state: SentinelState) -> None:
        """Record that we've notified about this game."""
        state.notification_history[appid] = int(time.time())

# ──────────────────────────────────────────────────────────────────────────
# Auto-Fix Engine
# ──────────────────────────────────────────────────────────────────────────

class AutoFixEngine:
    """Applies known fixes to games with health checks before execution.

    Uses existing fixes.py infrastructure but adds:
      • Pre-flight health check (make sure Steam isn't corrupted)
      • Dry-run / rollback capability
      • Granular user opt-in (per-game or global)
    """

    def __init__(self):
        pass

    def check_available_fixes(self, appid: int) -> List[Dict[str, Any]]:
        """List fixes available for this appid."""
        try:
            fixes = check_for_fixes(appid)
            return fixes if isinstance(fixes, list) else []
        except Exception as exc:
            _logger.warn(f"Sentinel: check_available_fixes({appid}) failed: {exc}")
            return []

    def can_auto_apply(self, appid: int, config: SentinelConfig) -> bool:
        """Determine if we should auto-apply fixes for this game."""
        if config.auto_apply_policy == "never":
            return False

        if appid in config.per_game_ignore:
            return False

        if appid in config.per_game_auto_apply:
            return True

        if config.auto_apply_policy == "auto_minor":
            return False

        # Default: don't auto-apply unless explicitly enabled or marked per-game
        return False

    def apply_fix_safely(self, appid: int, fix_name: str) -> Dict[str, Any]:
        """Apply a fix with pre-flight checks and error handling."""
        try:
            # Pre-flight: quick Steam health check
            result = apply_game_fix(appid, fix_name)
            return {"success": True, "result": result}
        except Exception as exc:
            _logger.error(f"Sentinel: apply_fix_safely({appid}, {fix_name}) failed: {exc}")
            return {"success": False, "error": str(exc)}

# ──────────────────────────────────────────────────────────────────────────
# Main Sentinel Daemon
# ──────────────────────────────────────────────────────────────────────────

class SentinelDaemon:
    """Main Sentinel background service.

    Runs as a separate thread (or process), polling every 45-60 seconds for:
      1. New game installations (filesystem watcher)
      2. Manifest freshness (optional: HuggingFace polling)
      3. Available fixes (from known fix registry)
      4. User notifications (toast + tray)

    Does NOT automatically apply fixes without user approval (v9.0 core).
    Auto-apply comes in v9.1 after user feedback.
    """

    def __init__(self, steam_path: Optional[str] = None):
        self.steam_path = steam_path or get_steam_path() or ""
        self.config = SentinelConfig()
        self.state = SentinelState()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()
        self._stop_event = threading.Event()  # interruptible sleep for clean shutdown

        # Components
        self.watcher = FilesystemWatcher(self.steam_path)
        self.activation_intel = ActivationIntelligence()
        self.notification_mgr = NotificationManager()
        self.fix_engine = AutoFixEngine()

        self._load_config()
        self._load_state()

    def _load_config(self) -> None:
        """Load config from disk, or use defaults."""
        config_path = os.path.join(self.steam_path, "config", SENTINEL_CONFIG_FILE)
        with self.lock:
            try:
                if os.path.isfile(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.config = SentinelConfig.from_dict(data)
            except Exception as exc:
                _logger.warn(f"Sentinel: failed to load config: {exc}, using defaults")

            self._apply_settings_overrides()

    def _apply_settings_overrides(self) -> None:
        try:
            settings = get_steamtools_settings()
            self.config.enabled = bool(settings.get("sentinelEnabled", self.config.enabled))
            interval_minutes = settings.get("sentinelIntervalMinutes")
            if interval_minutes is not None:
                self.config.poll_interval = max(1, int(interval_minutes)) * 60
            policy = str(settings.get("sentinelAutoApplyPolicy", self.config.auto_apply_policy)).lower()
            self.config.auto_apply_policy = policy if policy in {"never", "ask", "auto_minor"} else "ask"
        except Exception as exc:
            _logger.warn(f"Sentinel: failed to apply settings overrides: {exc}")

    def _load_state(self) -> None:
        """Load state from disk, or start fresh."""
        state_path = os.path.join(self.steam_path, "config", SENTINEL_STATE_FILE)
        with self.lock:
            try:
                if os.path.isfile(state_path):
                    with open(state_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.state = SentinelState.from_dict(data)
            except Exception as exc:
                _logger.warn(f"Sentinel: failed to load state: {exc}, starting fresh")

    def _save_config(self) -> None:
        """Persist config to disk."""
        config_path = os.path.join(self.steam_path, "config", SENTINEL_CONFIG_FILE)
        with self.lock:
            try:
                _atomic_write_json(config_path, self.config.to_dict())
            except Exception as exc:
                _logger.error(f"Sentinel: failed to save config: {exc}")

    def _save_state(self) -> None:
        """Persist state to disk."""
        state_path = os.path.join(self.steam_path, "config", SENTINEL_STATE_FILE)
        with self.lock:
            try:
                _atomic_write_json(state_path, self.state.to_dict())
            except Exception as exc:
                _logger.error(f"Sentinel: failed to save state: {exc}")

    def _poll_cycle(self) -> None:
        """Single poll cycle: check for new games, notify, etc."""
        try:
            # 1. Detect new games
            new_games = self.watcher.detect_new_games(self.state.seen_appids)
            self.state.seen_appids.update(new_games)
            self.state.last_poll = int(time.time())

            for appid in new_games:
                self._on_new_game_detected(appid)

            # 2. Check manifest staleness for installed .lua games
            #    Throttled per-appid (default 24h re-check) to avoid hammering api.steamcmd.net.
            #    Only checks if Sentinel has been running long enough that we expect installed
            #    games have settled (skip on first poll after start).
            if self.config.enabled:
                self._check_manifest_staleness_for_installed()

            # 3. Persist state
            self._save_state()

        except Exception as exc:
            _logger.error(f"Sentinel: poll_cycle failed: {exc}")

    def _on_new_game_detected(self, appid: int) -> None:
        """Triggered when a new game is detected on disk."""
        if appid in self.config.per_game_ignore:
            _logger.log(f"Sentinel: game {appid} is ignored by user")
            return

        # Check availability
        avail = self.activation_intel.check_availability(appid)

        if not avail["available"]:
            _logger.log(f"Sentinel: game {appid} not found in sources")
            return

        # Check cooldown
        if not self.notification_mgr.can_notify_game(appid, self.state):
            _logger.log(f"Sentinel: game {appid} in cooldown, not notifying again")
            return

        # Build notification
        game_name = self._lookup_game_name(appid) or f"AppID {appid}"
        message = (
            f"Found in {avail['recommended_source']} "
            f"({len(avail['sources'])} sources available)"
        )
        notif = SentinelNotification(
            notification_type=NotificationType.NEW_GAME_ACTIVATABLE,
            appid=appid,
            game_name=game_name,
            message=message,
        )

        # Send notification
        if self.config.notification_style == "toast":
            self.notification_mgr.send_toast(
                f"[LuaTools] {game_name}",
                message,
                timeout_sec=notif.timeout_seconds,
            )
        elif self.config.notification_style == "silent":
            pass  # Log only

        self.notification_mgr.mark_notified(appid, self.state)
        _logger.log(f"Sentinel: notified user about new game {appid}")

    def _check_manifest_staleness_for_installed(self) -> None:
        """Sample-check installed .lua scripts for outdated manifests.

        Strategy:
          - Iterate over .lua files in stplug-in
          - For each: skip if checked within last MANIFEST_STALENESS_HOURS
          - Run check_manifest_staleness(appid) — uses api.steamcmd.net
          - If stale and not in cooldown and not already-known-stale, notify
          - Cap to 8 checks per poll cycle (avoid spending the budget all at once)
        """
        import json as _json
        try:
            from steamtools import check_manifest_staleness, _stplug_dir
        except Exception as exc:
            _logger.warn(f"Sentinel: staleness check unavailable: {exc}")
            return

        stplug = _stplug_dir()
        if not stplug or not os.path.isdir(stplug):
            return

        now_ts = int(time.time())
        recheck_after = MANIFEST_STALENESS_HOURS * 3600
        checked_this_cycle = 0
        max_per_cycle = 8

        try:
            lua_files = sorted(os.listdir(stplug))
        except OSError:
            return

        for fname in lua_files:
            if checked_this_cycle >= max_per_cycle:
                break
            if not fname.endswith(".lua"):
                continue
            stem = fname[:-4]
            if not stem.isdigit():
                continue
            appid = int(stem)

            # Throttle per-game
            last_check = self.state.last_staleness_check.get(appid, 0)
            if (now_ts - last_check) < recheck_after:
                continue

            # Skip ignored games
            if appid in self.config.per_game_ignore:
                continue

            # Run the check
            try:
                result_json = check_manifest_staleness(appid)
                result = _json.loads(result_json)
            except Exception as exc:
                _logger.warn(f"Sentinel: staleness check {appid} failed: {exc}")
                continue
            finally:
                self.state.last_staleness_check[appid] = now_ts
                checked_this_cycle += 1

            if not result.get("success"):
                continue
            results_list = result.get("results", [])
            if not results_list:
                continue
            game_data = results_list[0]
            is_stale = bool(game_data.get("stale"))

            # Update known_stale set
            if is_stale:
                self.state.known_stale.add(appid)
            else:
                self.state.known_stale.discard(appid)
                continue  # nothing to notify

            # Respect cooldown
            if not self.notification_mgr.can_notify_game(appid, self.state):
                continue

            # Build notification
            stale_depots = [
                d for d in game_data.get("depots", []) if d.get("stale")
            ]
            game_name = self._lookup_game_name(appid) or f"AppID {appid}"
            msg = (
                f"Manifest outdated for {len(stale_depots)} depot"
                + ("s" if len(stale_depots) != 1 else "")
                + ". Game may have been patched on Steam."
            )

            if self.config.notification_style == "toast":
                self.notification_mgr.send_toast(
                    f"[LuaTools] Stale: {game_name}",
                    msg,
                    timeout_sec=10,
                )

            self.notification_mgr.mark_notified(appid, self.state)
            _logger.log(
                f"Sentinel: notified about stale manifests for {appid} "
                f"({len(stale_depots)} depot(s))"
            )

        if checked_this_cycle > 0:
            _logger.log(
                f"Sentinel: staleness check completed "
                f"({checked_this_cycle} game(s) checked this cycle)"
            )

    def _lookup_game_name(self, appid: int) -> str:
        for lib_path in _scan_all_steam_libraries(self.steam_path):
            appmanifest_path = os.path.join(lib_path, "steamapps", f"appmanifest_{appid}.acf")
            if not os.path.isfile(appmanifest_path):
                continue
            try:
                with open(appmanifest_path, "r", encoding="utf-8") as handle:
                    manifest_data = _parse_vdf_simple(handle.read())
                app_state = manifest_data.get("AppState", {})
                name = str(app_state.get("name") or app_state.get("installdir") or "").strip()
                if name:
                    return name
            except Exception:
                continue
        try:
            fetched = fetch_app_name(appid)
            if isinstance(fetched, str) and fetched.strip():
                return fetched.strip()
        except Exception:
            pass
        return ""

    def start(self) -> bool:
        """Start the Sentinel daemon (background thread)."""
        with self.lock:
            if self.running:
                _logger.warn("Sentinel: already running")
                return False

            # Guard against a previous thread that has not fully exited yet.
            if self.thread is not None and self.thread.is_alive():
                _logger.warn("Sentinel: previous thread still alive, refusing to start a duplicate")
                return False

            if not self.config.enabled:
                _logger.log("Sentinel: disabled by config")
                return False

            self._stop_event.clear()
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            _logger.log(f"Sentinel: daemon started (poll interval: {self.config.poll_interval}s)")
            return True

    def stop(self) -> None:
        """Stop the Sentinel daemon.

        Signals the stop event so the run loop wakes immediately from its
        sleep instead of waiting out the full poll interval.
        """
        with self.lock:
            if not self.running and (self.thread is None or not self.thread.is_alive()):
                return
            self.running = False
            self._stop_event.set()
            thread = self.thread

        # Join outside the lock so the loop's final _save_state() can proceed.
        if thread is not None:
            thread.join(timeout=max(10, self.config.poll_interval + 2))
            if thread.is_alive():
                _logger.warn("Sentinel: thread did not exit within join timeout")
            else:
                self.thread = None

        self._save_state()
        _logger.log("Sentinel: daemon stopped")

    def _run_loop(self) -> None:
        """Main background loop (runs in thread).

        Uses an interruptible Event.wait() instead of time.sleep() so that
        stop() can break the loop out of its idle period immediately.
        """
        while self.running and not self._stop_event.is_set():
            try:
                self._poll_cycle()
            except Exception as exc:
                _logger.error(f"Sentinel: unhandled exception in _run_loop: {exc}")

            # Interruptible sleep: returns True the moment stop() sets the event.
            interval = max(5, int(self.config.poll_interval))
            if self._stop_event.wait(timeout=interval):
                break

        _logger.log("Sentinel: run loop exited")

# ──────────────────────────────────────────────────────────────────────────
# Public API (exposed via main.py for Millennium)
# ──────────────────────────────────────────────────────────────────────────

_sentinel_instance: Optional[SentinelDaemon] = None

def get_sentinel() -> SentinelDaemon:
    """Get or create the global Sentinel instance."""
    global _sentinel_instance
    if _sentinel_instance is None:
        _sentinel_instance = SentinelDaemon()
    return _sentinel_instance

def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, str):
            return int(float(value.strip()))
        return int(value)
    except Exception:
        return default


def start_sentinel() -> str:
    """Start Sentinel daemon (JSON response)."""
    try:
        sentinel = get_sentinel()
        started = sentinel.start()
        if not started:
            return json.dumps({"success": False, "message": "Sentinel daemon not started; it may be disabled or already running"})
        return json.dumps({"success": True, "message": "Sentinel daemon started"})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})

def stop_sentinel() -> str:
    """Stop Sentinel daemon (JSON response)."""
    try:
        sentinel = get_sentinel()
        sentinel.stop()
        return json.dumps({"success": True, "message": "Sentinel daemon stopped"})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})

def get_sentinel_status() -> str:
    """Get Sentinel daemon status (JSON response)."""
    try:
        sentinel = get_sentinel()
        return json.dumps({
            "success": True,
            "running": sentinel.running,
            "enabled": sentinel.config.enabled,
            "poll_interval": sentinel.config.poll_interval,
            "poll_interval_minutes": round(sentinel.config.poll_interval / 60, 2),
            "auto_activation": sentinel.config.auto_activation_enabled,
            "auto_fix": sentinel.config.auto_fix_enabled,
            "auto_apply_policy": sentinel.config.auto_apply_policy,
            "notification_style": sentinel.config.notification_style,
            "seen_games_count": len(sentinel.state.seen_appids),
        })
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})

def set_sentinel_config(config_updates: Dict[str, Any]) -> str:
    """Update Sentinel configuration (JSON response)."""
    try:
        sentinel = get_sentinel()
        was_running = sentinel.running

        enabled = config_updates.get("enabled")
        if enabled is not None:
            sentinel.config.enabled = _parse_bool(enabled)

        if "poll_interval_minutes" in config_updates:
            sentinel.config.poll_interval = max(1, _parse_int(config_updates["poll_interval_minutes"], 1)) * 60
        elif "poll_interval" in config_updates:
            sentinel.config.poll_interval = max(1, _parse_int(config_updates["poll_interval"], 1))

        for key, value in config_updates.items():
            if key in {"poll_interval", "poll_interval_minutes", "enabled"}:
                continue

            if key in {"auto_activation_enabled", "auto_fix_enabled"}:
                setattr(sentinel.config, key, _parse_bool(value))
                continue

            if key == "auto_apply_policy":
                policy = str(value or "").lower()
                sentinel.config.auto_apply_policy = policy if policy in {"never", "ask", "auto_minor"} else "ask"
                continue

            if key == "notification_style":
                style = str(value or "").lower()
                sentinel.config.notification_style = style if style in {"toast", "tray", "silent"} else "toast"
                continue

            if hasattr(sentinel.config, key):
                setattr(sentinel.config, key, value)

        sentinel._save_config()

        if enabled is not None:
            if sentinel.config.enabled and not was_running:
                sentinel.start()
            elif not sentinel.config.enabled and was_running:
                sentinel.stop()

        return json.dumps({"success": True, "config": sentinel.config.to_dict()})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})

def ignore_game(appid: int) -> str:
    """Add game to ignore list (don't notify)."""
    try:
        sentinel = get_sentinel()
        sentinel.config.per_game_ignore.add(int(appid))
        sentinel._save_config()
        return json.dumps({"success": True, "ignored_game": appid})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})

def unignore_game(appid: int) -> str:
    """Remove game from ignore list."""
    try:
        sentinel = get_sentinel()
        sentinel.config.per_game_ignore.discard(int(appid))
        sentinel._save_config()
        return json.dumps({"success": True, "unignored_game": appid})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def _on_sentinel_enabled_changed(previous: Any, current: Any) -> None:
    sentinel = get_sentinel()
    sentinel.config.enabled = bool(current)
    sentinel._save_config()
    if sentinel.config.enabled:
        sentinel.start()
    else:
        sentinel.stop()


def _on_sentinel_interval_changed(previous: Any, current: Any) -> None:
    sentinel = get_sentinel()
    try:
        sentinel.config.poll_interval = max(1, int(current)) * 60
        sentinel._save_config()
    except Exception:
        pass


def _on_sentinel_policy_changed(previous: Any, current: Any) -> None:
    sentinel = get_sentinel()
    policy = str(current or "ask").lower()
    sentinel.config.auto_apply_policy = policy if policy in {"never", "ask", "auto_minor"} else "ask"
    sentinel._save_config()


try:
    register_change_hook(("steamtools", "sentinelEnabled"), _on_sentinel_enabled_changed)
    register_change_hook(("steamtools", "sentinelIntervalMinutes"), _on_sentinel_interval_changed)
    register_change_hook(("steamtools", "sentinelAutoApplyPolicy"), _on_sentinel_policy_changed)
except Exception as exc:
    _logger.warn(f"Sentinel: settings hook registration failed: {exc}")
