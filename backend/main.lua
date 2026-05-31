-- LuaTools Ultimate — Lua bootstrapper (v9.1, cross-platform)
--
-- Runs inside Millennium on BOTH Windows and Linux. Keeps the Python backend
-- intact and launches it as a localhost HTTP bridge. Must never block or throw
-- (would stall Steam startup): every step is pcall-guarded, millennium.ready()
-- is guaranteed, and the backend spawn is fully detached on each OS.
--
-- Spawn differs by platform:
--   Linux:   setsid bash launcher.sh </dev/null &       (.venv/bin/python3)
--   Windows: start "" /b launcher.bat                   (.venv\Scripts\pythonw.exe)
--
-- Adapted from the LuaToolsLinux fork by StarWarsK and geovanygrdt.

local millennium = require("millennium")
local fs = require("fs")
local logger = require("logger")

-- Windows if the path separator is a backslash.
local IS_WINDOWS = (package.config:sub(1, 1) == "\\")

local function log_warn(m) pcall(function() logger:warn("LuaTools: " .. tostring(m)) end) end
local function log_info(m) pcall(function() logger:info("LuaTools: " .. tostring(m)) end) end

local function guard(label, fn)
    local ok, err = pcall(fn)
    if not ok then log_warn(label .. ": " .. tostring(err)) end
    return ok
end

local function write_file(path, content)
    local f = io.open(path, "w")
    if not f then return false end
    f:write(content); f:close()
    return true
end

local function find_plugin_dir()
    local candidates = {}
    if IS_WINDOWS then
        -- Millennium >= 3.0: <Steam>\millennium\plugins ; older: <Steam>\plugins
        local sp = ""
        pcall(function() sp = millennium.steam_path() or "" end)
        if sp ~= "" then
            table.insert(candidates, fs.join(sp, "millennium", "plugins", "luatools"))
            table.insert(candidates, fs.join(sp, "plugins", "luatools"))
        end
        local inst_ok, inst = pcall(function() return millennium.get_install_path() end)
        if inst_ok and inst then
            table.insert(candidates, fs.join(inst, "plugins", "luatools"))
        end
    else
        local home = os.getenv("HOME") or ""
        table.insert(candidates, fs.join(home, ".local", "share", "millennium", "plugins", "luatools"))
        local inst_ok, inst = pcall(function() return millennium.get_install_path() end)
        if inst_ok and inst then
            table.insert(candidates, fs.join(inst, "plugins", "luatools"))
        end
    end
    for _, dir in ipairs(candidates) do
        if fs.exists(fs.join(dir, "public", "luatools.js")) then return dir end
    end
    return candidates[1] or "."
end

local function do_setup()
    local sp = ""
    pcall(function() sp = millennium.steam_path() or "" end)
    if sp ~= "" then
        local steam_path = sp:gsub("[/\\]+$", "")
        local plugin_dir = find_plugin_dir()
        local dest_dir = fs.join(steam_path, "steamui", "LuaTools")
        if not fs.exists(dest_dir) then
            guard("mkdir steamui/LuaTools", function() fs.create_directories(dest_dir) end)
        end
        local assets = {
            { "public/luatools_bridge.js", "luatools_bridge.js" },
            { "public/luatools.js",        "luatools.js" },
            { "public/luatools-icon.png",  "luatools-icon.png" },
            { "public/steamdb-webkit.css", "steamdb-webkit.css" },
        }
        for _, pair in ipairs(assets) do
            local src = fs.join(plugin_dir, pair[1])
            if fs.exists(src) then
                guard("copy " .. pair[2], function()
                    fs.copy(src, fs.join(dest_dir, pair[2]), false)
                end)
            end
        end
        local src_themes = fs.join(plugin_dir, "public", "themes")
        if fs.exists(src_themes) then
            guard("copy themes", function()
                fs.copy_recursive(src_themes, fs.join(dest_dir, "themes"), false)
            end)
        end
    else
        log_warn("steam_path empty; skipping asset copy")
    end

    guard("add_browser_js bridge", function()
        millennium.add_browser_js("LuaTools/luatools_bridge.js")
    end)
    guard("add_browser_js ui", function()
        millennium.add_browser_js("LuaTools/luatools.js")
    end)
