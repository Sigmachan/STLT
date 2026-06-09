"""slssteam_config round-trip + the critical PlayNotOwnedGames toggle."""

import os
import tempfile
import unittest

import _bootstrap  # noqa: F401
from _bootstrap import stubs


class TestSlssteamConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfgdir = os.path.join(self.tmp, "SLSsteam")
        os.makedirs(self.cfgdir, exist_ok=True)
        self.cfg = os.path.join(self.cfgdir, "config.yaml")
        stubs.slssteam_config_path = self.cfg
        stubs.slssteam_config_dir = self.cfgdir
        import importlib, slssteam_config
        importlib.reload(slssteam_config)
        self.sc = slssteam_config

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_config_exists_false_then_true(self):
        self.assertFalse(self.sc.config_exists())
        with open(self.cfg, "w") as _f: _f.write("PlayNotOwnedGames: no\n")
        self.assertTrue(self.sc.config_exists())

    def test_play_not_owned_roundtrip(self):
        with open(self.cfg, "w") as _f: _f.write("PlayNotOwnedGames: no\nSafeMode: no\n")
        self.assertFalse(self.sc.is_play_not_owned_enabled())
        self.sc.set_play_not_owned(True)
        self.assertTrue(self.sc.is_play_not_owned_enabled())
        # written as a YAML boolean literal
        with open(self.cfg, encoding="utf-8") as _f: body = _f.read()
        self.assertRegex(body, r"PlayNotOwnedGames:\s*(yes|true|True)")

    def test_set_play_not_owned_creates_missing_keys(self):
        with open(self.cfg, "w") as _f: _f.write("SafeMode: no\n")
        self.sc.set_play_not_owned(True)
        self.assertTrue(self.sc.is_play_not_owned_enabled())

    def test_safe_mode_read(self):
        with open(self.cfg, "w") as _f: _f.write("SafeMode: yes\n")
        self.assertTrue(self.sc.is_safe_mode_enabled())

    def test_get_value_default(self):
        with open(self.cfg, "w") as _f: _f.write("Foo: bar\n")
        self.assertEqual(self.sc.get_value("Foo"), "bar")
        self.assertEqual(self.sc.get_value("Missing", "fallback"), "fallback")

    def test_preserves_other_keys_on_write(self):
        with open(self.cfg, "w") as _f: _f.write("PlayNotOwnedGames: no\nVersion: 1.2.3\nSafeMode: no\n")
        self.sc.set_play_not_owned(True)
        with open(self.cfg, encoding="utf-8") as _f: body = _f.read()
        self.assertIn("1.2.3", body, "writing one key must not lose others")


if __name__ == "__main__":
    unittest.main()
