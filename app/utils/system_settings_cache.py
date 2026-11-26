"""Request-scoped + short process-TTL cache for SystemSettings."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from flask import current_app, g, has_app_context, has_request_context

_G_KEY = "_system_settings_map"
_REDIS_VERSION_KEY = "prismateams:system_settings:ver"
_listeners_registered = False

# Process-weiter Cache: weniger DB-Last bei parallelen Requests auf kleinen VPS.
_PROCESS_TTL_SECONDS = 45.0
_process_lock = threading.Lock()
_process_map: Optional[dict[str, Any]] = None
_process_loaded_at: float = 0.0
_process_version: Optional[str] = None

_redis_lock = threading.Lock()
_redis_client: Optional[Any] = None
_redis_client_url: Optional[str] = None


def _get_redis_client() -> Optional[Any]:
    """Return a shared Redis client when REDIS_ENABLED is active, else None."""
    global _redis_client, _redis_client_url
    if not has_app_context() or not current_app.config.get("REDIS_ENABLED"):
        return None
    url = current_app.config.get("REDIS_URL") or "redis://localhost:6379/0"
    with _redis_lock:
        if _redis_client is not None and _redis_client_url == url:
            return _redis_client
        try:
            import redis

            _redis_client = redis.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=0.3,
                socket_timeout=0.3,
            )
            _redis_client_url = url
            return _redis_client
        except Exception:
            return None


def _get_remote_version() -> Optional[str]:
    client = _get_redis_client()
    if client is None:
        return None
    try:
        val = client.get(_REDIS_VERSION_KEY)
        return str(val) if val is not None else None
    except Exception:
        return None


def _bump_remote_version() -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.incr(_REDIS_VERSION_KEY)
    except Exception:
        pass


def _load_settings_from_db() -> Optional[dict[str, Any]]:
    try:
        from app.models.settings import SystemSettings

        return {row.key: row.value for row in SystemSettings.query.all()}
    except Exception:
        return None


def _get_process_cached_map() -> dict[str, Any]:
    """Return settings map, refreshing on TTL expiry or cross-worker version change."""
    global _process_map, _process_loaded_at, _process_version

    now = time.monotonic()
    remote_ver = _get_remote_version()
    with _process_lock:
        version_matches = remote_ver is None or _process_version == remote_ver
        if (
            _process_map is not None
            and (now - _process_loaded_at) < _PROCESS_TTL_SECONDS
            and version_matches
        ):
            return _process_map

        mapping = _load_settings_from_db()
        if mapping is None:
            # DB-Fehler/Startup-Race nie als leeres Dict cachen (sonst Default-Logo/-Name für 45s)
            return _process_map if _process_map is not None else {}
        if not mapping:
            # Leere Tabelle nicht cachen, damit nach Migration/Setup sofort echte Werte greifen
            return {}
        _process_map = mapping
        _process_loaded_at = now
        _process_version = remote_ver
        return mapping


def get_settings_map() -> dict[str, Any]:
    """Return all system settings as key → value (request + process cache)."""
    if has_request_context():
        cached = getattr(g, _G_KEY, None)
        if isinstance(cached, dict) and cached:
            return cached

    mapping = _get_process_cached_map()

    if has_request_context() and mapping:
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


def invalidate_system_settings_cache(bump_remote: bool = True) -> None:
    """Drop request- and process-scoped settings maps (e.g. after a write)."""
    global _process_map, _process_loaded_at, _process_version

    if has_app_context() and hasattr(g, _G_KEY):
        delattr(g, _G_KEY)

    with _process_lock:
        _process_map = None
        _process_loaded_at = 0.0
        _process_version = None

    if bump_remote:
        _bump_remote_version()


def register_settings_cache_invalidation() -> None:
    """Clear cache when SystemSettings rows change (idempotent)."""
    global _listeners_registered
    if _listeners_registered:
        return

    from sqlalchemy import event
    from sqlalchemy.orm import Session, object_session

    from app.models.settings import SystemSettings

    def _on_change(mapper, connection, target):  # noqa: ARG001
        invalidate_system_settings_cache(bump_remote=False)
        sess = object_session(target)
        if sess is not None:
            sess.info["_system_settings_dirty"] = True

    def _on_after_commit(session):
        if session.info.pop("_system_settings_dirty", False):
            invalidate_system_settings_cache(bump_remote=True)

    def _on_after_rollback(session):
        if session.info.pop("_system_settings_dirty", False):
            invalidate_system_settings_cache(bump_remote=False)

    event.listen(SystemSettings, "after_insert", _on_change)
    event.listen(SystemSettings, "after_update", _on_change)
    event.listen(SystemSettings, "after_delete", _on_change)
    event.listen(Session, "after_commit", _on_after_commit)
    event.listen(Session, "after_rollback", _on_after_rollback)
    _listeners_registered = True
