"""Batch index for IMAP folder sync (avoids per-UID/message_id queries)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from app import db
from app.models.email import EmailMessage


class FolderSyncIndex:
    """In-memory lookup of mailbox emails for one folder sync run."""

    def __init__(self, folder_name: str, mailbox_id):
        self.folder_name = folder_name
        self.mailbox_id = mailbox_id
        self.by_uid: dict[str, EmailMessage] = {}
        self.by_mid_rows: dict[str, list[EmailMessage]] = defaultdict(list)
        self.global_mid_mailbox: dict[str, int | None] = {}
        self.reload()

    def reload(self) -> None:
        rows = (
            EmailMessage.query.filter_by(mailbox_id=self.mailbox_id)
            .order_by(EmailMessage.id.asc())
            .all()
        )
        self.by_uid = {}
        self.by_mid_rows = defaultdict(list)
        for row in rows:
            if row.folder == self.folder_name and row.imap_uid is not None:
                self.by_uid[str(row.imap_uid)] = row
            if row.message_id:
                self.by_mid_rows[row.message_id].append(row)

        self.global_mid_mailbox = {}
        for mid, mb_id in (
            db.session.query(EmailMessage.message_id, EmailMessage.mailbox_id)
            .filter(EmailMessage.message_id.isnot(None))
            .order_by(EmailMessage.id.asc())
            .all()
        ):
            if mid not in self.global_mid_mailbox:
                self.global_mid_mailbox[mid] = mb_id

    def get_by_uid(self, imap_uid) -> EmailMessage | None:
        if imap_uid is None:
            return None
        return self.by_uid.get(str(imap_uid))

    def get_by_mid(self, message_id: str, *, folder=None, exclude_folder=None) -> EmailMessage | None:
        if not message_id:
            return None
        for row in self.by_mid_rows.get(message_id) or []:
            if folder is not None and row.folder != folder:
                continue
            if exclude_folder is not None and row.folder == exclude_folder:
                continue
            return row
        return None

    def global_owner_mailbox(self, message_id: str):
        if not message_id:
            return None
        return self.global_mid_mailbox.get(message_id)

    def remember(self, row: EmailMessage) -> None:
        if row.folder == self.folder_name and row.imap_uid is not None:
            self.by_uid[str(row.imap_uid)] = row
        if row.message_id:
            rows = self.by_mid_rows[row.message_id]
            if row not in rows:
                rows.append(row)
            if row.message_id not in self.global_mid_mailbox:
                self.global_mid_mailbox[row.message_id] = row.mailbox_id

    def forget(self, row: EmailMessage) -> None:
        if row.imap_uid is not None:
            self.by_uid.pop(str(row.imap_uid), None)
        if row.message_id:
            rows = self.by_mid_rows.get(row.message_id) or []
            self.by_mid_rows[row.message_id] = [r for r in rows if r.id != row.id]


def mark_missing_server_uids(index: FolderSyncIndex, current_imap_uids: set[str], stats: dict) -> None:
    """Mark/move local rows whose IMAP UID is no longer on the server."""
    for uid, email_obj in list(index.by_uid.items()):
        if uid in current_imap_uids:
            continue
        other = index.get_by_mid(email_obj.message_id, exclude_folder=index.folder_name)
        if other:
            db.session.delete(email_obj)
            index.forget(email_obj)
            stats['moved_emails'] += 1
        else:
            email_obj.is_deleted_imap = True
            email_obj.last_imap_sync = datetime.utcnow()
            stats['deleted_emails'] += 1
