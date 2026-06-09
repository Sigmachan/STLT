# Changelog

## 10.2.4 — resource-leak cleanup + Millennium 3.0 fallback surface

Addresses an external Millennium 3.0 review (both findings verified against the
code before acting):

- **Unclosed file handles (real defects).** Reproduced with
  `python3 -W error::ResourceWarning`. Fixed the two shipped-code leaks
  (`accela_launcher.py` launcher-path read, `downloads.py` local-lua read) and
  the 31 unclosed `open()` one-liners across the test suite. The strict
  ResourceWarning run is now **clean** (was: many `unclosed file` traces).
- **Standalone fallback API surface.** The Millennium fallback (used in bridge
  mode) now exposes the full documented 3.0 surface — `cmp_version` (proper
  -1/0/1), `get_install_path`, `is_plugin_enabled`, `remove_browser_module`
  (returns the real `bool`) — and the standalone shim registers them. Note:
  nothing in the backend currently calls these, so this is contract
  future-proofing, not a live-bug fix.
- Regression test (`test_platform_bridge_api`) pins the surface + `cmp_version`
  semantics so the stubs can't drift. Suite: **90 green.**

## 10.2.3 — auto-update points at your fork, downgrade-proof

Re-enabled the self-updater against **Sigmachan/STLT** (your repo) with hard
guarantees so it can never hurt a fork that runs ahead of its releases:

- **Downgrade-proof comparison** (`is_newer_version`): updates fire only when a
  release is STRICTLY newer on normalized major.minor.patch. An older release
  (your usual case — local build ahead of GitHub), an equal version, a
  pre-release suffix on the same version, or a blank/garbage tag all resolve to
  "not newer" → no action. It will normally report up-to-date and do nothing.
- **No upstream conflation.** Removed both `luatools.vercel.app` fallbacks — the
  API-read proxy (served *upstream's* latest) and the download proxy (served a
  *different* codebase for your tag). The updater now uses only the real GitHub
  API for your repo and only a real attached release asset (`STLT.zip`).
- To publish an update: cut a release tagged ≥ the version and attach `STLT.zip`.
  To disable entirely: blank owner/repo in `update.json`.
- 6 tests covering the downgrade scenarios + config. Suite: **86 green.**

## 10.2.2 — safety: disable the self-updater's foreign-repo pointer

The auto-updater was configured to check `madoiscool/ltsteamplugin` (the
upstream this fork descends from). Since this fork's version (10.x) is ahead of
that repo, it read "up-to-date" — but if that repo ever tagged a higher version,
the updater could have **overwritten this fork with a different codebase** on the
next restart.

- `update.json` owner/repo are now **blank**, making the updater a safe, silent
  no-op that can never pull another repo's releases. A `_comment` documents how
  to re-enable it against *your own* fork. Missing-repo log softened from a
  warning to an intentional "disabled" message.
- Guard test ensures the updater can't silently regain a foreign-repo pointer.
  Suite: **80 green.**

## 10.2.1 — cross-platform fix: Steam-language detection on Linux/macOS

Confirmed from a live Linux run that the Millennium 3.0 Lua-backend + Python-HTTP
-bridge architecture works end-to-end (bridge binds :38495, IPC live) — the
sandbox does NOT block the spawn. The one cross-platform wart in the logs:

