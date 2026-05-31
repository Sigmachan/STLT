# LuaTools Sentinel v9.0 — Architecture & Design

**Version:** 9.0 (Major Release)  
**Release Date:** May 2026  
**Status:** Phase 1 (Core Implementation)

---

## Executive Summary

**LuaTools Sentinel** transforms LuaTools from a **manual plugin** into a **proactive background service**. Instead of requiring user interaction ("click to check, click to activate"), Sentinel automatically:

- 🔍 **Detects new game installations** (real-time filesystem watcher)
- 🎮 **Suggests activation** when the game is available in the source chain
- 📢 **Notifies non-intrusively** (Windows toast notifications with cooldown/snooze)
- 🛡️ **Health-checks before fixes** (validates Steam integrity before applying patches)
- 🎯 **Respects user preferences** (per-game ignore list, opt-in auto-apply)

### Why This Is v9.0

| Feature | v8.x (Manual) | v9.0 (Sentinel) |
|---------|---------------|-----------------|
| Discovery | "Click scan, wait" | Continuous monitoring |
| Activation Flow | User initiates | System suggests → user approves |
| Manifest Updates | Manual refresh | Auto-polling with staleness detection |
| Fixes | "Click apply" | "Apply automatically?" (user opt-in) |
| Resource Model | Idle when plugin closed | Lightweight background thread |
| User Experience | Tool that requires action | Service that works for you |

This is a **paradigm shift**, not a patch.

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│  LuaTools Sentinel (backend/sentinel.py)                       │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─ FilesystemWatcher ────────────────────────────────────┐   │
│  │ • Scans Steam/steamapps for .acf files                │   │
│  │ • Detects new AppIDs vs. previous state               │   │
│  │ • Throttled every 45-60 seconds (no CPU spike)        │   │
│  └────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  ┌─ ActivationIntelligence ───────────────────────────────┐   │
│  │ • Queries source chain (Ryuu → DepotBox → Morrenus)   │   │
│  │ • Returns: [available: bool, sources, confidence]      │   │
│  │ • Reuses existing downloads.py infrastructure          │   │
│  └────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  ┌─ NotificationManager ──────────────────────────────────┐   │
│  │ • Windows toast API (native, non-intrusive)            │   │
│  │ • Cooldown tracking (1 hour per game by default)       │   │
│  │ • User can snooze, ignore, or act immediately          │   │
│  └────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  ┌─ AutoFixEngine ────────────────────────────────────────┐   │
│  │ • Checks available fixes for game (v9.1)              │   │
│  │ • Health check before apply (v9.1)                    │   │
│  │ • Optional: auto-apply with user approval (v9.1)      │   │
│  └────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  ┌─ SentinelDaemon (main loop) ───────────────────────────┐   │
│  │ • Runs as background thread (started with plugin)      │   │
│  │ • Orchestrates components                             │   │
│  │ • Persists config & state to disk                     │   │
│  │ • Thread-safe, handles exceptions gracefully          │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘

IPC Layer (Millennium):
  • Exposed as `StartSentinel()`, `StopSentinel()`, etc. in main.py
  • Called from Steam UI (luatools.js frontend)
  • Returns JSON responses
```

---

## Phase 1: Core Implementation (v9.0)

### Components & Responsibilities

#### 1. **FilesystemWatcher**

```python
class FilesystemWatcher:
	def __init__(self, steam_path: str)
	def scan_installed_games() -> Set[int]
	def detect_new_games(previous_state: Set[int]) -> Set[int]
```

- Scans `Steam/steamapps/appmanifest_*.acf` files
- Extracts AppID from filename (e.g., `appmanifest_730.acf` → `730`)
- Returns set of installed AppIDs
- Gracefully handles missing directory, permission errors

**Design Note:** ACF format parsing not needed (just filename → AppID extraction).

#### 2. **ActivationIntelligence**

```python
class ActivationIntelligence:
	def check_availability(appid: int) -> Dict[str, Any]
	# Returns:
	# {
	#   "available": True/False,
	#   "sources": ["ryuu", "depotbox", "morrenus"],
	#   "confidence": 0.95,
	#   "recommended_source": "ryuu"
	# }
