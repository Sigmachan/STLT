"""health engine: report structure, severity rollup, and that the flagship
PlayNotOwnedGames-off case is surfaced as a blocking fix."""

import os
import tempfile
import unittest

import _bootstrap  # noqa: F401
from _bootstrap import stubs


class TestHealth(unittest.TestCase):

    def setUp(self):
        import importlib, health
        importlib.reload(health)
        self.health = health
        self.tmp = tempfile.mkdtemp()
        # Reset stubs to a "good Linux" baseline
        stubs.steam_path = self.tmp
        stubs.steam_running = False
        stubs.slssteam_installed = True
        stubs.slssteam_injected = True
        stubs.accela_installed = False
        cfgdir = os.path.join(self.tmp, "SLSsteam")
        os.makedirs(cfgdir, exist_ok=True)
        self.cfg = os.path.join(cfgdir, "config.yaml")
        stubs.slssteam_config_path = self.cfg
        stubs.slssteam_config_dir = cfgdir
        stubs.stplugin_dir = os.path.join(self.tmp, "config", "stplug-in")
        os.makedirs(stubs.stplugin_dir, exist_ok=True)
        # slssteam_config reads the stubbed path
        import importlib as il, slssteam_config
        il.reload(slssteam_config)
        # Neutralize the real network + dependency probes so tests are fast
        # and hermetic (they're not what these tests exercise).
        self.health._chk_network = lambda: {
            "id": "network", "label": "Network to sources", "status": "ok",
            "detail": "(stubbed in test)"}
        self.health._chk_python_deps = lambda: {
            "id": "python_deps", "label": "Python dependencies", "status": "ok",
            "detail": "(stubbed in test)"}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_report_shape(self):
        rep = self.health.run_health_check()
        for key in ("success", "overall", "summary", "checks", "fixes",
                    "generatedAt", "platform"):
            self.assertIn(key, rep)
        self.assertIn(rep["overall"], ("ok", "warn", "fail"))
        self.assertIsInstance(rep["checks"], list)
        self.assertTrue(len(rep["checks"]) >= 8)

    def test_play_not_owned_off_is_blocking_with_fix(self):
        open(self.cfg, "w").write("PlayNotOwnedGames: no\n")
        rep = self.health.run_health_check()
        pno = [c for c in rep["checks"] if c["id"] == "play_not_owned"][0]
        self.assertEqual(pno["status"], "fail")
        self.assertIn("fix", pno)
        self.assertEqual(pno["fix"]["ipc"], "SetSlssteamPlayNotOwned")
        # And it must bubble into the ordered fixes list
        ipcs = [f.get("ipc") for f in rep["fixes"]]
        self.assertIn("SetSlssteamPlayNotOwned", ipcs)
        self.assertEqual(rep["overall"], "fail")

    def test_play_not_owned_on_is_ok(self):
        open(self.cfg, "w").write("PlayNotOwnedGames: yes\n")
        rep = self.health.run_health_check()
        pno = [c for c in rep["checks"] if c["id"] == "play_not_owned"][0]
        self.assertEqual(pno["status"], "ok")

    def test_no_activation_tool_is_fail(self):
        stubs.slssteam_installed = False
        stubs.accela_installed = False
        rep = self.health.run_health_check()
        tool = [c for c in rep["checks"] if c["id"] == "activation_tool"][0]
        self.assertEqual(tool["status"], "fail")

    def test_severity_rollup_worst_wins(self):
        # Force a fail (no tool) — overall must be fail even if others are ok.
        stubs.slssteam_installed = False
        stubs.accela_installed = False
        rep = self.health.run_health_check()
        self.assertEqual(rep["overall"], "fail")

    def test_per_app_audit_runs(self):
        # Drop a keyed lua and confirm per-app checks appear.
        lua = os.path.join(stubs.stplugin_dir, "590830.lua")
        open(lua, "w").write('addappid(590830)\naddappid(590831,0,"%s")\n' % ("a" * 64))
        rep = self.health.run_health_check(appid=590830)
        ids = [c["id"] for c in rep["checks"]]
        self.assertIn("app_ownership", ids)
        self.assertIn("app_keys", ids)
        own = [c for c in rep["checks"] if c["id"] == "app_ownership"][0]
        self.assertEqual(own["status"], "ok")

    def test_per_app_missing_ownership_flagged(self):
        # A lua with ONLY keyed lines (no base addappid) — the exact bug the
        # stub filter caused — must be flagged.
        lua = os.path.join(stubs.stplugin_dir, "999999.lua")
        open(lua, "w").write('addappid(999998,0,"%s")\n' % ("b" * 64))
        rep = self.health.run_health_check(appid=999999)
        own = [c for c in rep["checks"] if c["id"] == "app_ownership"][0]
        self.assertEqual(own["status"], "fail")

    def test_render_text_no_crash(self):
        rep = self.health.run_health_check()
        out = self.health.render_text(rep)
        self.assertIsInstance(out, str)
        self.assertIn("LuaTools Health", out)


if __name__ == "__main__":
    unittest.main()
