"""Serverseitige automatische Antworten (Abwesenheit) beim IMAP-Sync."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from email.utils import parseaddr
from html import escape
from typing import Optional

from flask import current_app
from flask_mail import Message

from app import db
from app.models.email import EmailMessage, Mailbox, MailboxAutoReply, MailboxAutoReplyLog
from app.utils.common import portal_now_naive


DEFAULT_SUBJECT = 'Automatische Antwort: Re: {subject}'


def mailbox_auto_reply_key(mailbox: Optional[Mailbox] = None) -> str:
    if mailbox is None or getattr(mailbox, 'id', None) is None:
        return 'main'
    return str(mailbox.id)


def get_auto_reply_config(mailbox: Optional[Mailbox] = None) -> Optional[MailboxAutoReply]:
    key = mailbox_auto_reply_key(mailbox)
    return MailboxAutoReply.query.filter_by(mailbox_key=key).first()


def get_or_create_auto_reply_config(mailbox: Optional[Mailbox] = None) -> MailboxAutoReply:
    cfg = get_auto_reply_config(mailbox)
    if cfg:
        return cfg
    cfg = MailboxAutoReply(
        mailbox_key=mailbox_auto_reply_key(mailbox),
        mailbox_id=getattr(mailbox, 'id', None) if mailbox is not None else None,
        enabled=False,
        subject=DEFAULT_SUBJECT,
        body_html='',
    )
    db.session.add(cfg)
    return cfg


def is_auto_reply_active(config: Optional[MailboxAutoReply], now: Optional[datetime] = None) -> bool:
    if not config or not config.enabled:
        return False
    if not (config.body_html or '').strip():
        return False
    now = now or portal_now_naive()
    if config.start_at and now < config.start_at:
        return False
    if config.end_at and now > config.end_at:
        return False
    return True


def _normalize_email(addr: str) -> str:
    if not addr:
        return ''
    _, email_addr = parseaddr(addr)
    return (email_addr or addr).strip().lower()


def _own_addresses(mailbox: Optional[Mailbox]) -> set:
    addrs = set()
    if mailbox is None:
        for key in ('MAIL_USERNAME', 'MAIL_DEFAULT_SENDER', 'IMAP_USERNAME'):
            raw = current_app.config.get(key) or ''
            if raw:
                addrs.add(_normalize_email(raw))
        try:
            from config import get_formatted_sender
            addrs.add(_normalize_email(get_formatted_sender() or ''))
        except Exception:
            pass
    else:
        for attr in ('smtp_username', 'imap_username', 'oauth_email'):
            raw = getattr(mailbox, attr, None) or ''
            if raw:
                addrs.add(_normalize_email(raw))
    return {a for a in addrs if a and '@' in a}


def _is_inbox_folder(folder_name: str) -> bool:
    name = (folder_name or '').strip().strip('"')
    upper = name.upper()
    if upper == 'INBOX':
        return True
    return upper.endswith('/INBOX') or upper.endswith('.INBOX')


def _looks_like_noreply(addr: str) -> bool:
    local = (addr.split('@', 1)[0] if addr else '').lower()
    if not local:
        return False
    needles = (
        'noreply', 'no-reply', 'no_reply', 'donotreply', 'do-not-reply',
        'mailer-daemon', 'mailer_daemon', 'postmaster', 'bounce',
        'auto-reply', 'autoreply', 'automatic',
    )
    return any(n in local for n in needles)


def _header_val(email_msg, name: str) -> str:
    if email_msg is None:
        return ''
    try:
        val = email_msg.get(name, '') or ''
    except Exception:
        return ''
    if isinstance(val, bytes):
        val = val.decode('utf-8', errors='ignore')
    return str(val).strip()


def should_skip_auto_reply(
    email_msg,
    *,
    mailbox: Optional[Mailbox],
    folder_name: str,
    sender_display: str,
) -> Optional[str]:
    """Gibt Skip-Grund zurück oder None wenn geantwortet werden darf."""
    from app.blueprints.email.imap_client import is_sent_folder

    if not _is_inbox_folder(folder_name) or is_sent_folder(folder_name):
        return 'not_inbox'

    auto_sub = _header_val(email_msg, 'Auto-Submitted').lower()
    if auto_sub and auto_sub != 'no':
        return 'auto_submitted'

    precedence = _header_val(email_msg, 'Precedence').lower()
    if precedence in ('bulk', 'list', 'junk'):
        return 'precedence'

    if _header_val(email_msg, 'X-Auto-Response-Suppress'):
        return 'auto_response_suppress'

    if _header_val(email_msg, 'List-Id') or _header_val(email_msg, 'List-Unsubscribe'):
        return 'mailing_list'

    sender_email = _normalize_email(sender_display or _header_val(email_msg, 'From'))
    if not sender_email or '@' not in sender_email:
        return 'no_sender'

    if sender_email in _own_addresses(mailbox):
        return 'own_address'

    if _looks_like_noreply(sender_email):
        return 'noreply'

    key = mailbox_auto_reply_key(mailbox)
    today = portal_now_naive().date()
    already = MailboxAutoReplyLog.query.filter_by(
        mailbox_key=key,
        sender_email=sender_email,
        replied_on=today,
    ).first()
    if already:
        return 'already_today'

    return None


def _html_to_plain(html: str) -> str:
    text = re.sub(r'(?i)<br\s*/?>', '\n', html or '')
    text = re.sub(r'(?i)</p\s*>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


def _render_subject(template: str, original_subject: str) -> str:
    tpl = (template or '').strip() or DEFAULT_SUBJECT
    subj = original_subject or ''
    try:
        return tpl.format(subject=subj)[:500]
    except Exception:
        return (tpl.replace('{subject}', subj))[:500]


def _parse_form_datetime(raw: str) -> Optional[datetime]:
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def apply_auto_reply_from_form(config: MailboxAutoReply, form) -> None:
    """Aktualisiert Config aus request.form (ohne commit)."""
    config.enabled = form.get('auto_reply_enabled') == 'on'
    config.subject = (form.get('auto_reply_subject') or '').strip()[:500] or DEFAULT_SUBJECT
    config.body_html = (form.get('auto_reply_body') or '').strip()
    config.start_at = _parse_form_datetime(form.get('auto_reply_start_at', ''))
    config.end_at = _parse_form_datetime(form.get('auto_reply_end_at', ''))
    config.updated_at = datetime.utcnow()


def datetime_for_input(value: Optional[datetime]) -> str:
    if not value:
        return ''
    return value.strftime('%Y-%m-%dT%H:%M')


def send_auto_reply(
    incoming: EmailMessage,
    email_msg,
    mailbox: Optional[Mailbox],
) -> bool:
    """Sendet Auto-Antwort und schreibt Tages-Log. True bei Versand."""
    config = get_auto_reply_config(mailbox)
    if not is_auto_reply_active(config):
        return False

    skip = should_skip_auto_reply(
        email_msg,
        mailbox=mailbox,
        folder_name=incoming.folder or '',
        sender_display=incoming.sender or '',
    )
    if skip:
        logging.debug('Auto-reply skipped (%s) for mailbox=%s msg=%s', skip, mailbox_auto_reply_key(mailbox), incoming.id)
        return False

    sender_email = _normalize_email(incoming.sender or _header_val(email_msg, 'From'))
    subject = _render_subject(config.subject, incoming.subject or '')
    body_html = config.body_html or ''
    # Einfacher HTML-Wrapper falls reiner Text
    if '<' not in body_html:
        body_html = '<p>' + escape(body_html).replace('\n', '<br>\n') + '</p>'
    body_plain = _html_to_plain(body_html)

    from app.utils.multi_mailboxes import get_mailbox_smtp_config
    from app.blueprints.email.imap_client import _send_flask_message_via_smtp
    from app.utils.email_sender import send_email_with_lock

    if mailbox is not None:
        smtp_cfg = get_mailbox_smtp_config(mailbox)
        from_addr = smtp_cfg.get('sender') or smtp_cfg.get('user')
    else:
        smtp_cfg = None
        try:
            from config import get_formatted_sender
            from_addr = get_formatted_sender()
        except Exception:
            from_addr = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME')

    if not from_addr:
        logging.warning('Auto-reply: no sender configured for mailbox=%s', mailbox_auto_reply_key(mailbox))
        return False

    msg = Message(
        subject=subject,
        recipients=[sender_email],
        body=body_plain,
        html=body_html,
        sender=from_addr,
    )
    msg.extra_headers = msg.extra_headers or {}
    msg.extra_headers['Auto-Submitted'] = 'auto-replied'
    msg.extra_headers['X-Auto-Response-Suppress'] = 'All'
    msg.extra_headers['Precedence'] = 'auto_reply'
    in_reply_to = _header_val(email_msg, 'Message-ID') or (incoming.message_id or '')
    if in_reply_to:
        msg.extra_headers['In-Reply-To'] = in_reply_to
        refs = _header_val(email_msg, 'References')
        msg.extra_headers['References'] = (refs + ' ' + in_reply_to).strip() if refs else in_reply_to

    if mailbox is not None:
        _send_flask_message_via_smtp(msg, smtp_cfg)
    else:
        send_email_with_lock(msg)

    today = portal_now_naive().date()
    key = mailbox_auto_reply_key(mailbox)
    log = MailboxAutoReplyLog(
        mailbox_key=key,
        sender_email=sender_email,
        replied_on=today,
    )
    db.session.add(log)

    try:
        email_record = EmailMessage(
            subject=subject,
            sender=from_addr if isinstance(from_addr, str) else str(from_addr),
            recipients=sender_email,
            body_text=body_plain,
            body_html=body_html,
            folder='Sent',
            is_sent=True,
            is_read=True,
            sent_at=datetime.utcnow(),
            mailbox_id=getattr(mailbox, 'id', None) if mailbox is not None else None,
            message_id=None,
        )
        db.session.add(email_record)
    except Exception as persist_err:
        logging.warning('Auto-reply sent but DB Sent record failed: %s', persist_err)

    try:
        db.session.commit()
    except Exception as commit_err:
        logging.warning('Auto-reply log commit failed (may still have sent): %s', commit_err)
        db.session.rollback()
        # Best-effort: nur Tages-Log (Race / Unique) erneut versuchen
        try:
            exists = MailboxAutoReplyLog.query.filter_by(
                mailbox_key=key,
                sender_email=sender_email,
                replied_on=today,
            ).first()
            if not exists:
                db.session.add(MailboxAutoReplyLog(
                    mailbox_key=key,
                    sender_email=sender_email,
                    replied_on=today,
                ))
                db.session.commit()
        except Exception:
            db.session.rollback()

    logging.info(
        'Auto-reply sent mailbox=%s to=%s for incoming=%s',
        key,
        sender_email,
        incoming.id,
    )
    return True


def maybe_send_auto_reply(
    incoming: EmailMessage,
    email_msg,
    *,
    folder_name: str,
    mailbox_id: Optional[int],
) -> None:
    """Hook für folder_sync — Fehler dürfen Sync nicht abbrechen."""
    try:
        if getattr(incoming, 'is_sent', False):
            return
        if not _is_inbox_folder(folder_name):
            return

        mailbox = None
        if mailbox_id:
            mailbox = Mailbox.query.get(mailbox_id)
            if mailbox is None or not mailbox.is_active:
                return

        config = get_auto_reply_config(mailbox)
        if not is_auto_reply_active(config):
            return

        send_auto_reply(incoming, email_msg, mailbox)
    except Exception as exc:
        logging.error('Auto-reply failed for email %s: %s', getattr(incoming, 'id', None), exc, exc_info=True)
        try:
            db.session.rollback()
        except Exception:
            pass