```

- Queries existing `downloads.py` sources (`_try_ryuu`, `_try_depotbox`, etc.)
- Confidence scoring: Ryuu=0.95, DepotBox=0.85, Morrenus=0.75, etc.
- **v9.0 Limitation:** Simplified query (doesn't download full manifests, just existence check)
- **v9.1 Plan:** Full manifest staleness check + hash validation

#### 3. **NotificationManager**

```python
class NotificationManager:
	def enqueue(notif: SentinelNotification) -> None
	def send_toast(title: str, body: str, timeout_sec: int) -> None
	def can_notify_game(appid: int, state: SentinelState) -> bool
	def mark_notified(appid: int, state: SentinelState) -> None
```

- Sends **Windows 10+ toast notifications** (native, non-intrusive)
- Tracks notification history (cooldown: 1 hour per game)
- Falls back to console logging if toast library unavailable
- User can ignore games (added to `per_game_ignore` set)

**Dependencies:**
```bash
pip install win10toast  # Added to requirements.txt
```

#### 4. **AutoFixEngine**

```python
class AutoFixEngine:
	def check_available_fixes(appid: int) -> List[Dict[str, Any]]
	def can_auto_apply(appid: int, config: SentinelConfig) -> bool
	def apply_fix_safely(appid: int, fix_name: str) -> Dict[str, Any]
```

- **v9.0:** Lists available fixes (no auto-apply yet)
- **v9.1:** Health check + safe auto-apply
- Reuses existing `fixes.py` infrastructure
- Granular control: global opt-in or per-game override

#### 5. **SentinelDaemon** (Main Orchestrator)

```python
class SentinelDaemon:
	def __init__(steam_path: Optional[str] = None)
	def start() -> None  # Spawns background thread
	def stop() -> None   # Graceful shutdown
	def _run_loop() -> None  # Main thread loop (45-60s poll)
```

- **Thread Model:** Daemon thread (exits with Millennium)
- **State Persistence:** `sentinel_config.json` + `sentinel_state.json` in `Steam/config/`
- **Error Handling:** Logs exceptions, continues polling
- **Thread Safety:** Lock-protected config/state mutations

---

## Configuration & Persistence

### SentinelConfig (JSON)

```json
{
  "enabled": true,
  "poll_interval": 45,
  "auto_activation_enabled": false,
  "auto_fix_enabled": false,
  "notification_style": "toast",
  "per_game_ignore": [240, 570],
  "per_game_auto_apply": []
}
```

### SentinelState (JSON)

```json
{
  "last_poll": 1715900000,
  "seen_appids": [730, 570, 240, 1086940],
  "notification_history": {
	"2358720": 1715890000,
	"1086940": 1715886000
  }
}
```

- **Saved to:** `Steam/config/sentinel_config.json` and `Steam/config/sentinel_state.json`
- **Atomicity:** Writes via temp file + `os.replace()` (from `steam_version.py` pattern)
- **Concurrency:** Thread lock around mutation

---

## Public API (Millennium IPC)

All endpoints return **JSON** and are callable from `luatools.js`:

### 1. `StartSentinel()`
```python
→ {"success": True, "message": "Sentinel daemon started"}
```

### 2. `StopSentinel()`
```python
→ {"success": True, "message": "Sentinel daemon stopped"}
```

### 3. `GetSentinelStatus()`
```python
→ {
  "success": True,
  "running": True,
  "enabled": True,
  "poll_interval": 45,
  "auto_activation": False,
  "auto_fix": False,
  "seen_games_count": 47
}
```

### 4. `SetSentinelConfig(config_json)`
```python
SetSentinelConfig(JSON.stringify({
  enabled: true,
  poll_interval: 60,
  auto_activation_enabled: false
}))

