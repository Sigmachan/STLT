"""Filesystem path helpers for the LuaTools backend.

Linux-first (v9.1). Windows path logic is retained but shelved — it is only
reached when sys.platform reports Windows, which the Linux-only build never
does. Kept for the eventual cross-platform / Lua port.

Steam on Linux can live in several places depending on how it was installed
(native package, Flatpak, Snap). Resolution order:
  1. Millennium.steam_path()           — the framework already knows
  2. Standard native locations          — ~/.local/share/Steam etc.
  3. Flatpak / Snap sandboxed locations
Every candidate is symlink-resolved and validated (must contain steamapps/
or config/).
"""

import os
import sys

_IS_WINDOWS = sys.platform.startswith("win")

# Cached resolved Steam path
_STEAM_PATH_CACHE = ""


# ---------------------------------------------------------------------------
# Plugin layout helpers — platform-neutral
# ---------------------------------------------------------------------------

def get_backend_dir() -> str:
    """Return the absolute path to the backend directory."""
    return os.path.dirname(os.path.realpath(__file__))


def get_plugin_dir() -> str:
    """Return the absolute path to the root plugin directory."""
    return os.path.abspath(os.path.join(get_backend_dir(), ".."))


def backend_path(filename: str) -> str:
    """Return an absolute path to a file inside the backend directory."""
    return os.path.join(get_backend_dir(), filename)


def public_path(filename: str) -> str:
    """Return an absolute path to a file inside the public directory."""
    return os.path.join(get_plugin_dir(), "public", filename)


def data_path(filename: str = "") -> str:
    """Return an absolute path inside the backend/data directory.

    Creates the directory if it does not exist yet.
    """
    base = os.path.join(get_backend_dir(), "data")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    return os.path.join(base, filename) if filename else base


# ---------------------------------------------------------------------------
# Steam install path resolution
# ---------------------------------------------------------------------------

def _home() -> str:
    return os.path.expanduser("~")


def _is_valid_steam_dir(path: str) -> bool:
    """A directory is a Steam install if it has steamapps/ or config/."""
    if not path or not os.path.isdir(path):
        return False
    return (
        os.path.isdir(os.path.join(path, "steamapps"))
        or os.path.isdir(os.path.join(path, "config"))
    )


def _linux_steam_candidates() -> list:
    """Standard Steam locations on Linux, in priority order."""
    home = _home()
    xdg_data = os.environ.get("XDG_DATA_HOME", os.path.join(home, ".local", "share"))
    return [
        # Native package (most common on Arch / CachyOS)
        os.path.join(xdg_data, "Steam"),
        os.path.join(home, ".local", "share", "Steam"),
        # Classic symlinks — usually point at the above
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
        # Debian / Ubuntu packaged
        os.path.join(home, ".steam", "debian-installation"),
        # Flatpak
        os.path.join(home, ".var", "app", "com.valvesoftware.Steam",
                     ".local", "share", "Steam"),
        os.path.join(home, ".var", "app", "com.valvesoftware.Steam",
                     "data", "Steam"),
        # Snap
        os.path.join(home, "snap", "steam", "common", ".local", "share", "Steam"),
    ]


def _windows_steam_candidates() -> list:
    """Windows Steam locations — shelved, only reached on a Windows build."""
    cands = []
    pf86 = os.environ.get("PROGRAMFILES(X86)") or os.environ.get("ProgramFiles(x86)")
    if pf86:
        cands.append(os.path.join(pf86, "Steam"))
    pf = os.environ.get("PROGRAMFILES") or os.environ.get("ProgramFiles")
    if pf:
        cands.append(os.path.join(pf, "Steam"))
    return cands


def _steam_path_from_millennium() -> str:
    """Ask the Millennium framework where Steam is. Works on all platforms."""
    try:
        import Millennium  # provided by the Millennium runtime
        path = Millennium.steam_path()
        if path and os.path.isdir(path):
            return path
    except Exception:
        pass
    return ""


def _steam_path_from_registry() -> str:
    """Windows registry lookup — shelved, returns '' on Linux."""
    if not _IS_WINDOWS:
        return ""
    try:
        import winreg
        for hive, subkey, value in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, value)
                    if val and os.path.isdir(str(val)):
                        return str(val)
            except Exception:
                continue
    except Exception:
        pass
    return ""


def get_steam_path() -> str:
    """Return the absolute path to the Steam installation directory.

    Resolution order: Millennium API → registry (Windows only) → candidate
    scan. The result is symlink-resolved and cached for the process lifetime.
    Returns '' if Steam cannot be located.
    """
    global _STEAM_PATH_CACHE
    if _STEAM_PATH_CACHE:
        return _STEAM_PATH_CACHE

    # 1. Framework API — most reliable, cross-platform
    found = _steam_path_from_millennium()

    # 2. Registry (Windows only; no-op on Linux)
    if not found:
        found = _steam_path_from_registry()

    # 3. Candidate scan
    if not found:
        candidates = (
            _windows_steam_candidates() if _IS_WINDOWS
            else _linux_steam_candidates()
        )
        for cand in candidates:
            # Resolve symlinks — ~/.steam/steam is usually a link
            resolved = os.path.realpath(cand)
            if _is_valid_steam_dir(resolved):
                found = resolved
                break

    if found:
        found = os.path.realpath(found)
        _STEAM_PATH_CACHE = found

    return _STEAM_PATH_CACHE or ""


def steam_localappdata_dir() -> str:
    """Return the directory holding Steam's local caches (htmlcache, etc.).

    On Windows this is %LOCALAPPDATA%\\Steam — a location separate from the
    install dir. On Linux there is no such split: htmlcache, shadercache and
    friends live inside the main Steam directory, so this returns the same
    path as get_steam_path().
    """
    if _IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            return os.path.join(local, "Steam")
        return ""
    # Linux: caches are inside the install dir
    return get_steam_path()


def steam_program_files_dir() -> str:
    """Windows-only fallback path — shelved, returns '' on Linux."""
    if not _IS_WINDOWS:
        return ""
    for cand in _windows_steam_candidates():
        if os.path.isdir(cand):
            return cand
    return ""


# Backwards-compatible alias — some modules import the old name.
def steam_path_from_registry() -> str:
    """Deprecated alias for the Windows registry lookup."""
    return _steam_path_from_registry()
