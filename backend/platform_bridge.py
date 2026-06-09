"""Runtime bridge for optional Millennium integration (v9.1).

Lets the LuaTools backend run in two modes:
  1. Inside Millennium      — the real framework API is available
  2. Standalone bridge mode — launched by web_bridge_server.py as a plain
                              HTTP server; Millennium is not present

This module is the single source of truth for the Millennium API and the
Logger. web_bridge_server.py installs these into sys.modules before main.py
is imported, so every existing `import Millennium` / `import PluginUtils`
keeps working unchanged.

Adapted in part from the LuaToolsLinux fork by StarWarsK and geovanygrdt.
"""

from __future__ import annotations

import os
import re
import sys


# ---------------------------------------------------------------------------
# Millennium API — real or fallback
# ---------------------------------------------------------------------------

def _detect_steam_path_fallback() -> str:
    """Best-effort Steam discovery when the Millennium API is unavailable."""
    candidates = [
        os.path.expanduser("~/.steam/steam"),
        os.path.expanduser("~/.local/share/Steam"),
        os.path.expanduser("~/.steam/root"),
    ]
    if sys.platform.startswith("win"):
        for var in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(var, "")
            if base:
                candidates.append(os.path.join(base, "Steam"))
    for path in candidates:
        if path and os.path.isdir(path):
            return os.path.realpath(path)
    return ""


def _cmp_version_parts(version: str) -> tuple[int, ...]:
    """Return a numeric tuple for simple dotted version strings."""
    return tuple(int(part) for part in re.findall(r"\d+", str(version))) or (0,)


class _MillenniumFallback:
    """Stand-in for the Millennium runtime module when running standalone."""

    @staticmethod
    def steam_path() -> str:
        return _detect_steam_path_fallback()

    @staticmethod
    def add_browser_js(_path: str) -> None:
        return None

    @staticmethod
    def add_browser_css(_path: str) -> None:
        return None

    @staticmethod
    def ready() -> None:
        return None

    @staticmethod
    def call_frontend_method(*_args, **_kwargs):
        return None

    @staticmethod
    def version() -> str:
        return "standalone-bridge"

    @staticmethod
    def get_install_path() -> str:
        return _MillenniumFallback.steam_path()

    @staticmethod
    def remove_browser_module(_module_id: str) -> None:
        return None

    @staticmethod
    def cmp_version(left: str, right: str) -> int:
        left_parts = _cmp_version_parts(left)
        right_parts = _cmp_version_parts(right)
        max_len = max(len(left_parts), len(right_parts))
        left_padded = left_parts + (0,) * (max_len - len(left_parts))
        right_padded = right_parts + (0,) * (max_len - len(right_parts))
        return (left_padded > right_padded) - (left_padded < right_padded)

    @staticmethod
    def is_plugin_enabled(_name: str) -> bool:
        return True


try:
    import Millennium as _RealMillennium  # type: ignore
    Millennium = _RealMillennium
    IS_STANDALONE = False
except Exception:
    Millennium = _MillenniumFallback()  # type: ignore
    IS_STANDALONE = True


# ---------------------------------------------------------------------------
# Logger — real PluginUtils.Logger or a print-based fallback
# ---------------------------------------------------------------------------

class _FallbackLogger:
    """Print-based logger used when PluginUtils is unavailable."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def log(self, msg: object) -> None:
        print(f"[LuaTools] {msg}", flush=True)

    def info(self, msg: object) -> None:
        print(f"[LuaTools:info] {msg}", flush=True)

    def warn(self, msg: object) -> None:
        print(f"[LuaTools:warn] {msg}", flush=True)

    def error(self, msg: object) -> None:
        print(f"[LuaTools:error] {msg}", flush=True)


try:
    from PluginUtils import Logger as _RealLogger  # type: ignore
    Logger = _RealLogger
except Exception:
    Logger = _FallbackLogger  # type: ignore


def install_standalone_shims() -> None:
    """Register Millennium + PluginUtils in sys.modules for standalone mode.

    Call this BEFORE importing main.py when running outside Millennium, so
    every `import Millennium` / `from PluginUtils import Logger` resolves to
    these fallbacks instead of failing.
    """
    import types

    if "Millennium" not in sys.modules:
        mod = types.ModuleType("Millennium")
        for attr in (
            "steam_path",
            "add_browser_js",
            "add_browser_css",
            "ready",
            "call_frontend_method",
            "version",
            "get_install_path",
            "remove_browser_module",
            "cmp_version",
            "is_plugin_enabled",
        ):
            setattr(mod, attr, getattr(Millennium, attr))
        sys.modules["Millennium"] = mod

    if "PluginUtils" not in sys.modules:
        mod = types.ModuleType("PluginUtils")
        mod.Logger = Logger
        sys.modules["PluginUtils"] = mod
