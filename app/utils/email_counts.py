"""Unread email counts for dashboard and per-folder indicators."""

from __future__ import annotations

SENT_FOLDERS = ('Sent', 'Sent Messages')


def _accessible_mailbox_ids(user):
    """IDs of multi-mailboxes the user may see; None = no filtering (legacy)."""
    if user is None:
        return None
    try:
        from app.utils.multi_mailboxes import is_email_multi_enabled, get_accessible_mailboxes
        if not is_email_multi_enabled():
            return None
        ids = [mb.id for mb in get_accessible_mailboxes(user)]
        # Hauptpostfach (NULL) ist immer dabei wenn Nutzer E-Mail-Recht hat
        return ids
    except Exception:
        return None


def _multi_enabled() -> bool:
    try:
        from app.utils.multi_mailboxes import is_email_multi_enabled
        return bool(is_email_multi_enabled())
    except Exception:
        return False


def count_unread_emails(user=None, mailbox_id=None):
    """Count incoming emails that show the 'Neu' badge (unread, not sent)."""
    try:
        from app.models.email import EmailMessage
        from sqlalchemy import or_

        query = (
            EmailMessage.query.filter_by(is_read=False, is_sent=False)
            .filter(EmailMessage.folder.notin_([*SENT_FOLDERS, 'Drafts']))
        )
        if mailbox_id is not None:
            query = query.filter(EmailMessage.mailbox_id == mailbox_id)
        elif user is not None:
            ids = _accessible_mailbox_ids(user)
            if ids is not None:
                query = query.filter(
                    or_(EmailMessage.mailbox_id.is_(None), EmailMessage.mailbox_id.in_(ids))
                )
        return query.count()
    except Exception:
        return 0


def count_unread_emails_by_folder(user=None, mailbox_id=None, *, all_accessible=False):
    """Unread counts per folder.

    mailbox_id=None bedeutet bei aktivem Multi-Postfach das Hauptpostfach (IS NULL),
    nicht „alle Postfächer“. Für Dashboard-Aggregate all_accessible=True setzen.
    """
    try:
        from sqlalchemy import func, or_

        from app import db
        from app.models.email import EmailMessage

        query = (
            db.session.query(EmailMessage.folder, func.count(EmailMessage.id))
            .filter(EmailMessage.is_read.is_(False))
            .filter(EmailMessage.folder.notin_(list(SENT_FOLDERS)))
        )
        if mailbox_id is not None:
            query = query.filter(EmailMessage.mailbox_id == mailbox_id)
        elif all_accessible and user is not None:
            ids = _accessible_mailbox_ids(user)
            if ids is not None:
                query = query.filter(
                    or_(EmailMessage.mailbox_id.is_(None), EmailMessage.mailbox_id.in_(ids))
                )
        elif _multi_enabled():
            # Explizit Hauptpostfach — nicht mit anderen Postfächern vermischen
            query = query.filter(EmailMessage.mailbox_id.is_(None))
        rows = query.group_by(EmailMessage.folder).all()
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

        if user_id:
            user = User.query.get(user_id)
            count = count_unread_emails(user=user)
            by_folder = count_unread_emails_by_folder(user=user, all_accessible=True)
            payload = {'count': count, 'by_folder': by_folder}
            emit_dashboard_update(user_id, 'email_update', payload)
            return count

        user_ids = (
            db.session.query(User.id)
            .join(EmailPermission, User.id == EmailPermission.user_id)
            .filter(EmailPermission.can_read.is_(True))
            .all()
        )
        for (uid,) in user_ids:
            user = User.query.get(uid)
            count = count_unread_emails(user=user)
            by_folder = count_unread_emails_by_folder(user=user, all_accessible=True)
            emit_dashboard_update(uid, 'email_update', {'count': count, 'by_folder': by_folder})
        return count_unread_emails()
    except Exception:
        return count_unread_emails()
