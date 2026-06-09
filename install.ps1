# LuaTools Ultimate - Windows installer (v9.1, Millennium 3.0 / Lua build)
#
# Sets up the plugin under Millennium's plugins directory and prepares the
# Python virtual environment at install time, so the first Steam launch is
# fast and the localhost bridge comes up immediately.
#
# Run from the extracted plugin folder:   .\install.ps1
# (If blocked by execution policy:  powershell -ExecutionPolicy Bypass -File .\install.ps1 )
#
# Install flow patterns adapted from the official LuaTools installer.

$ErrorActionPreference = "Stop"
$PluginName = "luatools"

function Info($m) { Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[ OK ] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[FAIL] $m" -ForegroundColor Red; exit 1 }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- Locate Steam via registry ---
$steamPath = $null
foreach ($key in @("HKCU:\Software\Valve\Steam", "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam")) {
    try {
        $val = (Get-ItemProperty -Path $key -ErrorAction Stop)
        if ($val.SteamPath)    { $steamPath = $val.SteamPath; break }
        if ($val.InstallPath)  { $steamPath = $val.InstallPath; break }
    } catch {}
}
if (-not $steamPath) {
    foreach ($p in @("C:\Program Files (x86)\Steam", "C:\Program Files\Steam")) {
        if (Test-Path $p) { $steamPath = $p; break }
    }
}
if (-not $steamPath -or -not (Test-Path $steamPath)) { Fail "Steam installation not found." }
$steamPath = $steamPath -replace '/', '\'
Ok "Steam found: $steamPath"

# --- Determine Millennium plugins directory ---
# Millennium >= 3.0 uses <Steam>\millennium\plugins ; older uses <Steam>\plugins
$pluginsDir = $null
$cand30  = Join-Path $steamPath "millennium\plugins"
$candOld = Join-Path $steamPath "plugins"
if (Test-Path (Join-Path $steamPath "millennium")) {
    $pluginsDir = $cand30
} elseif (Test-Path $candOld) {
    $pluginsDir = $candOld
} else {
    $pluginsDir = $cand30
    Warn "Millennium dir not found. If Millennium isn't installed, run:"
    Warn '  iwr -useb "https://steambrew.app/install.ps1" | iex'
}
New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null
$installDir = Join-Path $pluginsDir $PluginName
Info "Installing to $installDir"

# --- Copy plugin into place (unless already running from there) ---
if ($ScriptDir -ne $installDir) {
    if (Test-Path $installDir) { Remove-Item -Recurse -Force $installDir }
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    Get-ChildItem -Path $ScriptDir -Force | Where-Object {
        $_.Name -notin @('.venv', '__pycache__') -and $_.Extension -ne '.pyc'
    } | Copy-Item -Destination $installDir -Recurse -Force
    Ok "Files copied"
} else {
    Info "Running from install dir; updating in place"
}

# --- Locate Python ---
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try { & $cmd --version *> $null; if ($LASTEXITCODE -eq 0) { $python = $cmd; break } } catch {}
}
if (-not $python) {
    Warn "Python not found on PATH. Install Python 3.10+ from https://python.org"
    Warn "The plugin will try to create the venv at first launch instead."
} else {
    # --- Create venv + install deps at install time ---
    $venvDir = Join-Path $installDir ".venv"
    Info "Creating Python virtual environment..."
    & $python -m venv $venvDir
    $venvPip = Join-Path $venvDir "Scripts\python.exe"
    if (Test-Path $venvPip) {
        Ok "venv created"
        Info "Installing Python requirements (httpx, beautifulsoup4, ruamel.yaml)..."
        & $venvPip -m pip install --quiet --disable-pip-version-check -r (Join-Path $installDir "requirements.txt")
        if ($LASTEXITCODE -eq 0) { Ok "Python requirements installed" }
        else { Warn "pip install failed; bridge may not start until deps are present." }
    } else {
        Warn "venv creation failed; the plugin will fall back to system python at launch."
    }
}

Write-Host ""
Ok "LuaTools Ultimate installed."
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1) (Re)start Steam."
Write-Host "  2) Steam -> menu (top-left) -> Millennium -> Plugins -> enable 'LuaTools Ultimate'."
Write-Host ""
Write-Host "  Bridge log (troubleshooting): %TEMP%\luatools_bridge.log"
