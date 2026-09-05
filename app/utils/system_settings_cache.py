"""Request-scoped cache for SystemSettings (one DB load per request)."""

from __future__ import annotations

from typing import Any, Optional

from flask import g, has_request_context

_G_KEY = "_system_settings_map"
_listeners_registered = False


def get_settings_map() -> dict[str, Any]:
    """Return all system settings as key → value (loaded once per request)."""
    if has_request_context():
        cached = getattr(g, _G_KEY, None)
        if isinstance(cached, dict):
            return cached

    mapping: dict[str, Any] = {}
    try:
        from app.models.settings import SystemSettings

        mapping = {row.key: row.value for row in SystemSettings.query.all()}
    except Exception:
        mapping = {}

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


def invalidate_system_settings_cache() -> None:
    """Drop the request-scoped settings map (e.g. after a write)."""
    if has_request_context() and hasattr(g, _G_KEY):
        delattr(g, _G_KEY)


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