- **`No module named 'winreg'` on Linux.** `_detect_steam_language()` always
  tried the Windows registry. Now it gates `winreg` behind `os.name == "nt"` and
  on Linux/macOS reads Steam's UI language from `registry.vdf` instead — real
  parity, no spurious warning. (paths.py's registry lookup was already gated.)
- Guard test added. Suite: **79 green.**

## 10.2.0 — Millennium 3.0 hardening + ACCELA integration fixes

**Verified against the real Millennium 3.0 contract** (official Lua API docs):
the Lua-backend + Python-HTTP-bridge architecture is correct — Python backends
are deprecated in 3.0, so `main.lua` (using `require("millennium")`,
`steam_path()`, `add_browser_js()` resolved from steamui, `ready()` inside
`on_load`) is the right design, not a workaround. No rearchitecture needed.

Millennium 3.0 robustness:
- **Bridge startup-race fix.** On first run, `main.lua` builds a venv and
  pip-installs before the Python server binds :38495; calls during that window
  used to fail silently. The shim now retries — but ONLY connection-level
  failures (request never reached the server, so safe to retry even for
  non-idempotent methods). HTTP/RPC errors that the server *answered* are never
  retried (no double-fire). Up to 5 attempts with backoff.

ACCELA integration fixes (audit of the 10.1.0 restore):
- **Temp-file leak fixed.** `run_with_zip` copied the bundle to `/tmp` with
  `delete=False` and never cleaned up. Each run now sweeps `luatools_accela_*.zip`
  copies older than an hour — self-maintaining, race-free (ACCELA runs async).
- **`GetAccelaInfo` / `SetAccelaPath` IPCs** — surface whether ACCELA is found
  and where, and let you point at its `run.sh` when auto-detection misses it.
- 5 new tests (sweep, status, bridge-shim guards). Suite: **77 green.**

## 10.1.1 — perf: setup gate off the network-critical path — perf: setup gate off the network-critical path

- The on-load setup check (`GetSetupState`) ran a full health report including a
  ~6s-timeout network probe, on the UI-init path. Network reachability is only a
  *warning* (it never changes the ready/blocker verdict), so it had no business
  gating interface readiness. Added a `quick=True` health path that skips the
  network probe; the on-load gate uses it, while the full Health Scan keeps it.
  Removes a potential multi-second stall on every load. (+1 test → 72.)

## 10.1.0 — ACCELA downloader restored (download-path correction)

**The important fix.** Upstream LuaToolsLinux downloads games by handing the
manifest/lua bundle to **ACCELA's `run.sh`** — ACCELA is the actual downloader.
STLT had dropped that: its install step only wrote the `.lua` into `stplug-in`
and relied on SLSsteam interception, so on ACCELA setups downloads never
started (and no restart helped, because restart was never the mechanism).

- **Restored ACCELA invocation.** After the bundle is downloaded and the `.lua`
  installed, if ACCELA is present the bundle is now handed to it so it downloads
  the game — the proven upstream mechanism. The `.lua` install is kept too, so
  SLSsteam users are unaffected.
- **Faithful env handling** (`accela_launcher.py`): strips
  `LD_LIBRARY_PATH` / `LD_PRELOAD` / `STEAM_RUNTIME` before launching ACCELA, as
  upstream learned — otherwise its Qt6 runtime crashes against Steam's libs.
  ACCELA is given its own copy of the bundle so cleanup can't race it; launched
  non-blocking so activation stays responsive.
- **Configurable launcher path** (`data/launcher_path.txt`), with auto-detection
  of `~/.local/share/ACCELA/run.sh`.
- **Auto-pilot corrected.** When ACCELA is installed, auto-finalize no longer
  fires `steam://install` (which targeted the SLSsteam theory and would pop a
  redundant dialog); it reports that ACCELA is downloading. `steam://install`
  remains only for SLSsteam-only setups.
- 8 new tests (launcher path/env/invocation + the ACCELA-vs-SLSsteam branch).
  Suite: **71 green.**

> Note: this corrects an earlier assumption that SLSsteam + `steam://install`
> drove downloads. The mechanism that demonstrably works upstream is ACCELA;
> this release puts it back.

## 10.0.0 — "It Just Works"

The release where the plugin gets out of your way. A new user installs it,
searches a game, and it downloads — no checklist, no restart, no guesswork.
Built as a series of verified increments (9.9.0-rc1…rc4), each shipped green.

### The happy path is now automatic
- **Auto-pilot.** Finishing an activation now applies the safe setup it needs
  and starts the download on the running Steam — no restart. It runs on *every*
  completion, whether or not the progress popup is open, so a download never
  silently fails to start because you looked away.
- **No-restart downloads.** Activations download on a running Steam by handing
  `steam://install/<appid>` to it (SLSsteam already serves ownership + depot
  keys live from the `.lua`). The stable protocol is used rather than a
  fragile reverse-engineered API.
- **First-run setup assistant.** On a fresh setup, a calm one-screen flow
  appears only when there's something to do: it auto-applies the safe fixes
  ("Set it up for me") and shows the single manual step (install/inject
  SLSsteam) with a copyable command — ending in "You're all set." If you're
  already good, it doesn't interrupt.
- **Self-healing.** On load, the plugin quietly re-applies the setup you already
  established if it regressed (e.g. PlayNotOwnedGames got reset), with a brief
  notice only when it actually fixes something.

### Calmer interface
- **Progressive disclosure.** The long SteamTools menu now shows just the
  primary actions (Quick Dashboard, Health Scan, Smart Restart) and folds the
  ~17 advanced tools behind one "Advanced tools" toggle. Nothing was removed.
- **Health Scan** now leads with a "System setup" section (every download
  prerequisite, with one-click fixes) above the per-game audit.

### Reliability (the part you don't see)
- **Diagnostic engine** (`health.py`) turns silent "won't download" failures
  into a severity-ranked checklist with actionable fixes.
- **Regression test suite** (stdlib `unittest`, zero dependencies): 60+ tests
  codifying every download bug ever fixed here as a guard — the `.lua` contract
  (golden fixtures, no stub filter, ManifestHub key-defer), the no-`StateFlags=4`
  download model, the canonical IPC surface, and the auto-pilot/self-heal flows.
  Run: `bash run_tests.sh`.

### The safety line (what we deliberately do NOT automate)
The automation is only trustworthy because it refuses to touch the things that
can brick Steam: it never auto-edits **steam.sh**, **config.vdf**, or
**steamui/index.html**. Those changes stay user-confirmed. Self-heal touches
only SLSsteam's own config and plugin-owned directories.

### Earlier fixes folded into this line (pre-10.0)
- Fixed the core "games don't download" bug: stopped stripping keyless
  `addappid()` ownership/DLC lines, stopped writing a "fully installed"
  (`StateFlags=4`) ACF, and stopped clobbering `config.vdf` keys while Steam runs.
- ManifestHub API path no longer finalizes a keyless activation; it defers to a
  keyed source so depots can actually decrypt.

---

_Upgrade is safe: existing settings and activations are preserved; new
behaviour is on by default and overridable. Per aspera ad astra._
