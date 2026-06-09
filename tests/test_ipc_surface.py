"""Trust floor for 10.0: the canonical IPC surface must stay wired.

These are the backend methods the "it just works" path depends on. If a refactor
removes or renames one, the frontend silently loses a capability — so guard them
at the source level (cheap, and catches the regression immediately).
"""

import os
import unittest

import _bootstrap  # noqa: F401
from _bootstrap import _BACKEND

_MAIN = os.path.join(_BACKEND, "main.py")

# IPC name -> why it's load-bearing for the 10.0 happy path
CANONICAL_IPCS = {
    "AutoFinalizeActivation": "auto-pilot spine: setup + download after activation",
    "StartDownloadNoRestart": "no-restart download trigger (manual fallback)",
    "GetLinuxHealthReport": "diagnostics / first-run setup checks",
    "SetSlssteamPlayNotOwned": "one-click + auto fix for the #1 download blocker",
    "SelfHealUI": "self-healing UI injection (user-confirmed)",
    "BatchHealthScan": "per-game health audit",
    "SmartRestartSteam": "fallback restart for config.vdf-bound changes",
    "GetSetupState": "first-run assistant: ready / auto-fixable / blockers",
    "RunSetup": "first-run assistant: apply the safe fixes",
    "MarkSetupSeen": "first-run assistant: remember it's been seen",
    "SelfHeal": "quiet self-healing of regressed setup on load",
}


class TestIpcSurface(unittest.TestCase):

    def setUp(self):
        with open(_MAIN, encoding="utf-8") as f:
            self.src = f.read()

    def test_canonical_ipcs_present(self):
        missing = [name for name in CANONICAL_IPCS
                   if f"def {name}(" not in self.src]
        self.assertEqual(missing, [],
                         "canonical IPC(s) missing from main.py — the happy path "
                         "loses a capability: " + ", ".join(missing))

    def test_ipcs_accept_contentscriptquery(self):
        # Millennium passes contentScriptQuery to every IPC; a handler that omits
        # it will throw at call time. Guard the load-bearing ones.
        import re
        for name in ("AutoFinalizeActivation", "StartDownloadNoRestart",
                     "GetLinuxHealthReport"):
            m = re.search(r"def %s\(([^)]*)\)" % name, self.src)
            self.assertIsNotNone(m, f"{name} not found")
            self.assertIn("contentScriptQuery", m.group(1),
                          f"{name} must accept contentScriptQuery")


if __name__ == "__main__":
    unittest.main()
