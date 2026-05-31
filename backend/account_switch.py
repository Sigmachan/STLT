"""One-click Steam account switching via DPAPI-decrypted refresh tokens.

Steam stores refresh tokens for every "remembered" account in two files:

    %LOCALAPPDATA%\\Steam\\local.vdf
        Encrypted refresh tokens, one DPAPI blob per account.
        Each blob is decryptable with the account's *AccountName* as DPAPI
        entropy.

    <SteamInstall>\\config\\loginusers.vdf
        Plaintext: SteamID64 -> AccountName mapping.

Workflow:
    1. extract_login_tokens()  -- DPAPI-decrypt every blob, match to account name
    2. switch_to_account(name) -- write the chosen account's token as MostRecent,
                                  kill Steam, launch steam://0

Steam restarts and auto-logins to the chosen account in ~3 seconds, no UI.
The current "MostRecent" pointer in loginusers.vdf is rewritten on every call.

Ported from RobiZkt's Steam-Token-Grabber. Windows-only -- uses DPAPI directly.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from logger import logger
from steam_utils import detect_steam_install_path
from steam_version import _steam_is_running


# ── DPAPI bindings ────────────────────────────────────────────────────────

class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


_crypt32 = None
if sys.platform.startswith("win"):
    try:
        _crypt32 = ctypes.WinDLL("crypt32.dll")
    except Exception as exc:
        logger.warn(f"LuaTools: crypt32.dll unavailable: {exc}")


def _dpapi_unprotect(data: bytes, entropy: bytes) -> Optional[bytes]:
    """CryptUnprotectData wrapper. Returns plaintext bytes or None."""
    if not _crypt32:
        return None
    blob_in = DATA_BLOB(len(data), (ctypes.c_byte * len(data))(*data))
    blob_ent = DATA_BLOB(len(entropy), (ctypes.c_byte * len(entropy))(*entropy))
    blob_out = DATA_BLOB()
    try:
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, ctypes.byref(blob_ent),
            None, None, 0, ctypes.byref(blob_out),
        )
        if not ok:
            return None
        plain = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return plain
    except Exception as exc:
        logger.warn(f"LuaTools: CryptUnprotectData failed: {exc}")
        return None


def _dpapi_protect(data: bytes, entropy: bytes) -> Optional[bytes]:
    """CryptProtectData wrapper for re-encrypting tokens back."""
    if not _crypt32:
        return None
    blob_in = DATA_BLOB(len(data), (ctypes.c_byte * len(data))(*data))
    blob_ent = DATA_BLOB(len(entropy), (ctypes.c_byte * len(entropy))(*entropy))
    blob_out = DATA_BLOB()
    try:
        ok = _crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, ctypes.byref(blob_ent),
            None, None, 0, ctypes.byref(blob_out),
        )
        if not ok:
            return None
        cipher = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return cipher
    except Exception as exc:
        logger.warn(f"LuaTools: CryptProtectData failed: {exc}")
        return None


# ── Steam file locations ──────────────────────────────────────────────────

def _local_vdf_path() -> str:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local_appdata, "Steam", "local.vdf") if local_appdata else ""


def _login_users_vdf_path() -> str:
    base = detect_steam_install_path()
    return os.path.join(base, "config", "loginusers.vdf") if base else ""


def _config_vdf_path() -> str:
    base = detect_steam_install_path()
    return os.path.join(base, "config", "config.vdf") if base else ""


# ── VDF parsing (very simple — Steam VDF only uses tabs/newlines, no nesting tricks) ──

def _parse_loginusers(text: str) -> List[Dict[str, Any]]:
    """Parse loginusers.vdf -> [{steamId64, AccountName, PersonaName, MostRecent}]."""
    accounts = []
    # Each account block: "76561...." { ... }
    for m in re.finditer(r'"(\d{17,})"\s*\{([^}]+)\}', text, re.DOTALL):
        sid64 = m.group(1)
        body = m.group(2)
        an = re.search(r'"AccountName"\s+"([^"]+)"', body)
        pn = re.search(r'"PersonaName"\s+"([^"]*)"', body)
        mr = re.search(r'"MostRecent"\s+"(\d)"', body)
        accounts.append({
            "steamId64": sid64,
            "accountName": an.group(1) if an else "",
            "personaName": pn.group(1) if pn else "",
            "mostRecent": mr.group(1) == "1" if mr else False,
        })
    return accounts


# ── Public API ────────────────────────────────────────────────────────────

def extract_login_tokens(contentScriptQuery: str = "") -> str:
    if not _IS_WINDOWS:
        return _linux_disabled_response()
    """Decrypt every saved Steam refresh token and match to account names.

    Returns:
        {success, tokens: [{accountName, personaName, steamId64, mostRecent,
                            tokenPreview, hasJwt}], path}
    """
    if not _crypt32:
        return json.dumps({
            "success": False,
            "error": "DPAPI unavailable (non-Windows or crypt32 missing)",
        })

    local_vdf = _local_vdf_path()
    login_vdf = _login_users_vdf_path()

    if not os.path.isfile(local_vdf):
        return json.dumps({
            "success": False,
            "error": f"local.vdf not found at {local_vdf}",
        })
    if not os.path.isfile(login_vdf):
        return json.dumps({
            "success": False,
            "error": f"loginusers.vdf not found at {login_vdf}",
        })

    try:
        with open(local_vdf, "r", encoding="utf-8", errors="replace") as f:
            local_text = f.read()
        with open(login_vdf, "r", encoding="utf-8", errors="replace") as f:
            login_text = f.read()
    except Exception as exc:
        return json.dumps({"success": False, "error": f"Read failed: {exc}"})

    accounts = _parse_loginusers(login_text)
    if not accounts:
        return json.dumps({"success": False, "error": "No accounts in loginusers.vdf"})

    # local.vdf has DPAPI-encrypted blobs encoded as long hex strings or sometimes
    # base64. Steam-Token-Grabber treats anything with 32+ hex chars as a candidate.
    hex_candidates = set(re.findall(r'"([a-fA-F0-9]{200,})"', local_text))
    # Also try base64-looking blobs in case Steam changes format
    b64_candidates = set(re.findall(r'"([A-Za-z0-9+/]{200,}={0,2})"', local_text))

    results: List[Dict[str, Any]] = []
    seen_accounts: set = set()

    def _try_decrypt(blob: bytes, account_name: str) -> Optional[str]:
        plain = _dpapi_unprotect(blob, account_name.encode("utf-8"))
        if not plain:
            return None
        try:
            text = plain.decode("utf-8", errors="ignore").strip("\x00").strip()
        except Exception:
            return None
        # Steam JWT refresh tokens have at least one dot ("eyJ...".".eyJ...".".sig")
        if "." in text and len(text) >= 30:
            return text
        return None

    for account in accounts:
        name = account["accountName"]
        if not name:
            continue
        for candidate in hex_candidates:
            try:
                blob = bytes.fromhex(candidate)
            except ValueError:
                continue
            token = _try_decrypt(blob, name)
            if token:
                if name in seen_accounts:
                    break  # one token per account
                seen_accounts.add(name)
                results.append({
                    "accountName": name,
                    "personaName": account["personaName"],
                    "steamId64": account["steamId64"],
                    "mostRecent": account["mostRecent"],
                    "tokenPreview": token[:20] + "..." + token[-10:] if len(token) > 40 else token,
                    "tokenLength": len(token),
                    "hasJwt": True,
                })
                break

        if name in seen_accounts:
            continue
        # Try base64 candidates as fallback
        for candidate in b64_candidates:
            try:
                blob = base64.b64decode(candidate)
            except Exception:
                continue
            token = _try_decrypt(blob, name)
            if token:
                seen_accounts.add(name)
                results.append({
                    "accountName": name,
                    "personaName": account["personaName"],
                    "steamId64": account["steamId64"],
                    "mostRecent": account["mostRecent"],
                    "tokenPreview": token[:20] + "..." + token[-10:] if len(token) > 40 else token,
                    "tokenLength": len(token),
                    "hasJwt": True,
                })
                break

    # Accounts in loginusers but with no decryptable token (haven't logged in yet)
    for account in accounts:
        if account["accountName"] and account["accountName"] not in seen_accounts:
            results.append({
                "accountName": account["accountName"],
                "personaName": account["personaName"],
                "steamId64": account["steamId64"],
                "mostRecent": account["mostRecent"],
                "tokenPreview": "",
                "tokenLength": 0,
                "hasJwt": False,
            })

    # Sort: most recent first, then accounts with tokens, then by name
    results.sort(key=lambda x: (not x["mostRecent"], not x["hasJwt"], x["accountName"]))

    return json.dumps({
        "success": True,
        "tokens": results,
        "localVdfPath": local_vdf,
        "loginUsersPath": login_vdf,
        "decryptableCount": len([r for r in results if r["hasJwt"]]),
    })


def _kill_steam_blocking(timeout: float = 6.0) -> bool:
    """Kill Steam and wait for the process to actually exit."""
    if not _steam_is_running():
        return True
    try:
        # Graceful shutdown first
        subprocess.Popen(
            ["cmd", "/c", "start", "", "steam://exit"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _steam_is_running():
            return True
        time.sleep(0.3)

    # Force kill
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "steam.exe", "/T"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        time.sleep(0.5)
        return not _steam_is_running()
    except Exception:
        return False


def _set_most_recent_in_loginusers(target_account: str, target_sid64: str) -> bool:
    """Rewrite loginusers.vdf so target_account is MostRecent=1, others 0.

    Preserves all existing fields. Only flips MostRecent.
    """
    path = _login_users_vdf_path()
    if not os.path.isfile(path):
        return False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    new_text_parts: List[str] = []
    cursor = 0
    for m in re.finditer(r'("(\d{17,})"\s*\{)([^}]+)(\})', text, re.DOTALL):
        block_start, sid, body, block_end = m.group(1), m.group(2), m.group(3), m.group(4)
        new_text_parts.append(text[cursor:m.start()])

        new_recent = "1" if sid == target_sid64 else "0"
        new_body = re.sub(
            r'("MostRecent"\s+")\d(")',
            rf'\g<1>{new_recent}\g<2>',
            body,
            count=1,
        )
        # If MostRecent wasn't present, add it
        if '"MostRecent"' not in new_body:
            new_body = new_body.rstrip() + f'\n\t\t"MostRecent"\t\t"{new_recent}"\n\t'

        new_text_parts.append(block_start + new_body + block_end)
        cursor = m.end()
    new_text_parts.append(text[cursor:])

    new_text = "".join(new_text_parts)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        logger.warn(f"LuaTools: loginusers.vdf rewrite failed: {exc}")
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


def switch_to_account(accountName: str = "",
                      contentScriptQuery: str = "") -> str:
    if not _IS_WINDOWS:
        return _linux_disabled_response()
    """Restart Steam logged in as the given account.

    Pre-conditions:
        - The account must already be "Remember me"-saved (decryptable token exists)
        - Steam will be killed during the switch

    Steps:
        1. Verify account has a decryptable token
        2. Kill Steam
        3. Flip MostRecent=1 for the target account in loginusers.vdf
        4. Launch steam://0 -- Steam auto-logs in to MostRecent account
    """
    accountName = (accountName or "").strip()
    if not accountName:
        return json.dumps({"success": False, "error": "accountName required"})

    # Step 1 -- verify token exists
    extract_result = json.loads(extract_login_tokens())
    if not extract_result.get("success"):
        return json.dumps({"success": False,
                           "error": "Token extraction failed: " + extract_result.get("error", "")})

    target = None
    for t in extract_result.get("tokens", []):
        if t["accountName"] == accountName:
            target = t
            break

    if not target:
        return json.dumps({"success": False,
                           "error": f"Account '{accountName}' not found in loginusers.vdf"})
    if not target["hasJwt"]:
        return json.dumps({"success": False,
                           "error": f"Account '{accountName}' has no decryptable token. "
                                    "Log in once via Steam UI with 'Remember me' to enable quick-switching."})

    sid64 = target["steamId64"]

    # Step 2 -- kill Steam
    was_running = _steam_is_running()
    if was_running:
        ok = _kill_steam_blocking(timeout=8.0)
        if not ok:
            return json.dumps({"success": False,
                               "error": "Failed to close Steam. Close it manually and retry."})

    # Step 3 -- flip MostRecent
    if not _set_most_recent_in_loginusers(accountName, sid64):
        return json.dumps({"success": False,
                           "error": "Failed to update loginusers.vdf"})

    # Step 4 -- launch Steam
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", "steam://0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
    except Exception as exc:
        return json.dumps({"success": False,
                           "error": f"Steam relaunch failed: {exc}"})

    logger.log(f"LuaTools: Switched to account '{accountName}' (SteamID {sid64})")
    return json.dumps({
        "success": True,
        "accountName": accountName,
        "steamId64": sid64,
        "wasSteamRunning": was_running,
        "message": "Steam is restarting. Will auto-login in a few seconds.",
    })
import sys as _sys
_IS_WINDOWS = _sys.platform.startswith("win")

def _linux_disabled_response(extra: str = "") -> str:
    """Standard JSON response for DPAPI-backed functions on Linux."""
    import json as _json
    msg = ("Account switching uses Windows DPAPI to decrypt Steam refresh "
           "tokens. Linux Steam stores credentials differently (no DPAPI), "
           "so this feature is disabled on Linux.")
    return _json.dumps({"success": False, "error": msg, "platform": "linux",
                        "shelved": True, "detail": extra})


