"""Drive ACCELA as the Linux game downloader.

This restores the mechanism upstream LuaToolsLinux actually uses — and which
STLT had dropped. Upstream downloads the manifest/lua bundle (a zip) and hands
it to ACCELA's run.sh; ACCELA then downloads the game. STLT only wrote the
.lua into stplug-in (relying on SLSsteam interception), which is why downloads
didn't actually start on ACCELA setups.

We do BOTH now: keep installing the .lua (so SLSsteam users still work) AND, if
ACCELA is present, hand it the bundle so it downloads the game.

Faithfully ports upstream's hard-won environment handling: ACCELA is a Qt6 app
that conflicts with Steam's bundled libraries, so LD_LIBRARY_PATH / LD_PRELOAD /
STEAM_RUNTIME are stripped before launching it (otherwise it crashes / spams
ld.so errors).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Optional

try:
    from logger import logger
except Exception:  # pragma: no cover
    class _L:
        def log(self, *a): pass
        def warn(self, *a): pass
        def error(self, *a): pass
    logger = _L()

# Env vars that must be removed before launching ACCELA (Steam/Millennium
# inject these and they break ACCELA's Qt6 runtime).
_CONFLICTING_ENV = ("LD_LIBRARY_PATH", "LD_PRELOAD", "STEAM_RUNTIME")


def _override_file() -> str:
    return os.path.join(os.path.dirname(__file__), "data", "launcher_path.txt")


def get_launcher_path() -> Optional[str]:
    """Resolve ACCELA's run.sh: explicit override file → detected install →
    default location. Returns None if ACCELA can't be found."""
    # 1. explicit user override (data/launcher_path.txt)
    try:
        ov = _override_file()
        if os.path.isfile(ov):
            with open(ov, encoding="utf-8") as f:
                p = f.read().strip()
            if p and os.path.exists(p):
                return p
    except Exception:
        pass
    # 2. detected ACCELA install
    try:
        from linux_platform import get_accela_dir
        d = get_accela_dir()
        if d:
            run = os.path.join(d, "run.sh")
            if os.path.isfile(run):
                return run
    except Exception:
        pass
    # 3. default location
    default = os.path.expanduser("~/.local/share/ACCELA/run.sh")
    return default if os.path.isfile(default) else None


def set_launcher_path(path: str) -> bool:
    """Persist an explicit launcher path override."""
    try:
        ov = _override_file()
        os.makedirs(os.path.dirname(ov), exist_ok=True)
        with open(ov, "w", encoding="utf-8") as f:
            f.write((path or "").strip())
        return True
    except Exception as exc:
        logger.warn(f"accela_launcher: could not save launcher path: {exc}")
        return False


def is_available() -> bool:
    return bool(get_launcher_path())


def get_status() -> Dict[str, Any]:
    """Diagnostic snapshot for the UI / health: is ACCELA found, and where."""
    path = get_launcher_path()
    return {
        "available": bool(path),
        "path": path or "",
        "override": _override_file() if os.path.isfile(_override_file()) else "",
    }


def _sweep_old_intakes(max_age_seconds: int = 3600) -> None:
    """Delete stale temp bundles we handed to ACCELA on past runs.

    Because ACCELA runs non-blocking we can't delete the copy immediately
    (ACCELA may still be reading it), so each run sweeps copies older than an
    hour. Self-maintaining, no leak.
    """
    import glob
    import time
    try:
        pattern = os.path.join(tempfile.gettempdir(), "luatools_accela_*.zip")
        now = time.time()
        for old in glob.glob(pattern):
            try:
                if now - os.path.getmtime(old) > max_age_seconds:
                    os.remove(old)
            except Exception:
                pass
    except Exception:
        pass


def _clean_env() -> Dict[str, str]:
    env = os.environ.copy()
    for k in _CONFLICTING_ENV:
        env.pop(k, None)
    return env


def run_with_zip(zip_path: str, block: bool = False,
                 timeout: Optional[int] = None) -> Dict[str, Any]:
    """Hand the downloaded bundle to ACCELA so it downloads the game.

    Non-blocking by default (so activation stays responsive while ACCELA
    downloads in the background). ACCELA is given its OWN copy of the zip so the
    caller can safely delete the original without racing ACCELA.

    Returns {invoked, blocked, reason?, returncode?}.
    """
    launcher = get_launcher_path()
    if not launcher:
        return {"invoked": False, "reason": "ACCELA not found"}
    if not zip_path or not os.path.isfile(zip_path):
        return {"invoked": False, "reason": "bundle missing"}

    # Self-maintaining cleanup of past runs' temp copies (no /tmp leak).
    _sweep_old_intakes()

    # Hand ACCELA its own copy so our cleanup can't race it.
    intake = zip_path
    try:
        tmp = tempfile.NamedTemporaryFile(prefix="luatools_accela_",
                                          suffix=".zip", delete=False)
        tmp.close()
        shutil.copyfile(zip_path, tmp.name)
        intake = tmp.name
    except Exception:
        intake = zip_path

    try:
        if not os.access(launcher, os.X_OK):
            try:
                os.chmod(launcher, 0o755)
            except Exception:
                pass
        proc = subprocess.Popen(
            [launcher, intake],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=_clean_env(),
        )
        logger.log(f"accela_launcher: handed bundle to ACCELA ({launcher})")
        if block:
            out, err = proc.communicate(timeout=timeout)
            if out:
                logger.log(f"accela_launcher: ACCELA out: {out[:200]}")
            if err:
                logger.warn(f"accela_launcher: ACCELA err: {err[:200]}")
            return {"invoked": True, "blocked": True, "returncode": proc.returncode}
        return {"invoked": True, "blocked": False}
    except Exception as exc:
        logger.error(f"accela_launcher: failed to run ACCELA: {exc}")
        return {"invoked": False, "reason": str(exc)}
