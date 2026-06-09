"""ui_injector self-heal: injection is idempotent, removal is clean, and the
steam.sh repair never fires without explicit confirm."""

import os
import tempfile
import unittest

import _bootstrap  # noqa: F401


SAMPLE_INDEX = (
    "<html><head><title>Steam</title></head>\n"
    "<body>\n  <div id='root'></div>\n</body></html>\n"
)


class TestUiInjector(unittest.TestCase):

    def setUp(self):
        import importlib, ui_injector
        importlib.reload(ui_injector)
        self.ui = ui_injector
        self.tmp = tempfile.mkdtemp()
        # Build a fake steam root with steamui/index.html
        self.root = os.path.join(self.tmp, ".local", "share", "Steam")
        os.makedirs(os.path.join(self.root, "steamui"), exist_ok=True)
        self.index = os.path.join(self.root, "steamui", "index.html")
        open(self.index, "w", encoding="utf-8").write(SAMPLE_INDEX)
        # Point the injector's candidate roots at our fake root only
        self.ui._candidate_steam_roots = lambda: [self.root]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _inject(self):
        return self.ui.ensure_ui_injection(inline=False)

    def test_injects_marker_block(self):
        res = self._inject()
        self.assertEqual(res["roots_patched"], 1)
        html = open(self.index, encoding="utf-8").read()
        self.assertIn(self.ui.MARKER_START, html)
        self.assertIn(self.ui.MARKER_END, html)

    def test_injection_is_idempotent(self):
        self._inject()
        html1 = open(self.index, encoding="utf-8").read()
        res2 = self._inject()
        html2 = open(self.index, encoding="utf-8").read()
        # No duplicate marker blocks
        self.assertEqual(html2.count(self.ui.MARKER_START), 1,
                         "re-injection must not duplicate the block")
        # Second run reports nothing newly patched (already up to date)
        self.assertEqual(res2["roots_patched"], 0)
        self.assertEqual(html1, html2)

    def test_remove_is_clean(self):
        self._inject()
        self.ui.remove_ui_injection()
        html = open(self.index, encoding="utf-8").read()
        self.assertNotIn(self.ui.MARKER_START, html)
        self.assertNotIn(self.ui.MARKER_END, html)
        # Original markup intact
        self.assertIn("<div id='root'></div>", html)

    def test_inject_then_remove_restores_original(self):
        original = open(self.index, encoding="utf-8").read()
        self._inject()
        self.ui.remove_ui_injection()
        restored = open(self.index, encoding="utf-8").read()
        self.assertEqual(restored.strip(), original.strip(),
                         "inject+remove should round-trip to the original page")

    def test_steam_sh_repair_refuses_without_confirm(self):
        res = self.ui.repair_steam_launcher(confirm=False)
        self.assertFalse(res.get("success"))
        self.assertIn("confirm", res.get("error", "").lower(),
                      "steam.sh repair must refuse without explicit confirm")


if __name__ == "__main__":
    unittest.main()
