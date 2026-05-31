# LuaTools Ultimate

**Version 9.0.7**

> *Made in Ingria by Free People*  
> *Tehty Inkerissä vapaiden ihmisten toimesta*  
> 59°57′N 30°19′E

> 📄 Other languages: [Русский](README.ru.md) · [Українська](README.uk.md) · [Беларуская](README.be.md) · [Suomi](README.fi.md)

---

## 1. What this is

**LuaTools Ultimate** is a Millennium plugin for the Steam client that activates games through SteamTools-style `.lua` scripts. The plugin pulls activation scripts from a chain of nine sources, repairs the depot manifest cache when it gets corrupted, handles multi-account workflows without restarts, configures Tokeer launchers for Denuvo-protected titles, and watches your library in the background through the Sentinel daemon.

The codebase is Python (backend) plus vanilla JavaScript (frontend), no build pipeline required.

---

## 2. Layout

```
ltsteamplugin-ultimate/
├── plugin.json                     Millennium manifest
├── README.md                       this file
├── README.ru.md / .uk.md / .be.md / .fi.md
├── CLAUDE.md                       development context
├── SENTINEL_v9.md                  Sentinel design doc
│
├── backend/
│   ├── main.py                     entry point + all IPC wrappers
│   │
│   ├── ── Download & activation ──
│   ├── downloads.py                nine-source chain
│   ├── batch.py                    parallel download queue
│   ├── source_chain.py             user-reorderable source priority
│   ├── history.py                  SQLite log, per-source stats
│   ├── custom_apis.py              user-defined extra sources
│   │
│   ├── ── Fixes & repair ──
│   ├── fixes.py                    HuggingFace index, RAR/7Z extraction, LFS
│   ├── cloud_fix.py                online-fix downloader
│   ├── steamtools.py               audit, cache repair, achievement schema
│   │
│   ├── ── Accounts (v8.4–8.5) ──
│   ├── account_transfer.py         userdata copy between accounts
│   ├── account_switch.py           DPAPI-decrypted one-click switching
│   ├── tokeer_launcher.py          Denuvo bypass launch-options writer
│   ├── key_vault.py                Ryuu / DepotBox / Morrenus key profiles
│   │
│   ├── ── v9.0 automation ──
│   ├── sentinel.py                 background watcher
│   ├── sentinel_worker.py          standalone worker (runs without Steam)
│   ├── sentinel_service.py         Windows Scheduled Task installer
│   ├── sync_engine.py              multi-machine sync (Git or folder)
│   ├── crack_migrator.py           legacy-crack detection and migration
│   ├── profiles.py                 per-game named configurations
│   ├── workshop_manager.py         Steam Workshop subscriptions
│   ├── achievement_watch.py        read-only achievement dashboard
│   │
│   ├── ── Infrastructure ──
│   ├── settings/                   schema + persistence
│   ├── steam_utils.py              VDF parser, install-path resolver
│   ├── steam_version.py            Steam process detection
│   ├── http_client.py              shared httpx client
│   ├── auto_update.py              GitHub release polling, key donation
│   ├── donate_keys.py              7-day dedup cache
│   ├── events.py                   webhook hooks (Discord, ntfy.sh)
│   ├── mod_system.py               user mod loader
│   ├── security.py                 ZIP validation, path-traversal guards
│   ├── paths.py                    Windows 11 path resolution
│   ├── logger.py
│   └── locales/                    30+ language translations
│
├── public/
│   ├── luatools.js                 frontend (~8,200 lines)
│   ├── steamdb-webkit.css          SteamDB integration styles
│   ├── luatools-icon.png
│   └── themes/                     12 themes
│       └── ingria.css              default theme
│
├── mods/                           user-installable Lua mods
├── scripts/                        PowerShell helpers
└── .millennium/Dist/               compiled frontend bundle
```

---

## 3. Features

### 3.1 Source chain

Activation scripts come from nine sources, queried in priority order:

