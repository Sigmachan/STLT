"""Steam Play (Proton) compatibility-tool mapping for Linux (v9.1).

Games activated via .lua manifests on Linux often fail to launch with
"error occurred while launching this game" / missing-executable, because
Steam has not assigned them a Steam Play compatibility tool (Proton). This
module writes CompatToolMapping entries into <Steam>/config/config.vdf so
activated games are launch-ready.

config.vdf structure (relevant section):
    "InstallConfigStore" { "Software" { "Valve" { "Steam" {
        "CompatToolMapping" {
            "<appid>" {
                "name"      "proton_experimental"
                "config"    ""
                "priority"  "250"
            }
        }
    } } } }

Safety:
  - Linux-only (Windows games run natively; no Proton needed).
  - Refuses to run while Steam is open (config.vdf is read at startup and
    rewritten at exit, so edits during a session are lost or clobbered).
  - Backs up config.vdf before every write.
  - Never clobbers an existing mapping unless force=True.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from logger import logger
from steam_utils import detect_steam_install_path
from steam_version import _steam_is_running

_IS_WINDOWS = sys.platform.startswith("win")
DEFAULT_TOOL = "proton_experimental"


def _config_vdf_path() -> str:
    steam = detect_steam_install_path()
    return os.path.join(steam, "config", "config.vdf") if steam else ""


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as exc:
        logger.warn(f"compat_tools: read failed: {exc}")
        return ""


def _write_with_backup(path: str, text: str) -> Tuple[bool, str]:
    try:
        backup = f"{path}.bak-{int(time.time())}"
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                original = f.read()
            with open(backup, "w", encoding="utf-8") as f:
                f.write(original)
        tmp = f"{path}.luatools-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True, backup
    except Exception as exc:
        logger.warn(f"compat_tools: write failed: {exc}")
        return False, ""


def _appid_entry(appid: int, tool: str, indent: str = "\t\t\t\t\t") -> str:
    """Build a CompatToolMapping appid block with Steam-style tab indentation."""
    inner = indent + "\t"
    return (
        f'{indent}"{appid}"\n'
        f'{indent}{{\n'
        f'{inner}"name"\t\t"{tool}"\n'
        f'{inner}"config"\t\t""\n'
        f'{inner}"priority"\t\t"250"\n'
        f'{indent}}}\n'
    )


class _MappingBlock:
    """Precisely-bounded CompatToolMapping block, indentation-aware."""
    __slots__ = ("body_start", "body_end", "body", "indent")

    def __init__(self, body_start: int, body_end: int, body: str, indent: str):
        self.body_start = body_start
        self.body_end = body_end
        self.body = body
        self.indent = indent


def _find_mapping_block(text: str) -> Optional[_MappingBlock]:
    """Locate the CompatToolMapping block by matching the closing brace at the
    SAME indentation as the opening key, so nested appid braces don't fool it."""
    # Opening: optional newline, captured tab indent, the key, then a brace
    m = re.search(r'\n(\t*)"CompatToolMapping"\s*\{[^\n]*\n', text)
    if not m:
        return None
    indent = m.group(1)
    body_start = m.end()
    # Closing brace at exactly the same indentation
    close = re.search(r'\n' + re.escape(indent) + r'\}', text[body_start:])
    if not close:
        return None
    body_end = body_start + close.start()
    return _MappingBlock(body_start, body_end, text[body_start:body_end], indent)


def _current_tool_for(text: str, appid: int) -> Optional[str]:
    """Return the currently-mapped tool name for appid, or None."""
    blk = _find_mapping_block(text)
    if not blk:
        return None
    # appid entries don't nest further, so non-greedy to first close is safe
    entry = re.search(
        rf'"\s*{appid}\s*"\s*\{{(.*?)\}}', blk.body, re.DOTALL
    )
    if not entry:
        return None
    name = re.search(r'"name"\s*"([^"]*)"', entry.group(1))
    return name.group(1) if name else None


def _set_mapping(text: str, appid: int, tool: str, force: bool) -> Tuple[str, str]:
    """Insert/replace the appid -> tool mapping. Returns (new_text, action)."""
    blk = _find_mapping_block(text)

    if not blk:
        # No CompatToolMapping block — create one inside the Steam section,
        # matching the indentation of the Steam block's children.
        steam_block = (re.search(r'\n(\t*)"Steam"\s*\{[^\n]*\n', text)
                       or re.search(r'\n(\t*)"steam"\s*\{[^\n]*\n', text))
        if not steam_block:
            return text, "no_steam_section"
        base = steam_block.group(1) + "\t"   # one level deeper than "Steam"
        insert_at = steam_block.end()
        block = (
            f'{base}"CompatToolMapping"\n{base}{{\n'
            + _appid_entry(appid, tool, base + "\t")
            + f'{base}}}\n'
        )
        new_text = text[:insert_at] + block + text[insert_at:]
        return new_text, "created_mapping"

    existing = _current_tool_for(text, appid)

    if existing is not None:
        if existing == tool:
            return text, "unchanged"
        if not force:
            return text, "exists_kept"  # don't clobber a user/other choice
        new_body = re.sub(
            rf'("\s*{appid}\s*"\s*\{{)(.*?)(\}})',
            lambda mo: mo.group(1) + re.sub(
                r'("name"\s*")[^"]*(")',
                lambda x: x.group(1) + tool + x.group(2),
                mo.group(2), count=1) + mo.group(3),
            blk.body, count=1, flags=re.DOTALL,
        )
        new_text = text[:blk.body_start] + new_body + text[blk.body_end:]
        return new_text, "replaced"

    # appid not present — append a fresh entry, indented one level into the body
    entry_indent = (blk.indent + "\t")
    new_body = blk.body.rstrip("\n\t ") + "\n" + _appid_entry(appid, tool, entry_indent)
    new_text = text[:blk.body_start] + new_body + text[blk.body_end:]
    return new_text, "inserted"


