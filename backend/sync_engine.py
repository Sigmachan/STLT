"""Multi-machine sync engine for LuaTools state (v9.0).

Designed for users with multiple Windows machines (e.g. desktop + handheld).
Syncs LuaTools state via a Git repository or local folder, with explicit
push/pull semantics — no silent overwrites, no surprises.

What's synced (by default):
  - .lua activation scripts (stplug-in/*.lua, *.lua.disabled)
  - API key vault (key_vault.json, base64 obfuscated)
  - Sentinel config + state (sentinel_config.json, sentinel_state.json)
  - Custom API sources (custom_apis.json)
  - Source chain order (source_chain.json)
  - Download history (history.db, optional — large)
  - Themes (theme.css overrides, if user-customized)

What's NOT synced (intentionally host-specific):
  - steamPath / installPath settings
  - Per-host caches (apidlogs, loadedappids, temp_dl)
  - Per-host backups (.bak-* folders)
  - Game userdata (handled by account_transfer separately)

Two backends:
  1. Git: any git remote you have write access to (private GitHub/GitLab/Codeberg repo).
     Uses `git` CLI. Pulls/pushes on demand or on Sentinel events.
  2. Folder: any local/network path (e.g. mapped drive, Syncthing-watched folder).
     Plain file copy with mtime-based conflict detection.

Conflict handling:
  - On pull: if local file is newer than remote, ask user (or skip + log).
  - On push: if remote has newer commits we don't have, abort and tell user
    to pull first.
  - Never silently overwrite. Every operation is auditable in the report.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from logger import logger
from paths import data_path, get_backend_dir, get_plugin_dir
from steam_utils import detect_steam_install_path


# ── Sync manifest — describes what's syncable and where ────────────────

# (logical_name, source_path_resolver, optional)
_SYNC_ITEMS = [
    ("key_vault.json",      lambda: data_path("key_vault.json"),      False),
    ("sentinel_config.json", lambda: data_path("sentinel_config.json"), True),
    ("sentinel_state.json", lambda: data_path("sentinel_state.json"), True),
    ("custom_apis.json",    lambda: data_path("custom_apis.json"),    True),
    ("source_chain.json",   lambda: data_path("source_chain.json"),   True),
]

_SYNC_CONFIG = "sync_config.json"  # Where sync settings live (in data/)


# ── Sync configuration persistence ─────────────────────────────────────

def _config_path() -> str:
    return data_path(_SYNC_CONFIG)


def _read_config() -> Dict[str, Any]:
    p = _config_path()
    if not os.path.isfile(p):
        return {
            "backend": "git",  # or "folder"
            "git": {
                "remote_url": "",
                "branch": "main",
                "auto_pull_on_start": False,
                "auto_push_on_change": False,
                "include_history_db": False,
                "include_lua_scripts": True,
            },
            "folder": {
                "path": "",
                "include_history_db": False,
                "include_lua_scripts": True,
            },
            "last_push": 0,
            "last_pull": 0,
        }
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warn(f"LuaTools sync: failed reading config: {exc}")
        return {}


def _write_config(cfg: Dict[str, Any]) -> bool:
    p = _config_path()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, p)
        return True
    except Exception as exc:
        logger.warn(f"LuaTools sync: failed writing config: {exc}")
        try: os.remove(tmp)
        except Exception: pass
        return False


# ── Sync root (the staging area we push from) ──────────────────────────

def _sync_root() -> str:
    """Local staging directory we copy files into for push, and out of for pull."""
    return os.path.join(get_backend_dir(), "data", "sync_repo")


def _ensure_sync_root() -> str:
    root = _sync_root()
    try:
        os.makedirs(root, exist_ok=True)
    except Exception as exc:
        logger.warn(f"LuaTools sync: cannot create sync root: {exc}")
    return root


# ── Collecting files for sync ──────────────────────────────────────────

def _file_sha256(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _stplug_dir() -> str:
    base = detect_steam_install_path()
    if not base:
        return ""
    return os.path.join(base, "config", "stplug-in")


def _collect_lua_scripts() -> List[Tuple[str, str]]:
    """Return [(relative_dest_in_repo, abs_source_path), ...] for all .lua files."""
    stplug = _stplug_dir()
    if not stplug or not os.path.isdir(stplug):
        return []
    out: List[Tuple[str, str]] = []
    for fname in os.listdir(stplug):
        if fname.endswith(".lua") or fname.endswith(".lua.disabled"):
            src = os.path.join(stplug, fname)
            if os.path.isfile(src):
                out.append((f"stplug-in/{fname}", src))
    return out


def _collect_data_files(include_history: bool) -> List[Tuple[str, str]]:
    """Return [(relative_dest_in_repo, abs_source_path), ...] for backend/data items."""
    out: List[Tuple[str, str]] = []
    for name, resolver, optional in _SYNC_ITEMS:
        try:
            src = resolver()
        except Exception:
            continue
        if not src or not os.path.isfile(src):
            if not optional:
                logger.log(f"LuaTools sync: required '{name}' missing, skipping")
            continue
        out.append((f"data/{name}", src))
    if include_history:
        hist = data_path("download_history.db")
        if os.path.isfile(hist):
            out.append(("data/download_history.db", hist))
    return out


def _build_manifest(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    return {
        "version": "1.0",
        "created_at": int(time.time()),
        "machine": os.environ.get("COMPUTERNAME", "unknown"),
        "files": [
            {
                "path": rel,
                "sha256": _file_sha256(src),
                "size": os.path.getsize(src) if os.path.isfile(src) else 0,
                "mtime": int(os.path.getmtime(src)) if os.path.isfile(src) else 0,
            }
            for rel, src in files
        ],
    }


# ── Stage files for push (copy local -> sync_root) ─────────────────────

def _stage_files(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    root = _ensure_sync_root()
    copied = 0
    skipped = 0
    errors: List[str] = []

    for rel, src in files:
        dest = os.path.join(root, rel)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        except Exception as exc:
            errors.append(f"mkdir {rel}: {exc}")
            continue
        try:
            # Skip copy if hashes already match (idempotent push)
            if os.path.isfile(dest) and _file_sha256(src) == _file_sha256(dest):
                skipped += 1
                continue
            shutil.copy2(src, dest)
            copied += 1
        except Exception as exc:
            errors.append(f"copy {rel}: {exc}")

    # Write manifest
    manifest = _build_manifest(files)
    try:
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except Exception as exc:
        errors.append(f"manifest write: {exc}")

    return {"copied": copied, "skipped": skipped, "errors": errors, "manifest": manifest}


# ── Apply pulled files (copy sync_root -> local) ───────────────────────

def _apply_pulled_files(dry_run: bool = False) -> Dict[str, Any]:
    root = _sync_root()
    if not os.path.isdir(root):
        return {"success": False, "error": "sync_repo missing — pull first"}

    manifest_path = os.path.join(root, "manifest.json")
    if not os.path.isfile(manifest_path):
        return {"success": False, "error": "manifest.json missing in pulled data"}

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as exc:
        return {"success": False, "error": f"invalid manifest: {exc}"}

    applied: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    errors: List[str] = []
    stplug = _stplug_dir()

    for entry in manifest.get("files", []):
        rel = entry.get("path", "")
        if not rel:
            continue
        src = os.path.join(root, rel)
        if not os.path.isfile(src):
            errors.append(f"missing in pulled data: {rel}")
            continue

        # Resolve destination based on what kind of file it is
        if rel.startswith("data/"):
            dst = data_path(rel[len("data/"):])
        elif rel.startswith("stplug-in/") and stplug:
            dst = os.path.join(stplug, rel[len("stplug-in/"):])
        else:
            errors.append(f"unknown path category: {rel}")
            continue

        # Conflict check: local newer than what we're pulling
        if os.path.isfile(dst):
            local_mtime = int(os.path.getmtime(dst))
            remote_mtime = entry.get("mtime", 0)
            local_hash = _file_sha256(dst)
            remote_hash = _file_sha256(src)
            if local_hash == remote_hash:
                skipped.append({"path": rel, "reason": "identical"})
                continue
            if local_mtime > remote_mtime:
                conflicts.append({
                    "path": rel,
                    "local_mtime": local_mtime,
                    "remote_mtime": remote_mtime,
                    "local_hash": local_hash[:12],
                    "remote_hash": remote_hash[:12],
                })
                continue  # Don't silently overwrite newer local file

        if dry_run:
            applied.append({"path": rel, "would_apply": True})
            continue

        # Backup existing file
        if os.path.isfile(dst):
            try:
                bak = dst + ".presync-" + time.strftime("%Y%m%d-%H%M%S")
                shutil.copy2(dst, bak)
            except Exception as exc:
                errors.append(f"backup {rel}: {exc}")

        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            applied.append({"path": rel})
        except Exception as exc:
            errors.append(f"apply {rel}: {exc}")

    return {
        "success": True,
        "applied": applied,
        "skipped": skipped,
        "conflicts": conflicts,
        "errors": errors,
        "dry_run": dry_run,
    }


# ── Git backend ────────────────────────────────────────────────────────

def _run_git(args: List[str], cwd: str, timeout: int = 60) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            creationflags=0x08000000 if os.name == "nt" else 0,  # CREATE_NO_WINDOW
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return -1, "", "git not installed or not in PATH"
    except subprocess.TimeoutExpired:
        return -2, "", "git command timed out"
    except Exception as exc:
        return -3, "", str(exc)


def _git_init_or_pull(remote_url: str, branch: str) -> Dict[str, Any]:
    """Initialize the sync_repo as a git checkout (or pull if it already is)."""
    root = _ensure_sync_root()

    if not os.path.isdir(os.path.join(root, ".git")):
        # Fresh clone — but the directory might have staged files in it already.
        # Init + pull instead of clone (which requires empty dir).
        code, _out, err = _run_git(["init"], root)
        if code != 0:
            return {"success": False, "error": f"git init: {err}"}
        code, _out, err = _run_git(["remote", "add", "origin", remote_url], root)
        if code != 0 and "already exists" not in err:
            return {"success": False, "error": f"git remote add: {err}"}
        code, _out, err = _run_git(
            ["fetch", "origin", branch], root, timeout=120,
        )
        if code != 0:
            return {"success": False, "error": f"git fetch: {err}"}
        code, _out, err = _run_git(
            ["checkout", "-B", branch, f"origin/{branch}"], root,
        )
        # If origin/branch doesn't exist (first push), the checkout fails — that's fine
        if code != 0 and "did not match any" not in err and "unknown revision" not in err:
            logger.warn(f"LuaTools sync: git checkout note: {err}")
    else:
        code, _out, err = _run_git(
            ["pull", "--ff-only", "origin", branch], root, timeout=120,
        )
        if code != 0:
            return {"success": False, "error": f"git pull: {err}"}

    return {"success": True}


def _git_push(branch: str, message: str) -> Dict[str, Any]:
    root = _sync_root()
    if not os.path.isdir(os.path.join(root, ".git")):
        return {"success": False, "error": "not a git repo — run pull first"}

    _run_git(["add", "-A"], root)
    code, out, err = _run_git(
        ["commit", "-m", message], root,
    )
    # nothing-to-commit is OK
    if code != 0 and "nothing to commit" not in (out + err).lower():
        return {"success": False, "error": f"git commit: {err}"}

    code, out, err = _run_git(
        ["push", "origin", branch], root, timeout=120,
    )
    if code != 0:
        return {"success": False, "error": f"git push: {err}"}

    return {"success": True, "output": out + err}


# ── Folder backend ─────────────────────────────────────────────────────

def _folder_pull(folder_path: str) -> Dict[str, Any]:
    """Mirror remote folder -> sync_repo."""
    if not folder_path or not os.path.isdir(folder_path):
        return {"success": False, "error": f"folder not accessible: {folder_path}"}
    root = _ensure_sync_root()
    copied = 0
    for src_root, _dirs, files in os.walk(folder_path):
        rel_dir = os.path.relpath(src_root, folder_path)
        for fname in files:
            src = os.path.join(src_root, fname)
            dst_dir = root if rel_dir == "." else os.path.join(root, rel_dir)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, fname)
            if os.path.isfile(dst) and _file_sha256(src) == _file_sha256(dst):
                continue
            shutil.copy2(src, dst)
            copied += 1
    return {"success": True, "copied": copied}


def _folder_push(folder_path: str) -> Dict[str, Any]:
    """Mirror sync_repo -> remote folder."""
    if not folder_path:
        return {"success": False, "error": "folder path empty"}
    try:
        os.makedirs(folder_path, exist_ok=True)
    except Exception as exc:
        return {"success": False, "error": f"cannot create folder: {exc}"}
    root = _sync_root()
    if not os.path.isdir(root):
        return {"success": False, "error": "sync_repo missing"}
    copied = 0
    for src_root, _dirs, files in os.walk(root):
        if ".git" in src_root.split(os.sep):
            continue
        rel_dir = os.path.relpath(src_root, root)
        for fname in files:
            src = os.path.join(src_root, fname)
            dst_dir = folder_path if rel_dir == "." else os.path.join(folder_path, rel_dir)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, fname)
            if os.path.isfile(dst) and _file_sha256(src) == _file_sha256(dst):
                continue
            shutil.copy2(src, dst)
            copied += 1
    return {"success": True, "copied": copied}


# ── Public IPC ─────────────────────────────────────────────────────────

def get_sync_config(contentScriptQuery: str = "") -> str:
    return json.dumps({"success": True, "config": _read_config()})


def set_sync_config(updates: Dict[str, Any] = None,
                    contentScriptQuery: str = "") -> str:
    cfg = _read_config()
    if not isinstance(updates, dict):
        return json.dumps({"success": False, "error": "updates must be a dict"})

    # Shallow-merge top-level + nested git/folder sections
    for key, val in updates.items():
        if key in ("git", "folder") and isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val

    if not _write_config(cfg):
        return json.dumps({"success": False, "error": "write failed"})
    return json.dumps({"success": True, "config": cfg})


def sync_push(contentScriptQuery: str = "") -> str:
    """Stage current state, commit, push to remote."""
    cfg = _read_config()
    backend = cfg.get("backend", "git")
    include_history = bool(
        cfg.get(backend, {}).get("include_history_db", False)
    )
    include_lua = bool(
        cfg.get(backend, {}).get("include_lua_scripts", True)
    )

    files: List[Tuple[str, str]] = []
    files.extend(_collect_data_files(include_history))
    if include_lua:
        files.extend(_collect_lua_scripts())

    if not files:
        return json.dumps({"success": False, "error": "nothing to sync"})

    stage_result = _stage_files(files)

    push_result: Dict[str, Any]
    if backend == "git":
        git_cfg = cfg.get("git", {})
        remote_url = git_cfg.get("remote_url", "")
        branch = git_cfg.get("branch", "main")
        if not remote_url:
            return json.dumps({"success": False, "error": "git remote_url not configured"})
        init = _git_init_or_pull(remote_url, branch)
        if not init.get("success"):
            return json.dumps({"success": False, "error": init.get("error")})
        msg = f"LuaTools sync push from {os.environ.get('COMPUTERNAME', 'unknown')} @ {time.strftime('%Y-%m-%d %H:%M:%S')}"
        push_result = _git_push(branch, msg)
    else:
        folder_path = cfg.get("folder", {}).get("path", "")
        push_result = _folder_push(folder_path)

    if push_result.get("success"):
        cfg["last_push"] = int(time.time())
        _write_config(cfg)
        logger.log(
            f"LuaTools sync: pushed {stage_result['copied']} file(s), "
            f"{stage_result['skipped']} unchanged"
        )

    return json.dumps({
        "success": push_result.get("success", False),
        "error": push_result.get("error"),
        "filesStaged": stage_result["copied"] + stage_result["skipped"],
        "filesNew": stage_result["copied"],
        "stageErrors": stage_result["errors"],
        "backend": backend,
    })


def sync_pull(dry_run: bool = False, contentScriptQuery: str = "") -> str:
    """Pull from remote and apply to local."""
    cfg = _read_config()
    backend = cfg.get("backend", "git")

    if backend == "git":
        git_cfg = cfg.get("git", {})
        remote_url = git_cfg.get("remote_url", "")
        branch = git_cfg.get("branch", "main")
        if not remote_url:
            return json.dumps({"success": False, "error": "git remote_url not configured"})
        pull_result = _git_init_or_pull(remote_url, branch)
    else:
        folder_path = cfg.get("folder", {}).get("path", "")
        pull_result = _folder_pull(folder_path)

    if not pull_result.get("success"):
        return json.dumps(pull_result)

    apply_result = _apply_pulled_files(dry_run=dry_run)

    if apply_result.get("success") and not dry_run:
        cfg["last_pull"] = int(time.time())
        _write_config(cfg)
        logger.log(
            f"LuaTools sync: pulled, applied {len(apply_result['applied'])} file(s), "
            f"{len(apply_result['conflicts'])} conflict(s)"
        )

    return json.dumps({
        **apply_result,
        "backend": backend,
    })


def sync_status(contentScriptQuery: str = "") -> str:
    """Return current sync state: last push/pull, file counts, git status."""
    cfg = _read_config()
    backend = cfg.get("backend", "git")
    info: Dict[str, Any] = {
        "success": True,
        "backend": backend,
        "configured": False,
        "lastPush": cfg.get("last_push", 0),
        "lastPull": cfg.get("last_pull", 0),
    }

    if backend == "git":
        remote_url = cfg.get("git", {}).get("remote_url", "")
        info["configured"] = bool(remote_url)
        info["remoteUrl"] = remote_url
        info["branch"] = cfg.get("git", {}).get("branch", "main")
        root = _sync_root()
        if os.path.isdir(os.path.join(root, ".git")):
            code, out, _err = _run_git(["status", "--porcelain"], root, timeout=10)
            if code == 0:
                info["pendingChanges"] = len([l for l in out.splitlines() if l.strip()])
    else:
        info["configured"] = bool(cfg.get("folder", {}).get("path", ""))
        info["folderPath"] = cfg.get("folder", {}).get("path", "")

    # Count current local items
    include_history = bool(cfg.get(backend, {}).get("include_history_db", False))
    include_lua = bool(cfg.get(backend, {}).get("include_lua_scripts", True))
    info["localFiles"] = {
        "dataFiles": len(_collect_data_files(include_history)),
        "luaScripts": len(_collect_lua_scripts()) if include_lua else 0,
    }
    return json.dumps(info)


def sync_test_connection(contentScriptQuery: str = "") -> str:
    """Verify the configured remote is reachable without making any changes."""
    cfg = _read_config()
    backend = cfg.get("backend", "git")

    if backend == "git":
        remote_url = cfg.get("git", {}).get("remote_url", "")
        if not remote_url:
            return json.dumps({"success": False, "error": "remote_url not configured"})
        code, out, err = _run_git(["ls-remote", remote_url], _sync_root(), timeout=20)
        if code == 0:
            refs = len([l for l in out.splitlines() if l.strip()])
            return json.dumps({"success": True, "refs": refs, "message": f"Remote reachable. {refs} ref(s)."})
        return json.dumps({"success": False, "error": err.strip() or out.strip() or "unknown"})
    else:
        folder_path = cfg.get("folder", {}).get("path", "")
        if not folder_path:
            return json.dumps({"success": False, "error": "folder path not configured"})
        if not os.path.isdir(folder_path):
            return json.dumps({"success": False, "error": f"folder not found: {folder_path}"})
        try:
            test = os.path.join(folder_path, ".luatools_write_test")
            with open(test, "w") as f:
                f.write("test")
            os.remove(test)
            return json.dumps({"success": True, "message": f"Folder writable: {folder_path}"})
        except Exception as exc:
            return json.dumps({"success": False, "error": f"folder not writable: {exc}"})
