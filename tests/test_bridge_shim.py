"""Source guards for the Millennium 3.0 bridge shim (luatools_bridge.js).

The shim is the linchpin of the 3.0 architecture: it redirects
Millennium.callServerMethod to the local Python HTTP bridge. We can't run it
headlessly here (no Steam, no server), so these are structural guards over the
load-bearing behavior: it must retry while the backend is still starting, and
it must NOT retry once the server has actually answered.
"""

import os
import unittest

BRIDGE = os.path.join(os.path.dirname(__file__), "..", "public", "luatools_bridge.js")


class TestBridgeShim(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(BRIDGE, encoding="utf-8") as f:
            cls.src = f.read()

    def test_targets_local_bridge(self):
        self.assertIn("127.0.0.1:38495", self.src)
        self.assertIn("callServerMethod", self.src)

    def test_retries_on_startup_race(self):
        # Must retry transient connection failures (first-run venv/pip window).
        self.assertIn("MAX_ATTEMPTS", self.src,
                      "bridge shim lost its startup-race retry")

    def test_does_not_retry_after_server_answered(self):
        # A response that reached the server must be marked so it is NOT retried
        # (retrying a landed non-idempotent call would double-fire it).
        self.assertIn("_reachedServer", self.src,
                      "bridge shim no longer distinguishes landed vs transient failures")


if __name__ == "__main__":
    unittest.main()
