#!/usr/bin/env python3
"""LuaTools Ultimate — standalone CLI.

Use core LuaTools features from the terminal with NO Steam UI / Millennium
required. Intended for SLSsteam/headless users and for debugging activation
("why won't this game download?").

Adapted for STLT's actual backend API (async StartAddViaLuaTools + status
polling), unlike upstream's CLI which targeted a different function set.

Examples:
    python3 standalone_cli.py init
    python3 standalone_cli.py check 590830        # is it available in sources?
    python3 standalone_cli.py add 590830          # activate (start + wait)
    python3 standalone_cli.py status 590830
    python3 standalone_cli.py has 590830
    python3 standalone_cli.py list
    python3 standalone_cli.py remove 590830
    python3 standalone_cli.py path 590830
    python3 standalone_cli.py fixes 590830
    python3 standalone_cli.py slssteam            # SLSsteam config + PlayNotOwned
    python3 standalone_cli.py play-not-owned on   # enable the critical setting
    python3 standalone_cli.py heal-ui             # self-heal the Steam UI
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def _load(result):
    """Parse a JSON IPC result string into a dict (best-effort)."""
    if isinstance(result, dict):
        return result
    try:
        return json.loads(result)
    except Exception:
        return {"raw": result}


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_init(m, args) -> int:
    m.InitApis("cli")
    _print(_load(m.GetInitApisMessage("cli")))
    return 0


def cmd_check(m, args) -> int:
    res = _load(m.CheckApisForApp(args.appid))
    _print(res)
    return 0


def cmd_add(m, args) -> int:
    print(f"[*] Starting activation for appid {args.appid} ...", file=sys.stderr)
    _print(_load(m.StartAddViaLuaTools(args.appid)))
    if args.no_wait:
        return 0
    # Poll status until terminal state
    deadline = time.time() + args.timeout
    last = None
    while time.time() < deadline:
        st = _load(m.GetAddViaLuaToolsStatus(args.appid))
        status = st.get("status") or st.get("state") or ""
        if status != last:
            print(f"[status] {status or st}", file=sys.stderr)
            last = status
        if status in ("done", "installed", "complete", "success",
                      "error", "failed", "cancelled", "not_found"):
            _print(st)
            return 0 if status in ("done", "installed", "complete", "success") else 1
        time.sleep(1.0)
    print("[!] Timed out waiting for activation.", file=sys.stderr)
    _print(_load(m.GetAddViaLuaToolsStatus(args.appid)))
    return 1


def cmd_status(m, args) -> int:
    _print(_load(m.GetAddViaLuaToolsStatus(args.appid)))
    return 0


def cmd_has(m, args) -> int:
    _print(_load(m.HasLuaToolsForApp(args.appid)))
    return 0


def cmd_list(m, args) -> int:
    _print(_load(m.GetInstalledLuaScripts("cli")))
    return 0


def cmd_remove(m, args) -> int:
    _print(_load(m.DeleteLuaToolsForApp(args.appid)))
    return 0


def cmd_path(m, args) -> int:
    _print(_load(m.GetGameInstallPath(args.appid)))
    return 0


def cmd_fixes(m, args) -> int:
    _print(_load(m.CheckForFixes(args.appid)))
    return 0


def cmd_audit(m, args) -> int:
    _print(_load(m.AuditLuaContent(args.appid)))
    return 0


def cmd_slssteam(m, args) -> int:
    _print(_load(m.GetSlssteamConfig("cli")))
    return 0


def cmd_play_not_owned(m, args) -> int:
    enabled = args.state.lower() in ("on", "true", "yes", "1", "enable", "enabled")
    _print(_load(m.SetSlssteamPlayNotOwned(enabled)))
    return 0


def cmd_heal_ui(m, args) -> int:
    _print(_load(m.SelfHealUI("cli")))
    return 0


def cmd_diagnose(m, args) -> int:
    """One-shot health check via the diagnostic engine: every prerequisite,
    severity-ranked, with fixes. Optionally scoped to an appid."""
    try:
        import health
        report = health.run_health_check(appid=args.appid or None)
        print(health.render_text(report))
        return 0 if report.get("overall") != "fail" else 1
    except Exception as exc:
        # Fallback to raw IPC if the engine import fails for any reason
        print(f"[!] health engine unavailable ({exc}); raw IPC follows:",
              file=sys.stderr)
        _print(_load(m.GetLinuxHealthReport(args.appid or 0)))
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LuaTools Ultimate standalone CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="initialize API sources")

    sp = sub.add_parser("check", help="check if an appid is available in sources")
    sp.add_argument("appid", type=int)

    sp = sub.add_parser("add", help="activate a game (start + wait for completion)")
    sp.add_argument("appid", type=int)
    sp.add_argument("--no-wait", action="store_true", help="start and return immediately")
    sp.add_argument("--timeout", type=int, default=300, help="seconds to wait (default 300)")

    for name, help_ in (("status", "poll activation status"),
                        ("has", "is the game activated?"),
                        ("remove", "remove activation for a game"),
                        ("path", "print install path"),
                        ("fixes", "check for known fixes"),
                        ("audit", "audit the .lua content")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("appid", type=int)

    sub.add_parser("list", help="list installed .lua scripts")
    sub.add_parser("slssteam", help="show SLSsteam config (PlayNotOwnedGames etc.)")

    sp = sub.add_parser("play-not-owned", help="enable/disable SLSsteam PlayNotOwnedGames")
    sp.add_argument("state", help="on|off")

    sub.add_parser("heal-ui", help="self-heal the Steam UI injection")

    sp = sub.add_parser("diagnose", help="one-shot health check (optionally for an appid)")
    sp.add_argument("appid", type=int, nargs="?", default=0)

    return p


_DISPATCH = {
    "init": cmd_init, "check": cmd_check, "add": cmd_add, "status": cmd_status,
    "has": cmd_has, "list": cmd_list, "remove": cmd_remove, "path": cmd_path,
    "fixes": cmd_fixes, "audit": cmd_audit, "slssteam": cmd_slssteam,
    "play-not-owned": cmd_play_not_owned, "heal-ui": cmd_heal_ui,
    "diagnose": cmd_diagnose,
}


def main() -> int:
    args = build_parser().parse_args()

    # `diagnose` must work even when everything else is broken (no Millennium,
    # no Steam, missing deps) — that's the whole point of a diagnostic. It uses
    # the health engine directly and needs no backend import.
    if args.cmd == "diagnose":
        try:
            import health
            report = health.run_health_check(appid=args.appid or None)
            print(health.render_text(report))
            return 0 if report.get("overall") != "fail" else 1
        except Exception as exc:
            print(f"health engine failed: {exc}", file=sys.stderr)
            return 2

    # Import the backend in standalone mode (platform_bridge provides the
    # Millennium shim, so this works with no Steam/Millennium present).
    try:
        import main as m  # noqa: WPS433
    except Exception as exc:
        print(f"Failed to import backend: {exc}", file=sys.stderr)
        print("(Tip: 'diagnose' works without the backend — try that first.)",
              file=sys.stderr)
        return 2

    # Best-effort startup parity with plugin mode.
    for fn in ("detect_steam_install_path", "ensure_http_client",
               "ensure_temp_download_dir", "init_applist", "init_games_db"):
        try:
            getattr(m, fn)() if fn != "ensure_http_client" else m.ensure_http_client("cli-init")
        except Exception:
            pass

    handler = _DISPATCH.get(args.cmd)
    if not handler:
        print(f"unknown command: {args.cmd}", file=sys.stderr)
        return 2
    return handler(m, args)


if __name__ == "__main__":
    raise SystemExit(main())