```
Local Folder → TwentyTwo Cloud → Ryuu Premium →
DepotBox Premium → ManifestHub API → Custom APIs →
Free APIs → SLStools Fallbacks → GitHub Repos
```

After three consecutive `connection refused` errors, the chain aborts. This prevents cascading failure when the network is down.

### 3.2 Depot cache repair

Four phases:

1. **Scan.** Every `.manifest` file is classified as valid, corrupt (bad magic bytes), zero-byte, or orphaned.
2. **Download.** Missing and corrupt manifests get re-fetched via GitHub mirrors → Morrenus → ManifestHub.
3. **Cleanup.** Empty files removed, corrupt replaced, old orphans purged, non-`.lua` files in `stplug-in/` cleared.
4. **Lua fix** *(opt-in).* Syntactically broken lines get commented out with a `--LUATOOLS_AUTOFIXED:` tag so they can be uncommented manually. Lines are never deleted.

Dry-run preview available before any destructive step.

### 3.3 Sentinel — background watcher

A daemon that runs either:

- as a thread inside the plugin process (default), or
- as a standalone worker via **Windows Scheduled Task** (`schtasks.exe /SC ONLOGON`, no UAC).

Sentinel:

- watches `steamapps/` for new installations
- pops Windows toast notifications when a newly-installed game is activatable through the source chain
- periodically checks manifest staleness via `api.steamcmd.net` (default: 24-hour per-game re-check)
- supports per-game ignore lists and notification cooldowns

Poll interval, auto-apply policy, and notification style are all configurable.

### 3.4 Account utilities

| Module | What it does |
|---|---|
| `account_transfer` | Copies `userdata/<accountId>/<appid>/` between two of your own Steam accounts. Used to migrate Denuvo activation tokens or cloud saves without re-logging in. |
| `account_switch` | Restarts Steam logged in as a chosen account. Decrypts saved refresh tokens via DPAPI, rewrites the `MostRecent` flag, and relaunches via `steam://0`. ~3-second switch. |
| `key_vault` | Snapshots active API keys as named profiles. Export to a portable base-64 `.ltkeys` blob to move keys between machines. |

### 3.5 Tokeer (Denuvo) auto-launcher

For 32 Denuvo-protected games that ship with a `tokeer_launcher.exe` (Pragmata, Resident Evil Requiem, MGSV: TPP, Hogwarts Legacy, Persona 5 Royal, Stellar Blade, Mortal Kombat 1, and others), the plugin writes the correct `"<path>\tokeer_launcher.exe" %command%` into Steam's launch options for the chosen account. Automatic `.bak-*` backup of `localconfig.vdf` before any write.

### 3.6 Multi-machine sync

State synchronization between LuaTools installs on different machines, with two backends:

- **Git.** Any private remote (GitHub, GitLab, Codeberg). Uses `git pull --ff-only` and `git push` via subprocess.
- **Folder.** Local path, mapped drive, or Syncthing-watched directory. SHA-256-based mirroring.

What syncs: `.lua` scripts, key vault profiles, Sentinel config, source chain config, optionally the download history database. Steam install paths and per-host caches stay local.

Conflict handling: if a local file is newer than the remote, the operation is paused with an explicit message. Every change is preceded by a `*.presync-<timestamp>` backup.

### 3.7 Crack auto-migrator

Scans installed games for signatures of eight crack families: Goldberg, CODEX/CPY, CreamAPI, ALI213, UnSteam, RUNE, generic Steam API loaders, DLL proxy hijacks. Each family has a weight; the dominant family is picked by total score.

Migration runs in *dry-run* mode by default. When confirmed, files move to `<game>/_luatools_migration_<timestamp>/`. Originals are never deleted, only relocated.

### 3.8 Per-game profiles

Each game can have multiple named configurations, each snapshotting the `.lua` content and launch options. Activation creates an automatic backup of the previous state. Switching between, say, *"Persona 5 + Tokeer"* and *"Persona 5 vanilla"* takes one click.

### 3.9 Workshop