# ── Public IPC ────────────────────────────────────────────────────────────

def _guard_linux() -> Optional[str]:
    if _IS_WINDOWS:
        return json.dumps({"success": False, "platform": "windows",
                           "error": "Compat tools are a Linux feature; "
                                    "Windows games run natively."})
    return None


def set_compat_tool(appid: int = 0, tool: str = DEFAULT_TOOL,
                    force: bool = False, contentScriptQuery: str = "") -> str:
    """Set the Steam Play compatibility tool for one appid."""
    g = _guard_linux()
    if g:
        return g
    if not appid:
        return json.dumps({"success": False, "error": "appid required"})
    if _steam_is_running():
        return json.dumps({"success": False, "error": "steam_running",
                           "message": "Close Steam before changing compatibility "
                                      "tools (config.vdf is rewritten on exit)."})
    path = _config_vdf_path()
    if not path or not os.path.isfile(path):
        return json.dumps({"success": False, "error": "config.vdf not found"})

    text = _read(path)
    if not text:
        return json.dumps({"success": False, "error": "config.vdf empty/unreadable"})

    new_text, action = _set_mapping(text, int(appid), tool, force)
    if action in ("unchanged", "exists_kept"):
        return json.dumps({"success": True, "action": action, "appid": appid,
                           "tool": _current_tool_for(text, appid) or tool})
    if action in ("no_steam_section",):
        return json.dumps({"success": False, "error": action})

    ok, backup = _write_with_backup(path, new_text)
    if not ok:
        return json.dumps({"success": False, "error": "write failed"})
    return json.dumps({"success": True, "action": action, "appid": appid,
                       "tool": tool, "backup": backup})


def get_compat_tool_status(contentScriptQuery: str = "") -> str:
    """List current CompatToolMapping entries."""
    g = _guard_linux()
    if g:
        return g
    path = _config_vdf_path()
    if not path or not os.path.isfile(path):
        return json.dumps({"success": False, "error": "config.vdf not found"})
    text = _read(path)
    blk = _find_mapping_block(text)
    mappings: Dict[str, str] = {}
    if blk:
        for entry in re.finditer(r'"\s*(\d+)\s*"\s*\{(.*?)\}', blk.body, re.DOTALL):
            name = re.search(r'"name"\s*"([^"]*)"', entry.group(2))
            if name:
                mappings[entry.group(1)] = name.group(1)
    return json.dumps({"success": True, "mappings": mappings,
                       "count": len(mappings), "default": DEFAULT_TOOL})


def fix_compat_tools_for_activated(tool: str = DEFAULT_TOOL, force: bool = False,
                                   contentScriptQuery: str = "") -> str:
    """Set the compat tool for every .lua-activated game that lacks a mapping.

    Reads the stplug-in directory for activated appids, then ensures each has
    a CompatToolMapping entry. Existing mappings are left alone unless force.
    """
    g = _guard_linux()
    if g:
        return g
    if _steam_is_running():
        return json.dumps({"success": False, "error": "steam_running",
                           "message": "Close Steam before running the compat-tool fix."})

    # Collect activated appids from stplug-in/*.lua
    try:
        import linux_platform as lp
        stplug = lp.get_stplugin_dir()
    except Exception:
        stplug = None
    if not stplug or not os.path.isdir(stplug):
        return json.dumps({"success": False, "error": "stplug-in dir not found"})

    appids: List[int] = []
    for fn in os.listdir(stplug):
        if fn.endswith(".lua"):
            base = fn[:-4]
            if base.isdigit():
                appids.append(int(base))
    if not appids:
        return json.dumps({"success": True, "fixed": [], "skipped": [],
                           "message": "No activated games found"})

    path = _config_vdf_path()
    if not path or not os.path.isfile(path):
        return json.dumps({"success": False, "error": "config.vdf not found"})

    text = _read(path)
    fixed, skipped = [], []
    for appid in appids:
        new_text, action = _set_mapping(text, appid, tool, force)
        if action in ("inserted", "replaced", "created_mapping"):
            text = new_text
            fixed.append(appid)
        else:
            skipped.append({"appid": appid, "reason": action})

    if fixed:
        ok, backup = _write_with_backup(path, text)
        if not ok:
            return json.dumps({"success": False, "error": "write failed"})
        return json.dumps({"success": True, "fixed": fixed, "skipped": skipped,
                           "tool": tool, "backup": backup})
    return json.dumps({"success": True, "fixed": [], "skipped": skipped,
                       "message": "All activated games already mapped"})


def auto_set_on_activation(appid: int, tool: str = DEFAULT_TOOL) -> None:
    """Best-effort hook: set compat tool when a game is activated (Linux only).

    Silent — never raises, never blocks activation. Skips if Steam is running
    (the mapping would be lost) so the manual 'fix all' button can catch it later.
    """
    if _IS_WINDOWS or not appid:
        return
    try:
        if _steam_is_running():
            return
        path = _config_vdf_path()
        if not path or not os.path.isfile(path):
            return
        text = _read(path)
        if not text:
            return
        new_text, action = _set_mapping(text, int(appid), tool, force=False)
        if action in ("inserted", "created_mapping"):
            _write_with_backup(path, new_text)
            logger.log(f"compat_tools: auto-set {tool} for {appid} ({action})")
    except Exception as exc:
        logger.warn(f"compat_tools: auto-set failed for {appid}: {exc}")
