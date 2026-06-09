"""accela_launcher: path resolution, availability gating, the env-stripping
that keeps ACCELA from crashing, and that run_with_zip actually invokes it."""

import os
import tempfile
import unittest

import _bootstrap  # noqa: F401


class _FakeProc:
    def __init__(self, *a, **k):
        self.returncode = 0
        self.args = a

    def communicate(self, timeout=None):
        return ("ok", "")


class TestAccelaLauncher(unittest.TestCase):

    def setUp(self):
        import importlib, accela_launcher
        importlib.reload(accela_launcher)
        self.la = accela_launcher
        self.tmp = tempfile.mkdtemp()
        # Redirect the override file into our temp dir
        self.override = os.path.join(self.tmp, "launcher_path.txt")
        self.la._override_file = lambda: self.override
        # A fake ACCELA run.sh
        self.run_sh = os.path.join(self.tmp, "run.sh")
        with open(self.run_sh, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.run_sh, 0o755)
        # Capture subprocess invocations instead of really launching
        self.calls = []
        def fake_popen(args, **kw):
            self.calls.append({"args": args, "env": kw.get("env")})
            return _FakeProc()
        self.la.subprocess.Popen = fake_popen

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_override_path_resolution(self):
        with open(self.override, "w") as f:
            f.write(self.run_sh)
        self.assertEqual(self.la.get_launcher_path(), self.run_sh)
        self.assertTrue(self.la.is_available())

    def test_set_launcher_path_persists(self):
        self.assertTrue(self.la.set_launcher_path(self.run_sh))
        self.assertEqual(self.la.get_launcher_path(), self.run_sh)

    def test_clean_env_strips_conflicting_vars(self):
        os.environ["LD_PRELOAD"] = "/x/overlay.so"
        os.environ["LD_LIBRARY_PATH"] = "/steam/libs"
        os.environ["STEAM_RUNTIME"] = "1"
        try:
            env = self.la._clean_env()
            self.assertNotIn("LD_PRELOAD", env)
            self.assertNotIn("LD_LIBRARY_PATH", env)
            self.assertNotIn("STEAM_RUNTIME", env)
        finally:
            for k in ("LD_PRELOAD", "LD_LIBRARY_PATH", "STEAM_RUNTIME"):
                os.environ.pop(k, None)

    def test_run_with_zip_gated_when_unavailable(self):
        # no override, no default → not available
        res = self.la.run_with_zip("/whatever.zip")
        self.assertFalse(res["invoked"])

    def test_run_with_zip_invokes_with_clean_env(self):
        self.la.set_launcher_path(self.run_sh)
        os.environ["LD_PRELOAD"] = "/x/overlay.so"
        zip_path = os.path.join(self.tmp, "bundle.zip")
        with open(zip_path, "wb") as f:
            f.write(b"PK\x03\x04fake")
        try:
            res = self.la.run_with_zip(zip_path)
        finally:
            os.environ.pop("LD_PRELOAD", None)
        self.assertTrue(res["invoked"])
        self.assertEqual(len(self.calls), 1)
        # launched the run.sh with a zip argument
        self.assertEqual(self.calls[0]["args"][0], self.run_sh)
        self.assertTrue(str(self.calls[0]["args"][1]).endswith(".zip"))
        # env was cleaned
        self.assertNotIn("LD_PRELOAD", self.calls[0]["env"])

    def test_run_with_zip_missing_bundle(self):
        self.la.set_launcher_path(self.run_sh)
        res = self.la.run_with_zip(os.path.join(self.tmp, "nope.zip"))
        self.assertFalse(res["invoked"])

    def test_get_status(self):
        self.la.set_launcher_path(self.run_sh)
        st = self.la.get_status()
        self.assertTrue(st["available"])
        self.assertEqual(st["path"], self.run_sh)

    def test_sweep_removes_only_stale_temp_copies(self):
        import tempfile as _tf, time
        # one stale, one fresh temp bundle in the system temp dir
        stale = os.path.join(_tf.gettempdir(), "luatools_accela_STALE.zip")
        fresh = os.path.join(_tf.gettempdir(), "luatools_accela_FRESH.zip")
        open(stale, "w").close()
        open(fresh, "w").close()
        old = time.time() - 7200  # 2h ago
        os.utime(stale, (old, old))
        try:
            self.la._sweep_old_intakes(max_age_seconds=3600)
            self.assertFalse(os.path.exists(stale), "stale temp copy should be swept")
            self.assertTrue(os.path.exists(fresh), "fresh temp copy must be kept")
        finally:
            for p in (stale, fresh):
                try:
                    os.remove(p)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
