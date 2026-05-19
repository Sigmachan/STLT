<div align="right">
  <strong>🌍 Languages:</strong>
  <a href="#english-version">🇬🇧 English</a> |
  <a href="#русская-версия">🇷🇺 Русский</a>
</div>

---

<a id="english-version"></a>
# 🇬🇧 LuaTools Ultimate v8.4

## Windows 11 Native · Zero-Bloat · Trigger-Only Architecture

### What's New in Ultimate Edition (My New Features)

**Global Improvements & Download System:**
* Full download pipeline with multi-API fallback.
* Game fixes system, auto-update, and built-in app database.
* Frontend web UI injection, theme support, and i18n (30+ languages).
* Premium sources: Ryuu (Priority 1) + DepotBox (Priority 2).
* Enhanced settings with convenient text fields for API keys and cookies.
* Built-in system with 11 CSS themes and a `themes.json` palette.

**New Collection Sync and Content Audit Features:**
* `GetSteamToolsIds()` — scans the `stplug-in` folder and returns a comma-separated appid list for collection sync.
* `AuditLuaContent()` — verifies depot, DLC, and Workshop content coverage inside `.lua` files.
* Content audit runs automatically after every successful installation.
* New settings: collection name, replace mode, and a toggle to hide/show disabled scripts.

**Exclusive New SteamTools Features (Windows 11 Native):**
* `GetCacheInfo()` / `CleanSteamCache()` — smart cache cleanup (htmlcache, shader, downloads, appcache, depotcache, logs).
* `CreateBackup()` / `ListBackups()` / `RestoreBackup()` / `DeleteBackup()` — timestamped zip backups of `stplug-in` + `depotcache`.
* `GetSteamFolderStats()` — detailed disk usage breakdown for all Steam directories.
* `ToggleLuaScript()` — enable and disable lua scripts without needing to delete them.
* PowerShell helper script (`steamtools_helper.ps1`) for standalone or advanced use.

**Account Transfer & Cloud Save Migration:**
* `ListUserdataAccounts()` — list all Steam accounts with their disk usage and app count.
* `InspectGameUserdata()` — examine game data folder structure and size for an account.
* `TransferGameUserdata()` — copy Denuvo tokens, cloud saves, and profile data between your own Steam accounts without re-logging in.
* `RestoreGameUserdataBackup()` — restore previous versions of transferred game data.
* Full backup/restore chain with timestamp tracking and partial failure resilience.

**API Key Vault & Profile Management:**
* `ListKeyProfiles()` — view saved credential profiles with masked display for security.
* `SaveKeyProfile()` — snapshot current API keys (Ryuu, DepotBox, Morrenus, ManifestHub, SteamGridDB, GitHub) into a named profile.
* `LoadKeyProfile()` — instantly switch between key profiles (e.g., work → personal account).
* `ExportKeyProfile()` — portable base64 `.ltkeys` archives for backup or machine transfer.
* `ImportKeyProfile()` — restore profiles from exported blobs with optional auto-activation.
* Granular per-key encryption state tracking and masked preview during import.

---

### Architecture

```text
ltsteamplugin-ultimate/
├── plugin.json                  # v8.4 manifest
├── backend/
│   ├── main.py                  # Plugin entry — all API endpoints (1070 LOC)
│   ├── steamtools.py            # Collection sync, audit, cache, backups
│   ├── cloud_fix.py             # ★ SteamTools cloud-save diagnostic (safe, read-only)
│   ├── steam_version.py         # ★ Steam client version detection & update blocking
│   ├── account_transfer.py      # ★ Account-to-account game-data transfer (Denuvo tokens, saves)
│   ├── key_vault.py             # ★ API key vault: profiles, export/import with security
│   ├── downloads.py             # Downloads + Ryuu/DepotBox + post-install audit
│   ├── steamtools_helper.ps1    # PowerShell standalone helper
│   ├── paths.py                 # Win11 native paths, registry, %LOCALAPPDATA%
│   ├── steam_utils.py           # VDF parser, game path resolver
│   ├── auto_update.py           # GitHub release auto-updater + key donation
│   ├── settings/
│   │   ├── options.py           # Schema: general + steamtools groups
│   │   └── manager.py           # Settings persistence, validation, getters
│   └── ...                      # api_manifest, config, fixes, http_client, locales, etc.
├── public/
│   ├── luatools.js              # Frontend web UI
│   ├── luatools-icon.png
│   ├── steamdb-webkit.css
│   └── themes/                  # 11 CSS themes
└── .millennium/Dist/            # Compiled frontend

---

### Code Quality & Recent Improvements (v8.4)

**Enhanced Error Handling & Resilience:**
- cloud_fix.py: Granular OS error handling with partial success tracking for stella fallback quarantine
- account_transfer.py: Robust backup listing with permission error recovery and graceful continuation
- key_vault.py: Fixed field counting logic and improved error logging throughout vault operations
- All modules validated with Python syntax checker and full type hints

**Safety & Backward Compatibility:**
- Zero breaking changes from v8.0+ � all new features are purely additive
- Existing API endpoints remain unchanged; new functionality exposed through new functions
- Full docstring coverage for all public methods
- Comprehensive error messages for troubleshooting

**Testing & Validation:**
- Python 3.8+ compatible (tested on Windows 11 + Millennium 2.36+)
- All file operations include atomic writes and rollback logic
- Permission denied and OSError scenarios handled gracefully
- Integration with existing logger infrastructure for audit trails

## License

MIT License � See LICENSE file for details.

## Contributing

See CONTRIBUTING.md for contribution guidelines.
