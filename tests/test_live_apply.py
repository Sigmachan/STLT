"""live_apply: starting a download on a running Steam without a restart.

Verifies the function hands the correct steam:// URL to the OS, refuses when
no .lua is installed, and surfaces (without blocking on) prerequisite warnings.
"""

import os
import sys
import tempfile
import types
import unittest

import _bootstrap  # noqa: F401
from _bootstrap import stubs


class TestLiveApply(unittest.TestCase):

    def setUp(self):
        # Stub steam_utils.has_lua_for_app via a controllable flag
        self._has_lua = True
        su = sys.modules["steam_utils"]
        su.has_lua_for_app = lambda appid: self._has_lua

        import importlib, live_apply
        importlib.reload(live_apply)
        self.la = live_apply
        # Capture the URL instead of actually launching anything
        self.opened = []
        self.la._open_url = lambda url: (self.opened.append(url) or True)
        # Good Linux baseline so no warnings unless a test wants them
        stubs.slssteam_installed = True
        stubs.slssteam_injected = True
        stubs.steam_running = True
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "config.yaml")
        with open(self.cfg, "w") as _f: _f.write("PlayNotOwnedGames: yes\n")
        stubs.slssteam_config_path = self.cfg
        stubs.slssteam_config_dir = self.tmp
        import importlib as il, slssteam_config
        il.reload(slssteam_config)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fires_correct_steam_url(self):
        res = self.la.trigger_steam_install(570)
        self.assertTrue(res["success"])
        self.assertTrue(res["triggered"])
        self.assertEqual(self.opened, ["steam://install/570"])

    def test_refuses_when_no_lua(self):
        self._has_lua = False
        res = self.la.trigger_steam_install(570)
        self.assertFalse(res["success"])
        self.assertFalse(res.get("triggered", False))
        self.assertEqual(self.opened, [], "must not fire a URL when nothing is activated")
        self.assertIn("activate", res["message"].lower())

    def test_invalid_appid(self):
        res = self.la.trigger_steam_install("not-a-number")
        self.assertFalse(res["success"])

    def test_play_not_owned_off_warns_but_still_fires(self):
        with open(self.cfg, "w") as _f: _f.write("PlayNotOwnedGames: no\n")
        import importlib as il, slssteam_config
        il.reload(slssteam_config)
        res = self.la.trigger_steam_install(570)
        self.assertTrue(res["triggered"], "the URL handoff is harmless; still fire it")
        self.assertTrue(any("PlayNotOwnedGames" in w for w in res["warnings"]),
                        "PlayNotOwnedGames-off should surface as a warning")

    def test_open_failure_reported(self):
        self.la._open_url = lambda url: False
        res = self.la.trigger_steam_install(570)
        self.assertFalse(res["success"])
        self.assertFalse(res["triggered"])

    def test_steam_not_running_message_differs(self):
        stubs.steam_running = False
        res = self.la.trigger_steam_install(570)
        self.assertTrue(res["triggered"])
        self.assertFalse(res["steam_running"])
        self.assertIn("started", res["message"].lower())