→ {
  "success": True,
  "config": { ...updated config... }
}
```

### 5. `IgnoreGameNotifications(appid)`
```python
IgnoreGameNotifications(2358720)
→ {"success": True, "ignored_game": 2358720}
```

### 6. `UnignoreGameNotifications(appid)`
```python
UnignoreGameNotifications(2358720)
→ {"success": True, "unignored_game": 2358720}
```

---

## Usage Flow

### For End User (Kira)

1. **Sentinel auto-starts** when Millennium loads the plugin
2. **New game installed** → Sentinel detects it (~45s scan cycle)
3. **Toast notification appears:**
   ```
   [LuaTools] Black Myth: Wukong
   Found in Ryuu (3 sources available)
   [Activate] [Ignore] [Dismiss]
   ```
4. **User clicks [Activate]** → Existing `StartAddViaLuaTools(appid)` flow
5. **If she ignores:**
   ```
   Sentinel skips that game for 1 hour (cooldown)
   Can be re-enabled in UI
   ```

### For Developer (Adding Features)

1. **UI Integration** (v9.0):
   - Sentinel settings panel in Steam UI
   - Toggle daemon on/off
   - Per-game ignore list
   - Notification style selector (toast/silent)

2. **v9.1 Auto-Apply:**
   - Add "enable auto-fix" toggle
   - Show fix history in UI
   - Implement rollback button

3. **v9.2+ Multi-Machine:**
   - Cloud sync of profiles + config
   - Credentials from key_vault.py

---

## Technical Decisions

### 1. Why Thread, Not Separate Process?

- **Simpler:** Shares same Python interpreter, logger, HTTP client
- **Cleaner shutdown:** Thread dies with Millennium
- **State sharing:** Easy access to sentinel globals from UI code

### 2. Why 45-60s Poll Interval?

- **Not too frequent:** Avoids CPU/disk thrashing
- **Practical:** User notices new game within ~1 minute
- **Configurable:** Advanced users can adjust in config

### 3. Why Notification Cooldown (1 hour)?

- **Not spammy:** Game reinstalled? You won't be nagged 47 times
- **Per-game:** Different games can notify independently
- **Overridable:** User can manually adjust in config

### 4. Why Reuse downloads.py Sources?

- **No code duplication:** Existing source chain logic already works
- **Consistency:** Same availability checking as manual mode
- **Future-proof:** New sources added to downloads.py auto-appear in Sentinel

### 5. Why NO Auto-Apply in v9.0?

- **Safety first:** Applying fixes touches system files — too risky to automate immediately
- **User feedback:** Gather Kira's feedback on toast notifications first
- **Phased:** v9.1 adds health checks, v9.1+ adds safe auto-apply

---

## Known Limitations (v9.0)

| Limitation | Reason | v9.1+ Plan |
|-----------|--------|-----------|
| Availability check is "quick" (no full manifest download) | Avoid network overhead | Add staleness check if manifest older than 24h |
| No fix auto-apply | Too risky without telemetry | Add health check, rollback, user approval |
| No multi-machine sync | Out of scope for core | Cloud sync (v9.2+) |
| Game names are "AppID only" | No Steam API in plugin | Lookup from `gameinfo.vdf` or local cache |
| Windows-only (toast) | Platform limitation | Fall back to tray icon on other OS (future) |

---

## Error Handling

- **Filesystem errors (permission denied):** Log warning, continue next cycle
- **Network errors (sources down):** Return "not available", don't fail
- **Config/state corruption:** Use defaults, log error
- **Thread crash:** Caught at top level, daemon restarts polling

Example:
```python
def _poll_cycle(self) -> None:
	try:
		new_games = self.watcher.detect_new_games(...)
		# ... process games ...
		self._save_state()
	except Exception as exc:
		_logger.error(f"Sentinel: poll_cycle failed: {exc}")
		# Continue to next cycle (don't crash thread)
```

---

## Testing Checklist (Before Release)

- [ ] Sentinel starts automatically with Millennium
- [ ] Daemon stops cleanly on plugin unload
- [ ] Filesystem watcher detects new .acf files
- [ ] Toast notifications appear (Windows 10+)
- [ ] Cooldown prevents spam (test with 1 minute TTL)
- [ ] Config persists across restarts
- [ ] Ignore list actually prevents notifications
- [ ] Thread doesn't consume CPU when idle (check Task Manager)
- [ ] Logs show expected messages ("Sentinel: poll_cycle ...")
- [ ] Permission errors don't crash daemon

---

## Future Roadmap

### Phase 1 (v9.0) ✓
- [x] Filesystem watcher
- [x] Activation intelligence
- [x] Toast notifications
- [x] Configuration & persistence
- [x] Public IPC API

### Phase 2 (v9.1)
- [ ] Manifest staleness detection (HuggingFace polling)
- [ ] Fix health check (pre-flight validation)
- [ ] Safe auto-apply (with rollback)
- [ ] Fix history + audit log

### Phase 3 (v9.2+)
- [ ] Multi-machine sync (cloud or git-based)
- [ ] Batch fix application
- [ ] Achievement schema auto-update
- [ ] Performance optimizations (hash-based change detection)

---

## References

- `backend/sentinel.py` — Full implementation
- `backend/main.py` — Endpoints & integration
- `backend/downloads.py` — Source chain (reused)
- `backend/fixes.py` — Fix infrastructure (reused)
- `requirements.txt` — Dependencies

---

**Architecture Document v1.0**  
Last Updated: May 2026  
Maintainer: Kira (Sigmachan)
