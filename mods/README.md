# LuaTools Mods

Drop mod folders here. Each mod needs a `manifest.json`:

```json
{
    "id": "my-mod",
    "name": "My Mod",
    "version": "1.0.0",
    "author": "You",
    "description": "What it does",
    "main": "mod.js",
    "style": "style.css",
    "hooks": ["onOverlayOpen", "onDownloadComplete"],
    "dependencies": []
}
```

Compatible with Kite Loader mod format. See API docs:
- `LuaToolsMods.registerMod(def)` — register your mod
- `LuaToolsMods.showToast(msg, ms)` — toast notification
- `LuaToolsMods.createPanel({id, title, content})` — styled panel
- `LuaToolsMods.injectCSS(id, css)` — inject stylesheet
- `LuaToolsMods.getStorage(modId)` — per-mod localStorage wrapper
- `LuaToolsMods.fireHook(name, data)` — trigger lifecycle events

Lifecycle hooks: onOverlayOpen, onOverlayClose, onFixApplied, onFixFailed,
onGameDetected, onSettingsOpen, onDownloadStart, onDownloadComplete, onModsPanel
