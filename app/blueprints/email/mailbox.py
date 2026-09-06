"""Mailbox permissions, folder trees, and list queries."""

from flask import (
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from uuid import uuid4
from app import db, mail
from app.blueprints.sse import emit_email_sync_status
from app.models.email import EmailAttachment, EmailFolder, EmailMessage, EmailPermission
from app.models.settings import SystemSettings
from app.utils.notifications import send_email_notification
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from flask_mail import Message
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import unquote
import imaplib
import email as email_module
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import threading
import time
import logging
import io
import hashlib
from markupsafe import Markup
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy import func, cast, Integer, or_
from sqlalchemy.orm import defer
import re

from app.utils.email_sender import get_logo_base64, get_logo_data, send_email_with_lock
from app.utils.lock_manager import (
    acquire_email_sync_lock,
    heartbeat_email_sync_lock,
    try_acquire_email_sync_leader,
)
from app.utils.common import format_datetime
from app.blueprints.email._bp import EMAIL_LIST_PER_PAGE, email_bp, logger

from app.blueprints.email.imap_client import (
    gmail_folder_role,
    is_sent_folder,
    is_standard_mail_folder,
)

def check_email_permission(permission_type='read'):
    """Check if current user has email permissions."""
    # Gast-Accounts haben keinen Zugriff auf E-Mail-Modul
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return False
    
    perm = EmailPermission.query.filter_by(user_id=current_user.id).first()
    if not perm:
        return False
    return perm.can_read if permission_type == 'read' else perm.can_send


def generate_email_idempotency_key(user_id, subject, recipients, body_hash, timestamp_second):
    """
    Generiere einen eindeutigen Idempotenz-Key für eine E-Mail.
    
    Args:
        user_id: ID des Benutzers
        subject: Betreff der E-Mail
        recipients: Empfänger (normalisiert)
        body_hash: Hash des E-Mail-Bodys
        timestamp_second: Timestamp auf Sekunde gerundet
    
    Returns:
        Idempotenz-Key als Hex-String
    """
    key_string = f"{user_id}:{subject}:{recipients}:{body_hash}:{timestamp_second}"
    return hashlib.sha256(key_string.encode('utf-8')).hexdigest()[:32]


def check_duplicate_email(user_id, subject, recipients, body_hash, time_window_seconds=60):
    """
    Prüfe, ob eine identische E-Mail in den letzten time_window_seconds Sekunden
    vom gleichen Benutzer versendet wurde.
    
    Args:
        user_id: ID des Benutzers
        subject: Betreff der E-Mail
        recipients: Empfänger (normalisiert, sortiert)
        body_hash: Hash des E-Mail-Bodys (MD5)
        time_window_seconds: Zeitfenster in Sekunden (Standard: 60)
    
    Returns:
        True wenn Duplikat gefunden wurde, False sonst
    """
    try:
        # Normalisiere Empfänger: sortiere und lowerc
        normalized_recipients = ','.join(sorted([r.strip().lower() for r in recipients.split(',') if r.strip()]))
        
        # Zeitfenster berechnen
        now = datetime.utcnow()
        time_threshold = now - timedelta(seconds=time_window_seconds)
        
        # Prüfe in der Datenbank nach identischen E-Mails
        # Wir prüfen auf: gleicher User, gleicher Betreff, gleiche Empfänger, innerhalb des Zeitfensters
        duplicate_query = EmailMessage.query.filter(
            EmailMessage.sent_by_user_id == user_id,
            EmailMessage.subject == subject,
            EmailMessage.recipients == normalized_recipients,
            EmailMessage.sent_at >= time_threshold,
            EmailMessage.is_sent == True
        )
        
        # Prüfe Body-Ähnlichkeit durch Vergleich des Body-Hash
        for email in duplicate_query.all():
            if email.body_html:
                # Generiere Hash des gespeicherten Body-Inhalts
                email_body_hash = hashlib.md5(email.body_html.encode('utf-8')).hexdigest()
                # Vergleiche mit dem aktuellen Body-Hash
                if email_body_hash == body_hash:
                    return True
        
        return False
        
    except Exception as e:
        logging.error(f"Fehler bei Idempotenz-Prüfung: {e}")
        # Bei Fehler: erlaube Versand (Fail-Open), aber logge Warnung
        return False


def _folder_mailbox_filter(mailbox_id):
    """SQL-Filter für EmailFolder/EmailMessage.mailbox_id (NULL = Hauptpostfach)."""
    from app.models.email import EmailFolder
    if mailbox_id is None:
        return EmailFolder.mailbox_id.is_(None)
    return EmailFolder.mailbox_id == mailbox_id


def _message_mailbox_filter(mailbox_id):
    from app.models.email import EmailMessage
    if mailbox_id is None:
        return EmailMessage.mailbox_id.is_(None)
    return EmailMessage.mailbox_id == mailbox_id


def _find_email_folder(name, mailbox_id=None):
    """Eine Ordnerzeile für Postfach; bei MySQL-NULL-Duplikaten die älteste."""
    return (
        EmailFolder.query.filter_by(name=name)
        .filter(_folder_mailbox_filter(mailbox_id))
        .order_by(EmailFolder.id.asc())
        .first()
    )


def _has_dedicated_google_mailbox() -> bool:
    try:
        from app.utils.multi_mailboxes import is_email_multi_enabled
        from app.models.email import Mailbox
        if not is_email_multi_enabled():
            return False
        return (
            Mailbox.query.filter_by(provider='google', is_active=True).first() is not None
        )
    except Exception:
        return False


def _is_provider_namespace_folder(name: str) -> bool:
    n = (name or '').strip()
    lower = n.lower()
    return (
        lower.startswith('[gmail]/')
        or lower.startswith('[google mail]/')
        or n.startswith('[Gmail]')
        or n.startswith('[Google Mail]')
    )


def _delete_messages_in_folders_on_main(folder_names):
    """Löscht Mails (+Anhänge) bestimmter Ordner nur auf dem Hauptpostfach."""
    names = [n for n in folder_names if n]
    if not names:
        return 0
    msg_ids = [
        row[0]
        for row in db.session.query(EmailMessage.id)
        .filter(EmailMessage.mailbox_id.is_(None))
        .filter(EmailMessage.folder.in_(names))
        .all()
    ]
    return _delete_email_rows_by_ids(msg_ids)


def _delete_email_rows_by_ids(msg_ids) -> int:
    from app.models.email import EmailAttachment

    ids = [int(i) for i in (msg_ids or []) if i is not None]
    if not ids:
        return 0
    chunk = 500
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        EmailAttachment.query.filter(EmailAttachment.email_id.in_(part)).delete(
            synchronize_session=False
        )
        EmailMessage.query.filter(EmailMessage.id.in_(part)).delete(synchronize_session=False)
    return len(ids)


def _base_message_id(message_id: str) -> str:
    mid = (message_id or '').strip()
    if '#mb' in mid:
        return mid.rsplit('#mb', 1)[0]
    return mid


def _extract_email_addresses(*parts) -> set:
    import re
    found = set()
    for part in parts:
        if not part:
            continue
        for addr in re.findall(r'[\w.+\-]+@[\w.\-]+', str(part).lower()):
            found.add(addr.strip().lower())
    return found


def _main_account_addresses() -> set:
    """Adressen des Hauptpostfachs aus der App-Config."""
    try:
        from app.utils.multi_mailboxes import get_main_imap_config, get_main_smtp_config
        imap = get_main_imap_config() or {}
        smtp = get_main_smtp_config() or {}
        addrs = _extract_email_addresses(
            imap.get('user'),
            smtp.get('user'),
            smtp.get('sender'),
            current_app.config.get('MAIL_USERNAME'),
            current_app.config.get('MAIL_DEFAULT_SENDER'),
        )
        return addrs
    except Exception:
        try:
            return _extract_email_addresses(
                current_app.config.get('MAIL_USERNAME'),
                current_app.config.get('MAIL_DEFAULT_SENDER'),
            )
        except Exception:
            return set()


def _email_belongs_to_main_account(msg, main_addrs: set) -> bool:
    """True, wenn die Mail klar zum Hauptpostfach gehört (Empfänger bzw. Absender)."""
    if not main_addrs:
        return True  # ohne Config nichts löschen
    if msg.is_sent or is_sent_folder(msg.folder or ''):
        involved = _extract_email_addresses(msg.sender)
    else:
        involved = _extract_email_addresses(msg.recipients, msg.cc, msg.bcc)
        # Manche Exporte speichern nur den Absender – dann konservativ behalten
        if not involved:
            return True
    if not involved:
        return True
    return bool(involved & main_addrs)


def _purge_emails_not_for_main_account() -> int:
    """Löscht Hauptpostfach-Mails, deren Empfänger/Absender nicht zur Config-Adresse passen.

    Typischer Fall nach dem alten SET-NULL-Bug: persönliche ik.me-/Gmail-Mails
    liegen unter mailbox_id NULL, obwohl MAIL_USERNAME z. B. tech-merian@ikmail.com ist.
    """
    main_addrs = _main_account_addresses()
    if not main_addrs:
        logging.info('Hauptpostfach-Adressfilter übersprungen: keine MAIL_USERNAME konfiguriert')
        return 0

    purge_ids = []
    for msg in EmailMessage.query.filter(EmailMessage.mailbox_id.is_(None)).all():
        if not _email_belongs_to_main_account(msg, main_addrs):
            purge_ids.append(msg.id)

    if not purge_ids:
        return 0
    logging.info(
        'Entferne %s Mails vom Hauptpostfach (gehören nicht zu %s); IDs z.B. %s',
        len(purge_ids),
        sorted(main_addrs),
        purge_ids[:12],
    )
    return _delete_email_rows_by_ids(purge_ids)


def _purge_stray_multi_emails_from_main() -> int:
    """Entfernt Mails, die durch SET-NULL/Kollisionen im Hauptpostfach gelandet sind.

    Erkennung:
    - message_id mit Suffix ``#mbN`` (Kollisionsmarker eines anderen Postfachs)
    - gleiche Basis-Message-ID oder gleiches (folder, imap_uid) wie solche Mails
    - IMAP-UIDs, die klar außerhalb der UID-Cluster des Hauptpostfachs liegen (z. B. Gmail)
    """
    import statistics

    marked = (
        EmailMessage.query.filter(EmailMessage.mailbox_id.is_(None))
        .filter(EmailMessage.message_id.like('%#mb%'))
        .all()
    )
    purge_ids = {m.id for m in marked}

    # Geschwister: gleiche Basis-Message-ID oder gleicher Ordner+UID
    base_mids = {_base_message_id(m.message_id) for m in marked if m.message_id}
    folder_uids = {
        (m.folder, str(m.imap_uid))
        for m in marked
        if m.folder and m.imap_uid is not None
    }
    if base_mids or folder_uids:
        candidates = EmailMessage.query.filter(EmailMessage.mailbox_id.is_(None)).all()
        for m in candidates:
            if m.id in purge_ids:
                continue
            if m.message_id and _base_message_id(m.message_id) in base_mids:
                purge_ids.add(m.id)
                continue
            if m.folder and m.imap_uid is not None and (m.folder, str(m.imap_uid)) in folder_uids:
                purge_ids.add(m.id)

    # UID-Ausreißer pro Ordner (Gmail-UIDs sind oft deutlich höher als Infomaniak etc.)
    by_folder = {}
    for m in EmailMessage.query.filter(EmailMessage.mailbox_id.is_(None)).all():
        try:
            uid = int(m.imap_uid) if m.imap_uid is not None else None
        except (TypeError, ValueError):
            uid = None
        if uid is None:
            continue
        by_folder.setdefault(m.folder or '', []).append((uid, m.id))

    for folder, pairs in by_folder.items():
        if len(pairs) < 8:
            continue
        uids = sorted(u for u, _ in pairs)
        try:
            median = statistics.median(uids)
        except statistics.StatisticsError:
            continue
        # Klarer Sprung: UID > max(3×Median, Median+500) und > 1000
        threshold = max(median * 3, median + 500, 1000)
        for uid, mid in pairs:
            if uid > threshold:
                purge_ids.add(mid)

    if not purge_ids:
        return 0
    logging.info(
        'Entferne %s fremde/verschmutzte Mails vom Hauptpostfach (IDs z.B. %s)',
        len(purge_ids),
        sorted(purge_ids)[:12],
    )
    return _delete_email_rows_by_ids(purge_ids)


def _cleanup_main_mailbox_folder_pollution():
    """Entfernt Duplikate und fremde Provider-Ordner vom Hauptpostfach (mailbox_id NULL)."""
    try:
        from app.utils.multi_mailboxes import (
            is_email_multi_enabled,
            cleanup_orphaned_multi_mailbox_rows,
        )

        changed = False

        # 0) Verwaiste Multi-Postfach-Daten (mailbox_id zeigt ins Leere)
        if is_email_multi_enabled():
            orphan_stats = cleanup_orphaned_multi_mailbox_rows()
            if any(orphan_stats.values()):
                changed = True
                logging.info('Verwaiste Multi-Postfach-Daten entfernt: %s', orphan_stats)

        # 1) Doppelte Ordnernamen unter Hauptpostfach (MySQL: UNIQUE ignoriert NULL)
        main_folders = (
            EmailFolder.query.filter(EmailFolder.mailbox_id.is_(None))
            .order_by(EmailFolder.id.asc())
            .all()
        )
        seen_names = {}
        for folder in main_folders:
            key = folder.name
            if key in seen_names:
                db.session.delete(folder)
                changed = True
            else:
                seen_names[key] = folder

        # 2) Bei Multi-Postfach: Provider-Namespaces gehören nie zum Hauptpostfach
        #    (nach Delete ohne Cascade landeten sie bisher per SET NULL hier)
        if is_email_multi_enabled():
            foreign = [
                f for f in EmailFolder.query.filter(EmailFolder.mailbox_id.is_(None)).all()
                if _is_provider_namespace_folder(f.name)
            ]
            if foreign:
                names = [f.name for f in foreign]
                _delete_messages_in_folders_on_main(names)
                for folder in foreign:
                    db.session.delete(folder)
                changed = True
                logging.info(
                    'Fremde Provider-Ordner vom Hauptpostfach entfernt: %s',
                    names,
                )

            # 3) Einzelne Mails aus anderen Postfächern (SET-NULL / #mb-Suffix / UID-Ausreißer)
            n_stray = _purge_stray_multi_emails_from_main()
            if n_stray:
                changed = True

            # 4) Mails, die nicht an die konfigurierte Hauptpostfach-Adresse gehen
            n_wrong_acct = _purge_emails_not_for_main_account()
            if n_wrong_acct:
                changed = True

        if changed:
            db.session.commit()
            logging.info('Hauptpostfach-Ordner bereinigt')
        return changed
    except Exception as exc:
        db.session.rollback()
        logging.warning('Hauptpostfach-Ordner-Bereinigung fehlgeschlagen: %s', exc)
        return False


def _build_folder_tree(all_folders):
    """Build a sorted + hierarchical view of folder list.

    Returns a list of folder dicts with keys:
        - folder: EmailFolder
        - depth: int
        - short_name: str
    Standard folders come first in a fixed order, custom folders are rendered
    as a tree sorted alphabetically at each level.
    """
    standard_folder_order = [
        'INBOX',
        'Drafts', '[Gmail]/Drafts', '[Google Mail]/Drafts',
        'Sent', 'Sent Messages', '[Gmail]/Sent Mail', '[Google Mail]/Sent Mail',
        'Archive', 'Archives',
        'Trash', 'Deleted Messages', '[Gmail]/Trash', '[Google Mail]/Trash', '[Gmail]/Bin',
        'Spam', 'Junk', '[Gmail]/Spam', '[Google Mail]/Spam',
        'Starred', '[Gmail]/Starred',
        'Important', '[Gmail]/Important',
        'All Mail', '[Gmail]/All Mail', '[Google Mail]/All Mail',
    ]

    standard_folders = []
    custom_folders = []
    for folder in all_folders:
        if folder.is_system or (folder.folder_type == 'standard' and folder.name in standard_folder_order) or is_standard_mail_folder(folder.name):
            standard_folders.append(folder)
        else:
            custom_folders.append(folder)

    def standard_sort_key(f):
        try:
            return standard_folder_order.index(f.name)
        except ValueError:
            role = gmail_folder_role(f.name)
            role_order = {
                'Drafts': 1, 'Sent': 2, 'Archive': 3, 'Trash': 4,
                'Spam': 5, 'Starred': 6, 'Important': 7, 'All Mail': 8,
            }
            return 50 + role_order.get(role or '', 40)

    standard_folders.sort(key=standard_sort_key)

    # Gleicher Anzeigename (z. B. Archive + Archives → „Archiv“) nur einmal
    deduped_standard = []
    seen_display = set()
    for f in standard_folders:
        label = (f.display_name or f.name or '').strip().lower()
        role = gmail_folder_role(f.name)
        dedupe_key = role or label or f.name
        if dedupe_key in seen_display:
            continue
        seen_display.add(dedupe_key)
        deduped_standard.append(f)
    standard_folders = deduped_standard

    # Build tree for custom folders by parent_folder
    custom_by_parent = {}
    for f in custom_folders:
        custom_by_parent.setdefault(f.parent_folder, []).append(f)
    for arr in custom_by_parent.values():
        arr.sort(key=lambda x: (x.short_name or x.name).lower())

    ordered = []
    for f in standard_folders:
        ordered.append({
            'folder': f,
            'depth': 0,
            'short_name': f.display_name,
        })

    def walk_custom(parent_name, depth):
        children = custom_by_parent.get(parent_name, [])
        for child in children:
            ordered.append({
                'folder': child,
                'depth': depth,
                'short_name': child.short_name or child.display_name,
            })
            walk_custom(child.name, depth + 1)

    # Start with roots (parent None or parent that is a system folder not already nested).
    walk_custom(None, 0)
    # Also handle custom folders whose parent is a system folder (rare)
    handled_names = {entry['folder'].name for entry in ordered}
    for parent_name, children in custom_by_parent.items():
        if parent_name and parent_name not in handled_names:
            # Parent is a system folder – render these children as top-level for simplicity
            for child in children:
                if child.name not in handled_names:
                    ordered.append({
                        'folder': child,
                        'depth': 0,
                        'short_name': child.short_name or child.display_name,
                    })
                    walk_custom(child.name, 1)
    return ordered


def _folder_tree_context(mailbox_id=None):
    if mailbox_id is None:
        _cleanup_main_mailbox_folder_pollution()
    all_folders = (
        EmailFolder.query.filter(_folder_mailbox_filter(mailbox_id)).all()
    )
    # Sicherheit: namensgleiche Duplikate in der UI zusammenführen
    deduped = []
    seen = set()
    for folder in sorted(all_folders, key=lambda f: f.id or 0):
        if folder.name in seen:
            continue
        seen.add(folder.name)
        deduped.append(folder)
    ordered = _build_folder_tree(deduped)
    # `folders` is kept as flat list for backwards compatibility with the
    # templates; `folder_tree` adds depth information for the sidebar.
    flat = [entry['folder'] for entry in ordered]
    return flat, ordered


def _multi_mailbox_sidebar_trees(user, accessible_mailboxes):
    """Ordnerbäume + Unread-Counts für Hauptpostfach und alle zugänglichen Multi-Postfächer."""
    from app.utils.email_counts import count_unread_emails_by_folder

    trees = {}
    unread = {}
    _, trees['main'] = _folder_tree_context(mailbox_id=None)
    unread['main'] = count_unread_emails_by_folder(user=user, mailbox_id=None)
    for mb in accessible_mailboxes or []:
        _, trees[mb.id] = _folder_tree_context(mailbox_id=mb.id)
        unread[mb.id] = count_unread_emails_by_folder(user=user, mailbox_id=mb.id)
    return trees, unread


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _emails_for_folder(
    folder_name: str,
    search_query: str = '',
    mailbox_id=None,
    page: int = 1,
    per_page: int = EMAIL_LIST_PER_PAGE,
):
    """Load a page of emails for a folder (bodies: text only, no HTML)."""
    query = EmailMessage.query.options(
        defer(EmailMessage.body_html),
    ).filter_by(folder=folder_name).filter(
        _message_mailbox_filter(mailbox_id)
    )
    if search_query:
        query = query.filter(
            EmailMessage.subject.ilike(f'%{_escape_like(search_query)}%', escape='\\')
        )
    page = max(1, int(page or 1))
    per_page = min(max(1, int(per_page or EMAIL_LIST_PER_PAGE)), EMAIL_LIST_PER_PAGE)
    return query.order_by(EmailMessage.received_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )


def _restore_false_deleted_flags(emails, folder_name: str) -> None:
    restored_count = 0
    for email in emails:
        if email.is_deleted_imap:
            email.is_deleted_imap = False
            restored_count += 1
    if restored_count > 0:
        db.session.commit()
        logging.info(
            f"Wiederhergestellt {restored_count} fälschlicherweise als gelöscht "
            f"markierte E-Mails im Ordner '{folder_name}'"
        )


def _resolve_request_mailbox(permission='read'):
    """Parse ?mailbox= from request; return (mailbox_or_None, mailbox_id)."""
    from app.utils.multi_mailboxes import (
        is_email_multi_enabled,
        get_mailbox_for_user,
    )
    raw = request.args.get('mailbox') or request.form.get('mailbox_id') or request.form.get('mailbox')
    if not is_email_multi_enabled() or raw in (None, '', 'main', '0'):
        return None, None
    try:
        mid = int(raw)
    except (TypeError, ValueError):
        return None, None
    mb = get_mailbox_for_user(current_user, mid, permission=permission)
    if mb is None:
        return None, None
    return mb, mb.id
