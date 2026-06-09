# Changelog

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
