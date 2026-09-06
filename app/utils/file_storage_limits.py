"""Datei-Groessenlimits und Speicherkontingente (global + Nutzer-Ausnahmen)."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from sqlalchemy import func

from app import db
from app.models.file import File, FileStorageException, FileVersion
from app.models.settings import SystemSettings

# Defaults (gleich Migration / frueherer Hardcode)
DEFAULT_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
DEFAULT_QUOTA_BYTES = 15 * 1024 * 1024 * 1024  # 15 GB
CONTENT_LENGTH_BUFFER = 1 * 1024 * 1024  # 1 MB

SETTING_MAX_FILE = "files_max_file_size_bytes"
SETTING_QUOTA_ENABLED = "files_storage_quota_enabled"
SETTING_QUOTA_BYTES = "files_storage_quota_bytes"

UNIT_FACTORS = {
    "KB": 1024,
    "MB": 1024 ** 2,
    "GB": 1024 ** 3,
    "TB": 1024 ** 4,
}

# P24: TTL-Cache fuer Usage-SUM (Context-Processor / Nav)
_USAGE_CACHE_TTL = 45.0
_USAGE_CACHE_MAX = 512
_usage_cache: dict[int, tuple[float, int]] = {}
_usage_cache_lock = threading.Lock()
_usage_listeners_registered = False


def _get_setting(key: str) -> Optional[str]:
    try:
        from app.utils.system_settings_cache import get_setting as cached_get

        value = cached_get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text if text != "" else None
    except Exception:
        pass
    row = SystemSettings.query.filter_by(key=key).first()
    if not row or row.value is None:
        return None
    value = str(row.value).strip()
    return value if value != "" else None


def _parse_int(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_global_max_file_size() -> int:
    return max(1, _parse_int(_get_setting(SETTING_MAX_FILE), DEFAULT_MAX_FILE_SIZE_BYTES))


def is_quota_enabled() -> bool:
    raw = _get_setting(SETTING_QUOTA_ENABLED)
    if raw is None:
        return False
    return raw.lower() in ("true", "1", "yes", "on")


def get_default_quota() -> int:
    return max(0, _parse_int(_get_setting(SETTING_QUOTA_BYTES), DEFAULT_QUOTA_BYTES))


def resolve_limits_for_user(user_id: int) -> dict[str, Any]:
    """Effektive Limits fuer einen Nutzer (Global + Ausnahme)."""
    max_file = get_global_max_file_size()
    quota_on = is_quota_enabled()
    quota = get_default_quota() if quota_on else None

    exc = FileStorageException.query.filter_by(user_id=user_id).first()
    if exc:
        if exc.max_file_size_bytes is not None and exc.max_file_size_bytes > 0:
            max_file = int(exc.max_file_size_bytes)
        if quota_on and exc.quota_bytes is not None and exc.quota_bytes >= 0:
            quota = int(exc.quota_bytes)

    return {
        "max_file_size": int(max_file),
        "quota_enabled": bool(quota_on),
        "quota_bytes": int(quota) if quota_on and quota is not None else None,
        "has_exception": exc is not None,
    }


def invalidate_user_usage_cache(user_id: Optional[int] = None) -> None:
    """Verwirft Usage-Cache (ein User oder alle)."""
    with _usage_cache_lock:
        if user_id is None:
            _usage_cache.clear()
        else:
            _usage_cache.pop(int(user_id), None)
    try:
        from flask import g, has_request_context

        if has_request_context():
            cache = getattr(g, "_user_usage_bytes", None)
            if isinstance(cache, dict):
                if user_id is None:
                    cache.clear()
                else:
                    cache.pop(int(user_id), None)
    except Exception:
        pass


def _query_user_usage_bytes(user_id: int) -> int:
    files_sum = (
        db.session.query(func.coalesce(func.sum(File.file_size), 0))
        .filter(File.uploaded_by == user_id)
        .scalar()
    )
    versions_sum = (
        db.session.query(func.coalesce(func.sum(FileVersion.file_size), 0))
        .filter(FileVersion.uploaded_by == user_id)
        .scalar()
    )
    return int(files_sum or 0) + int(versions_sum or 0)


def calculate_user_usage_bytes(user_id: int, *, use_cache: bool = True) -> int:
    """Physischer Speicher: aktuelle Dateien (inkl. Papierkorb) + Versionen."""
    uid = int(user_id)
    if use_cache:
        try:
            from flask import g, has_request_context

            if has_request_context():
                req_cache = getattr(g, "_user_usage_bytes", None)
                if req_cache is None:
                    req_cache = {}
                    g._user_usage_bytes = req_cache
                if uid in req_cache:
                    return req_cache[uid]
        except Exception:
            req_cache = None

        now = time.time()
        with _usage_cache_lock:
            entry = _usage_cache.get(uid)
            if entry and (now - entry[0]) <= _USAGE_CACHE_TTL:
                value = entry[1]
            else:
                value = None
        if value is not None:
            try:
                if req_cache is not None:
                    req_cache[uid] = value
            except Exception:
                pass
            return value

    value = _query_user_usage_bytes(uid)

    if use_cache:
        now = time.time()
        with _usage_cache_lock:
            if len(_usage_cache) >= _USAGE_CACHE_MAX:
                oldest = sorted(_usage_cache.items(), key=lambda kv: kv[1][0])[
                    : max(1, _USAGE_CACHE_MAX // 4)
                ]
                for drop_id, _ in oldest:
                    _usage_cache.pop(drop_id, None)
            _usage_cache[uid] = (now, value)
        try:
            from flask import g, has_request_context

            if has_request_context():
                req_cache = getattr(g, "_user_usage_bytes", None)
                if req_cache is None:
                    req_cache = {}
                    g._user_usage_bytes = req_cache
                req_cache[uid] = value
        except Exception:
            pass
    return value


def register_usage_cache_invalidation() -> None:
    """Invalidiert Usage-Cache bei File-/Versions-Aenderungen."""
    global _usage_listeners_registered
    if _usage_listeners_registered:
        return
    from sqlalchemy import event

    def _on_change(mapper, connection, target):  # noqa: ARG001
        uid = getattr(target, "uploaded_by", None)
        if uid is not None:
            invalidate_user_usage_cache(int(uid))

    for model in (File, FileVersion):
        event.listen(model, "after_insert", _on_change)
        event.listen(model, "after_update", _on_change)
        event.listen(model, "after_delete", _on_change)
    _usage_listeners_registered = True


def check_upload_allowed(
    user_id: int,
    new_size: int,
    *,
    pending_bytes: int = 0,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Prueft Dateilimit und Kontingent.

    pending_bytes: bereits gepruefte, noch nicht in der DB liegende Bytes derselben Batch.

    Returns:
        (ok, error_code, message)
        error_code: 'file_too_large' | 'quota_exceeded' | None
    """
    limits = resolve_limits_for_user(user_id)
    max_file = limits["max_file_size"]
    if new_size > max_file:
        try:
            from app.utils.i18n import translate
            msg = translate(
                "files.storage.file_too_large",
                limit=format_bytes_de(max_file),
            )
        except Exception:
            msg = f"Die Datei ist zu groß (max. {format_bytes_de(max_file)})."
        return (
            False,
            "file_too_large",
            msg,
        )

    if limits["quota_enabled"] and limits["quota_bytes"] is not None:
        # Upload-Check: immer frisch (kein TTL-Cache)
        usage = calculate_user_usage_bytes(user_id, use_cache=False) + max(0, int(pending_bytes))
        quota = limits["quota_bytes"]
        if usage + new_size > quota:
            free = max(0, quota - usage)
            try:
                from app.utils.i18n import translate
                msg = translate(
                    "files.storage.quota_exceeded",
                    used=format_bytes_de(usage),
                    quota=format_bytes_de(quota),
                    free=format_bytes_de(free),
                )
            except Exception:
                msg = (
                    f"Speicherkontingent voll "
                    f"({format_bytes_de(usage)} von {format_bytes_de(quota)} belegt, "
                    f"noch {format_bytes_de(free)} frei)."
                )
            return (
                False,
                "quota_exceeded",
                msg,
            )

    return True, None, None


