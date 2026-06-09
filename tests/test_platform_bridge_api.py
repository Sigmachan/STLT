"""Millennium 3.0 API surface guard for the standalone bridge fallback."""

import sys
import unittest

import _bootstrap  # noqa: F401


class TestPlatformBridgeApi(unittest.TestCase):

    def setUp(self):
        import importlib
        import platform_bridge
        importlib.reload(platform_bridge)
        self.pb = platform_bridge

    def test_fallback_exposes_documented_millennium_3_api(self):
        expected = {
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
        }
        missing = sorted(name for name in expected if not hasattr(self.pb.Millennium, name))
        self.assertEqual(missing, [], "standalone bridge fallback missing Millennium 3.0 API: " + ", ".join(missing))

    def test_install_standalone_shims_registers_the_full_api_surface(self):
        # Reset sys.modules so the shim can repopulate the fallback cleanly.
        sys.modules.pop("Millennium", None)
        sys.modules.pop("PluginUtils", None)

        self.pb.install_standalone_shims()

        mod = sys.modules["Millennium"]
        expected = {
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
        }
        missing = sorted(name for name in expected if not hasattr(mod, name))
        self.assertEqual(missing, [], "shim did not register full Millennium 3.0 API surface: " + ", ".join(missing))


if __name__ == "__main__":
    unittest.main()
