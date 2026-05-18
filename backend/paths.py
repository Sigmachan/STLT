"""Filesystem path helpers for the LuaTools backend.

Windows 11 native: uses registry + env vars, no WSL/bash.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Plugin layout helpers
# ---------------------------------------------------------------------------

def get_backend_dir() -> str:
    """Return the absolute path to the backend directory."""
    return os.path.dirname(os.path.realpath(__file__))


def get_plugin_dir() -> str:
    """Return the absolute path to the root plugin directory."""
    backend_dir = get_backend_dir()
    return os.path.abspath(os.path.join(backend_dir, ".."))


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
    if filename:
        return os.path.join(base, filename)
    return base


# ---------------------------------------------------------------------------
# Windows 11 Steam path helpers
# ---------------------------------------------------------------------------

def _env(name: str) -> str:
    """Expand a Windows environment variable safely."""
    return os.environ.get(name, "")


def steam_localappdata_dir() -> str:
    """Return %LOCALAPPDATA%\\Steam (shader cache, htmlcache, etc.)."""
    local = _env("LOCALAPPDATA")
    if local:
        return os.path.join(local, "Steam")
    return ""


def steam_program_files_dir() -> str:
    """Return %PROGRAMFILES(X86)%\\Steam as fallback path."""
    pf = _env("PROGRAMFILES(X86)") or _env("ProgramFiles(x86)")
    if pf:
        return os.path.join(pf, "Steam")
    return ""


def steam_path_from_registry() -> str:
    """Read Steam install path from Windows registry (read-only)."""
    if not sys.platform.startswith("win"):
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            val, _ = winreg.QueryValueEx(key, "SteamPath")
            if val and os.path.isdir(str(val)):
                return str(val)
    except Exception:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam") as key:
            val, _ = winreg.QueryValueEx(key, "InstallPath")
            if val and os.path.isdir(str(val)):
                return str(val)
    except Exception:
        pass
    return ""
