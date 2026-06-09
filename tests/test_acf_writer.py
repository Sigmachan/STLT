"""acf_writer download-model invariants.

Codifies the fix: Linux activation must let Steam DOWNLOAD, which means
activate_game_on_linux must NOT write a 'fully installed' (StateFlags=4) ACF,
and must not write config.vdf while Steam is running (keys would be wiped).
"""

import os
import tempfile
import unittest

import _bootstrap  # noqa: F401
from _bootstrap import stubs


class TestAcfWriterDownloadModel(unittest.TestCase):

    def setUp(self):
        import importlib
        import acf_writer
        importlib.reload(acf_writer)
        self.acf = acf_writer
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "steamapps"), exist_ok=True)
        os.makedirs(os.path.join(self.tmp, "config"), exist_ok=True)
        stubs.steam_path = self.tmp

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_activation_does_not_write_installed_acf(self):
        """The download-killer: a StateFlags=4 ACF makes Steam think the game
        is installed and skip downloading. activate_game_on_linux must not
        create one."""
        stubs.steam_running = False
        keys = [("590831", "5368f87f9235f5cd8144e9eea13824133defa90e4a90c2d478fac61ca5cfcc8a")]
        self.acf.activate_game_on_linux(590830, keys)
        acf_file = os.path.join(self.tmp, "steamapps", "appmanifest_590830.acf")
        self.assertFalseIfExistsHasState4(acf_file)

    def assertFalseIfExistsHasState4(self, acf_file):
        if os.path.isfile(acf_file):
            content = open(acf_file, encoding="utf-8").read()
            self.assertNotIn('"StateFlags"\t\t"4"', content)
            self.assertNotIn('"StateFlags": "4"', content)
            # Generic guard regardless of formatting
            self.assertNotRegex(content, r'StateFlags["\s:]+4\b',
                                "activate_game_on_linux wrote a fully-installed ACF "
                                "(StateFlags=4) — this blocks downloading")

    def test_activation_skips_configvdf_when_steam_running(self):
        """config.vdf written while Steam runs is wiped on exit — must skip."""
        stubs.steam_running = True
        keys = [("590831", "a" * 64)]
        result = self.acf.activate_game_on_linux(590830, keys)
        self.assertEqual(result.get("keys_added", -1), 0,
                         "must not write config.vdf while Steam is running")
        # Skipping the write is NOT a failure (the .lua carries the keys).
        self.assertTrue(result.get("success"),
                        "skipping config.vdf while Steam runs must still succeed")

    def test_write_acf_still_available_for_other_model(self):
        """We kept write_acf() in the module for the 'files already on disk'
        model — it just isn't called on the download path."""
        self.assertTrue(hasattr(self.acf, "write_acf"),
                        "write_acf() should remain available (unused on download path)")

    def test_success_is_error_based_not_keys_based(self):
        """Success must mean 'no errors', so a deliberate config.vdf skip
        doesn't report failure."""
        stubs.steam_running = True
        result = self.acf.activate_game_on_linux(590830, [("1", "b" * 64)])
        self.assertIn("success", result)
        self.assertEqual(result.get("errors", []), [])


if __name__ == "__main__":
    unittest.main()
