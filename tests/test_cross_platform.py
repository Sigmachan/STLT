"""Cross-platform guards: Windows-only APIs must not run on Linux/macOS.

These are source-level checks (the modules pull in heavy deps that aren't worth
stubbing) over the load-bearing invariant Kira hit: `winreg` is Windows-only and
must never be attempted off Windows, and Linux must have a real fallback.
"""

import os
import re
import unittest

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")


def _read(rel):
    with open(os.path.join(BACKEND, rel), encoding="utf-8") as f:
        return f.read()


class TestCrossPlatform(unittest.TestCase):

    def test_language_detection_gates_winreg_and_has_linux_fallback(self):
        src = _read("settings/manager.py")
        # winreg must be reached only on Windows.
        self.assertIn('os.name == "nt"', src,
                      "Steam-language detection no longer gates winreg behind Windows")
        # ...and there must be a non-winreg path for Linux/macOS.
        self.assertIn("_steam_language_from_vdf", src,
                      "Linux/macOS Steam-language fallback (registry.vdf) is missing")
        self.assertIn("registry.vdf", src)

    def test_registry_steam_path_is_windows_gated(self):
        src = _read("paths.py")
        # The registry Steam-path lookup must bail out early off Windows.
        self.assertTrue(
            re.search(r"_steam_path_from_registry[\s\S]{0,200}_IS_WINDOWS", src),
            "registry Steam-path lookup is not guarded behind a Windows check",
        )


if __name__ == "__main__":
    unittest.main()