def get_max_configured_file_size() -> int:
    """Groesstes Dateilimit (Global + alle Ausnahmen) fuer Flask MAX_CONTENT_LENGTH."""
    max_size = get_global_max_file_size()
    try:
        exc_max = (
            db.session.query(func.max(FileStorageException.max_file_size_bytes))
            .filter(FileStorageException.max_file_size_bytes.isnot(None))
            .scalar()
        )
        if exc_max is not None:
            max_size = max(max_size, int(exc_max))
    except Exception:
        # Tabelle ggf. noch nicht migriert
        pass
    return max(1, max_size)


def sync_flask_max_content_length(app=None) -> int:
    """Setzt app.config['MAX_CONTENT_LENGTH'] aus dem groessten Dateilimit + Puffer."""
    from flask import current_app

    target = app or current_app._get_current_object()
    value = get_max_configured_file_size() + CONTENT_LENGTH_BUFFER
    target.config["MAX_CONTENT_LENGTH"] = value
    return value


def format_bytes_de(n: int | float | None) -> str:
    """Menschenlesbare Groesse mit deutschem Komma (z. B. 3,29 GB)."""
    if n is None:
        return "0 B"
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "0 B"
    if value < 0:
        value = 0.0

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1

    if idx == 0:
        return f"{int(value)} {units[idx]}"
    # Zwei Nachkommastellen, deutsches Komma, trailing zeros strippen
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    text = text.replace(".", ",")
    return f"{text} {units[idx]}"


