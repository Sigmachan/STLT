"""First-run setup assistant: marker persistence, classification of issues into
auto-fixable vs blockers, and that run_setup applies the safe fixes."""

import os
import tempfile
import unittest

import _bootstrap  # noqa: F401
from _bootstrap import stubs


class TestSetupAssistant(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Persistent marker dir
        self.data_dir = os.path.join(self.tmp, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        stubs.data_dir = self.data_dir

        # A "good Linux" baseline
        self.steam = os.path.join(self.tmp, "Steam")
        os.makedirs(os.path.join(self.steam, "steamui"), exist_ok=True)
        stubs.steam_path = self.steam
        stubs.steam_running = False
        stubs.slssteam_installed = True
        stubs.slssteam_injected = True
        stubs.accela_installed = False
        self.cfgdir = os.path.join(self.steam, "SLSsteam")
        os.makedirs(self.cfgdir, exist_ok=True)
        self.cfg = os.path.join(self.cfgdir, "config.yaml")
        open(self.cfg, "w").write("PlayNotOwnedGames: yes\n")
        stubs.slssteam_config_path = self.cfg
        stubs.slssteam_config_dir = self.cfgdir
        stubs.stplugin_dir = os.path.join(self.steam, "config", "stplug-in")
        os.makedirs(stubs.stplugin_dir, exist_ok=True)

        # Health: neutralize real network/dep probes for hermeticity
        import importlib, health, slssteam_config
        importlib.reload(slssteam_config)
        importlib.reload(health)
        health._chk_network = lambda: {"id": "network", "label": "Network", "status": "ok", "detail": ""}
        health._chk_python_deps = lambda: {"id": "python_deps", "label": "Deps", "status": "ok", "detail": ""}
        import setup_assistant
        importlib.reload(setup_assistant)
        self.sa = setup_assistant

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_marker_roundtrip(self):
        self.assertFalse(self.sa.has_seen_setup())
        self.assertTrue(self.sa.mark_setup_seen())
        self.assertTrue(self.sa.has_seen_setup())

    def test_firstrun_reflects_marker(self):
        self.assertTrue(self.sa.get_setup_state()["firstRun"])
        self.sa.mark_setup_seen()
        self.assertFalse(self.sa.get_setup_state()["firstRun"])

    def test_ready_when_all_ok(self):
        s = self.sa.get_setup_state()
        self.assertTrue(s["success"])
        self.assertTrue(s["ready"], f"expected ready; summary={s.get('summary')}")
        self.assertEqual(s["autoFixable"], [])
        self.assertEqual(s["blockers"], [])

    def test_play_not_owned_is_autofixable(self):
        open(self.cfg, "w").write("PlayNotOwnedGames: no\n")
        import importlib, slssteam_config
        importlib.reload(slssteam_config)
        s = self.sa.get_setup_state()
        self.assertFalse(s["ready"])
        ids = [f["id"] for f in s["autoFixable"]]
        self.assertIn("play_not_owned", ids)

    def test_no_tool_is_blocker_not_autofixable(self):
        stubs.slssteam_installed = False
        stubs.accela_installed = False
        s = self.sa.get_setup_state()
        self.assertFalse(s["ready"])
        bids = [b["id"] for b in s["blockers"]]
        self.assertIn("activation_tool", bids)
        self.assertNotIn("activation_tool", [f["id"] for f in s["autoFixable"]])

    def test_run_setup_enables_play_not_owned(self):
        open(self.cfg, "w").write("PlayNotOwnedGames: no\n")
        import importlib, slssteam_config
        importlib.reload(slssteam_config)
        res = self.sa.run_setup()
        self.assertTrue(any("PlayNotOwnedGames" in a for a in res["applied"]),
                        "run_setup should auto-enable PlayNotOwnedGames")
        self.assertTrue(res["ready"], "should be ready after the safe fix")
        importlib.reload(slssteam_config)
        self.assertTrue(slssteam_config.is_play_not_owned_enabled())

    def test_self_heal_noop_before_setup_seen(self):
        # First run (no marker): self-heal must not touch anything.
        open(self.cfg, "w").write("PlayNotOwnedGames: no\n")
        import importlib, slssteam_config
        importlib.reload(slssteam_config)
        res = self.sa.self_heal()
        self.assertFalse(res["ran"])
        self.assertEqual(res["healed"], [])
        importlib.reload(slssteam_config)
        self.assertFalse(slssteam_config.is_play_not_owned_enabled(),
                         "self-heal must not change state before setup is completed")

    def test_self_heal_reenables_regressed_play_not_owned(self):
        self.sa.mark_setup_seen()
        open(self.cfg, "w").write("PlayNotOwnedGames: no\n")  # regressed
        import importlib, slssteam_config
        importlib.reload(slssteam_config)
        res = self.sa.self_heal()
        self.assertTrue(res["ran"])
        self.assertTrue(any("PlayNotOwnedGames" in h for h in res["healed"]))
        importlib.reload(slssteam_config)
        self.assertTrue(slssteam_config.is_play_not_owned_enabled())

    def test_self_heal_recreates_missing_stplugin_dir(self):
        self.sa.mark_setup_seen()
        import shutil
        shutil.rmtree(stubs.stplugin_dir, ignore_errors=True)
        res = self.sa.self_heal()
        self.assertTrue(any("stplug-in" in h for h in res["healed"]))
        self.assertTrue(os.path.isdir(stubs.stplugin_dir))

    def test_self_heal_noop_when_healthy(self):
        self.sa.mark_setup_seen()  # PNO already 'yes', dir exists from setUp
        res = self.sa.self_heal()
        self.assertTrue(res["ran"])
        self.assertEqual(res["healed"], [], "nothing to heal on a healthy setup")


if __name__ == "__main__":
    unittest.main()
