"""Regression test for the standalone Millennium fallback API surface.

Millennium 3.0 documents these on the runtime module; our standalone bridge
fallback must expose the same surface so backend code that targets the 3.0
contract never hits an AttributeError when running outside Millennium. (Per the
Millennium 3.0 review — keeps the stub semantics from silently drifting.)
"""

import importlib
import sys
import unittest

import _bootstrap  # noqa: F401

_DOCUMENTED = (
    "steam_path", "add_browser_js", "add_browser_css", "ready",
    "call_frontend_method", "version", "get_install_path",
    "remove_browser_module", "cmp_version", "is_plugin_enabled",
)


class TestPlatformBridgeFallbackAPI(unittest.TestCase):

    def setUp(self):
        # Force the FALLBACK path (no real Millennium / PluginUtils present).
        sys.modules.pop("Millennium", None)
        sys.modules.pop("PluginUtils", None)
        import platform_bridge
        self.pb = importlib.reload(platform_bridge)
        self.F = self.pb._MillenniumFallback

    def tearDown(self):
        sys.modules.pop("Millennium", None)
        sys.modules.pop("PluginUtils", None)

    def test_full_documented_surface_present(self):
        for m in _DOCUMENTED:
            self.assertTrue(hasattr(self.F, m),
                            f"standalone fallback is missing documented API: {m}")

    def test_cmp_version_returns_minus_one_zero_one(self):
        self.assertEqual(self.F.cmp_version("1.0.0", "2.0.0"), -1)
        self.assertEqual(self.F.cmp_version("2.0.0", "2.0.0"), 0)
        self.assertEqual(self.F.cmp_version("2.1.0", "2.0.9"), 1)
        # uneven lengths normalize correctly
        self.assertEqual(self.F.cmp_version("2", "2.0.0"), 0)

    def test_is_plugin_enabled_and_remove_module_contract(self):
        self.assertIs(self.F.is_plugin_enabled("whatever"), True)
        # real API returns a bool; fallback must too (not None)
        self.assertIs(self.F.remove_browser_module(123), True)

    def test_standalone_shims_register_full_surface(self):
        sys.modules.pop("Millennium", None)
        self.pb.install_standalone_shims()
        mod = sys.modules.get("Millennium")
        self.assertIsNotNone(mod)
        for attr in _DOCUMENTED:
            self.assertTrue(hasattr(mod, attr),
                            f"standalone shim did not register: {attr}")


if __name__ == "__main__":
    unittest.main()
