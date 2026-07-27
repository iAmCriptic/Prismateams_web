"""Unread email counts for dashboard and per-folder indicators."""

from __future__ import annotations

SENT_FOLDERS = ('Sent', 'Sent Messages')


def count_unread_emails():
    """Count incoming emails that show the 'Neu' badge (unread, not sent)."""
    try:
        from app.models.email import EmailMessage

        return (
            EmailMessage.query.filter_by(is_read=False, is_sent=False)
            .filter(EmailMessage.folder.notin_([*SENT_FOLDERS, 'Drafts']))
            .count()
        )
    except Exception:
        return 0


def count_unread_emails_by_folder():
    """Unread counts per folder (same idea as the 'Neu' flag; Sent excluded)."""
    try:
        from sqlalchemy import func

        from app import db
        from app.models.email import EmailMessage

        rows = (
            db.session.query(EmailMessage.folder, func.count(EmailMessage.id))
            .filter(EmailMessage.is_read.is_(False))
            .filter(EmailMessage.folder.notin_(list(SENT_FOLDERS)))
            .group_by(EmailMessage.folder)
            .all()
        )
        return {folder: int(count) for folder, count in rows if folder}
    except Exception:
        return {}


def emit_email_unread_update(user_id=None):
    """Push current unread totals (and per-folder) to dashboard / email UI listeners."""
    try:
        from app.models.email import EmailPermission
        from app.models.user import User
        from app.utils.dashboard_events import emit_dashboard_update
        from app import db

        count = count_unread_emails()
        by_folder = count_unread_emails_by_folder()
        payload = {'count': count, 'by_folder': by_folder}

        if user_id:
            emit_dashboard_update(user_id, 'email_update', payload)
            return count

        user_ids = (
            db.session.query(User.id)
            .join(EmailPermission, User.id == EmailPermission.user_id)
            .filter(EmailPermission.can_read.is_(True))
            .all()
        )
        for (uid,) in user_ids:
            emit_dashboard_update(uid, 'email_update', payload)
        return count
    except Exception:
        return count_unread_emails()
