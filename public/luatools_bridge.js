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

    window.Millennium.callServerMethod = function (plugin, method, args) {
        var payload = {
            method: String(method || ""),
            args: (args && typeof args === "object") ? args : {}
        };
        return fetch(BRIDGE_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(function (res) {
            if (!res || !res.ok) {
                throw new Error("LuaTools bridge unavailable (HTTP "
                                 + (res ? res.status : "no response") + ")");
            }
            return res.json();
        }).then(function (body) {
            if (!body || body.success !== true) {
                throw new Error((body && body.error)
                                ? String(body.error)
                                : "LuaTools RPC failed");
            }
            return body.result;
        }).catch(function (err) {
            if (typeof nativeCall === "function") {
                console.warn("[LuaTools] bridge unavailable, falling back to native Millennium.callServerMethod:", err);
                return nativeCall(plugin, method, args);
            }
            console.error("[LuaTools] bridge error:", err);
            throw err;
        });
    };

    console.log("[LuaTools] Millennium 3.0 bridge shim active -> " + BRIDGE_URL);
})();
