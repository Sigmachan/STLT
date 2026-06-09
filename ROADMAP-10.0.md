# LuaTools Ultimate 10.0 — "It Just Works"

> The release where the plugin disappears. A new user installs it, searches a
> game, and it downloads — zero ritual, zero checklist, zero restart. Complexity
> is the builder's burden to hide, not the user's to manage. Apple philosophy,
> applied to a Steam plugin.

This is **evolution, not demolition.** No rewrite. We keep the ~50 modules of
hard-won logic and the test suite that guards it; 10.0 is about *how it feels*,
not starting over.

---

## Three pillars

1. **Effortless** — the happy path needs no decisions. Onboarding, auto-pilot,
   self-healing defaults.
2. **Calm** — progressive disclosure. The 15 panels still exist, but the menu
   breathes; advanced power is one click away, not in your face.
3. **Trustworthy** — it doesn't break silently. Every load-bearing path changed
   in 10.0 is covered by tests; the health engine surfaces anything it can't fix.

The hardest pillar is restraint: "it just works" is only safe because we
*refuse* to auto-do the dangerous things (steam.sh, config.vdf).

---

## Workstreams (priority-ordered)

### P0 — First-run setup assistant ("You're all set")
The Apple setup-assistant moment. On first load, silently run the health engine.
If everything's good → a single calm "You're all set." If a prerequisite is
missing → one guided flow: auto-enable PlayNotOwnedGames, and for the one step
that can't be automated safely (SLSsteam injection) show exactly one clear
instruction. Ends with a confirmed-ready state, never a wall of checkboxes.
- **Reuses:** `GetLinuxHealthReport`, `auto_finalize` fix logic.
- **New:** guided overlay + a "first-run seen" flag (persisted in settings).
- **Risk:** medium (new overlay, first-run detection). **Effort:** medium.
- **Done when:** fresh install → one guided flow → games download with no
  further config.

### P0 — Auto-pilot as the spine
Make `AutoFinalizeActivation` the single canonical post-activation path, and
funnel *every* activation entry point through it (menu add, library button,
direct-URL add). Remove "restart Steam" prompts everywhere auto-pilot supersedes
them — keeping them only where config.vdf genuinely needs Steam closed.
- **Risk:** medium (several call sites). **Effort:** medium.
- **Done when:** no path tells you to restart unless it truly must.

### P1 — Menu consolidation / progressive disclosure
Primary surface shrinks to the few things people actually use (Add Game, Health,
Settings). Everything else (Sentinel, Sync, Migrator, KeyVault, Tokeer, Repair,
Achievements, …) folds under one **Advanced / Tools** group. Additive grouping —
**no feature is removed**, just reorganized.
- **Risk:** medium-high (menu markup lives in the 9000-line JS — handle like the
  health-panel change: study patterns, mirror them, verify the seam).
- **Effort:** medium.
- **Done when:** top-level menu shows ≤4 primary items; advanced tools one click
  away.

### P1 — Self-healing defaults
What can fix itself, should — quietly. UI self-heal runs on load if the marker's
missing. Depot-cache corruption is offered a fix on detection instead of being
buried in a panel. Silent unless action is needed; never nags.
- **Risk:** low-medium. **Effort:** low-medium.
- **Done when:** common breakages self-repair or prompt exactly once, clearly.

### P1 — Trust floor: expand test coverage
A major version raises the safety floor. Add regression tests for the source-
chain selection logic, settings read/write, and the auto-pilot call-site funnel
before/while refactoring it.
- **Risk:** low. **Effort:** medium.
- **Done when:** every load-bearing path touched in 10.0 is covered; suite green.

