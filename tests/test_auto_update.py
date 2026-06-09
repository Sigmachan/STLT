"""Auto-updater safety: the version comparison must be downgrade-proof, the
config must point at THIS fork (not a foreign repo), and the upstream-proxy
fallbacks (which would pull a different codebase) must be gone."""

import json
import os
import sys
import unittest

import _bootstrap  # noqa: F401

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")


def _load_utils():
    # utils imports `backend_path`/`get_plugin_dir` from paths; the shared stub
    # doesn't define them, so add no-op versions locally before importing.
    import paths as _paths
    if not hasattr(_paths, "backend_path"):
        _paths.backend_path = lambda *a, **k: ""
    if not hasattr(_paths, "get_plugin_dir"):
        _paths.get_plugin_dir = lambda *a, **k: ""
    import importlib
    import utils
    return importlib.reload(utils)


class TestDowngradeProofComparison(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.u = _load_utils()

    def test_older_release_never_wins(self):
        # Kira's exact scenario: GitHub release behind the local build.
        self.assertFalse(self.u.is_newer_version("7.2.2", "10.2.2"))
        self.assertFalse(self.u.is_newer_version("9.9.9", "10.0.0"))

    def test_equal_is_not_newer(self):
        self.assertFalse(self.u.is_newer_version("10.2.2", "10.2.2"))

    def test_prerelease_suffix_on_same_version_is_not_newer(self):
        # '10.2.2-dev5' normalizes to (10,2,2) == current -> no pointless update
        self.assertFalse(self.u.is_newer_version("10.2.2-dev5", "10.2.2"))

    def test_genuinely_newer_release_wins(self):
        self.assertTrue(self.u.is_newer_version("10.3.0", "10.2.2"))
        self.assertTrue(self.u.is_newer_version("v11.0.0", "10.2.2"))

    def test_blank_or_garbage_never_wins(self):
        self.assertFalse(self.u.is_newer_version("", "10.2.2"))
        self.assertFalse(self.u.is_newer_version("latest", "10.2.2"))
        self.assertFalse(self.u.is_newer_version(None, "10.2.2"))


class TestUpdateConfig(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(BACKEND, "update.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)

    def test_points_at_this_fork_not_upstream(self):
        gh = self.cfg.get("github", {})
        self.assertEqual((gh.get("owner") or "").lower(), "sigmachan")
        self.assertEqual((gh.get("repo") or "").upper(), "STLT")
        self.assertNotIn("madoiscool", json.dumps(self.cfg).lower(),
                         "config still references the upstream repo")

    def test_no_upstream_proxy_fallbacks_remain(self):
        with open(os.path.join(BACKEND, "auto_update.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("luatools.vercel.app/api/github-latest", src,
                         "upstream API-read proxy fallback still present")
        self.assertNotIn("api/get-plugin/", src,
                         "upstream download-proxy fallback still present")
        self.assertIn("is_newer_version", src,
                      "updater no longer uses the downgrade-proof comparison")


if __name__ == "__main__":
    unittest.main()
