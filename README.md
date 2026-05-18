<div align="right">
  <strong>🌍 Languages:</strong>
  <a href="#english-version">🇬🇧 English</a> |
  <a href="#русская-версия">🇷🇺 Русский</a>
</div>

---

<a id="english-version"></a>
# 🇬🇧 LuaTools Ultimate v8.0

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

---

### Architecture

```text
ltsteamplugin-ultimate/
├── plugin.json                  # v8.0 manifest
├── backend/
│   ├── main.py                  # Plugin entry — all API endpoints
│   ├── steamtools.py            # ★ NEW: collection sync, audit, cache, backups
│   ├── steamtools_helper.ps1    # ★ NEW: PowerShell standalone helper
│   ├── downloads.py             # Downloads + Ryuu/DepotBox + post-install audit
│   ├── paths.py                 # Enhanced: Win11 native paths, registry, %LOCALAPPDATA%
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
