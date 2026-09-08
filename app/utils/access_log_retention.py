"""Retention cleanup for IP/UA-bearing records (sessions + share access logs)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import current_app

from app import db

logger = logging.getLogger(__name__)

SETTING_SESSION_DAYS = 'session_record_retention_days'
SETTING_SHARE_LOG_DAYS = 'share_access_log_retention_days'
DEFAULT_SESSION_DAYS = 30
DEFAULT_SHARE_LOG_DAYS = 90


def _read_days(setting_key: str, config_key: str, default: int) -> int:
    try:
        from app.models.settings import SystemSettings
        row = SystemSettings.query.filter_by(key=setting_key).first()
        if row is not None and str(row.value).strip() != '':
            return max(0, int(str(row.value).strip()))
    except Exception:
        pass
    try:
        return max(0, int(current_app.config.get(config_key, default)))
    except (TypeError, ValueError):
        return default


def get_session_record_retention_days() -> int:
    return _read_days(SETTING_SESSION_DAYS, 'SESSION_RECORD_RETENTION_DAYS', DEFAULT_SESSION_DAYS)


def get_share_access_log_retention_days() -> int:
    return _read_days(SETTING_SHARE_LOG_DAYS, 'SHARE_ACCESS_LOG_RETENTION_DAYS', DEFAULT_SHARE_LOG_DAYS)


def set_session_record_retention_days(days: int) -> None:
    _upsert_days(SETTING_SESSION_DAYS, days, 'Aufbewahrung UserSession-Zeilen in Tagen (0 = kein Auto-Purge)')


def set_share_access_log_retention_days(days: int) -> None:
    _upsert_days(SETTING_SHARE_LOG_DAYS, days, 'Aufbewahrung ShareAccessLog in Tagen (0 = kein Auto-Purge)')


def _upsert_days(key: str, days: int, description: str) -> None:
    from app.models.settings import SystemSettings
    days = max(0, min(3650, int(days)))
    row = SystemSettings.query.filter_by(key=key).first()
    if row:
        row.value = str(days)
    else:
        db.session.add(SystemSettings(key=key, value=str(days), description=description))


def purge_expired_access_logs() -> dict:
    """Delete expired UserSession rows and ShareAccessLog entries. Returns counts."""
    from app.models.user_session import UserSession
    from app.models.public_share import ShareAccessLog

    session_days = get_session_record_retention_days()
    share_days = get_share_access_log_retention_days()
    now = datetime.utcnow()
    deleted_sessions = 0
    deleted_share_logs = 0

    if session_days > 0:
        cutoff = now - timedelta(days=session_days)
        try:
            deleted_sessions = (
                UserSession.query.filter(UserSession.last_activity < cutoff)
                .delete(synchronize_session=False)
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to purge expired user sessions')
            deleted_sessions = 0

    if share_days > 0:
        cutoff = now - timedelta(days=share_days)
        try:
            deleted_share_logs = (
                ShareAccessLog.query.filter(ShareAccessLog.accessed_at < cutoff)
                .delete(synchronize_session=False)
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to purge expired share access logs')
            deleted_share_logs = 0

    if deleted_sessions or deleted_share_logs:
        logger.info(
            'Access-log purge: sessions=%s (>%sd), share_logs=%s (>%sd)',
            deleted_sessions,
            session_days,
            deleted_share_logs,
            share_days,
        )

    return {
        'deleted_sessions': int(deleted_sessions or 0),
        'deleted_share_logs': int(deleted_share_logs or 0),
        'session_retention_days': session_days,
        'share_log_retention_days': share_days,
        'sessions_disabled': session_days <= 0,
        'share_logs_disabled': share_days <= 0,
    }
