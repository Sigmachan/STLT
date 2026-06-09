"""Test bootstrap for LuaTools Ultimate.

Importing this module makes the backend importable in a hermetic test
environment: it puts backend/ on sys.path and injects controllable stub
modules for the heavy externals (logger, paths, steam_utils, steam_version,
linux_platform) so the lean modules under test (health, slssteam_config,
acf_writer, ui_injector) import without a real Steam / Millennium present.

Tests can adjust the stubs via the `stubs` object, e.g.:
    from _bootstrap import stubs
    stubs.steam_path = "/tmp/fake-steam"
    stubs.steam_running = False
    stubs.slssteam_config_path = "/tmp/SLSsteam/config.yaml"
"""

import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, "..", "backend"))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

FIXTURES = os.path.join(_HERE, "fixtures")


class _Stubs:
    """Mutable knobs the fake modules read from, so tests can steer behavior."""
    def __init__(self):
        self.steam_path = ""
        self.steam_running = False
        self.slssteam_config_path = ""
        self.slssteam_config_dir = ""
        self.slssteam_installed = False
        self.slssteam_injected = False
        self.accela_installed = False
        self.stplugin_dir = ""
        self.data_dir = ""


stubs = _Stubs()


def _install_stub_modules():
    # logger ------------------------------------------------------------------
    if "logger" not in sys.modules:
        log = types.ModuleType("logger")
        class _L:
            def log(self, *a): pass
            def warn(self, *a): pass
            def error(self, *a): pass
        log.logger = _L()
        sys.modules["logger"] = log

    # paths -------------------------------------------------------------------
    if "paths" not in sys.modules:
        paths = types.ModuleType("paths")
        def data_path(name=""):
            base = stubs.data_dir or os.path.join(_HERE, "_tmp_data")
            os.makedirs(base, exist_ok=True)
            return os.path.join(base, name) if name else base
        def get_plugin_dir():
            return os.path.normpath(os.path.join(_BACKEND, ".."))
        def get_backend_dir():
            return _BACKEND
        def public_path(name=""):
            return os.path.join(get_plugin_dir(), "public", name)
        paths.data_path = data_path
        paths.get_plugin_dir = get_plugin_dir
        paths.get_backend_dir = get_backend_dir
        paths.public_path = public_path
        sys.modules["paths"] = paths

    # steam_utils -------------------------------------------------------------
    if "steam_utils" not in sys.modules:
        su = types.ModuleType("steam_utils")
        su.detect_steam_install_path = lambda: stubs.steam_path
        su._parse_vdf_simple = lambda *a, **k: {}
        sys.modules["steam_utils"] = su

    # steam_version -----------------------------------------------------------
    if "steam_version" not in sys.modules:
        sv = types.ModuleType("steam_version")
        sv._steam_is_running = lambda: stubs.steam_running
        sys.modules["steam_version"] = sv

    # linux_platform ----------------------------------------------------------
    if "linux_platform" not in sys.modules:
        lp = types.ModuleType("linux_platform")
        lp.find_steam_root = lambda: stubs.steam_path or None
        lp.get_slssteam_config_path = lambda: stubs.slssteam_config_path
        lp.get_slssteam_config_dir = lambda: (
            stubs.slssteam_config_dir or os.path.dirname(stubs.slssteam_config_path))
        lp.check_slssteam_installed = lambda: stubs.slssteam_installed
        lp.check_accela_installed = lambda: stubs.accela_installed
        lp.get_stplugin_dir = lambda root=None: stubs.stplugin_dir or None
        lp.get_depotcache_dir = lambda root=None: None
        def check_slssteam_injection():
            if not stubs.slssteam_installed:
                return {"injected": False, "error": "SLSsteam not installed"}
            return {"injected": stubs.slssteam_injected,
                    "steamShPath": os.path.join(stubs.steam_path or "", "steam.sh"),
                    "error": None}
        lp.check_slssteam_injection = check_slssteam_injection
        def detect_activation_tool():
            sls = stubs.slssteam_installed
            acc = stubs.accela_installed
            return {"slssteam": sls, "accela": acc, "anyAvailable": sls or acc,
                    "preferred": "slssteam" if sls else ("accela" if acc else None)}
        lp.detect_activation_tool = detect_activation_tool
        lp.get_platform_summary = lambda: {}
        sys.modules["linux_platform"] = lp


_install_stub_modules()