User Workshop subscriptions are parsed from `localconfig.vdf`. For each subscribed item, the public `ISteamRemoteStorage/GetPublishedFileDetails` endpoint returns metadata plus a direct download URL. Downloads bypass the Steam client — useful when Workshop content fails to fetch for `.lua`-activated games.

### 3.10 Achievement watchlist *(read-only)*

A dashboard showing achievement progress per `.lua`-activated game. Data sources:

- Web API schema (`ISteamUserStats/GetSchemaForGame`) for the total count
- Local `UserGameStats_<accountId>_<appid>.bin` for unlock count

**This module never writes to stats files.** The read-only design is deliberate: modifying public achievement state violates Steam's terms and creates account risk.

---

## 4. Requirements

| Component | Requirement |
|---|---|
| OS | Windows 10 / 11 (x64) |
| Platform | Millennium 2.35+ |
| Python | shipped with Millennium |
| Network | Outbound HTTPS to `huggingface.co`, `api.steampowered.com`, `api.steamcmd.net`, `github.com`, and any configured premium sources |
| Optional | 7-Zip or WinRAR (for RAR/7Z fix extraction), Git (for repo-based sync) |

---

## 5. Installation

1. Extract the archive to `<Steam>\plugins\luatools\` (for example, `D:\Steam\plugins\luatools\`).
2. Restart Steam.
3. Enable the plugin: **Steam → Millennium → Plugins → LuaTools Ultimate**.

On first launch with a Russian locale, the Ingria theme suggestion appears as a one-time non-modal card. Accepting it is optional. The setting is remembered per browser.

---

## 6. Safety notes

- **Steam must be closed** before any operation that writes to `userdata/`, `localconfig.vdf`, or `loginusers.vdf`. Running Steam will overwrite your changes when it next shuts down. All affected operations refuse to run while Steam is detected as active.
- **Backups are automatic** before any destructive operation. Naming: `*.bak-<timestamp>` or `*.presync-<timestamp>` in the same directory as the original. Use `ListUserdataBackups()` to enumerate them.
- **DPAPI tokens are read-only.** Account switching only flips the `MostRecent` pointer in `loginusers.vdf`. The JWT itself is never decrypted, modified, or transmitted.
- **Lua auto-fix is reversible.** Broken lines aren't deleted — they're commented out with an explicit `--LUATOOLS_AUTOFIXED:` tag and can be restored manually.

---

## 7. IPC reference

See `backend/main.py`. Most-used endpoints:

```
RepairDepotCache(appid, fix_lua, remove_orphans, dry_run)
SyncDepotcache(appid)
GetAchievementProgress(appid, accountId32)
TransferGameUserdata(from, to, appid, overwrite, backup)
SwitchToAccount(accountName)
ConfigureTokeerLaunch(appid, accountId32)
SyncPush() / SyncPull(dryRun=False)
ScanCrackedGames() / MigrateGame(appid, dryRun=True)
ListWorkshopSubscribed(appid, accountId32)
SaveProfile(appid, name) / ActivateProfile(appid, slug)
GetSentinelService() / InstallSentinelService()
```

---

## 8. Credits

| Source | Contribution |
|---|---|
| **madoiscool** | original `ltsteamplugin` |
| **sigmachan** | modded fork (Ryuu/DepotBox/themes) |
| **clemdotla** | `steamtools-collection` — audit and sync logic, ported from Lua to Python for Windows |
| **RaiSantos** | `lt_api_links` — Tokeer compatibility list, `Devuvo.ps1`, HuggingFace fixes index, multi-source manifest chain, library refresh strategy |
| **RobiZkt** | `Steam-Token-Grabber` — DPAPI implementation for account switching |
| **SteamTokenDumper community** | depot ID database |

---

## 9. Non-political note

The plugin contains no political symbols, no flag patterns, no slogans. The default theme palette is based on the climate of the northwest region — clear winter skies over the Gulf of Finland, the soft glow of white nights. Any further associations the reader brings are the reader's own.

---

*Technical terms appear in canonical English form throughout (`appmanifest`, `localconfig.vdf`, `DPAPI`) to keep code-grepping consistent across languages.*
