/*
 * LuaTools bridge shim (v9.1)
 *
 * On Millennium 3.0+ the native Python backend is gone; the backend now runs
 * as a standalone HTTP server (web_bridge_server.py) on 127.0.0.1:38495.
 * This shim redirects Millennium.callServerMethod to that server so the
 * existing frontend (luatools.js) works unchanged.
 *
 * Loaded before luatools.js by main.lua.
 */
(function () {
    "use strict";
    if (typeof window === "undefined") return;

    var BRIDGE_URL = "http://127.0.0.1:38495/rpc";

    window.Millennium = window.Millennium || {};

    // Preserve a native implementation if one somehow exists.
    var nativeCall = window.Millennium.callServerMethod;

    function _sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    // POST once. A rejected fetch (connection refused) means the request never
    // reached the server, so the caller may safely retry even non-idempotent
    // methods. An HTTP/RPC error means the server DID receive it — never retry.
    function _post(payload) {
        return fetch(BRIDGE_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(function (res) {
            if (!res || !res.ok) {
                var e = new Error("LuaTools bridge HTTP " + (res ? res.status : "?"));
                e._reachedServer = true;   // do not retry
                throw e;
            }
            return res.json();
        }).then(function (body) {
            if (!body || body.success !== true) {
                var e = new Error((body && body.error) ? String(body.error) : "LuaTools RPC failed");
                e._reachedServer = true;   // server answered; do not retry
                throw e;
            }
            return body.result;
        });
    }

    window.Millennium.callServerMethod = function (plugin, method, args) {
        var payload = {
            method: String(method || ""),
            args: (args && typeof args === "object") ? args : {}
        };
        // On first run the Lua bootstrapper builds a venv + pip-installs before
        // the Python server binds :38495. Retry ONLY connection-level failures
        // (request never landed) so calls during that window don't silently die.
        var MAX_ATTEMPTS = 5;
        function attempt(n) {
            return _post(payload).catch(function (err) {
                var transient = !err || !err._reachedServer;   // fetch reject = not yet up
                if (transient && n < MAX_ATTEMPTS) {
                    return _sleep(400 * n).then(function () { return attempt(n + 1); });
                }
                if (typeof nativeCall === "function") {
                    return nativeCall(plugin, method, args);   // legacy fallback
                }
                throw err;
            });
        }
        return attempt(1);
    };

    console.log("[LuaTools] bridge shim active -> " + BRIDGE_URL);
})();
