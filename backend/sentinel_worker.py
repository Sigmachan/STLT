"""Standalone Sentinel worker — runs SentinelDaemon outside of the Steam process.

Designed to be installed as a Windows Scheduled Task that runs at user login.
Lets Sentinel detect new games + check for staleness even when Steam isn't open.

Usage:
    python sentinel_worker.py            # runs the daemon, blocks
    python sentinel_worker.py --once     # single poll cycle, exit
    python sentinel_worker.py --status   # print status JSON and exit

Logs to:
    <plugin>/backend/data/sentinel_worker.log
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

# Make sure the backend dir is on sys.path so imports resolve when run
# as a standalone script.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


def _log_path() -> str:
    from paths import data_path
    return data_path("sentinel_worker.log")


def _log(msg: str) -> None:
    """Append to worker log + print to stdout (visible if run manually)."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _run_once() -> int:
    """Execute one poll cycle and exit."""
    try:
        from sentinel import get_sentinel
        daemon = get_sentinel()
        daemon._load_config()
        daemon._load_state()
        if not daemon.config.enabled:
            _log("Sentinel disabled in config — exiting")
            return 0
        daemon._poll_cycle()
        _log(f"Single poll cycle complete. seen_appids={len(daemon.state.seen_appids)}")
        return 0
    except Exception as exc:
        _log(f"ERROR: {exc}")
        traceback.print_exc()
        return 1


def _run_forever() -> int:
    """Block + run the poll loop. Exit on Ctrl-C."""
    try:
        from sentinel import get_sentinel
        daemon = get_sentinel()
        if not daemon.start():
            _log("Sentinel failed to start (likely disabled in config)")
            return 1
        _log("Sentinel worker started — polling every "
             f"{daemon.config.poll_interval}s")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            _log("Ctrl-C received — stopping daemon")
            daemon.stop()
            return 0
    except Exception as exc:
        _log(f"ERROR: {exc}")
        traceback.print_exc()
        return 1


def _print_status() -> int:
    try:
        from sentinel import get_sentinel_status
        print(get_sentinel_status())
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LuaTools Sentinel standalone worker"
    )
    parser.add_argument("--once", action="store_true",
                        help="Run a single poll cycle and exit")
    parser.add_argument("--status", action="store_true",
                        help="Print Sentinel status JSON and exit")
    args = parser.parse_args()

    if args.status:
        return _print_status()
    if args.once:
        return _run_once()
    return _run_forever()


if __name__ == "__main__":
    sys.exit(main())
