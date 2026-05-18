<#
.SYNOPSIS
    LuaTools Ultimate — Windows 11 Steam Maintenance Helper
.DESCRIPTION
    Standalone PowerShell script for advanced Steam maintenance operations.
    Can be invoked from the plugin backend or run manually.
    Zero dependencies, zero background processes — runs on trigger only.
.NOTES
    All paths resolved from Windows Registry + environment variables.
    No WSL, no bash, no Linux emulation.
#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("CacheInfo","CleanCache","Backup","Restore","FolderStats","VerifyIntegrity")]
    [string]$Action = "CacheInfo",

    [string]$Categories = "",
    [string]$BackupLabel = "",
    [string]$RestoreFile = ""
)

$ErrorActionPreference = "Stop"

# ── Steam Path Resolution ─────────────────────────────────────────────────

function Get-SteamPath {
    # Try HKCU first
    try {
        $reg = Get-ItemProperty -Path "HKCU:\Software\Valve\Steam" -Name "SteamPath" -ErrorAction Stop
        if ($reg.SteamPath -and (Test-Path $reg.SteamPath)) {
            return $reg.SteamPath
        }
    } catch {}

    # Try HKLM
    try {
        $reg = Get-ItemProperty -Path "HKLM:\Software\Valve\Steam" -Name "InstallPath" -ErrorAction Stop
        if ($reg.InstallPath -and (Test-Path $reg.InstallPath)) {
            return $reg.InstallPath
        }
    } catch {}

    # Fallback: common paths
    $fallbacks = @(
        "${env:ProgramFiles(x86)}\Steam",
        "$env:ProgramFiles\Steam",
        "C:\Steam"
    )
    foreach ($p in $fallbacks) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Get-SteamLocalAppData {
    $local = $env:LOCALAPPDATA
    if ($local) {
        $p = Join-Path $local "Steam"
        if (Test-Path $p) { return $p }
    }
    return $null
}

# ── Utilities ──────────────────────────────────────────────────────────────

function Get-DirSizeMB([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $bytes = (Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue |
              Measure-Object -Property Length -Sum -ErrorAction SilentlyContinue).Sum
    return [math]::Round(($bytes / 1MB), 2)
}

function Remove-DirContents([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $before = Get-DirSizeMB $Path
    Get-ChildItem -Path $Path -Force -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            if ($_.PSIsContainer) {
                Remove-Item $_.FullName -Recurse -Force -ErrorAction Stop
            } else {
                Remove-Item $_.FullName -Force -ErrorAction Stop
            }
        } catch {
            # Locked file — Steam is likely running
        }
    }
    $after = Get-DirSizeMB $Path
    return [math]::Max(0, $before - $after)
}

# ── Actions ────────────────────────────────────────────────────────────────

function Invoke-CacheInfo {
    $steamPath = Get-SteamPath
    $localPath = Get-SteamLocalAppData

    $targets = @{
        htmlcache     = @( (Join-Path $steamPath "htmlcache"), (Join-Path $localPath "htmlcache") )
        shadercache   = @( (Join-Path $steamPath "steamapps\shadercache"), (Join-Path $localPath "shadercache") )
        downloadcache = @( (Join-Path $steamPath "steamapps\downloading"), (Join-Path $steamPath "steamapps\temp") )
        appcache      = @( (Join-Path $steamPath "appcache") )
        depotcache    = @( (Join-Path $steamPath "depotcache") )
        logs          = @( (Join-Path $steamPath "logs") )
    }

    $result = @{}
    $totalMB = 0

    foreach ($key in $targets.Keys) {
        $catMB = 0
        foreach ($p in $targets[$key]) {
            if ($p -and (Test-Path $p)) {
                $catMB += Get-DirSizeMB $p
            }
        }
        $result[$key] = @{ sizeMB = $catMB }
        $totalMB += $catMB
    }

    $result["_total"] = @{ sizeMB = $totalMB }
    return $result | ConvertTo-Json -Depth 3
}

function Invoke-CleanCache {
    $steamPath = Get-SteamPath
    $localPath = Get-SteamLocalAppData

    $allTargets = @{
        htmlcache     = @( (Join-Path $steamPath "htmlcache"), (Join-Path $localPath "htmlcache") )
        shadercache   = @( (Join-Path $steamPath "steamapps\shadercache"), (Join-Path $localPath "shadercache") )
        downloadcache = @( (Join-Path $steamPath "steamapps\downloading"), (Join-Path $steamPath "steamapps\temp") )
        appcache      = @( (Join-Path $steamPath "appcache") )
        depotcache    = @( (Join-Path $steamPath "depotcache") )
        logs          = @( (Join-Path $steamPath "logs") )
    }

    $requested = if ($Categories) { $Categories -split "," | ForEach-Object { $_.Trim() } } else { $allTargets.Keys }

    $freed = @{}
    foreach ($key in $requested) {
        if (-not $allTargets.ContainsKey($key)) { continue }
        $catFreed = 0
        foreach ($p in $allTargets[$key]) {
            if ($p -and (Test-Path $p)) {
                $catFreed += Remove-DirContents $p
            }
        }
        $freed[$key] = @{ freedMB = $catFreed }
    }

    return @{ success = $true; freed = $freed } | ConvertTo-Json -Depth 3
}

function Invoke-Backup {
    $steamPath = Get-SteamPath
    $stplug = Join-Path $steamPath "config\stplug-in"
    $depot  = Join-Path $steamPath "depotcache"

    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $label = if ($BackupLabel) { "_$($BackupLabel -replace '[^\w\-]','_')" } else { "" }
    $backupDir = Join-Path $PSScriptRoot "data\luatools_backups"
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

    $zipName = "backup_${stamp}${label}.zip"
    $zipPath = Join-Path $backupDir $zipName

    $tempDir = Join-Path $env:TEMP "lt_backup_$stamp"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    if (Test-Path $stplug) { Copy-Item $stplug -Destination (Join-Path $tempDir "stplug-in") -Recurse }
    if (Test-Path $depot)  { Copy-Item $depot  -Destination (Join-Path $tempDir "depotcache") -Recurse }

    Compress-Archive -Path "$tempDir\*" -DestinationPath $zipPath -Force
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue

    $size = (Get-Item $zipPath).Length
    return @{ success = $true; path = $zipPath; sizeMB = [math]::Round($size/1MB, 2) } | ConvertTo-Json
}

function Invoke-Restore {
    if (-not $RestoreFile -or -not (Test-Path $RestoreFile)) {
        return @{ success = $false; error = "Backup file not found" } | ConvertTo-Json
    }

    $steamPath = Get-SteamPath
    $tempDir = Join-Path $env:TEMP "lt_restore_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Expand-Archive -Path $RestoreFile -DestinationPath $tempDir -Force

    $count = 0
    $stplugSrc = Join-Path $tempDir "stplug-in"
    if (Test-Path $stplugSrc) {
        $dest = Join-Path $steamPath "config\stplug-in"
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
        Copy-Item "$stplugSrc\*" -Destination $dest -Recurse -Force
        $count += (Get-ChildItem $stplugSrc -Recurse -File).Count
    }

    $depotSrc = Join-Path $tempDir "depotcache"
    if (Test-Path $depotSrc) {
        $dest = Join-Path $steamPath "depotcache"
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
        Copy-Item "$depotSrc\*" -Destination $dest -Recurse -Force
        $count += (Get-ChildItem $depotSrc -Recurse -File).Count
    }

    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    return @{ success = $true; restoredFiles = $count } | ConvertTo-Json
}

function Invoke-FolderStats {
    $steamPath = Get-SteamPath
    $dirs = @("steamapps","config","depotcache","appcache","htmlcache","logs","userdata")
    $result = @{}
    foreach ($d in $dirs) {
        $p = Join-Path $steamPath $d
        $result[$d] = @{
            path   = $p
            sizeMB = Get-DirSizeMB $p
            exists = (Test-Path $p)
        }
    }
    return @{ success = $true; steamPath = $steamPath; folders = $result } | ConvertTo-Json -Depth 3
}

# ── Dispatch ───────────────────────────────────────────────────────────────

switch ($Action) {
    "CacheInfo"       { Invoke-CacheInfo }
    "CleanCache"      { Invoke-CleanCache }
    "Backup"          { Invoke-Backup }
    "Restore"         { Invoke-Restore }
    "FolderStats"     { Invoke-FolderStats }
    default           { Write-Output '{"error":"Unknown action"}' }
}