end

local function spawn_backend_linux(plugin_dir)
    local venv_dir = fs.join(plugin_dir, ".venv")
    local venv_py  = fs.join(venv_dir, "bin", "python3")
    local bridge   = fs.join(plugin_dir, "backend", "web_bridge_server.py")
    local reqs     = fs.join(plugin_dir, "requirements.txt")
    local launcher = fs.join(plugin_dir, ".luatools_launch.sh")
    local script = table.concat({
        "#!/usr/bin/env bash", "set +e",
        'VENV_PY="' .. venv_py .. '"',
        'BRIDGE="' .. bridge .. '"',
        'REQS="' .. reqs .. '"',
        'PY="$VENV_PY"',
        'if [ ! -x "$VENV_PY" ]; then python3 -m venv "' .. venv_dir .. '" 2>/dev/null; fi',
        'if [ -x "$VENV_PY" ]; then "$VENV_PY" -m pip install --quiet --disable-pip-version-check -r "$REQS" 2>/dev/null; else PY="python3"; fi',
        'exec "$PY" "$BRIDGE"', "",
    }, "\n")
    if not write_file(launcher, script) then log_warn("launcher write failed"); return end
    os.execute("chmod +x '" .. launcher .. "' 2>/dev/null")
    os.execute("setsid bash '" .. launcher .. "' </dev/null >/tmp/luatools_bridge.log 2>&1 &")
    log_info("backend spawned (linux, detached)")
end

local function spawn_backend_windows(plugin_dir)
    local venv_py  = fs.join(plugin_dir, ".venv", "Scripts", "pythonw.exe")
    local venv_pip = fs.join(plugin_dir, ".venv", "Scripts", "python.exe")
    local venv_dir = fs.join(plugin_dir, ".venv")
    local bridge   = fs.join(plugin_dir, "backend", "web_bridge_server.py")
    local reqs     = fs.join(plugin_dir, "requirements.txt")
    local launcher = fs.join(plugin_dir, ".luatools_launch.bat")
    -- %~dp0 = the .bat's own dir. Falls back to system pythonw if venv missing.
    local script = table.concat({
        "@echo off",
        'set "VENV_PY=' .. venv_py .. '"',
        'set "VENV_PIP=' .. venv_pip .. '"',
        'set "BRIDGE=' .. bridge .. '"',
        'if not exist "%VENV_PY%" ( python -m venv "' .. venv_dir .. '" )',
        'if exist "%VENV_PIP%" ( "%VENV_PIP%" -m pip install --quiet --disable-pip-version-check -r "' .. reqs .. '" )',
        'if exist "%VENV_PY%" ( start "" /b "%VENV_PY%" "%BRIDGE%" ) else ( start "" /b pythonw "%BRIDGE%" )',
        "",
    }, "\r\n")
    if not write_file(launcher, script) then log_warn("launcher write failed"); return end
    -- start /b launches detached and returns immediately (no blocking, no window).
    os.execute('start "" /b cmd /c "' .. launcher .. '"')
    log_info("backend spawned (windows, detached)")
end

local function spawn_backend()
    local plugin_dir = find_plugin_dir()
    if IS_WINDOWS then spawn_backend_windows(plugin_dir)
    else spawn_backend_linux(plugin_dir) end
end

local function on_load()
    guard("do_setup", do_setup)
    guard("ready", function() millennium.ready() end)  -- before spawn, always
    guard("spawn_backend", spawn_backend)
    log_info("on_load complete (" .. (IS_WINDOWS and "windows" or "linux") .. ")")
end

local function on_unload()
    pcall(function()
        if IS_WINDOWS then
            os.execute('taskkill /F /FI "WINDOWTITLE eq web_bridge_server*" >nul 2>&1')
            os.execute('wmic process where "commandline like \'%%web_bridge_server.py%%\'" delete >nul 2>&1')
        else
            os.execute("pkill -f web_bridge_server.py 2>/dev/null || true")
        end
    end)
    log_info("unloaded")
end

return { on_load = on_load, on_unload = on_unload }