def bytes_from_value_unit(amount: float | int | str, unit: str) -> int:
    """Zahl + Einheit (KB/MB/GB/TB) -> Bytes."""
    factor = UNIT_FACTORS.get(str(unit).upper(), UNIT_FACTORS["MB"])
    try:
        num = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        num = 0.0
    return max(0, int(num * factor))


def split_bytes_for_ui(n: int | None) -> tuple[str, str]:
    """Bytes -> (Anzeigewert, Einheit) fuer Admin-Formulare."""
    if n is None or n <= 0:
        return "100", "MB"
    value = float(n)
    for unit in ("TB", "GB", "MB", "KB"):
        factor = UNIT_FACTORS[unit]
        if value >= factor:
            amount = value / factor
            text = f"{amount:.4f}".rstrip("0").rstrip(".")
            return text, unit
    return str(int(value)), "KB"


def usage_payload_for_user(user_id: int, *, force_usage: bool = False) -> dict[str, Any]:
    """JSON-Payload fuer Sidebar-Widget / API.

    P24: SUM nur wenn Quota aktiv (oder force_usage fuer Files-API).
    """
    limits = resolve_limits_for_user(user_id)
    quota = limits["quota_bytes"]
    quota_enabled = bool(limits["quota_enabled"] and quota is not None)

    if quota_enabled or force_usage:
        usage = calculate_user_usage_bytes(user_id, use_cache=True)
    else:
        usage = 0

    percent = 0.0
    if quota_enabled and quota > 0:
        percent = min(100.0, (usage / quota) * 100.0)

    return {
        "quota_enabled": quota_enabled,
        "used_bytes": usage,
        "quota_bytes": quota if quota_enabled else None,
        "percent": round(percent, 1),
        "used_label": format_bytes_de(usage),
        "quota_label": format_bytes_de(quota) if quota_enabled else None,
        "max_file_size": limits["max_file_size"],
        "max_file_label": format_bytes_de(limits["max_file_size"]),
        "warning": percent >= 80.0 if quota_enabled else False,
    }
