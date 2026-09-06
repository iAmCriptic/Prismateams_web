"""Brute-force protection for public share / dropbox passwords (token + IP)."""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from typing import Optional, Tuple

_MAX_FAILURES = 5
_LOCK_DURATION = timedelta(minutes=15)
_store: dict[str, dict] = {}
_lock = Lock()


def _client_ip() -> str:
    from flask import request

    forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return forwarded or (request.remote_addr or 'unknown')


def _bucket_key(kind: str, token: str, ip: Optional[str] = None) -> str:
    return f'{kind}:{(token or "").strip()}:{ip or _client_ip()}'


def share_auth_locked(kind: str, token: str, ip: Optional[str] = None) -> Tuple[bool, int]:
    """
    Returns (is_locked, remaining_seconds).
    """
    key = _bucket_key(kind, token, ip)
    now = datetime.utcnow()
    with _lock:
        entry = _store.get(key)
        if not entry:
            return False, 0
        until = entry.get('until')
        if until and until > now:
            return True, max(1, int((until - now).total_seconds()))
        if until and until <= now:
            entry['until'] = None
            entry['fails'] = 0
        return False, 0


def register_share_auth_failure(kind: str, token: str, ip: Optional[str] = None) -> Tuple[bool, int]:
    """
    Count a failed password attempt.
    Returns (locked_now, remaining_seconds_if_locked).
    """
    key = _bucket_key(kind, token, ip)
    now = datetime.utcnow()
    with _lock:
        entry = _store.setdefault(key, {'fails': 0, 'until': None})
        until = entry.get('until')
        if until and until > now:
            return True, max(1, int((until - now).total_seconds()))
        entry['fails'] = int(entry.get('fails') or 0) + 1
        if entry['fails'] >= _MAX_FAILURES:
            entry['until'] = now + _LOCK_DURATION
            entry['fails'] = 0
            return True, int(_LOCK_DURATION.total_seconds())
        return False, 0


def clear_share_auth_failures(kind: str, token: str, ip: Optional[str] = None) -> None:
    key = _bucket_key(kind, token, ip)
    with _lock:
        _store.pop(key, None)
