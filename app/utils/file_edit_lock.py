"""Exclusive edit locks for text/markdown files in the files module."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from flask import url_for

from app import db
from app.models.file import FileEditLock
from app.models.user import User

DEFAULT_TTL_SECONDS = 90


def purge_expired() -> int:
    now = datetime.utcnow()
    count = FileEditLock.query.filter(FileEditLock.expires_at <= now).delete(synchronize_session=False)
    if count:
        db.session.flush()
    return int(count or 0)


def get_active_lock(file_id: int) -> FileEditLock | None:
    purge_expired()
    return FileEditLock.query.filter_by(file_id=file_id).first()


def _locker_payload(lock: FileEditLock) -> dict[str, Any]:
    user = lock.locker or User.query.get(lock.locked_by)
    display_name = (user.full_name if user else None) or 'Unbekannt'
    avatar_url = None
    avatar = getattr(user, 'profile_picture', None) if user else None
    if avatar:
        try:
            avatar_url = url_for('settings.profile_picture', filename=avatar)
        except Exception:
            avatar_url = None
    return {
        'user_id': lock.locked_by,
        'display_name': display_name,
        'avatar_url': avatar_url,
        'expires_at': lock.expires_at.isoformat() + 'Z' if lock.expires_at else None,
    }


def acquire(
    file_id: int,
    user_id: int,
    *,
    session_key: str | None = None,
    ttl_seconds: int | None = None,
) -> tuple[FileEditLock | None, FileEditLock | None]:
    """
    Try to acquire an exclusive edit lock.

    Returns (lock, None) on success, or (None, blocking_lock) if another user holds it.
    """
    ttl = int(ttl_seconds or DEFAULT_TTL_SECONDS)
    now = datetime.utcnow()
    lock = get_active_lock(file_id)

    if lock and lock.locked_by != user_id:
        return None, lock

    key = (session_key or '').strip() or secrets.token_urlsafe(24)
    if not lock:
        lock = FileEditLock(
            file_id=file_id,
            locked_by=user_id,
            session_key=key,
            last_heartbeat_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        db.session.add(lock)
    else:
        # Same user: refresh and optionally rotate session key when starting fresh.
        if session_key:
            lock.session_key = key
        lock.refresh(ttl_seconds=ttl)

    db.session.flush()
    return lock, None


def heartbeat(session_key: str, user_id: int, ttl_seconds: int | None = None) -> FileEditLock | None:
    ttl = int(ttl_seconds or DEFAULT_TTL_SECONDS)
    purge_expired()
    lock = FileEditLock.query.filter_by(session_key=session_key).first()
    if not lock or lock.locked_by != user_id:
        return None
    lock.refresh(ttl_seconds=ttl)
    db.session.flush()
    return lock


def release(session_key: str, user_id: int) -> bool:
    purge_expired()
    lock = FileEditLock.query.filter_by(session_key=session_key).first()
    if not lock or lock.locked_by != user_id:
        return False
    db.session.delete(lock)
    db.session.flush()
    return True


def release_for_file(file_id: int, user_id: int) -> bool:
    lock = get_active_lock(file_id)
    if not lock or lock.locked_by != user_id:
        return False
    db.session.delete(lock)
    db.session.flush()
    return True


def user_holds_lock(file_id: int, user_id: int) -> bool:
    lock = get_active_lock(file_id)
    return bool(lock and lock.locked_by == user_id)


def serialize_lock(lock: FileEditLock | None, *, include_session: bool = True) -> dict[str, Any] | None:
    if not lock:
        return None
    payload = _locker_payload(lock)
    payload['file_id'] = lock.file_id
    if include_session:
        payload['session_key'] = lock.session_key
    return payload