### P2 — Calm visual + copy pass
Consistent icons, restrained palette, plain-language messages ("Downloading — no
restart needed," not jargon). Not a redesign — coherence.
- **Risk:** low but broad (CSS/strings). **Effort:** medium.
- **Done when:** copy and iconography are consistent across primary surfaces.

### P2 — Release hygiene
CHANGELOG, a one-time "What's new in 10.0" note, version bump, and migration
safety (existing settings/defaults preserved — nobody's config breaks on upgrade).
- **Risk:** low. **Effort:** low.

---

## Explicitly OUT of 10.0 (saying no is the point)

- No rewrite from scratch.
- No new download sources / providers (feature creep).
- No auto-editing of `steam.sh` or `config.vdf` — the safety line holds.
- No changes to core download-chain logic except *adding tests around it*.
- No new platform support.

---

## Sequence

1. **Trust floor first** — tests for what we're about to touch, so refactors are safe.
2. **Auto-pilot spine** — funnel all activation paths through `AutoFinalize`.
3. **First-run assistant.**
4. **Menu consolidation.**
5. **Self-healing defaults.**
6. **Calm pass + release hygiene.**
7. Tag **10.0**.

Each step ships as its own tested build (9.9-rc1, rc2, …) so nothing big lands
unverified — same cadence we've used all along.

---

## Definition of done (10.0 acceptance)

- A brand-new user, post-install, can search → activate → download with **zero
  manual config and no restart** — or gets **exactly one** clear instruction for
  the single un-automatable step.
- Top-level menu: **≤4 primary items.**
- Every code path changed in 10.0 is covered by the test suite; **suite green.**
- **No silent failure modes** remain on the happy path — the health engine
  surfaces anything it can't auto-fix.

## Progress

- **9.9.0-rc1** — Step 1 (trust floor) + Step 2 (auto-pilot spine) ✅
  - Auto-pilot now runs on **every** activation completion, not only when the
    popup is open (download starts whether or not you're watching); once-per-appid
    guarded; renders into the popup when visible, else a toast.
  - Trust-floor regression guards added: canonical IPC surface (`test_ipc_surface`),
    frontend spine wired + unconditional (`test_frontend_spine`), settings read
    (`test_live_apply`). Suite: **50 green.**
- Next: Step 3 (first-run setup assistant).
- **9.9.0-rc2** — Step 3 (first-run setup assistant) ✅
  - On load, if it's a first run or something is blocking downloads, a calm
    one-screen assistant appears: it auto-applies the safe fixes ("Set it up for
    me" → enables PlayNotOwnedGames, self-heals UI) and shows the single manual
    step (install/inject SLSsteam) with a copyable command — then "You're all set."
  - Backend `setup_assistant` (marker-file "seen" flag, auto-fix vs blocker
    classification) + `GetSetupState` / `RunSetup` / `MarkSetupSeen` IPCs.
  - Guards: `test_setup_assistant` (6) + frontend wiring guard. Suite: **57 green.**
- Next: Step 4 (menu consolidation / progressive disclosure).
- **9.9.0-rc3** — Step 4 (menu consolidation / progressive disclosure) ✅
  - The long SteamTools list (≈17 tools) now collapses behind one **"Advanced
    tools (N)"** toggle; only the primary actions (Quick Dashboard, Health Scan,
    Smart Restart) stay visible. Pure DOM visibility on the flex column — no
    reparenting — wrapped in try/catch so a failure leaves the full menu intact.
  - Guard: `test_frontend_spine::test_menu_consolidation_present`. Suite: **58 green.**
- Next: Step 5 (self-healing defaults) → Step 6 (calm pass + hygiene) → tag 10.0.
- **9.9.0-rc4** — Step 5 (self-healing defaults) ✅
  - On load, a quiet `SelfHeal` runs *before* the setup check: it re-applies the
    state you already established if it regressed (re-enables PlayNotOwnedGames,
    recreates the stplug-in dir). A brief toast appears only when it actually
    fixed something — never nags. **No-op until setup has been completed once.**
  - Held the safety line: self-heal touches only SLSsteam's own config + plugin
    dirs, **never** Steam's files (steam.sh/config.vdf/steamui) — those stay
    user-confirmed via the assistant.
  - Guards: 4 `self_heal` tests + frontend wiring guard. Suite: **63 green.**
- Next: Step 6 (calm copy/visual pass + release hygiene) → tag **10.0**.
- **10.0.0** — Step 6 (calm pass + release hygiene) ✅ — **TAGGED** 🎉
  - Calmer first-run: the assistant now only appears when there's something to
    do; if you're already set up it never interrupts (silently remembered).
  - Release hygiene: `CHANGELOG.md`, version → 10.0.0, migration-safe (existing
    settings/activations preserved; new behaviour on-by-default + overridable).
  - Trust floor hardened: IPC surface guard now covers all 11 canonical IPCs
    (incl. the setup-assistant + self-heal ones). Suite: **63 green.**

### Definition of done — met
- Fresh user: search → activate → download, no manual config and no restart, or
  exactly one clear instruction for the un-automatable step. ✅
- Top-level menu ≤4 primary items. ✅
- Every path changed in 10.0 covered by tests; suite green. ✅
- No silent failure modes on the happy path. ✅

_Per aspera ad astra._
