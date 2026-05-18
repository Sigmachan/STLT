"""
Security utilities for LuaTools.

Provides ZIP archive validation and safe extraction helpers to prevent
common archive attacks (path traversal, absolute paths, symlinks and ZIP bombs).
"""

from __future__ import annotations

import io
import os
import re
import shutil
import zipfile
from typing import Iterable, List, Optional, Tuple

# Security limits
MAX_ZIP_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_FILES_IN_ZIP = 1000
MAX_SINGLE_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024  # 500 MB

# Allowed file extensions in archives. Kept as an informational allow-list for
# callers that want to enforce their own policy; validate_zip_archive currently
# focuses on structural safety so existing archive formats keep working.
ALLOWED_EXTENSIONS = {'.lua', '.manifest', '.bin', '.json', '.txt'}
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _normalise_zip_member(filename: str) -> Optional[str]:
    """Return a safe, POSIX-style archive path or None if the name is unsafe."""
    if not filename:
        return None

    name = filename.replace('\\', '/')
    if name.startswith('/') or name.startswith('\\'):
        return None
    if _WINDOWS_DRIVE_RE.match(name) or ':' in name:
        # Reject drive letters and NTFS alternate data streams.
        return None

    parts = [part for part in name.split('/') if part not in ('', '.')]
    if not parts or any(part == '..' for part in parts):
        return None

    return '/'.join(parts)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    """Detect Unix symlinks encoded in ZIP external attributes."""
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def _safe_join(base_dir: str, member_name: str) -> Optional[str]:
    """Resolve member_name under base_dir, returning None if it escapes base_dir."""
    try:
        base = os.path.realpath(base_dir)
        target = os.path.realpath(os.path.join(base, member_name))
        base_cmp = os.path.normcase(base)
        target_cmp = os.path.normcase(target)
        if os.path.commonpath([base_cmp, target_cmp]) != base_cmp:
            return None
        return target
    except (OSError, ValueError):
        return None


def validate_zip_archive(archive_bytes: bytes, appid: str = "unknown") -> Tuple[bool, Optional[str]]:
    """
    Validate a ZIP archive for structural security issues.

    Checks:
    - Archive size limit
    - Number of files limit
    - Path traversal and absolute paths
    - Symlink entries
    - Duplicate destination paths
    - Individual file size limits
    - Total uncompressed size / compression ratio (ZIP bomb protection)

    Returns:
        Tuple of (is_valid, error_message)
        If valid: (True, None)
        If invalid: (False, "error description")
    """
    if len(archive_bytes) > MAX_ZIP_SIZE:
        return False, f"Archive too large: {len(archive_bytes)} bytes (max {MAX_ZIP_SIZE})"

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
            infos = zf.infolist()

            if len(infos) > MAX_FILES_IN_ZIP:
                return False, f"Too many files in archive: {len(infos)} (max {MAX_FILES_IN_ZIP})"

            total_uncompressed = 0
            seen_paths = set()

            for info in infos:
                file_name = info.filename
                safe_name = _normalise_zip_member(file_name)
                if safe_name is None:
                    return False, f"Unsafe archive path detected: {file_name}"

                if _is_zip_symlink(info):
                    return False, f"Symlink entry is not allowed: {file_name}"

                if safe_name in seen_paths:
                    return False, f"Duplicate archive path detected: {file_name}"
                seen_paths.add(safe_name)

                if info.is_dir():
                    continue

                if info.file_size > MAX_SINGLE_FILE_SIZE:
                    return False, f"File too large: {file_name} ({info.file_size} bytes)"

                total_uncompressed += info.file_size
                if total_uncompressed > MAX_TOTAL_UNCOMPRESSED:
                    return False, "Total uncompressed size too large (ZIP bomb protection)"

            if len(archive_bytes) > 0:
                ratio = total_uncompressed / len(archive_bytes)
                if ratio > 100:
                    return False, f"Suspicious compression ratio: {ratio:.1f}:1"

            return True, None

    except zipfile.BadZipFile as e:
        return False, f"Invalid ZIP file: {e}"
    except Exception as e:
        return False, f"Error validating archive: {e}"


def get_file_extension(filename: str) -> str:
    """Get file extension from filename."""
    _, ext = os.path.splitext(filename)
    return ext


def is_safe_path(base_dir: str, file_path: str) -> bool:
    """
    Check if file_path resolves safely within base_dir.
    Prevents path traversal attacks when extracting files.
    """
    return _safe_join(base_dir, file_path) is not None


def safe_extract_file(archive: zipfile.ZipFile, file_name: str, dest_dir: str) -> Tuple[bool, Optional[str], Optional[bytes]]:
    """
    Safely read a single file from an archive.

    Returns:
        Tuple of (success, error_message, file_content)
    """
    safe_name = _normalise_zip_member(file_name)
    if safe_name is None or not is_safe_path(dest_dir, safe_name):
        return False, f"Path traversal blocked: {file_name}", None

    try:
        info = archive.getinfo(file_name)
        if _is_zip_symlink(info):
            return False, f"Symlink entry blocked: {file_name}", None
        content = archive.read(file_name)
        return True, None, content
    except Exception as e:
        return False, f"Failed to read {file_name}: {e}", None


def safe_extract_archive(
    archive: zipfile.ZipFile,
    dest_dir: str,
    members: Optional[Iterable[zipfile.ZipInfo]] = None,
) -> List[str]:
    """Safely extract ZIP members into dest_dir and return extracted file paths."""
    os.makedirs(dest_dir, exist_ok=True)
    extracted: List[str] = []

    for info in members or archive.infolist():
        safe_name = _normalise_zip_member(info.filename)
        if safe_name is None:
            raise RuntimeError(f"Unsafe archive path detected: {info.filename}")
        if _is_zip_symlink(info):
            raise RuntimeError(f"Symlink entry is not allowed: {info.filename}")

        target = _safe_join(dest_dir, safe_name)
        if target is None:
            raise RuntimeError(f"Archive member escapes destination: {info.filename}")

        if info.is_dir():
            os.makedirs(target, exist_ok=True)
            continue

        os.makedirs(os.path.dirname(target), exist_ok=True)
        with archive.open(info, "r") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        extracted.append(target)

    return extracted