class TestAutoFinalize(unittest.TestCase):

    def setUp(self):
        self._has_lua = True
        su = sys.modules["steam_utils"]
        su.has_lua_for_app = lambda appid: self._has_lua

        # Controllable settings stub for autoStartDownload
        self._auto_enabled = True
        sm = types.ModuleType("settings.manager")
        sm.get_steamtools_settings = lambda: {"general": {"autoStartDownload": self._auto_enabled}}
        # ensure the 'settings' package exists for the submodule import
        if "settings" not in sys.modules:
            pkg = types.ModuleType("settings")
            pkg.__path__ = []
            sys.modules["settings"] = pkg
        sys.modules["settings.manager"] = sm

        import importlib, live_apply
        importlib.reload(live_apply)
        self.la = live_apply
        self.opened = []
        self.la._open_url = lambda url: (self.opened.append(url) or True)

        # Control ACCELA availability deterministically (default: not present,
        # so these tests exercise the SLSsteam / steam:// path).
        self._accela = False
        import types as _t
        accela_stub = _t.ModuleType("accela_launcher")
        accela_stub.is_available = lambda: self._accela
        sys.modules["accela_launcher"] = accela_stub

        stubs.slssteam_installed = True
        stubs.slssteam_injected = True
        stubs.accela_installed = False
        stubs.steam_running = True
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "config.yaml")
        with open(self.cfg, "w") as _f: _f.write("PlayNotOwnedGames: yes\n")
        stubs.slssteam_config_path = self.cfg
        stubs.slssteam_config_dir = self.tmp
        import importlib as il, slssteam_config
        il.reload(slssteam_config)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        sys.modules.pop("settings.manager", None)
        sys.modules.pop("accela_launcher", None)

    def test_happy_path_triggers_download(self):
        res = self.la.auto_finalize_activation(570)
        self.assertTrue(res["success"])
        self.assertTrue(res["downloadTriggered"])
        self.assertEqual(self.opened, ["steam://install/570"])
        self.assertEqual(res["autoFixed"], [])

    def test_auto_enables_play_not_owned(self):
        with open(self.cfg, "w") as _f: _f.write("PlayNotOwnedGames: no\n")
        import importlib as il, slssteam_config
        il.reload(slssteam_config)
        res = self.la.auto_finalize_activation(570)
        self.assertTrue(res["success"])
        self.assertTrue(any("PlayNotOwnedGames" in f for f in res["autoFixed"]),
                        "should auto-enable PlayNotOwnedGames")
        # and it was actually written
        self.assertTrue(slssteam_config.is_play_not_owned_enabled())

    def test_blocker_no_activation_tool(self):
        stubs.slssteam_installed = False
        stubs.accela_installed = False
        res = self.la.auto_finalize_activation(570)
        self.assertFalse(res["success"])
        self.assertEqual(res["blocker"], "no_activation_tool")
        self.assertEqual(self.opened, [], "must not fire download when no tool")

    def test_blocker_not_injected(self):
        stubs.slssteam_installed = True
        stubs.slssteam_injected = False
        res = self.la.auto_finalize_activation(570)
        self.assertFalse(res["success"])
        self.assertEqual(res["blocker"], "not_injected")

    def test_blocker_no_lua(self):
        self._has_lua = False
        res = self.la.auto_finalize_activation(570)
        self.assertFalse(res["success"])
        self.assertEqual(res["blocker"], "no_lua")

    def test_skipped_when_disabled(self):
        self._auto_enabled = False
        res = self.la.auto_finalize_activation(570)
        self.assertTrue(res["success"])
        self.assertTrue(res["skipped"])
        self.assertEqual(self.opened, [], "disabled = no auto download")

    def test_setting_enabled_reads_flag(self):
        self._auto_enabled = True
        self.assertTrue(self.la._setting_enabled("autoStartDownload", True))
        self._auto_enabled = False
        self.assertFalse(self.la._setting_enabled("autoStartDownload", True))

    def test_setting_enabled_default_when_missing(self):
        # Unknown key falls back to the supplied default.
        self.assertTrue(self.la._setting_enabled("nonexistentKey", True))
        self.assertFalse(self.la._setting_enabled("nonexistentKey", False))

    def test_prefers_accela_when_available(self):
        # When ACCELA is the downloader, auto-finalize must NOT fire steam://
        # install (download already happened at activation); it reports ACCELA.
        self._accela = True
        res = self.la.auto_finalize_activation(570)
        self.assertTrue(res["success"])
        self.assertTrue(res["downloadTriggered"])
        self.assertEqual(res.get("downloader"), "accela")
        self.assertEqual(self.opened, [],
                         "must not fire steam://install when ACCELA is the downloader")
        self.assertIn("ACCELA", res["message"])

    def test_slssteam_path_when_no_accela(self):
        self._accela = False
        res = self.la.auto_finalize_activation(570)
        self.assertEqual(res.get("downloader"), "slssteam")
        self.assertEqual(self.opened, ["steam://install/570"])


if __name__ == "__main__":
    unittest.main()