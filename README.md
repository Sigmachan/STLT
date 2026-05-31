# LuaTools Ultimate

[English](#en) · [Русский](#ru) · [Українська](#uk) · [Беларуская](#be) · [Suomi](#fi)

> **One file, one README:** click a language above to jump to that section in the same file without reloading.
>
> If you want a compact readme view, use your editor's search or collapse blocks.

---

<a id="en"></a>
## English

**Version 9.0.7**

> *Made in Ingria by Free People*  
> *Tehty Inkerissä vapaiden ihmisten toimesta*  
> 59°57′N 30°19′E

> 📄 Other languages: [Русский](#ru) · [Українська](#uk) · [Беларуская](#be) · [Suomi](#fi)
>
> **Click a language above to jump to that section in the same file.**
>
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

---

<a id="ru"></a>
## Русский

**Версия 9.0.7**

> *Made in Ingria by Free People*  
> *Tehty Inkerissä vapaiden ihmisten toimesta*  
> 59°57′N 30°19′E

> 📄 Другие языки: [English (US)](#en) · [Українська](#uk) · [Беларуская](#be) · [Suomi](#fi)
>
> **Click a language above to jump to that section in the same file.**

---

## 1. Назначение

Программный комплекс **LuaTools Ultimate** предназначен для автоматизированной активации игр в среде Steam-клиента через скрипты формата SteamTools (`.lua`). Реализован в виде плагина для платформы Millennium.

Комплекс обеспечивает:

- получение активационных скриптов из распределённой цепочки источников;
- поддержание целостности кэша манифестов и автоматическое восстановление повреждённых записей;
- управление учётными данными между несколькими пользовательскими аккаунтами без перезагрузки клиента;
- настройку обходных загрузчиков для игр под защитой Denuvo (Tokeer);
- наблюдение в фоновом режиме за изменениями состояния установленной библиотеки.

---

## 2. Состав

```
ltsteamplugin-ultimate/
├── plugin.json                     манифест Millennium
├── README.md
├── CLAUDE.md                       контекст для разработки
├── SENTINEL_v9.md                  проектная документация Sentinel
│
├── backend/
│   ├── main.py                     точка входа, IPC-обёртки
│   │
│   ├── ── Загрузка и активация ──
│   ├── downloads.py                цепочка из девяти источников
│   ├── batch.py                    параллельная очередь загрузок
│   ├── source_chain.py             пользовательская переупорядочиваемая цепочка
│   ├── history.py                  SQLite-журнал, статистика по источникам
│   ├── custom_apis.py              пользовательские источники
│   │
│   ├── ── Восстановление и фиксы ──
│   ├── fixes.py                    индекс через HuggingFace, RAR/7Z, LFS
│   ├── cloud_fix.py                загрузчик online-исправлений
│   ├── steamtools.py               аудит, ремонт кэша, схема достижений
│   │
│   ├── ── Учётные записи (v8.4–8.5) ──
│   ├── account_transfer.py         копирование userdata между аккаунтами
│   ├── account_switch.py           DPAPI-расшифровка, переключение
│   ├── tokeer_launcher.py          обход Denuvo через Tokeer
│   ├── key_vault.py                профили ключей Ryuu/DepotBox/Morrenus
│   │
│   ├── ── Автоматизация v9.0 ──
│   ├── sentinel.py                 фоновый наблюдатель
│   ├── sentinel_worker.py          автономный воркер (без Steam)
│   ├── sentinel_service.py         установщик планировщика Windows
│   ├── sync_engine.py              синхронизация между машинами (Git / папка)
│   ├── crack_migrator.py           обнаружение и миграция старых кряков
│   ├── profiles.py                 профили конфигурации на игру
│   ├── workshop_manager.py         менеджер Workshop-подписок
│   ├── achievement_watch.py        мониторинг достижений (только чтение)
│   │
│   ├── ── Инфраструктура ──
│   ├── settings/                   схема и хранение настроек
│   ├── steam_utils.py              парсинг VDF, поиск установки
│   ├── steam_version.py            детектор процесса Steam
│   ├── http_client.py              общий httpx-клиент
│   ├── auto_update.py              опрос GitHub, рассылка ключей
│   ├── donate_keys.py              антидубликат-кэш на 7 суток
│   ├── events.py                   webhook-хуки (Discord, ntfy.sh)
│   ├── mod_system.py               загрузчик пользовательских модов
│   ├── security.py                 проверка ZIP, защита от path traversal
│   ├── paths.py                    разрешение путей под Windows 11
│   ├── logger.py
│   └── locales/                    локализации (более 30 языков)
│
├── public/
│   ├── luatools.js                 фронт-энд (~8200 строк)
│   ├── steamdb-webkit.css          интеграция SteamDB
│   ├── luatools-icon.png
│   └── themes/                     12 тем оформления
│       └── ingria.css              тема по умолчанию
│
├── mods/                           пользовательские .lua-моды
├── scripts/                        вспомогательные сценарии PowerShell
└── .millennium/Dist/               скомпилированный фронт-энд
```

---

## 3. Функциональные возможности

### 3.1 Цепочка источников

Активационные скрипты получаются последовательным опросом девяти источников в порядке приоритета:

```
Локальная папка → TwentyTwo Cloud → Ryuu Premium →
DepotBox Premium → ManifestHub API → Custom APIs →
Free APIs → SLStools Fallbacks → GitHub-репозитории
```

При обнаружении трёх подряд ошибок типа *connection refused* цепочка прерывается. Это предотвращает каскадный отказ при отсутствии сети.

### 3.2 Восстановление кэша манифестов

Производится в четыре фазы:

1. **Сканирование.** Каждый файл `.manifest` классифицируется как: валидный (правильная сигнатура), повреждённый (нарушенная сигнатура), нулевого размера, или орфан (отсутствует в цепочке).
2. **Загрузка.** Повторное получение отсутствующих и повреждённых манифестов через зеркала GitHub → Morrenus → ManifestHub.
3. **Очистка.** Удаление пустых файлов, замена повреждённых, удаление устаревших орфанов, удаление не-`.lua` файлов из `stplug-in/`.
4. **Восстановление Lua** *(по запросу).* Комментирование синтаксически неверных строк с меткой `--LUATOOLS_AUTOFIXED:`, что обеспечивает обратимость.

Перед любой деструктивной операцией доступен режим предварительного просмотра.

### 3.3 Sentinel — фоновое наблюдение

Программный демон, выполняющийся в виде:

- потока внутри процесса плагина (по умолчанию), либо
- автономного процесса через **запланированную задачу Windows** (`schtasks.exe /SC ONLOGON`, без UAC).

Функции демона:

- наблюдение за директорией `steamapps/` на предмет новых установок;
- оповещение пользователя через всплывающие уведомления Windows при появлении активационного скрипта в цепочке источников;
- периодическая проверка устаревания манифестов с использованием `api.steamcmd.net` (по умолчанию — раз в 24 часа на игру);
- список игнорируемых игр и индивидуальные тайм-ауты уведомлений.

Период опроса, политика автоматического применения и стиль уведомлений настраиваются.

### 3.4 Учётные записи

| Подсистема | Назначение |
|---|---|
| `account_transfer` | Перенос `userdata/<accountId>/<appid>/` между двумя собственными аккаунтами для миграции токенов активации Denuvo и облачных сохранений. |
| `account_switch` | Перезапуск Steam с автологином в выбранный аккаунт через расшифровку refresh-токенов методом DPAPI. Время переключения — около трёх секунд. |
| `key_vault` | Снимки активных API-ключей в виде профилей. Экспорт в портативный base64-формат `.ltkeys` для переноса между машинами. |

### 3.5 Обход Denuvo (Tokeer)

Для тридцати двух игр, выпускающих защищённый исполняемый файл вместе с `tokeer_launcher.exe`, выполняется автоматическая запись Steam launch options в `localconfig.vdf` указанного пользователя. Перечень игр включает Pragmata, Resident Evil Requiem, MGSV: TPP, Hogwarts Legacy, Persona 5 Royal, Stellar Blade, Mortal Kombat 1 и другие современные тайтлы.

### 3.6 Многомашинная синхронизация

Состояние комплекса синхронизируется между несколькими установками через один из двух механизмов:

- **Git.** Произвольный удалённый репозиторий (приватный GitHub/GitLab/Codeberg). Используются стандартные команды `git pull/push --ff-only`.
- **Папка.** Локальный путь, сетевой диск или каталог под наблюдением Syncthing. Зеркалирование по содержимому (SHA-256).

Синхронизируется: `.lua`-скрипты, профили ключей, конфигурация Sentinel, цепочка источников, по запросу — журнал загрузок. Пути установки Steam и кеши остаются на каждой машине локальными.

При обнаружении конфликта (локальный файл новее удалённого) операция приостанавливается с явным сообщением. Все изменения предваряются резервной копией `*.presync-<метка-времени>`.

### 3.7 Миграция кряков

Сканирование установленных игр на наличие сигнатур восьми семейств: Goldberg, CODEX/CPY, CreamAPI, ALI213, UnSteam, RUNE, обобщённые загрузчики Steam API, прокси-перехваты DLL. Каждое семейство получает весовой коэффициент; доминирующее определяется суммарным баллом.

Миграция выполняется в режиме *dry-run* по умолчанию. При подтверждении файлы перемещаются в `<игра>/_luatools_migration_<метка-времени>/`. Уничтожение исходных данных не производится никогда.

### 3.8 Профили на игру

Для каждой игры сохраняются именованные конфигурации, включающие содержимое `.lua`-скрипта и параметры запуска. При активации профиля автоматически создаётся резервная копия предыдущего состояния. Переключение между, например, *«Persona 5 + Tokeer»* и *«Persona 5 vanilla»* выполняется одним кликом.

### 3.9 Workshop

Подписки пользователя в Steam Workshop читаются из `localconfig.vdf`. Для каждого подписанного предмета через публичную точку `ISteamRemoteStorage/GetPublishedFileDetails` получаются метаданные и URL прямой загрузки. Загрузка производится напрямую — в обход Steam-клиента, что позволяет получать Workshop-контент для игр, активированных через LuaTools.

### 3.10 Мониторинг достижений *(только чтение)*

Дашборд прогресса достижений по каждой `.lua`-активированной игре. Данные собираются из:

- схемы Web API (`ISteamUserStats/GetSchemaForGame`) — общее число достижений;
- локального файла `UserGameStats_<accountId>_<appid>.bin` — счётчик выполненных.

Запись в файлы статистики не производится. Подсистема намеренно реализована только в режиме чтения — модификация публичной статистики достижений противоречит политике Steam и создаёт риск для аккаунта.

---

## 4. Системные требования

| Компонент | Требование |
|---|---|
| ОС | Windows 10 / 11 (x64) |
| Платформа | Millennium 2.35+ |
| Python | поставляется с Millennium |
| Сеть | TCP-исходящий: HTTPS на `huggingface.co`, `api.steampowered.com`, `api.steamcmd.net`, `github.com`, выбранные премиум-источники |
| Опционально | 7-Zip или WinRAR (для извлечения RAR/7Z-фиксов); Git (для синхронизации через репозиторий) |

---

## 5. Установка

1. Распаковать архив в `<Steam>\plugins\luatools\` (например, `D:\Steam\plugins\luatools\`).
2. Перезапустить Steam-клиент.
3. Включить плагин: **Steam → Millennium → Plugins → LuaTools Ultimate**.

При первом запуске на русской локали будет предложена тема оформления *Ingria*; принятие предложения необязательно и сохраняется однократно.

---

## 6. Указания по безопасной эксплуатации

- **Steam должен быть выключен** перед любой операцией, изменяющей `userdata/`, `localconfig.vdf` или `loginusers.vdf`. При активном Steam-клиенте система перезапишет внесённые изменения при следующем штатном выходе.
- **Резервные копии создаются автоматически** перед каждой деструктивной операцией. Соглашение об именовании: `*.bak-<метка-времени>` или `*.presync-<метка-времени>` в той же директории. См. `ListUserdataBackups()` для перечня.
- **DPAPI-токены читаются, но не изменяются.** Переключение аккаунта оперирует только указателем `MostRecent` в `loginusers.vdf`. Сам JWT не расшифровывается, не модифицируется, не передаётся вовне.
- **Автоисправление `.lua` обратимо.** Повреждённые строки не удаляются — они комментируются с явной меткой `--LUATOOLS_AUTOFIXED:` и могут быть восстановлены вручную.

---

## 7. Перечень IPC-точек

См. файл `backend/main.py`. Краткая выборка наиболее используемых:

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

## 8. Благодарности

| Источник | Вклад |
|---|---|
| **madoiscool** | оригинальный `ltsteamplugin` |
| **sigmachan** | модифицированный форк (Ryuu/DepotBox/темы) |
| **clemdotla** | `steamtools-collection` — логика аудита и синхронизации, портирована с Lua на Python для Windows |
| **RaiSantos** | `lt_api_links` — перечень совместимости с Tokeer, `Devuvo.ps1`, HuggingFace-индекс фиксов, цепочка манифестов, обновление библиотеки Steam |
| **RobiZkt** | `Steam-Token-Grabber` — реализация DPAPI для переключения аккаунтов |
| **сообщество SteamTokenDumper** | база данных Depot-идентификаторов |

---

## 9. Принцип неагитации

Программный комплекс не содержит политических элементов оформления. Цветовая палитра темы по умолчанию основана на климатических условиях северо-западного региона: ясное небо над Финским заливом, белые ночи. Любые иные ассоциации остаются на стороне читателя.

---

*Документ составлен на русском языке. Технические термины приведены в общепринятой англоязычной записи во избежание неоднозначности при поиске по коду.*

---

<a id="uk"></a>
## Українська

**Версія 9.0.7**

> *Made in Ingria by Free People*  
> *Tehty Inkerissä vapaiden ihmisten toimesta*  
> 59°57′N 30°19′E

> 📄 Інші мови: [Русский](#ru) · [English (US)](#en) · [Беларуская](#be) · [Suomi](#fi)
>
> **Click a language above to jump to that section in the same file.**

---

## 1. Призначення

Програмний комплекс **LuaTools Ultimate** призначений для автоматизованої активації ігор у середовищі Steam-клієнта через скрипти формату SteamTools (`.lua`). Реалізовано як плагін для платформи Millennium.

Комплекс забезпечує:

- отримання активаційних скриптів із розподіленого ланцюга джерел;
- підтримання цілісності кешу маніфестів та автоматичне відновлення пошкоджених записів;
- керування обліковими даними між декількома користувацькими акаунтами без перезавантаження клієнта;
- налаштування обхідних завантажувачів для ігор під захистом Denuvo (Tokeer);
- спостереження у фоновому режимі за змінами стану встановленої бібліотеки.

---

## 2. Склад

```
ltsteamplugin-ultimate/
├── plugin.json                     маніфест Millennium
├── README.md / .ru.md / .uk.md / .be.md / .fi.md
├── CLAUDE.md                       контекст для розробки
├── SENTINEL_v9.md                  проєктна документація Sentinel
│
├── backend/
│   ├── main.py                     точка входу, IPC-обгортки
│   │
│   ├── ── Завантаження та активація ──
│   ├── downloads.py                ланцюг із дев'яти джерел
│   ├── batch.py                    паралельна черга завантажень
│   ├── source_chain.py             користувацький ланцюг джерел
│   ├── history.py                  журнал SQLite, статистика
│   ├── custom_apis.py              користувацькі джерела
│   │
│   ├── ── Виправлення та відновлення ──
│   ├── fixes.py                    індекс HuggingFace, RAR/7Z, LFS
│   ├── cloud_fix.py                завантажувач online-виправлень
│   ├── steamtools.py               аудит, ремонт кешу, схема досягнень
│   │
│   ├── ── Акаунти (v8.4–8.5) ──
│   ├── account_transfer.py         перенесення userdata між акаунтами
│   ├── account_switch.py           DPAPI-розшифрування, перемикання
│   ├── tokeer_launcher.py          обхід Denuvo через Tokeer
│   ├── key_vault.py                профілі ключів Ryuu/DepotBox/Morrenus
│   │
│   ├── ── Автоматизація v9.0 ──
│   ├── sentinel.py                 фоновий спостерігач
│   ├── sentinel_worker.py          автономний воркер (без Steam)
│   ├── sentinel_service.py         встановлювач планувальника Windows
│   ├── sync_engine.py              синхронізація між машинами
│   ├── crack_migrator.py           виявлення та міграція старих кряків
│   ├── profiles.py                 профілі конфігурації на гру
│   ├── workshop_manager.py         менеджер підписок Workshop
│   ├── achievement_watch.py        моніторинг досягнень (лише читання)
│   │
│   ├── ── Інфраструктура ──
│   ├── settings/                   схема та зберігання налаштувань
│   ├── steam_utils.py              парсер VDF, пошук встановлення
│   ├── steam_version.py            детектор процесу Steam
│   ├── http_client.py              спільний httpx-клієнт
│   ├── auto_update.py              опитування GitHub, розсилка ключів
│   ├── donate_keys.py              антидублікат-кеш на 7 діб
│   ├── events.py                   webhook-гачки (Discord, ntfy.sh)
│   ├── mod_system.py               завантажувач користувацьких модів
│   ├── security.py                 перевірка ZIP, захист від path traversal
│   ├── paths.py                    розв'язання шляхів під Windows 11
│   ├── logger.py
│   └── locales/                    локалізації (понад 30 мов)
│
├── public/
│   ├── luatools.js                 фронт-енд (~8200 рядків)
│   ├── steamdb-webkit.css          інтеграція SteamDB
│   ├── luatools-icon.png
│   └── themes/                     12 тем оформлення
│       └── ingria.css              тема за замовчуванням
│
├── mods/                           користувацькі .lua-моди
├── scripts/                        допоміжні сценарії PowerShell
└── .millennium/Dist/               скомпільований фронт-енд
```

---

## 3. Можливості

### 3.1 Ланцюг джерел

Активаційні скрипти отримуються послідовним опитуванням дев'яти джерел у порядку пріоритету:

```
Локальна тека → TwentyTwo Cloud → Ryuu Premium →
DepotBox Premium → ManifestHub API → Custom APIs →
Free APIs → SLStools Fallbacks → GitHub-репозиторії
```

Після трьох поспіль помилок типу *connection refused* ланцюг переривається. Це запобігає каскадному збою за відсутності мережі.

### 3.2 Відновлення кешу маніфестів

Виконується у чотири фази:

1. **Сканування.** Кожен файл `.manifest` класифікується як: дійсний, пошкоджений, нульового розміру або осиротілий.
2. **Завантаження.** Повторне отримання відсутніх і пошкоджених маніфестів через дзеркала GitHub → Morrenus → ManifestHub.
3. **Очищення.** Видалення порожніх файлів, заміна пошкоджених, видалення застарілих сиріт, видалення не-`.lua` файлів зі `stplug-in/`.
4. **Відновлення Lua** *(за запитом).* Коментування синтаксично неправильних рядків з міткою `--LUATOOLS_AUTOFIXED:`, що забезпечує оборотність.

Перед будь-якою деструктивною операцією доступний режим попереднього перегляду.

### 3.3 Sentinel — фонове спостереження

Програмний демон, що виконується як:

- потік усередині процесу плагіна (за замовчуванням), або
- автономний процес через **заплановане завдання Windows** (`schtasks.exe /SC ONLOGON`, без UAC).

Функції демона:

- спостереження за теками `steamapps/` на предмет нових встановлень;
- сповіщення користувача через спливаючі повідомлення Windows;
- періодична перевірка застарівання маніфестів через `api.steamcmd.net` (за замовчуванням — раз на 24 години на гру);
- список ігнорованих ігор та індивідуальні тайм-аути сповіщень.

### 3.4 Облікові записи

| Підсистема | Призначення |
|---|---|
| `account_transfer` | Перенесення `userdata/<accountId>/<appid>/` між двома власними акаунтами для міграції токенів Denuvo та хмарних збережень. |
| `account_switch` | Перезапуск Steam з автологіном до обраного акаунта через розшифрування refresh-токенів методом DPAPI. Час перемикання — близько трьох секунд. |
| `key_vault` | Знімки активних API-ключів у вигляді профілів. Експорт у переносний base64-формат `.ltkeys` для перенесення між машинами. |

### 3.5 Обхід Denuvo (Tokeer)

Для тридцяти двох ігор, що випускають захищений виконуваний файл разом із `tokeer_launcher.exe`, виконується автоматичний запис Steam launch options у `localconfig.vdf` зазначеного користувача. Перелік ігор включає Pragmata, Resident Evil Requiem, MGSV: TPP, Hogwarts Legacy, Persona 5 Royal, Stellar Blade, Mortal Kombat 1 та інші сучасні тайтли.

### 3.6 Багатомашинна синхронізація

Стан комплексу синхронізується між кількома встановленнями через один із двох механізмів:

- **Git.** Довільний віддалений репозиторій (приватний GitHub/GitLab/Codeberg).
- **Тека.** Локальний шлях, мережевий диск або каталог під наглядом Syncthing. Дзеркалювання за вмістом (SHA-256).

Синхронізується: `.lua`-скрипти, профілі ключів, конфігурація Sentinel, ланцюг джерел, за запитом — журнал завантажень.

### 3.7 Міграція кряків

Сканування встановлених ігор на наявність сигнатур восьми сімейств: Goldberg, CODEX/CPY, CreamAPI, ALI213, UnSteam, RUNE, узагальнені завантажувачі Steam API, проксі-перехоплення DLL.

Міграція виконується у режимі *dry-run* за замовчуванням. При підтвердженні файли переміщуються до `<гра>/_luatools_migration_<мітка-часу>/`. Знищення вихідних даних не виконується ніколи.

### 3.8 Профілі на гру

Для кожної гри зберігаються іменовані конфігурації, що включають вміст `.lua`-скрипта та параметри запуску. Перемикання між, наприклад, *«Persona 5 + Tokeer»* та *«Persona 5 vanilla»* виконується одним кліком.

### 3.9 Workshop

Підписки користувача у Steam Workshop читаються з `localconfig.vdf`. Для кожного підписаного предмета через публічну точку `ISteamRemoteStorage/GetPublishedFileDetails` отримуються метадані та URL прямого завантаження. Завантаження виконується безпосередньо — в обхід Steam-клієнта.

### 3.10 Моніторинг досягнень *(лише читання)*

Дашборд прогресу досягнень за кожною `.lua`-активованою грою. Дані збираються з:

- схеми Web API (`ISteamUserStats/GetSchemaForGame`) — загальна кількість досягнень;
- локального файлу `UserGameStats_<accountId>_<appid>.bin` — лічильник виконаних.

Запис до файлів статистики не виконується. Підсистема свідомо реалізована лише у режимі читання — модифікація публічної статистики досягнень суперечить політиці Steam.

---

## 4. Системні вимоги

| Компонент | Вимога |
|---|---|
| ОС | Windows 10 / 11 (x64) |
| Платформа | Millennium 2.35+ |
| Python | постачається з Millennium |
| Мережа | TCP-вихідний: HTTPS до `huggingface.co`, `api.steampowered.com`, `api.steamcmd.net`, `github.com`, обрані преміум-джерела |
| Опціонально | 7-Zip або WinRAR (для розпакування RAR/7Z-виправлень); Git (для синхронізації через репозиторій) |

---

## 5. Встановлення

1. Розпакувати архів до `<Steam>\plugins\luatools\` (наприклад, `D:\Steam\plugins\luatools\`).
2. Перезапустити Steam-клієнт.
3. Увімкнути плагін: **Steam → Millennium → Plugins → LuaTools Ultimate**.

---

## 6. Поради з безпеки

- **Steam має бути вимкненим** перед будь-якою операцією, що змінює `userdata/`, `localconfig.vdf` або `loginusers.vdf`.
- **Резервні копії створюються автоматично** перед кожною деструктивною операцією. Іменування: `*.bak-<мітка-часу>` або `*.presync-<мітка-часу>`.
- **DPAPI-токени читаються, але не змінюються.** Перемикання акаунта оперує лише вказівником `MostRecent` у `loginusers.vdf`.
- **Автовиправлення `.lua` оборотне.** Пошкоджені рядки не видаляються — вони коментуються з явною міткою `--LUATOOLS_AUTOFIXED:`.

---

## 7. Перелік IPC-точок

Див. файл `backend/main.py`. Стислий перелік найуживаніших:

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

## 8. Подяки

| Джерело | Внесок |
|---|---|
| **madoiscool** | оригінальний `ltsteamplugin` |
| **sigmachan** | модифікований форк (Ryuu/DepotBox/теми) |
| **clemdotla** | `steamtools-collection` — логіка аудиту та синхронізації, портована з Lua на Python для Windows |
| **RaiSantos** | `lt_api_links` — перелік сумісності з Tokeer, `Devuvo.ps1`, HuggingFace-індекс виправлень, ланцюг маніфестів, оновлення бібліотеки Steam |
| **RobiZkt** | `Steam-Token-Grabber` — реалізація DPAPI для перемикання акаунтів |
| **спільнота SteamTokenDumper** | база даних Depot-ідентифікаторів |

---

## 9. Принцип неагітації

Програмний комплекс не містить політичних елементів оформлення. Палітра теми за замовчуванням ґрунтується на кліматичних умовах північно-західного регіону: чисте небо над Фінською затокою, білі ночі. Будь-які інші асоціації залишаються на боці читача.

---

*Технічні терміни наведено у загальноприйнятій англомовній формі для уніфікації пошуку коду між мовами.*

---

<a id="be"></a>
## Беларуская

**Версія 9.0.7**

> *Made in Ingria by Free People*  
> *Tehty Inkerissä vapaiden ihmisten toimesta*  
> 59°57′N 30°19′E

> 📄 Іншыя мовы: [Русский](#ru) · [English (US)](#en) · [Українська](#uk) · [Suomi](#fi)
>
> **Click a language above to jump to that section in the same file.**

---

## 1. Прызначэнне

Праграмны комплекс **LuaTools Ultimate** прызначаны для аўтаматызаванай актывацыі гульняў у асяроддзі Steam-кліента праз скрыпты фармату SteamTools (`.lua`). Рэалізаваны ў выглядзе плагіна для платформы Millennium.

Комплекс забяспечвае:

- атрыманне актывацыйных скрыптаў з размеркаванага ланцуга крыніц;
- падтрыманне цэласнасці кэша маніфестаў і аўтаматычнае аднаўленне пашкоджаных запісаў;
- кіраванне ўліковымі дадзенымі паміж некалькімі карыстальніцкімі акаўнтамі без перазагрузкі кліента;
- наладку абыходных загрузчыкаў для гульняў пад абаронай Denuvo (Tokeer);
- назіранне ў фонавым рэжыме за зменамі стану ўсталяванай бібліятэкі.

---

## 2. Склад

```
ltsteamplugin-ultimate/
├── plugin.json                     маніфест Millennium
├── README.md / .ru.md / .uk.md / .be.md / .fi.md
├── CLAUDE.md                       кантэкст для распрацоўкі
├── SENTINEL_v9.md                  праектная дакументацыя Sentinel
│
├── backend/
│   ├── main.py                     пункт уваходу, IPC-абгорткі
│   │
│   ├── ── Загрузка і актывацыя ──
│   ├── downloads.py                ланцуг з дзевяці крыніц
│   ├── batch.py                    паралельная чарга загрузак
│   ├── source_chain.py             карыстальніцкі ланцуг крыніц
│   ├── history.py                  журнал SQLite, статыстыка
│   ├── custom_apis.py              карыстальніцкія крыніцы
│   │
│   ├── ── Выпраўленні і аднаўленне ──
│   ├── fixes.py                    індэкс HuggingFace, RAR/7Z, LFS
│   ├── cloud_fix.py                загрузчык online-выпраўленняў
│   ├── steamtools.py               аўдыт, рамонт кэша, схема дасягненняў
│   │
│   ├── ── Акаўнты (v8.4–8.5) ──
│   ├── account_transfer.py         перанос userdata паміж акаўнтамі
│   ├── account_switch.py           DPAPI-расшыфроўка, пераключэнне
│   ├── tokeer_launcher.py          абыход Denuvo праз Tokeer
│   ├── key_vault.py                профілі ключоў Ryuu/DepotBox/Morrenus
│   │
│   ├── ── Аўтаматызацыя v9.0 ──
│   ├── sentinel.py                 фонавы назіральнік
│   ├── sentinel_worker.py          аўтаномны воркер (без Steam)
│   ├── sentinel_service.py         усталёўшчык планавальніка Windows
│   ├── sync_engine.py              сінхранізацыя паміж машынамі
│   ├── crack_migrator.py           выяўленне і міграцыя старых крэкаў
│   ├── profiles.py                 профілі канфігурацыі на гульню
│   ├── workshop_manager.py         менеджар падпісак Workshop
│   ├── achievement_watch.py        маніторынг дасягненняў (толькі чытанне)
│   │
│   ├── ── Інфраструктура ──
│   ├── settings/                   схема і захоўванне налад
│   ├── steam_utils.py              парсер VDF, пошук усталявання
│   ├── steam_version.py            дэтэктар працэсу Steam
│   ├── http_client.py              агульны httpx-кліент
│   ├── auto_update.py              апытванне GitHub, рассылка ключоў
│   ├── donate_keys.py              антыдублікат-кэш на 7 сутак
│   ├── events.py                   webhook-хукі (Discord, ntfy.sh)
│   ├── mod_system.py               загрузчык карыстальніцкіх модаў
│   ├── security.py                 праверка ZIP, абарона ад path traversal
│   ├── paths.py                    вызначэнне шляхоў пад Windows 11
│   ├── logger.py
│   └── locales/                    лакалізацыі (больш за 30 моў)
│
├── public/
│   ├── luatools.js                 фронт-энд (~8200 радкоў)
│   ├── steamdb-webkit.css          інтэграцыя SteamDB
│   ├── luatools-icon.png
│   └── themes/                     12 тэм аздаблення
│       └── ingria.css              тэма па змаўчанні
│
├── mods/                           карыстальніцкія .lua-моды
├── scripts/                        дапаможныя сцэнарыі PowerShell
└── .millennium/Dist/               скампіляваны фронт-энд
```

---

## 3. Магчымасці

### 3.1 Ланцуг крыніц

Актывацыйныя скрыпты атрымліваюцца паслядоўным апытваннем дзевяці крыніц у парадку прыярытэту:

```
Лакальная папка → TwentyTwo Cloud → Ryuu Premium →
DepotBox Premium → ManifestHub API → Custom APIs →
Free APIs → SLStools Fallbacks → GitHub-рэпазіторыі
```

Пасля трох запар памылак тыпу *connection refused* ланцуг перарываецца. Гэта прадухіляе каскадны збой пры адсутнасці сеткі.

### 3.2 Аднаўленне кэша маніфестаў

Выконваецца ў чатыры фазы:

1. **Сканаванне.** Кожны файл `.manifest` класіфікуецца як: сапраўдны, пашкоджаны, нулявога памеру або асірацелы.
2. **Загрузка.** Паўторнае атрыманне адсутных і пашкоджаных маніфестаў праз люстэркі GitHub → Morrenus → ManifestHub.
3. **Ачыстка.** Выдаленне пустых файлаў, замена пашкоджаных, выдаленне састарэлых сірот, выдаленне не-`.lua` файлаў са `stplug-in/`.
4. **Аднаўленне Lua** *(па запыце).* Каменціраванне сінтаксічна няправільных радкоў з пазнакай `--LUATOOLS_AUTOFIXED:`, што забяспечвае зваротнасць.

Перад любой дэструктыўнай аперацыяй даступны рэжым папярэдняга прагляду.

### 3.3 Sentinel — фонавае назіранне

Праграмны дэман, які выконваецца як:

- паток унутры працэсу плагіна (па змаўчанні), або
- аўтаномны працэс праз **запланаваную задачу Windows** (`schtasks.exe /SC ONLOGON`, без UAC).

Функцыі дэмана:

- назіранне за папкай `steamapps/` на прадмет новых усталяванняў;
- апавяшчэнне карыстальніка праз усплывальныя паведамленні Windows;
- перыядычная праверка састарэння маніфестаў праз `api.steamcmd.net` (па змаўчанні — раз на 24 гадзіны на гульню);
- спіс ігнараваных гульняў і індывідуальныя тайм-аўты апавяшчэнняў.

### 3.4 Уліковыя запісы

| Падсістэма | Прызначэнне |
|---|---|
| `account_transfer` | Перанос `userdata/<accountId>/<appid>/` паміж двума ўласнымі акаўнтамі для міграцыі токенаў Denuvo і воблачных захаванняў. |
| `account_switch` | Перазапуск Steam з аўталагінам у выбраны акаўнт праз расшыфроўку refresh-токенаў метадам DPAPI. Час пераключэння — каля трох секунд. |
| `key_vault` | Здымкі актыўных API-ключоў у выглядзе профіляў. Экспарт у пераносны base64-фармат `.ltkeys` для пераносу паміж машынамі. |

### 3.5 Абыход Denuvo (Tokeer)

Для трыццаці двух гульняў, якія выпускаюць абаронены выканальны файл разам з `tokeer_launcher.exe`, выконваецца аўтаматычны запіс Steam launch options у `localconfig.vdf` указанага карыстальніка. Пералік гульняў уключае Pragmata, Resident Evil Requiem, MGSV: TPP, Hogwarts Legacy, Persona 5 Royal, Stellar Blade, Mortal Kombat 1 і іншыя сучасныя тайтлы.

### 3.6 Шматмашынная сінхранізацыя

Стан комплексу сінхранізуецца паміж некалькімі ўсталяваннямі праз адзін з двух механізмаў:

- **Git.** Адвольны выдалены рэпазіторый (прыватны GitHub/GitLab/Codeberg).
- **Папка.** Лакальны шлях, сеткавы дыск або каталог пад наглядам Syncthing. Люстэркаванне па змесціве (SHA-256).

Сінхранізуецца: `.lua`-скрыпты, профілі ключоў, канфігурацыя Sentinel, ланцуг крыніц, па запыце — журнал загрузак.

### 3.7 Міграцыя крэкаў

Сканаванне ўсталяваных гульняў на наяўнасць сігнатур васьмі сямействаў: Goldberg, CODEX/CPY, CreamAPI, ALI213, UnSteam, RUNE, абагульненыя загрузчыкі Steam API, проксі-перахопы DLL.

Міграцыя выконваецца ў рэжыме *dry-run* па змаўчанні. Пры пацвярджэнні файлы перамяшчаюцца ў `<гульня>/_luatools_migration_<пазнака-часу>/`. Знішчэнне зыходных дадзеных не выконваецца ніколі.

### 3.8 Профілі на гульню

Для кожнай гульні захоўваюцца іменаваныя канфігурацыі, якія ўключаюць змесціва `.lua`-скрыпта і параметры запуску. Пераключэнне паміж, напрыклад, *«Persona 5 + Tokeer»* і *«Persona 5 vanilla»* выконваецца адным клікам.

### 3.9 Workshop

Падпіскі карыстальніка ў Steam Workshop чытаюцца з `localconfig.vdf`. Для кожнага падпісанага прадмета праз публічны пункт `ISteamRemoteStorage/GetPublishedFileDetails` атрымліваюцца метададзеныя і URL прамой загрузкі. Загрузка выконваецца напрамую — у абыход Steam-кліента.

### 3.10 Маніторынг дасягненняў *(толькі чытанне)*

Дашборд прагрэсу дасягненняў па кожнай `.lua`-актываванай гульні. Дадзеныя збіраюцца з:

- схемы Web API (`ISteamUserStats/GetSchemaForGame`) — агульная колькасць дасягненняў;
- лакальнага файла `UserGameStats_<accountId>_<appid>.bin` — лічыльнік выкананых.

Запіс у файлы статыстыкі не выконваецца. Падсістэма свядома рэалізавана толькі ў рэжыме чытання — мадыфікацыя публічнай статыстыкі дасягненняў супярэчыць палітыцы Steam.

---

## 4. Сістэмныя патрабаванні

| Кампанент | Патрабаванне |
|---|---|
| АС | Windows 10 / 11 (x64) |
| Платформа | Millennium 2.35+ |
| Python | пастаўляецца з Millennium |
| Сетка | TCP-выходны: HTTPS да `huggingface.co`, `api.steampowered.com`, `api.steamcmd.net`, `github.com`, выбраныя прэміум-крыніцы |
| Апцыянальна | 7-Zip або WinRAR (для распакоўкі RAR/7Z-выпраўленняў); Git (для сінхранізацыі праз рэпазіторый) |

---

## 5. Усталяванне

1. Распакаваць архіў у `<Steam>\plugins\luatools\` (напрыклад, `D:\Steam\plugins\luatools\`).
2. Перазапусціць Steam-кліент.
3. Уключыць плагін: **Steam → Millennium → Plugins → LuaTools Ultimate**.

---

## 6. Парады па бяспецы

- **Steam павінен быць выключаны** перад любой аперацыяй, якая змяняе `userdata/`, `localconfig.vdf` або `loginusers.vdf`.
- **Рэзервовыя копіі ствараюцца аўтаматычна** перад кожнай дэструктыўнай аперацыяй. Іменаванне: `*.bak-<пазнака-часу>` або `*.presync-<пазнака-часу>`.
- **DPAPI-токены чытаюцца, але не змяняюцца.** Пераключэнне акаўнта аперуе толькі паказальнікам `MostRecent` у `loginusers.vdf`.
- **Аўтавыпраўленне `.lua` зваротнае.** Пашкоджаныя радкі не выдаляюцца — яны каменціруюцца з відавочнай пазнакай `--LUATOOLS_AUTOFIXED:`.

---

## 7. Пералік IPC-кропак

Гл. файл `backend/main.py`. Сціслы пералік найбольш ужывальных:

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

## 8. Падзякі

| Крыніца | Уклад |
|---|---|
| **madoiscool** | арыгінальны `ltsteamplugin` |
| **sigmachan** | мадыфікаваны форк (Ryuu/DepotBox/тэмы) |
| **clemdotla** | `steamtools-collection` — логіка аўдыту і сінхранізацыі, партаваная з Lua на Python для Windows |
| **RaiSantos** | `lt_api_links` — пералік сумяшчальнасці з Tokeer, `Devuvo.ps1`, HuggingFace-індэкс выпраўленняў, ланцуг маніфестаў, абнаўленне бібліятэкі Steam |
| **RobiZkt** | `Steam-Token-Grabber` — рэалізацыя DPAPI для пераключэння акаўнтаў |
| **супольнасць SteamTokenDumper** | база дадзеных Depot-ідэнтыфікатараў |

---

## 9. Прынцып неагітацыі

Праграмны комплекс не змяшчае палітычных элементаў аздаблення. Палітра тэмы па змаўчанні заснавана на кліматычных умовах паўночна-заходняга рэгіёна: чыстае неба над Фінскім залівам, белыя ночы. Любыя іншыя асацыяцыі застаюцца на баку чытача.

---

*Тэхнічныя тэрміны прыведзены ў агульнапрынятай англамоўнай форме для ўніфікацыі пошуку коду паміж мовамі.*

---

<a id="fi"></a>
## Suomi

**Versio 9.0.7**

> *Made in Ingria by Free People*  
> *Tehty Inkerissä vapaiden ihmisten toimesta*  
> 59°57′N 30°19′E

> 📄 Muut kielet: [Русский](#ru) · [English (US)](#en) · [Українська](#uk) · [Беларуская](#be)
>
> **Click a language above to jump to that section in the same file.**

---

## 1. Tarkoitus

**LuaTools Ultimate** on Millennium-alustan liitännäinen Steam-asiakasohjelmaan. Se aktivoi pelejä SteamTools-tyylisten `.lua`-komentosarjojen avulla.

Ohjelmisto tarjoaa:

- aktivointikomentosarjojen haun yhdeksän lähteen ketjusta;
- depot-manifestien välimuistin eheyden ylläpidon ja vioittuneiden tietueiden automaattisen korjauksen;
- useiden käyttäjätilien hallinnan ilman asiakasohjelman uudelleenkäynnistystä;
- Tokeer-käynnistimien määrityksen Denuvo-suojatuille peleille;
- asennetun pelikirjaston tilan taustaseurannan.

Ohjelmistorunko on toteutettu Pythonilla (taustajärjestelmä) ja JavaScriptillä (käyttöliittymä). Erillistä käännösvaihetta ei tarvita.

---

## 2. Rakenne

```
ltsteamplugin-ultimate/
├── plugin.json                     Millennium-manifesti
├── README.md / .ru.md / .uk.md / .be.md / .fi.md
├── CLAUDE.md                       kehityskonteksti
├── SENTINEL_v9.md                  Sentinelin suunnitteludokumentti
│
├── backend/
│   ├── main.py                     sisääntulopiste, IPC-kääreet
│   │
│   ├── ── Lataus ja aktivointi ──
│   ├── downloads.py                yhdeksän lähteen ketju
│   ├── batch.py                    rinnakkainen latausjono
│   ├── source_chain.py             käyttäjän järjestämä lähdeketju
│   ├── history.py                  SQLite-loki, lähdekohtainen tilasto
│   ├── custom_apis.py              käyttäjän omat lähteet
│   │
│   ├── ── Korjaukset ──
│   ├── fixes.py                    HuggingFace-indeksi, RAR/7Z, LFS
│   ├── cloud_fix.py                online-korjausten latain
│   ├── steamtools.py               auditointi, välimuistin korjaus
│   │
│   ├── ── Käyttäjätilit (v8.4–8.5) ──
│   ├── account_transfer.py         userdata-kansion kopiointi
│   ├── account_switch.py           DPAPI-purku, tilin vaihto
│   ├── tokeer_launcher.py          Denuvo-ohitus Tokeerilla
│   ├── key_vault.py                Ryuu/DepotBox/Morrenus-avainprofiilit
│   │
│   ├── ── Automaatio v9.0 ──
│   ├── sentinel.py                 taustavalvoja
│   ├── sentinel_worker.py          itsenäinen työprosessi
│   ├── sentinel_service.py         Windows-ajastetun tehtävän asentaja
│   ├── sync_engine.py              koneiden välinen synkronointi
│   ├── crack_migrator.py           vanhojen krakkausten tunnistus
│   ├── profiles.py                 pelikohtaiset kokoonpanot
│   ├── workshop_manager.py         Steam Workshop -tilausten hallinta
│   ├── achievement_watch.py        saavutusten seuranta (vain luku)
│   │
│   ├── ── Infrastruktuuri ──
│   ├── settings/                   asetusten skeema ja tallennus
│   ├── steam_utils.py              VDF-jäsennin, asennuspolun haku
│   ├── steam_version.py            Steam-prosessin tunnistus
│   ├── http_client.py              jaettu httpx-asiakas
│   ├── auto_update.py              GitHub-julkaisujen seuranta
│   ├── donate_keys.py              7 vuorokauden kaksoiskappalevälimuisti
│   ├── events.py                   webhook-koukut (Discord, ntfy.sh)
│   ├── mod_system.py               käyttäjämodien latain
│   ├── security.py                 ZIP-tarkistus, polkusuojaus
│   ├── paths.py                    Windows 11 -polkujen ratkaisu
│   ├── logger.py
│   └── locales/                    yli 30 kielen käännökset
│
├── public/
│   ├── luatools.js                 käyttöliittymä (~8200 riviä)
│   ├── steamdb-webkit.css          SteamDB-integraatio
│   ├── luatools-icon.png
│   └── themes/                     12 teemaa
│       └── ingria.css              oletusteema
│
├── mods/                           käyttäjän .lua-modit
├── scripts/                        PowerShell-apuskriptit
└── .millennium/Dist/               käännetty käyttöliittymäpaketti
```

---

## 3. Toiminnot

### 3.1 Lähdeketju

Aktivointikomentosarjat haetaan kyselemällä yhdeksää lähdettä tärkeysjärjestyksessä:

```
Paikallinen kansio → TwentyTwo Cloud → Ryuu Premium →
DepotBox Premium → ManifestHub API → Custom APIs →
Free APIs → SLStools Fallbacks → GitHub-arkistot
```

Kolmen peräkkäisen *connection refused* -virheen jälkeen ketju keskeytetään. Tämä estää kaskadimaisen virheen verkon ollessa poissa käytöstä.

### 3.2 Depot-välimuistin korjaus

Suoritetaan neljässä vaiheessa:

1. **Kartoitus.** Jokainen `.manifest`-tiedosto luokitellaan kelvolliseksi, vioittuneeksi, nollatavuiseksi tai orvoksi.
2. **Lataus.** Puuttuvat ja vioittuneet manifestit haetaan uudelleen peilipalvelimilta GitHub → Morrenus → ManifestHub.
3. **Siivous.** Tyhjät tiedostot poistetaan, vioittuneet korvataan, vanhentuneet orvot poistetaan.
4. **Lua-korjaus** *(valinnainen).* Syntaktisesti virheelliset rivit kommentoidaan merkinnällä `--LUATOOLS_AUTOFIXED:`, mikä tekee toiminnosta peruutettavan.

Esikatselutila on käytettävissä ennen jokaista tuhoavaa toimenpidettä.

### 3.3 Sentinel — taustaseuranta

Ohjelmademoni, joka suoritetaan joko:

- säikeenä liitännäisprosessin sisällä (oletus), tai
- itsenäisenä prosessina **Windowsin ajastetun tehtävän** kautta (`schtasks.exe /SC ONLOGON`, ei UAC:ia).

Demonin toiminnot:

- `steamapps/`-kansion seuranta uusien asennusten varalta;
- käyttäjän ilmoittaminen Windowsin ponnahdusviesteillä;
- manifestien vanhentumisen säännöllinen tarkistus `api.steamcmd.net`-rajapinnan kautta (oletus: 24 tunnin pelikohtainen tarkistusväli);
- ohitettujen pelien luettelo ja ilmoituskohtaiset aikakatkaisut.

### 3.4 Käyttäjätilit

| Osajärjestelmä | Tarkoitus |
|---|---|
| `account_transfer` | Kopioi `userdata/<accountId>/<appid>/` kahden oman tilin välillä Denuvo-aktivointitunnusten tai pilvitallennusten siirtämiseksi. |
| `account_switch` | Käynnistää Steamin uudelleen valitulle tilille kirjautuneena. Purkaa tallennetut refresh-tunnukset DPAPI-menetelmällä. Vaihto kestää noin kolme sekuntia. |
| `key_vault` | Tallentaa aktiiviset API-avaimet nimettyinä profiileina. Vie kannettavaan base64-muotoon `.ltkeys`. |

### 3.5 Denuvo-ohitus (Tokeer)

Kolmellekymmenelle kahdelle Denuvo-suojatulle pelille, jotka toimitetaan `tokeer_launcher.exe`-tiedoston kanssa, kirjoitetaan automaattisesti Steamin käynnistysasetukset valitun käyttäjän `localconfig.vdf`-tiedostoon. Luetteloon kuuluvat muun muassa Pragmata, Resident Evil Requiem, MGSV: TPP, Hogwarts Legacy, Persona 5 Royal, Stellar Blade ja Mortal Kombat 1.

### 3.6 Koneiden välinen synkronointi

Ohjelmiston tila synkronoidaan usean asennuksen välillä kahdella mekanismilla:

- **Git.** Mikä tahansa yksityinen etäarkisto (GitHub, GitLab, Codeberg).
- **Kansio.** Paikallinen polku, verkkoasema tai Syncthing-valvottu hakemisto. Peilaus sisällön mukaan (SHA-256).

Synkronoidaan: `.lua`-komentosarjat, avainprofiilit, Sentinelin kokoonpano, lähdeketju, pyydettäessä latausloki. Steamin asennuspolut ja konekohtaiset välimuistit pysyvät paikallisina.

### 3.7 Krakkausten siirto

Asennettujen pelien kartoitus kahdeksan krakkausperheen tunnisteiden varalta: Goldberg, CODEX/CPY, CreamAPI, ALI213, UnSteam, RUNE, yleiset Steam API -lataimet, DLL-välityskaappaukset.

Siirto suoritetaan oletuksena *dry-run* -tilassa. Vahvistettaessa tiedostot siirretään hakemistoon `<peli>/_luatools_migration_<aikaleima>/`. Alkuperäisiä tiedostoja ei koskaan poisteta.

### 3.8 Pelikohtaiset profiilit

Jokaiselle pelille voidaan tallentaa useita nimettyjä kokoonpanoja, joista kukin sisältää `.lua`-komentosarjan sisällön ja käynnistysasetukset. Vaihto esimerkiksi kokoonpanojen *»Persona 5 + Tokeer»* ja *»Persona 5 vanilla»* välillä tapahtuu yhdellä napsautuksella.

### 3.9 Workshop

Käyttäjän Steam Workshop -tilaukset luetaan `localconfig.vdf`-tiedostosta. Jokaiselle tilatulle kohteelle haetaan metatiedot ja suora latausosoite julkisen `ISteamRemoteStorage/GetPublishedFileDetails`-rajapinnan kautta. Lataus tapahtuu suoraan Steam-asiakasohjelman ohi.

### 3.10 Saavutusten seuranta *(vain luku)*

Koontinäyttö, joka esittää saavutusten edistymisen kunkin `.lua`-aktivoidun pelin osalta. Tietolähteet:

- Web API -skeema (`ISteamUserStats/GetSchemaForGame`) — saavutusten kokonaismäärä;
- paikallinen tiedosto `UserGameStats_<accountId>_<appid>.bin` — avattujen laskuri.

Tilastotiedostoihin ei kirjoiteta. Osajärjestelmä on tarkoituksellisesti toteutettu vain luku -tilassa — julkisten saavutustilastojen muokkaaminen rikkoo Steamin käyttöehtoja.

---

## 4. Järjestelmävaatimukset

| Komponentti | Vaatimus |
|---|---|
| Käyttöjärjestelmä | Windows 10 / 11 (x64) |
| Alusta | Millennium 2.35+ |
| Python | toimitetaan Millenniumin mukana |
| Verkko | Lähtevä HTTPS osoitteisiin `huggingface.co`, `api.steampowered.com`, `api.steamcmd.net`, `github.com` sekä valitut premium-lähteet |
| Valinnainen | 7-Zip tai WinRAR (RAR/7Z-korjausten purkuun), Git (arkistopohjaiseen synkronointiin) |

---

## 5. Asennus

1. Pura arkisto hakemistoon `<Steam>\plugins\luatools\` (esimerkiksi `D:\Steam\plugins\luatools\`).
2. Käynnistä Steam uudelleen.
3. Ota liitännäinen käyttöön: **Steam → Millennium → Plugins → LuaTools Ultimate**.

---

## 6. Turvallisuusohjeet

- **Steamin on oltava suljettuna** ennen jokaista toimenpidettä, joka kirjoittaa tiedostoihin `userdata/`, `localconfig.vdf` tai `loginusers.vdf`.
- **Varmuuskopiot luodaan automaattisesti** ennen jokaista tuhoavaa toimenpidettä. Nimeämiskäytäntö: `*.bak-<aikaleima>` tai `*.presync-<aikaleima>`.
- **DPAPI-tunnukset luetaan, mutta niitä ei muuteta.** Tilin vaihto käsittelee vain `loginusers.vdf`-tiedoston `MostRecent`-osoitinta.
- **Lua-automaattikorjaus on peruutettavissa.** Virheellisiä rivejä ei poisteta — ne kommentoidaan selkeällä merkinnällä `--LUATOOLS_AUTOFIXED:`.

---

## 7. IPC-rajapinta

Katso tiedosto `backend/main.py`. Yleisimmin käytetyt:

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

## 8. Kiitokset

| Lähde | Panos |
|---|---|
| **madoiscool** | alkuperäinen `ltsteamplugin` |
| **sigmachan** | muokattu haarautuma (Ryuu/DepotBox/teemat) |
| **clemdotla** | `steamtools-collection` — auditointi- ja synkronointilogiikka, siirretty Luasta Pythoniin Windowsille |
| **RaiSantos** | `lt_api_links` — Tokeer-yhteensopivuusluettelo, `Devuvo.ps1`, HuggingFace-korjausindeksi, manifestiketju |
| **RobiZkt** | `Steam-Token-Grabber` — DPAPI-toteutus tilin vaihtoon |
| **SteamTokenDumper-yhteisö** | depot-tunnusten tietokanta |

---

## 9. Aatteellisuuden hylkääminen

Ohjelmisto ei sisällä poliittisia tunnuksia, lippukuvioita eikä iskulauseita. Oletusteeman väripaletti perustuu luoteisalueen ilmastoon: kirkas talvitaivas Suomenlahden yllä, valoisten öiden pehmeä hehku. Kaikki muut mielleyhtymät jäävät lukijan omiksi.

---

*Tekniset termit esitetään vakiintuneessa englanninkielisessä muodossa, jotta koodihaku pysyy yhtenäisenä kielten välillä.*

---
