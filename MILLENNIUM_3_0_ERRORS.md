# Millennium 3.0 current errors and flaws

Date: 2026-06-10

## Summary

The current Millennium 3.0 bridge path is mostly functional, but there are still two real categories of issues to address:

1. The standalone fallback API surface was incomplete for the documented Millennium 3.0 contract.
2. The test suite still emits many ResourceWarning leaks from unclosed file handles.

## 1) Verified Millennium 3.0 API contract gap

### What was failing

A dedicated regression test in [tests/test_platform_bridge_api.py](tests/test_platform_bridge_api.py) previously failed because the standalone fallback did not expose the full documented API surface:

- `cmp_version`
- `get_install_path`
- `is_plugin_enabled`
- `remove_browser_module`

This was reproduced with:

```sh
python3 -m unittest discover -s tests -p 'test_platform_bridge_api.py' -v
```

The failure output showed the missing members exactly, which confirmed the standalone bridge contract was not aligned with the Millennium 3.0 surface.

### Current status

The fallback shim in [backend/platform_bridge.py](backend/platform_bridge.py) now exposes the missing members and the standalone module registration path also includes them.

### Remaining concern

The fallback implementations are still intentionally minimal stubs (for example, `is_plugin_enabled()` always returns `True` and `remove_browser_module()` is a no-op). That is acceptable for a standalone safety net, but it is not a full semantic replacement for the real Millennium runtime.

## 2) ResourceWarning leaks still present

### What is still happening

Running the full suite with warnings promoted to errors shows many unclosed file handles, especially in:

- [backend/accela_launcher.py](backend/accela_launcher.py)
- [tests/test_health.py](tests/test_health.py)
- [tests/test_live_apply.py](tests/test_live_apply.py)
- [backend/downloads.py](backend/downloads.py)
- temporary Steam / SLSsteam config files created during tests

Verified with:

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v
```

The command exits with `EXIT_CODE=0`, but the warning summary still reports many `ResourceWarning: unclosed file ...` traces. That means the code currently passes tests but still has real cleanup defects.

## 3) Practical defect list to fix next

1. Replace the fallback stubs in [backend/platform_bridge.py](backend/platform_bridge.py) with more realistic Millennium-compatible behavior where possible.
2. Fix unclosed file handles in [backend/accela_launcher.py](backend/accela_launcher.py) and the tests that create temp config / Lua files.
3. Audit any file-open patterns in [backend/downloads.py](backend/downloads.py) to ensure all read/write paths close cleanly.
4. Add a small regression test for the fallback behavior of `cmp_version()` and `is_plugin_enabled()` so the stub semantics do not silently drift.

## 4) Bottom line

The Millennium 3.0 API-surface mismatch has been verified and corrected at the contract level, but the current codebase still has warning-based cleanup problems that should be fixed before calling the bridge path fully production-clean.
