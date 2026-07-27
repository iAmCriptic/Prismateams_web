"""OnlyOffice editing presence (who has a document open)."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from flask import url_for

from app import db
from app.models.onlyoffice_session import OnlyOfficeSession

STALE_AFTER_SECONDS = 90


def _avatar_url(filename: str | None) -> str | None:
    if not filename:
        return None
    try:
        return url_for('settings.profile_picture', filename=filename)
    except Exception:
        return None


def _initials(display_name: str | None) -> str:
    """Build avatar initials; ignore punctuation like '(Admin)'."""
    cleaned = re.sub(r'[^\w\s]', ' ', display_name or '', flags=re.UNICODE)
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def cleanup_stale_sessions() -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=STALE_AFTER_SECONDS)
    stale = OnlyOfficeSession.query.filter(OnlyOfficeSession.last_seen < cutoff).all()
    count = len(stale)
    for row in stale:
        db.session.delete(row)
    return count


def upsert_session(
    *,
    file_id: int,
    session_key: str | None,
    user_id: int | None,
    guest_key: str | None,
    display_name: str,
    avatar_filename: str | None = None,
) -> OnlyOfficeSession:
    cleanup_stale_sessions()
    key = (session_key or '').strip() or secrets.token_urlsafe(24)
    row = OnlyOfficeSession.query.filter_by(session_key=key).first()
    now = datetime.utcnow()
    if row:
        row.file_id = file_id
        row.user_id = user_id
        row.guest_key = guest_key
        row.display_name = display_name[:255]
        row.avatar_filename = avatar_filename
        row.last_seen = now
    else:
        row = OnlyOfficeSession(
            file_id=file_id,
            user_id=user_id,
            guest_key=guest_key,
            display_name=display_name[:255],
            avatar_filename=avatar_filename,
            session_key=key,
            last_seen=now,
            created_at=now,
        )
        db.session.add(row)
    return row


def heartbeat_session(session_key: str) -> OnlyOfficeSession | None:
    cleanup_stale_sessions()
    row = OnlyOfficeSession.query.filter_by(session_key=session_key).first()
    if not row:
        return None
    row.last_seen = datetime.utcnow()
    return row


def leave_session(session_key: str) -> bool:
    row = OnlyOfficeSession.query.filter_by(session_key=session_key).first()
    if not row:
        return False
    db.session.delete(row)
    return True


def presence_for_file_ids(file_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    cleanup_stale_sessions()
    if not file_ids:
        return {}
    cutoff = datetime.utcnow() - timedelta(seconds=STALE_AFTER_SECONDS)
    rows = (
        OnlyOfficeSession.query.filter(
            OnlyOfficeSession.file_id.in_(file_ids),
            OnlyOfficeSession.last_seen >= cutoff,
        )
        .order_by(OnlyOfficeSession.last_seen.desc())
        .all()
    )
    result: dict[int, list[dict[str, Any]]] = {fid: [] for fid in file_ids}
    seen_users: dict[int, set[str]] = {fid: set() for fid in file_ids}
    for row in rows:
        identity = f'u:{row.user_id}' if row.user_id else f'g:{row.guest_key or row.session_key}'
        if identity in seen_users[row.file_id]:
            continue
        seen_users[row.file_id].add(identity)
        result[row.file_id].append(
            {
                'user_id': row.user_id,
                'display_name': row.display_name,
                'avatar_url': _avatar_url(row.avatar_filename),
                'initials': _initials(row.display_name),
            }
        )
    return result


def presence_for_folder(folder_id: int | None) -> dict[str, list[dict[str, Any]]]:
    from app.models.file import File

    q = File.query.filter_by(is_current=True)
    if folder_id is None:
        q = q.filter(File.folder_id.is_(None))
    else:
        q = q.filter_by(folder_id=folder_id)
    file_ids = [f.id for f in q.with_entities(File.id).all()]
    by_id = presence_for_file_ids(file_ids)
    return {str(fid): users for fid, users in by_id.items() if users}
