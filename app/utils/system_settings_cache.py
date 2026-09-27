"""Request-scoped + short process-TTL cache for SystemSettings."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from flask import g, has_request_context

_G_KEY = "_system_settings_map"
_listeners_registered = False

# Process-weiter Cache: weniger DB-Last bei parallelen Requests auf kleinen VPS.
_PROCESS_TTL_SECONDS = 45.0
_process_lock = threading.Lock()
_process_map: Optional[dict[str, Any]] = None
_process_loaded_at: float = 0.0


def _load_settings_from_db() -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    try:
        from app.models.settings import SystemSettings

        mapping = {row.key: row.value for row in SystemSettings.query.all()}
    except Exception:
        mapping = {}
    return mapping


def _get_process_cached_map() -> dict[str, Any]:
    """Return settings map, refreshing at most every _PROCESS_TTL_SECONDS."""
    global _process_map, _process_loaded_at

    now = time.monotonic()
    with _process_lock:
        if (
            _process_map is not None
            and (now - _process_loaded_at) < _PROCESS_TTL_SECONDS
        ):
            return _process_map

        mapping = _load_settings_from_db()
        _process_map = mapping
        _process_loaded_at = now
        return mapping


def get_settings_map() -> dict[str, Any]:
    """Return all system settings as key → value (request + process cache)."""
    if has_request_context():
        cached = getattr(g, _G_KEY, None)
        if isinstance(cached, dict):
            return cached

    mapping = _get_process_cached_map()

    if has_request_context():
        setattr(g, _G_KEY, mapping)
    return mapping


def get_setting(key: str, default: Optional[Any] = None) -> Optional[Any]:
    """Read one setting from the request-scoped map."""
    mapping = get_settings_map()
    if key not in mapping:
        return default
    value = mapping[key]
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == "":
        return default
    return value


_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})


def setting_bool(key: str, default: bool = False) -> bool:
    """Read a boolean setting from the request-scoped map."""
    value = get_setting(key)
    if value is None:
        return default
    return str(value).strip().lower() in _TRUE_VALUES


def setting_exists(key: str) -> bool:
    """True if the key is stored and non-empty."""
    return get_setting(key) is not None


def invalidate_system_settings_cache() -> None:
    """Drop request- and process-scoped settings maps (e.g. after a write)."""
    global _process_map, _process_loaded_at

    if has_request_context() and hasattr(g, _G_KEY):
        delattr(g, _G_KEY)

    with _process_lock:
        _process_map = None
        _process_loaded_at = 0.0


def register_settings_cache_invalidation() -> None:
    """Clear cache when SystemSettings rows change (idempotent)."""
    global _listeners_registered
    if _listeners_registered:
        return

    from sqlalchemy import event

    from app.models.settings import SystemSettings

    def _on_change(mapper, connection, target):  # noqa: ARG001
        invalidate_system_settings_cache()

    event.listen(SystemSettings, "after_insert", _on_change)
    event.listen(SystemSettings, "after_update", _on_change)
    event.listen(SystemSettings, "after_delete", _on_change)
    _listeners_registered = True
