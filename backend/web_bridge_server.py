"""Standalone HTTP RPC bridge for LuaTools (v9.1).

Millennium 3.0 dropped native Python plugin backends. This server keeps the
entire existing Python backend intact and exposes it over localhost HTTP:

  POST /rpc      {method, args}  ->  {success, result} | {success, error}
  GET  /<file>   serves static assets from public/

The Lua bootstrapper (main.lua) launches this process and injects a tiny JS
shim that redirects Millennium.callServerMethod to POST /rpc.

Improvements over the LuaToolsLinux reference this is adapted from:
  - ThreadingHTTPServer: concurrent RPC calls (a long download no longer
    freezes the whole UI)
  - Errors propagate to the client as {success:false, error} instead of
    being swallowed into a null result
  - Graceful handling when the port is already bound
"""

import importlib.util
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes

HOST = "127.0.0.1"
PORT = 38495

_backend_dir = os.path.dirname(os.path.abspath(__file__))
_plugin_root = os.path.dirname(_backend_dir)
_public_dir = os.path.join(_plugin_root, "public")

for _p in (_backend_dir, _plugin_root):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(_backend_dir)


# ── Install standalone shims before importing main.py ─────────────────────
try:
    import platform_bridge
    platform_bridge.install_standalone_shims()
except Exception as exc:  # pragma: no cover
    print(f"[bridge] platform_bridge unavailable: {exc}", flush=True)


# ── Load the existing backend ─────────────────────────────────────────────
_main = None
_load_error = ""
try:
    _spec = importlib.util.spec_from_file_location(
        "main", os.path.join(_backend_dir, "main.py")
    )
    _main = importlib.util.module_from_spec(_spec)
    sys.modules["main"] = _main
    _spec.loader.exec_module(_main)

    # Run the plugin's _load() lifecycle hook if present
    if hasattr(_main, "plugin") and hasattr(_main.plugin, "_load"):
        try:
            _main.plugin._load()
        except Exception as exc:
            print(f"[bridge] plugin._load() warning: {exc}", flush=True)

    print("[bridge] backend loaded OK", flush=True)
except Exception:
    _load_error = traceback.format_exc()
    print(f"[bridge] FAILED to load backend:\n{_load_error}", flush=True)


# ── RPC handler ───────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):  # silence default logging
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        """Serve static assets from public/."""
        rel = self.path.split("?")[0].lstrip("/")
        target = os.path.abspath(os.path.join(_public_dir, rel))
        # Path-traversal guard: must stay inside public/
        if not target.startswith(os.path.abspath(_public_dir)):
            self.send_error(403)
            return
        if os.path.isfile(target):
            self.send_response(200)
            mime, _ = mimetypes.guess_type(target)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self._cors()
            self.end_headers()
            with open(target, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/rpc":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"

        response = self._dispatch(raw)

        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, raw: bytes) -> dict:
        """Parse the RPC payload, call the backend function, return a result."""
        method = ""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            method = str(payload.get("method", ""))
            args = payload.get("args", {})
            if not isinstance(args, dict):
                args = {}

            # Frontend-side logging shortcut
            if method == "Logger.log":
                print(f"[JS] {args.get('message', '')}", flush=True)
                return {"success": True, "result": "logged"}

            if _main is None:
                return {"success": False,
                        "error": f"backend failed to load: {_load_error[:300]}"}

            func = getattr(_main, method, None)
            if func is None or not callable(func):
                return {"success": False,
                        "error": f"unknown method: {method}"}

            # Call with kwargs; fall back to no-args if the signature differs
            try:
                result = func(**args)
            except TypeError:
                result = func()
            return {"success": True, "result": result}

        except Exception as exc:
            print(f"[bridge] RPC error in '{method}':\n{traceback.format_exc()}",
                  flush=True)
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def run():
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), _Handler)
    except OSError as exc:
        # Port already bound — most likely a previous bridge still alive.
        print(f"[bridge] cannot bind {HOST}:{PORT} ({exc}). "
              f"Is another bridge already running?", flush=True)
        sys.exit(1)

    print(f"[bridge] LuaTools RPC bridge listening on {HOST}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("[bridge] stopped", flush=True)


if __name__ == "__main__":
    run()
