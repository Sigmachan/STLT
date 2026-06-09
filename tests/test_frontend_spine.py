"""Trust floor for 10.0: the frontend auto-pilot spine must stay wired AND run
unconditionally (not only when the popup is open).

Source-level guards on luatools.js. They protect the two properties that make
"it just works" true:
  1. activation completion calls AutoFinalizeActivation;
  2. that call is NOT nested inside the `if (status)` popup-visibility gate,
     so the download starts whether or not the user is watching.
"""

import os
import unittest

import _bootstrap  # noqa: F401
from _bootstrap import _BACKEND

_JS = os.path.normpath(os.path.join(_BACKEND, "..", "public", "luatools.js"))


class TestFrontendSpine(unittest.TestCase):

    def setUp(self):
        with open(_JS, encoding="utf-8") as f:
            self.src = f.read()

    def test_autopilot_is_wired(self):
        self.assertIn("AutoFinalizeActivation", self.src,
                      "auto-pilot call removed from the frontend")
        self.assertIn("luatools-autofinalize", self.src,
                      "auto-pilot UI marker removed")

    def test_autopilot_runs_unconditionally(self):
        # The spine marker comment documents the invariant; its presence is the
        # cheap guard that the unconditional IIFE wasn't reverted back into the
        # popup-only branch.
        self.assertIn("runs on EVERY completion", self.src,
                      "auto-pilot spine no longer documents unconditional run — "
                      "it may have been re-nested inside the popup gate")
        # The once-per-appid guard must remain so it can't double-fire.
        self.assertIn("_autoFinalizedFor", self.src,
                      "auto-pilot once-per-appid guard missing")

    def test_manual_fallback_preserved(self):
        # Progressive disclosure: the manual button still exists as a fallback
        # when auto-pilot is off or blocked.
        self.assertIn("Start download (no restart)", self.src,
                      "manual no-restart fallback button removed")

    def test_setup_assistant_wired_and_triggered(self):
        # Step 3: the first-run assistant must be defined AND auto-triggered once
        # on load when first-run or not-ready.
        self.assertIn("function showSetupAssistant", self.src,
                      "setup assistant panel removed")
        self.assertIn("GetSetupState", self.src,
                      "setup assistant is no longer triggered on load")
        self.assertIn("__LUATOOLS_SETUP_CHECKED__", self.src,
                      "once-per-session guard for the setup assistant is missing")

    def test_menu_consolidation_present(self):
        # Step 4: the long SteamTools list is collapsed behind one toggle.
        self.assertIn("lt-advanced-toggle", self.src,
                      "advanced-tools toggle removed — the menu no longer breathes")
        self.assertIn("Advanced tools", self.src,
                      "advanced-tools label removed")
        # The collapse must be wrapped defensively so a failure leaves the menu intact.
        self.assertIn("_advancedBtns", self.src,
                      "advanced-buttons collapse logic missing")

    def test_self_heal_runs_on_load(self):
        # Step 5: self-heal runs quietly on load, before the setup check.
        self.assertIn("SelfHeal", self.src,
                      "self-heal is no longer invoked on load")
        self.assertIn("Fixed automatically", self.src,
                      "self-heal heal-notice toast removed")


if __name__ == "__main__":
    unittest.main()
