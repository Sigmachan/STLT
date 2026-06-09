"""The .lua activation contract.

This is the most important test file: it codifies the exact bugs that broke
downloads in this project's history, so they cannot silently return.

Contract (matches upstream LuaToolsLinux behaviour):
  - Processing a downloaded .lua keeps EVERY addappid() line (keyless ones are
    ownership grants / DLC unlocks, NOT stubs).
  - Active setManifestid() lines are commented out (use-latest).
  - Comments and depot keys are preserved verbatim.
  - The build-from-scratch ManifestHub path must NOT finalize an empty-key
    activation (addappid(x, y, "")).
"""

import os
import re
import unittest

import _bootstrap  # noqa: F401  (installs path + stubs)
from _bootstrap import FIXTURES, _BACKEND


def process_lua(text: str) -> str:
    """Reference implementation of the contract — mirrors downloads.py /
    upstream: comment active setManifestid, keep everything else."""
    out = []
    for line in text.splitlines(True):
        if re.match(r"^\s*setManifestid\(", line) and not re.match(r"^\s*--", line):
            line = re.sub(r"^(\s*)", r"\1--", line)
        out.append(line)
    return "".join(out)


def read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return f.read()


class TestLuaContract(unittest.TestCase):

    def test_fixture_590830_has_ownership_and_keys(self):
        text = read_fixture("590830.lua")
        # base ownership grant present
        self.assertRegex(text, r"(?m)^addappid\(590830\)$",
                         "base ownership line missing from fixture")
        # at least one 64-char depot key present
        self.assertTrue(re.search(r'addappid\(\d+,0,"[a-fA-F0-9]{64}"', text),
                        "expected depot keys in fixture")

    def test_processing_keeps_all_addappid(self):
        text = read_fixture("2483190.lua")
        before = len(re.findall(r"^\s*addappid\(", text, re.M))
        processed = process_lua(text)
        after = len(re.findall(r"^\s*addappid\(", processed, re.M))
        self.assertEqual(before, after,
                         "processing must not drop ANY addappid line "
                         "(keyless ones are ownership/DLC grants)")

    def test_processing_keeps_keyless_dlc_unlocks(self):
        # 2483190.lua has many keyless DLC addappid() lines — all must survive.
        text = read_fixture("2483190.lua")
        processed = process_lua(text)
        for dlc in ("4439240", "4439250", "4520350", "4562050"):
            self.assertIn(f"addappid({dlc})", processed,
                          f"DLC unlock {dlc} was stripped")

    def test_processing_comments_setmanifestid(self):
        text = read_fixture("590830.lua")
        processed = process_lua(text)
        # No ACTIVE (uncommented) setManifestid should remain.
        active = [ln for ln in processed.splitlines()
                  if re.match(r"^\s*setManifestid\(", ln)]
        self.assertEqual(active, [], "active setManifestid lines must be commented")
        # But the (now-commented) ids are still present.
        self.assertIn("--setManifestid(590831", processed)

    def test_processing_preserves_keys_verbatim(self):
        text = read_fixture("590830.lua")
        processed = process_lua(text)
        for key in ("d9b26387a4295869ed1ce85b03f90e6fc26c20abfb6662f36abd172536b17c9e",
                    "5368f87f9235f5cd8144e9eea13824133defa90e4a90c2d478fac61ca5cfcc8a"):
            self.assertIn(key, processed, "depot key was altered/dropped")

    def test_processing_is_idempotent(self):
        text = read_fixture("2483190.lua")
        once = process_lua(text)
        twice = process_lua(once)
        self.assertEqual(once, twice, "processing must be idempotent")

    # ── Regression guards on the actual source ──────────────────────────────

    def test_downloads_has_no_stub_filter(self):
        """The over-aggressive 'stub' filter that stripped keyless addappid
        lines must never come back. Guards against re-introducing the bug by
        detecting the dangerous PATTERN — a 64-hex-key presence check whose
        failure branch skips (continue) the line — not merely the word 'stub'."""
        src = open(os.path.join(_BACKEND, "downloads.py"), encoding="utf-8").read()
        # The original bug: `if not key_match: ... continue` inside the lua
        # line loop, where key_match tested for a 64-char depot key. That
        # skipped every keyless ownership/DLC line.
        dangerous = re.search(
            r'(?:key_match|re\.search)[^\n]*\{64\}[^\n]*\n'  # a 64-hex key test
            r'(?:[^\n]*\n){0,3}?'                            # within a few lines
            r'\s*continue\b',                                # ...then skip the line
            src)
        self.assertIsNone(
            dangerous,
            "downloads.py skips lua lines that lack a 64-hex depot key — the "
            "keyless-addappid stub filter has returned and will break downloads")
        # The explicit filter comment must also be gone.
        self.assertNotIn("Stub line", src,
                         "the keyless-addappid stub-filter comment has returned")

    def test_manifesthub_does_not_finalize_empty_keys(self):
        """The ManifestHub API path must NOT finalize an empty-key activation;
        it should defer to a keyed source (return False after caching)."""
        src = open(os.path.join(_BACKEND, "downloads.py"), encoding="utf-8").read()
        # The empty-key builder may still exist for caching, but it must be
        # followed by a 'defer to keyed source' return, not finalize(). (The
        # phrase is split across f-string lines in the source, so match a
        # stable fragment.)
        self.assertIn("deferring activation to a", src,
                      "manifesthub empty-key defer logic missing — the empty-key "
                      "activation bug may have returned")


if __name__ == "__main__":
    unittest.main()
