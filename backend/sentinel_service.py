"""Background-service installer for the Sentinel worker (v9.1, Linux-first).

On Linux, Sentinel runs as a **systemd user service** — the clean analogue
of the Windows Scheduled Task. `systemctl --user` needs no root, matching
the no-UAC property of the Windows version.

  Unit file: ~/.config/systemd/user/luatools-sentinel.service
  Runs:      <plugin>/.venv/bin/python3  <plugin>/backend/sentinel_worker.py

The service starts with the user's graphical session, which is exactly when
Steam might be launched — so Sentinel is watching whenever it could matter.
(For watching across the full boot, the user can opt into linger separately
with `loginctl enable-linger` — not done automatically.)

Windows Scheduled Task logic is retained but shelved behind _IS_WINDOWS.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List

from logger import logger

_IS_WINDOWS = sys.platform.startswith("win")

# Linux
_UNIT_NAME = "luatools-sentinel.service"
# Windows (shelved)
_TASK_NAME = "LuaToolsSentinel"


# ── Shared helpers ────────────────────────────────────────────────────────

def _plugin_dir() -> str:
    from paths import get_plugin_dir
    return get_plugin_dir()


def _worker_script() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "sentinel_worker.py")


def _venv_python() -> str:
    """Return the venv python if it exists, else the current interpreter."""
    venv_py = os.path.join(_plugin_dir(), ".venv", "bin", "python3")
    if os.path.isfile(venv_py):
        return venv_py
    return sys.executable or "python3"


# ── Linux: systemd user service ───────────────────────────────────────────

def _systemctl_available() -> bool:
    return shutil.which("systemctl") is not None


def _run_systemctl(args: List[str], timeout: int = 20) -> Dict[str, Any]:
    """Run `systemctl --user ...`. Returns {success, code, output, error}."""
    try:
        proc = subprocess.run(
            ["systemctl", "--user"] + args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout,
        )
        return {
            "success": proc.returncode == 0,
            "code": proc.returncode,
            "output": (proc.stdout or "").strip(),
            "error": (proc.stderr or "").strip(),
        }
    except FileNotFoundError:
        return {"success": False, "code": -1, "error": "systemctl not found"}
    except subprocess.TimeoutExpired:
        return {"success": False, "code": -2, "error": "systemctl timed out"}
    except Exception as exc:
        return {"success": False, "code": -3, "error": str(exc)}


def _unit_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")


def _unit_path() -> str:
    return os.path.join(_unit_dir(), _UNIT_NAME)


def _unit_file_content() -> str:
    py = _venv_python()
    worker = _worker_script()
    return (
        "[Unit]\n"
        "Description=LuaTools Sentinel - background game-activation watcher\n"
        "After=default.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={py} {worker}\n"
        "Restart=on-failure\n"
        "RestartSec=30\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _linux_status() -> Dict[str, Any]:
    if not _systemctl_available():
        return {
            "success": True, "supported": False,
            "message": "systemd (systemctl) not available on this system",
        }

    installed = os.path.isfile(_unit_path())
    info: Dict[str, Any] = {
        "success": True, "supported": True, "installed": installed,
        "unitName": _UNIT_NAME, "unitPath": _unit_path(),
    }
    if installed:
        enabled = _run_systemctl(["is-enabled", _UNIT_NAME])
        active = _run_systemctl(["is-active", _UNIT_NAME])
        info["enabled"] = enabled.get("output", "") == "enabled"
        info["enabledState"] = enabled.get("output", "") or enabled.get("error", "")
        info["active"] = active.get("output", "") == "active"
        info["activeState"] = active.get("output", "") or active.get("error", "")
    else:
        info["message"] = "Sentinel service not installed"
    return info


def _linux_install() -> Dict[str, Any]:
    if not _systemctl_available():
        return {"success": False, "error": "systemd not available on this system"}

    worker = _worker_script()
    if not os.path.isfile(worker):
        return {"success": False, "error": f"worker script missing: {worker}"}

    try:
        os.makedirs(_unit_dir(), exist_ok=True)
        with open(_unit_path(), "w", encoding="utf-8") as f:
            f.write(_unit_file_content())
    except Exception as exc:
        return {"success": False, "error": f"failed to write unit file: {exc}"}

    reload_res = _run_systemctl(["daemon-reload"])
    if not reload_res["success"]:
        return {"success": False, "error": f"daemon-reload failed: {reload_res.get('error')}"}

    enable_res = _run_systemctl(["enable", "--now", _UNIT_NAME])
    if not enable_res["success"]:
        return {"success": False,
                "error": f"enable failed: {enable_res.get('error')}",
                "unitPath": _unit_path()}

    logger.log(f"sentinel_service: installed + started systemd unit {_UNIT_NAME}")
    return {
        "success": True,
        "unitName": _UNIT_NAME,
        "unitPath": _unit_path(),
        "interpreter": _venv_python(),
        "message": "Sentinel service installed and started. "
                   "It will auto-start with your session.",
    }


def _linux_uninstall() -> Dict[str, Any]:
    if not _systemctl_available():
        return {"success": False, "error": "systemd not available"}

    # Stop + disable; ignore errors if it was never enabled
    _run_systemctl(["disable", "--now", _UNIT_NAME])

    removed = False
    if os.path.isfile(_unit_path()):
        try:
            os.remove(_unit_path())
            removed = True
        except Exception as exc:
            return {"success": False, "error": f"failed to remove unit: {exc}"}

    _run_systemctl(["daemon-reload"])
    logger.log(f"sentinel_service: removed systemd unit {_UNIT_NAME}")
    return {
        "success": True,
        "unitName": _UNIT_NAME,
        "message": "Sentinel service removed" if removed
                   else "Service was not installed",
    }


def _linux_start_now() -> Dict[str, Any]:
    if not _systemctl_available():
        return {"success": False, "error": "systemd not available"}
    if not os.path.isfile(_unit_path()):
        return {"success": False, "error": "service not installed"}
    res = _run_systemctl(["start", _UNIT_NAME])
    if res["success"]:
        return {"success": True, "message": "Sentinel service started"}
    return {"success": False, "error": res.get("error", "start failed")}


# ── Windows: Scheduled Task (shelved) ─────────────────────────────────────

def _run_schtasks(args: list, timeout: int = 30) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            ["schtasks"] + args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout,
            creationflags=0x08000000 if _IS_WINDOWS else 0,
        )
        return {"success": proc.returncode == 0, "code": proc.returncode,
                "output": proc.stdout, "error": proc.stderr}
    except Exception as exc:
        return {"success": False, "code": -1, "error": str(exc)}


def _windows_status() -> Dict[str, Any]:
    result = _run_schtasks(["/Query", "/TN", _TASK_NAME, "/FO", "LIST"])
    if not result["success"]:
        err = (result.get("error") or "").lower()
        if "cannot find" in err:
            return {"success": True, "supported": True, "installed": False,
                    "message": "Scheduled task not installed"}
        return {"success": False, "supported": True, "installed": False,
                "error": result.get("error", "query failed")}
    info: Dict[str, Any] = {"success": True, "supported": True, "installed": True}
    for line in (result.get("output") or "").splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            if k.strip() in ("Status", "Next Run Time", "Last Run Time"):
                info[k.strip()] = v.strip()
    return info


# ── Public IPC — dispatches by platform ───────────────────────────────────

def get_service_status(contentScriptQuery: str = "") -> str:
    """Status of the Sentinel background service (systemd unit on Linux)."""
    try:
        info = _windows_status() if _IS_WINDOWS else _linux_status()
        return json.dumps(info)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def install_service(contentScriptQuery: str = "") -> str:
    """Install + enable the Sentinel background service.

    Linux: writes a systemd user unit and `systemctl --user enable --now`.
    No root required.
    """
    try:
        if _IS_WINDOWS:
            return json.dumps({"success": False,
                               "error": "Windows build is shelved"})
        return json.dumps(_linux_install())
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def uninstall_service(contentScriptQuery: str = "") -> str:
    """Stop, disable and remove the Sentinel background service."""
    try:
        if _IS_WINDOWS:
            return json.dumps({"success": False,
                               "error": "Windows build is shelved"})
        return json.dumps(_linux_uninstall())
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


def start_service_now(contentScriptQuery: str = "") -> str:
    """Start the Sentinel service immediately."""
    try:
        if _IS_WINDOWS:
            return json.dumps({"success": False,
                               "error": "Windows build is shelved"})
        return json.dumps(_linux_start_now())
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
