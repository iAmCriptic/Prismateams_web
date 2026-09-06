"""Compose, reply, forward, draft, and HTML preview."""

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

from app.blueprints.email.html_render import (
    build_footer_html,
    build_quoted_forward_html,
    build_quoted_reply_html,
    html_to_plain_text,
    render_custom_email,
)
from app.blueprints.email.imap_client import (
    _send_flask_message_via_smtp,
    is_sent_folder,
    save_email_to_imap_sent,
)
from app.blueprints.email.mailbox import (
    _find_email_folder,
    _folder_tree_context,
    _resolve_request_mailbox,
    check_duplicate_email,
    check_email_permission,
    generate_email_idempotency_key,
)

def prefix_subject(subject: str, prefix: str) -> str:
    clean = subject or ''
    if not clean.lower().startswith(f"{prefix.lower()}: "):
        return f"{prefix}: {clean}"
    return clean


def normalize_addresses(addresses):
    if not addresses:
        return []
    raw_values = []
    if isinstance(addresses, str):
        raw_values = [addresses]
    elif isinstance(addresses, (list, tuple, set)):
        raw_values = [str(p).strip() for p in addresses if str(p).strip()]
    else:
        raw_values = [str(addresses).strip()]

    parts = []
    try:
        # Unterstützt zuverlässig Formate wie:
        # "Max Mustermann <max@firma.de>", "max@firma.de", gemischte Listen usw.
        from email.utils import getaddresses

        parsed = getaddresses(raw_values)
        for name, addr in parsed:
            candidate = (addr or '').strip()
            if not candidate:
                fallback = (name or '').strip()
                if '@' in fallback and ' ' not in fallback:
                    candidate = fallback
            if candidate:
                parts.append(candidate)
    except Exception:
        parts = []

    # Fallback bei ungewöhnlichen Rohwerten
    if not parts:
        for raw in raw_values:
            for token in str(raw).replace(';', ',').split(','):
                token = token.strip()
                if not token:
                    continue
                if '<' in token and '>' in token:
                    token = token.split('<')[-1].split('>')[0].strip()
                if token:
                    parts.append(token)

    seen = set()
    result = []
    for a in parts:
        key = a.lower()
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result


def build_plain_quote_header(email_msg: EmailMessage) -> str:
    sent_at = email_msg.received_at or email_msg.sent_at or datetime.utcnow()
    header = (
        f"Von: {email_msg.sender}\n"
        f"An: {email_msg.recipients or ''}\n"
        f"{'CC: ' + email_msg.cc + '\n' if email_msg.cc else ''}"
        f"Datum: {format_datetime(sent_at, '%d.%m.%Y %H:%M')}\n"
        f"Betreff: {email_msg.subject}\n\n"
    )
    return header


def quote_plain(email_msg: EmailMessage) -> str:
    body = email_msg.body_text or ''
    if not body and email_msg.body_html:
        import re
        body = re.sub(r'<[^>]+>', '', email_msg.body_html)
        body = body.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    
    header = build_plain_quote_header(email_msg)
    
    quoted_lines = []
    quoted_lines.append(header)
    for line in body.split('\n'):
        quoted_lines.append(f"> {line}")
    
    return '\n'.join(quoted_lines)


def build_reply_context(email_msg: EmailMessage, mode: str):
    to_list = []
    if email_msg.sender:
        to_list += normalize_addresses(email_msg.sender)
    cc_list = []
    if mode == 'reply_all':
        to_list += normalize_addresses(email_msg.recipients)
        cc_list += normalize_addresses(email_msg.cc)
        own = (current_user.email or '').lower()
        to_list = [a for a in to_list if a.lower() != own]
        cc_list = [a for a in cc_list if a.lower() != own]
    to_list = normalize_addresses(to_list)
    cc_list = normalize_addresses(cc_list)

    subject = prefix_subject(email_msg.subject or '', 'Re')
    # NOTE: We intentionally do NOT pre-fill the editor body with the quoted
    # original anymore. The reply editor stays clean so users only write their
    # reply in our CSS format. The original message is automatically appended
    # below our styled email when the reply is sent (see compose() handler
    # and build_quoted_reply_html()).
    body_prefill = ''
    
    # Extrahiere erste Zeile für Vorschau
    first_line = ''
    body_text = email_msg.body_text or ''
    if not body_text and email_msg.body_html:
        import re
        body_text = re.sub(r'<[^>]+>', '', email_msg.body_html)
        body_text = body_text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    
    if body_text:
        lines = body_text.strip().split('\n')
        first_line = lines[0].strip() if lines else ''
        if len(first_line) > 100:
            first_line = first_line[:100] + '...'
    
    # HTML-Inhalt für Vorschau vorbereiten (mit gleicher Formatierung wie in view_email)
    original_html = None
    if email_msg.body_html:
        try:
            if isinstance(email_msg.body_html, bytes):
                html_content = email_msg.body_html.decode('utf-8', errors='replace')
            else:
                html_content = str(email_msg.body_html)
            
            import re
            
            # Gleiche Formatierung wie in view_email
            html_content = html_content.replace('\u2011', '-')
            html_content = html_content.replace('\u2013', '-')
            html_content = html_content.replace('\u2014', '--')
            html_content = html_content.replace('\u2018', "'")
            html_content = html_content.replace('\u2019', "'")
            html_content = html_content.replace('\u201c', '"')
            html_content = html_content.replace('\u201d', '"')
            html_content = html_content.replace('\u2026', '...')
            html_content = html_content.replace('\ufffc', '')
            
            html_content = re.sub(r'<o:p\s*/>', '', html_content)
            html_content = re.sub(r'<o:p>.*?</o:p>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<w:.*?>.*?</w:.*?>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<m:.*?>.*?</m:.*?>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<v:.*?>.*?</v:.*?>', '', html_content, flags=re.DOTALL)
            
            html_content = re.sub(r'<a([^>]*)href="([^"]*)"([^>]*)>', r'<a\1href="\2" target="_blank" rel="noopener noreferrer"\3>', html_content)
            
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, flags=re.IGNORECASE | re.DOTALL)
            if body_match:
                body_content = body_match.group(1)
                html_content = re.sub(r'<body[^>]*>.*?</body>', '<div class="email-body-wrapper">' + body_content + '</div>', html_content, flags=re.IGNORECASE | re.DOTALL)
            else:
                if not html_content.strip().startswith('<div'):
                    html_content = '<div class="email-body-wrapper">' + html_content + '</div>'
            
            # Remove html tags
            html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE)
            
            def scope_style_tags(match):
                style_content = match.group(1) if match.group(1) else ''
                if not style_content.strip():
                    return ''
                
                lines = style_content.split('\n')
                scoped_lines = []
                in_media = False
                media_prefix = ''
                
                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped.startswith('@'):
                        if '@media' in line_stripped:
                            in_media = True
                            media_prefix = line_stripped
                            scoped_lines.append(line)
                            continue
                        elif line_stripped == '}' and in_media:
                            in_media = False
                            media_prefix = ''
                            scoped_lines.append(line)
                            continue
                    
                    if in_media:
                        if '{' in line and not line_stripped.startswith('@'):
                            scoped_line = re.sub(
                                r'([^{}]+)\{',
                                r'.email-original-content-inner \1{',
                                line
                            )
                            scoped_lines.append(scoped_line)
                        else:
                            scoped_lines.append(line)
                    else:
                        if '{' in line:
                            scoped_line = re.sub(
                                r'([^{}]+)\{',
                                r'.email-original-content-inner \1{',
                                line
                            )
                            scoped_lines.append(scoped_line)
                        else:
                            scoped_lines.append(line)
                
                scoped_css = '\n'.join(scoped_lines)
                scoped_css = re.sub(r'\.email-original-content-inner\s+\.email-original-content-inner', '.email-original-content-inner', scoped_css)
                scoped_css = re.sub(r'\.email-original-content-inner\s+body\s*\{', '.email-original-content-inner {', scoped_css, flags=re.IGNORECASE)
                scoped_css = re.sub(r'\.email-original-content-inner\s+html\s*\{', '.email-original-content-inner {', scoped_css, flags=re.IGNORECASE)
                
                return f'<style type="text/css">{scoped_css}</style>'
            
            html_content = re.sub(r'<style[^>]*>(.*?)</style>', scope_style_tags, html_content, flags=re.IGNORECASE | re.DOTALL)
            
            if not html_content.strip().startswith('<'):
                html_content = f'<div class="email-body-wrapper">{html_content}</div>'
            
            if not html_content.strip().startswith('<div class="email-original-content-inner">'):
                html_content = f'<div class="email-original-content-inner">{html_content}</div>'
            
            html_content = replace_cid_images_in_email_html(html_content, email_msg)

            from app.blueprints.email.html_render import sanitize_email_inline_html
            original_html = sanitize_email_inline_html(html_content)
        except Exception as e:
            logging.error(f"HTML processing error for original email: {e}")
            original_html = None
    
    # Anhänge-IDs für Mitnahme
    attachment_ids = [str(a.id) for a in email_msg.attachments]
    
    return {
        'to': ', '.join(to_list),
        'cc': ', '.join(cc_list),
        'bcc': '',
        'subject': subject,
        'body': body_prefill,
        'in_reply_to': email_msg.message_id or '',
        'references': email_msg.message_id or '',
        'original_email': email_msg,
        'original_html': original_html,
        'original_first_line': first_line,
        'original_attachment_ids': ','.join(attachment_ids),
        # Used by the new reply flow: the compose form posts this id back so the
        # server can append the quoted original below our styled reply.
        'reply_to_email_id': email_msg.id,
        'is_forward': False,
    }


def build_forward_context(email_msg: EmailMessage, include_attachments: bool):
    """Wie Antworten: Editor leer, Original wird beim Senden unter dem Portal-Text eingefügt."""
    subject = prefix_subject(email_msg.subject or '', 'Fwd')
    first_line = ''
    body_text = email_msg.body_text or ''
    if not body_text and email_msg.body_html:
        body_text = re.sub(r'<[^>]+>', '', email_msg.body_html)
        body_text = body_text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    if body_text:
        lines = body_text.strip().split('\n')
        first_line = lines[0].strip() if lines else ''
        if len(first_line) > 100:
            first_line = first_line[:100] + '...'
    attachment_ids = []
    if include_attachments:
        attachment_ids = [str(a.id) for a in email_msg.attachments]
    return {
        'to': '',
        'cc': '',
        'bcc': '',
        'subject': subject,
        'body': '',
        'forward_attachment_ids': ','.join(attachment_ids),
        'forward_from_email_id': email_msg.id,
        'is_forward': True,
        'is_reply': False,
        'original_email': email_msg,
        'original_first_line': first_line,
        'in_reply_to': '',
        'references': '',
    }


@email_bp.route('/reply/<int:email_id>')
@login_required
@check_module_access('module_email')
def reply(email_id: int):
    if not check_email_permission('send'):
        flash(translate('email.flash.no_send_permission'), 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_reply_context(email_msg, 'reply')
    ctx['is_reply'] = True
    ctx.update(_compose_multi_context())
    return render_template('email/compose.html', **ctx)


@email_bp.route('/reply-all/<int:email_id>')
@login_required
@check_module_access('module_email')
def reply_all(email_id: int):
    if not check_email_permission('send'):
        flash(translate('email.flash.no_send_permission'), 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_reply_context(email_msg, 'reply_all')
    ctx['is_reply'] = True
    ctx.update(_compose_multi_context())
    return render_template('email/compose.html', **ctx)


@email_bp.route('/forward/<int:email_id>')
@login_required
@check_module_access('module_email')
def forward(email_id: int):
    if not check_email_permission('send'):
        flash(translate('email.flash.no_send_permission'), 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_forward_context(email_msg, include_attachments=True)
    ctx.update(_compose_multi_context())
    return render_template('email/compose.html', **ctx)


def _compose_multi_context():
    from app.utils.multi_mailboxes import (
        is_email_multi_enabled,
        get_accessible_mailboxes,
        is_email_html_design_default,
        get_mailbox_use_logo,
        format_send_as_label,
        get_mailbox_from_address,
    )
    active_mailbox, mailbox_id = _resolve_request_mailbox('send')
    use_mailbox_logo = True
    team_logo_available = False
    if active_mailbox and active_mailbox.mailbox_type == 'team' and active_mailbox.logo_filename:
        team_logo_available = True
        use_mailbox_logo = get_mailbox_use_logo(current_user, active_mailbox)
    accessible = get_accessible_mailboxes(current_user, 'send') if is_email_multi_enabled() else []
    send_as_options = [
        {
            'id': mb.id,
            'label': format_send_as_label(mb, fallback=mb.display_name),
            'address': get_mailbox_from_address(mb),
            'display_name': mb.display_name,
        }
        for mb in accessible
    ]
    return {
        'email_multi_enabled': is_email_multi_enabled(),
        'accessible_mailboxes': accessible,
        'send_as_options': send_as_options,
        'main_send_as_label': format_send_as_label(None, fallback=translate('email.multi.main_mailbox')),
        'active_mailbox': active_mailbox,
        'active_mailbox_id': mailbox_id,
        'use_html_design': is_email_html_design_default(),
        'use_mailbox_logo': use_mailbox_logo,
        'team_logo_available': team_logo_available,
    }


@email_bp.route('/compose', methods=['GET', 'POST'])
@login_required
@check_module_access('module_email')
def compose():
    """Compose and send an email."""
    if not check_email_permission('send'):
        flash(translate('email.flash.no_send_permission'), 'danger')
        return redirect(url_for('email.index'))
    
    if request.method == 'POST':
        # Prüfe ob AJAX-Request
        is_ajax_request = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.headers.get('Accept', '').startswith('application/json')
        )
        
        to = request.form.get('to', '').strip()
        cc = request.form.get('cc', '').strip()
        bcc = request.form.get('bcc', '').strip()
        subject = request.form.get('subject', '').strip()
        body_html = request.form.get('body', '').strip()
        in_reply_to = request.form.get('in_reply_to', '').strip()
        references = request.form.get('references', '').strip()
        forward_attachment_ids = request.form.get('forward_attachment_ids', '').strip()
        original_attachment_ids = request.form.get('original_attachment_ids', '').strip()
        # New reply flow: client posts the id of the email we are replying to.
        # The server builds a quoted block and appends it below our styled reply.
        reply_to_email_id_raw = request.form.get('reply_to_email_id', '').strip()
        forward_from_email_id_raw = request.form.get('forward_from_email_id', '').strip()
        draft_id = request.form.get('draft_id', type=int)
        use_html_design = request.form.get('use_html_design', 'on') == 'on'
        active_mailbox, mailbox_id = _resolve_request_mailbox('send')
        if active_mailbox is None and request.form.get('mailbox_id'):
            from app.utils.multi_mailboxes import get_mailbox_for_user
            try:
                mid = int(request.form.get('mailbox_id'))
                active_mailbox = get_mailbox_for_user(current_user, mid, 'send')
                mailbox_id = active_mailbox.id if active_mailbox else None
            except (TypeError, ValueError):
                pass

        use_mailbox_logo = True
        if active_mailbox and active_mailbox.mailbox_type == 'team' and active_mailbox.logo_filename:
            use_mailbox_logo = request.form.get('use_mailbox_logo') == 'on'
            from app.utils.multi_mailboxes import set_mailbox_use_logo
            set_mailbox_use_logo(current_user, active_mailbox, use_mailbox_logo)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        
        if not all([to, subject, body_html]):
            error_msg = 'Bitte füllen Sie alle Pflichtfelder aus.'
            if is_ajax_request:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'danger')
            return render_template('email/compose.html')
        
        # Generiere Body-Hash für Idempotenz-Prüfung
        body_hash = hashlib.md5(body_html.encode('utf-8')).hexdigest()
        
        # Prüfe auf Duplikat (Idempotenz)
        if check_duplicate_email(current_user.id, subject, to, body_hash, time_window_seconds=60):
            error_msg = 'Diese E-Mail wurde bereits vor kurzem versendet. Bitte warten Sie einen Moment oder ändern Sie den Inhalt.'
            logging.warning(f"Doppelversendung verhindert: User {current_user.id}, Betreff: {subject}")
            if is_ajax_request:
                return jsonify({'success': False, 'message': error_msg}), 409
            flash(error_msg, 'warning')
            return render_template('email/compose.html')
        
        # Logo als CID-Anhang vorbereiten
        from app.utils.multi_mailboxes import get_mailbox_logo_data
        logo_data, logo_mime_type, logo_filename = get_mailbox_logo_data(
            active_mailbox, user=current_user, use_logo=use_mailbox_logo
        )
        logo_cid = None
        if logo_data and logo_mime_type and use_html_design:
            logo_cid = "portal_logo"
            # Logo-Bytes werden später als CID-Anhang hinzugefügt
        
        # Zitiertes Original unter unserem Text (Antwort oder Weiterleitung)
        quoted_reply_html = None
        if reply_to_email_id_raw:
            try:
                original = EmailMessage.query.get(int(reply_to_email_id_raw))
                if original is not None:
                    quoted_reply_html = build_quoted_reply_html(original)
            except (ValueError, TypeError):
                logging.warning(f"Ungültige reply_to_email_id: {reply_to_email_id_raw}")
            except Exception as quote_exc:
                logging.error(f"Fehler beim Aufbereiten der zitierten Original-E-Mail: {quote_exc}")
        elif forward_from_email_id_raw:
            try:
                original_fwd = EmailMessage.query.get(int(forward_from_email_id_raw))
                if original_fwd is not None:
                    quoted_reply_html = build_quoted_forward_html(original_fwd)
            except (ValueError, TypeError):
                logging.warning(f"Ungültige forward_from_email_id: {forward_from_email_id_raw}")
            except Exception as quote_exc:
                logging.error(f"Fehler beim Aufbereiten der weitergeleiteten Original-E-Mail: {quote_exc}")

        full_body_html, full_body_plain = render_custom_email(
            subject,
            body_html,
            logo_cid=logo_cid,
            quoted_reply_html=quoted_reply_html,
            mailbox=active_mailbox,
            use_html_design=use_html_design,
            use_mailbox_logo=use_mailbox_logo,
            logo_user=current_user,
        )
        
        
        try:
            from config import get_formatted_sender
            from app.utils.multi_mailboxes import get_mailbox_smtp_config
            if active_mailbox is not None:
                smtp_cfg = get_mailbox_smtp_config(active_mailbox)
                sender = smtp_cfg.get('sender') or smtp_cfg.get('user')
            else:
                sender = get_formatted_sender()
            if not sender:
                error_msg = 'E-Mail-Absender ist nicht konfiguriert. Bitte kontaktieren Sie den Administrator.'
                if is_ajax_request:
                    return jsonify({'success': False, 'message': error_msg}), 500
                flash(error_msg, 'danger')
                return render_template('email/compose.html')
            
            # Erstelle normale Flask-Mail Message (Flask-Mail erstellt automatisch multipart)
            msg = Message(
                subject=subject,
                recipients=to.split(','),
                body=full_body_plain,
                html=full_body_html,
                sender=sender
            )
            
            # Thread-Header setzen
            if in_reply_to:
                if not hasattr(msg, 'extra_headers') or msg.extra_headers is None:
                    msg.extra_headers = {}
                msg.extra_headers['In-Reply-To'] = in_reply_to
            if references:
                if not hasattr(msg, 'extra_headers') or msg.extra_headers is None:
                    msg.extra_headers = {}
                msg.extra_headers['References'] = references
            
            if cc:
                msg.cc = [a.strip() for a in cc.split(',') if a.strip()]
            if bcc:
                msg.bcc = [a.strip() for a in bcc.split(',') if a.strip()]
            
            # Logo als inline CID-Anhang (Flask-Mail 0.10: Content-ID in Attachment-Headers)
            if logo_data and logo_mime_type and logo_cid:
                from app.utils.email_sender import _logo_attachment_filename
                attachment_filename = _logo_attachment_filename(logo_mime_type)
                msg.attach(
                    attachment_filename,
                    logo_mime_type,
                    logo_data,
                    disposition='inline',
                    headers={'Content-ID': f'<{logo_cid}>'},
                )
                logging.info(f"Logo als inline attachment mit CID: {attachment_filename}")

            if 'attachments' in request.files:
                attachments = request.files.getlist('attachments')
                for attachment in attachments:
                    if attachment.filename:
                        msg.attach(
                            attachment.filename,
                            attachment.content_type or 'application/octet-stream',
                            attachment.read()
                        )
                        attachment.seek(0)

            # Forward attachments
            if forward_attachment_ids:
                id_list = [i for i in forward_attachment_ids.split(',') if i]
                for aid in id_list:
                    try:
                        att = EmailAttachment.query.get(int(aid))
                        if not att:
                            continue
                        if att.is_large_file and att.file_path:
                            with open(att.file_path, 'rb') as f:
                                data = f.read()
                            msg.attach(att.filename, att.content_type or 'application/octet-stream', data)
                        else:
                            data = att.get_content()
                            if data:
                                msg.attach(att.filename, att.content_type or 'application/octet-stream', data)
                    except Exception as _:
                        continue
            
            # Original attachments (from reply)
            if original_attachment_ids:
                id_list = [i for i in original_attachment_ids.split(',') if i]
                for aid in id_list:
                    try:
                        att = EmailAttachment.query.get(int(aid))
                        if not att:
                            continue
                        if att.is_large_file and att.file_path:
                            with open(att.file_path, 'rb') as f:
                                data = f.read()
                            msg.attach(att.filename, att.content_type or 'application/octet-stream', data)
                        else:
                            data = att.get_content()
                            if data:
                                msg.attach(att.filename, att.content_type or 'application/octet-stream', data)
                    except Exception as _:
                        continue

            if logo_cid:
                from app.utils.email_sender import _mark_logo_inline
                _mark_logo_inline(msg, logo_cid=logo_cid)

            if active_mailbox is not None:
                _send_flask_message_via_smtp(msg, get_mailbox_smtp_config(active_mailbox))
            else:
                send_email_with_lock(msg)
            
            # Entwurf nach erfolgreichem Versand entfernen (lokal + IMAP), damit er nicht in Entwürfe bleibt
            if draft_id:
                draft_msg = EmailMessage.query.get(draft_id)
                if (
                    draft_msg
                    and draft_msg.folder == 'Drafts'
                    and draft_msg.sent_by_user_id == current_user.id
                ):
                    if draft_msg.imap_uid:
                        imap_ok, imap_err = delete_email_from_imap(draft_msg.imap_uid, draft_msg.folder)
                        if not imap_ok:
                            logging.warning(
                                'Entwurf %s konnte auf IMAP nicht gelöscht werden: %s',
                                draft_id,
                                imap_err,
                            )
                    db.session.delete(draft_msg)
                elif draft_msg:
                    logging.warning(
                        'Ignoriere draft_id=%s beim Senden (kein Entwurf des Nutzers oder falscher Ordner).',
                        draft_id,
                    )
            
            # E-Mail im IMAP Sent-Ordner speichern und Ordner-Namen ermitteln
            sent_folder_name = 'Sent'  # Fallback-Wert
            try:
                save_success, imap_sent_folder = save_email_to_imap_sent(msg)
                if imap_sent_folder:
                    sent_folder_name = imap_sent_folder
                elif save_success:
                    # Falls erfolgreich aber kein Ordner-Name zurückgegeben, versuche den Ordner-Namen aus der Datenbank zu ermitteln
                    existing_sent_folder = EmailFolder.query.filter_by(folder_type='standard').all()
                    for folder in existing_sent_folder:
                        if is_sent_folder(folder.name):
                            sent_folder_name = folder.name
                            break
            except Exception as save_error:
                logging.warning(f"Failed to save email to IMAP Sent folder: {save_error}")
                # Nicht kritisch - E-Mail wurde bereits versendet
                # Versuche trotzdem, den richtigen Ordner-Namen zu finden
                try:
                    existing_sent_folder = EmailFolder.query.filter_by(folder_type='standard').all()
                    for folder in existing_sent_folder:
                        if is_sent_folder(folder.name):
                            sent_folder_name = folder.name
                            break
                except:
                    pass
            
            email_record = EmailMessage(
                subject=subject,
                sender=sender,
                recipients=to,
                cc=cc,
                bcc=bcc or None,
                body_text=full_body_plain,
                body_html=full_body_html,
                folder=sent_folder_name,
                is_sent=True,
                is_read=True,  # E-Mails im "Sent"-Ordner sind immer als gelesen markiert
                sent_by_user_id=current_user.id,
                sent_at=datetime.utcnow(),
                has_attachments=bool(request.files.getlist('attachments')) or bool(forward_attachment_ids) or bool(original_attachment_ids),
                mailbox_id=mailbox_id,
            )
            db.session.add(email_record)
            db.session.commit()
            
            success_msg = 'E-Mail wurde erfolgreich gesendet.'
            redirect_url = url_for('email.index')
            
            if is_ajax_request:
                return jsonify({
                    'success': True,
                    'message': success_msg,
                    'redirect_url': redirect_url
                }), 200
            
            flash(success_msg, 'success')
            return redirect(redirect_url)
        
        except Exception as e:
            error_msg = f'Fehler beim Senden der E-Mail: {str(e)}'
            logging.error(f"E-Mail-Versand Fehler: {e}", exc_info=True)
            if is_ajax_request:
                return jsonify({'success': False, 'message': error_msg}), 500
            flash(error_msg, 'danger')
            return render_template('email/compose.html')
    
    # GET Request - optionale Vorbelegung (z. B. aus Kontakte-Modul)
    to_prefill = request.args.get('to', '').strip()
    cc_prefill = request.args.get('cc', '').strip()
    bcc_prefill = request.args.get('bcc', '').strip()
    subject_prefill = request.args.get('subject', '').strip()

    # GET Request - Prüfe ob ein Entwurf geladen werden soll
    draft_id = request.args.get('draft_id', type=int)
    if draft_id:
        try:
            draft_email = EmailMessage.query.get(draft_id)
            if draft_email and draft_email.folder == 'Drafts':
                # Prüfe, ob der Benutzer Zugriff auf diesen Entwurf hat
                if draft_email.sent_by_user_id == current_user.id:
                    # Parse recipients und cc aus JSON-String falls vorhanden
                    to_list = []
                    cc_list = []
                    
                    try:
                        import json
                        if draft_email.recipients:
                            recipients_data = json.loads(draft_email.recipients) if draft_email.recipients.startswith('[') else [draft_email.recipients]
                            to_list = [r.strip() for r in recipients_data if r.strip()]
                        else:
                            to_list = [draft_email.recipients.strip()] if draft_email.recipients and draft_email.recipients.strip() else []
                    except:
                        # Fallback: Einfach als String verwenden
                        to_list = [draft_email.recipients.strip()] if draft_email.recipients and draft_email.recipients.strip() else []
                    
                    try:
                        import json
                        if draft_email.cc:
                            cc_data = json.loads(draft_email.cc) if draft_email.cc.startswith('[') else [draft_email.cc]
                            cc_list = [c.strip() for c in cc_data if c.strip()]
                        else:
                            cc_list = [draft_email.cc.strip()] if draft_email.cc and draft_email.cc.strip() else []
                    except:
                        cc_list = [draft_email.cc.strip()] if draft_email.cc and draft_email.cc.strip() else []
                    
                    bcc_list = []
                    raw_bcc = getattr(draft_email, 'bcc', None) or ''
                    if raw_bcc:
                        try:
                            import json
                            if isinstance(raw_bcc, str) and raw_bcc.startswith('['):
                                bcc_data = json.loads(raw_bcc)
                                bcc_list = [c.strip() for c in bcc_data if c and str(c).strip()]
                            else:
                                bcc_list = [str(raw_bcc).strip()] if str(raw_bcc).strip() else []
                        except Exception:
                            bcc_list = [str(raw_bcc).strip()] if str(raw_bcc).strip() else []
                    
                    # Anhänge-IDs für Mitnahme
                    attachment_ids = [str(a.id) for a in draft_email.attachments]
                    
                    return render_template('email/compose.html',
                        to=', '.join(to_list) if to_list else '',
                        cc=', '.join(cc_list) if cc_list else '',
                        bcc=', '.join(bcc_list) if bcc_list else '',
                        subject=draft_email.subject or '',
                        body=draft_email.body_html or '',
                        draft_id=draft_id,
                        original_attachment_ids=','.join(attachment_ids) if attachment_ids else '',
                        **_compose_multi_context(),
                    )
                else:
                    flash('Sie haben keinen Zugriff auf diesen Entwurf.', 'danger')
            else:
                flash('Entwurf nicht gefunden.', 'danger')
        except Exception as e:
            logging.error(f"Fehler beim Laden des Entwurfs: {e}", exc_info=True)
            flash('Fehler beim Laden des Entwurfs.', 'danger')
    
    return render_template(
        'email/compose.html',
        to=to_prefill,
        cc=cc_prefill,
        bcc=bcc_prefill,
        subject=subject_prefill,
        **_compose_multi_context(),
    )


@email_bp.route('/save_draft', methods=['POST'])
@login_required
@check_module_access('module_email')
def save_draft():
    """Speichere einen E-Mail-Entwurf."""
    if not check_email_permission('send'):
        return jsonify({'success': False, 'message': 'Nicht autorisiert'}), 403
    
    try:
        # Unterstütze sowohl JSON als auch FormData
        if request.is_json:
            data = request.get_json()
            to = (data.get('to') or '').strip()
            cc = (data.get('cc') or '').strip()
            bcc = (data.get('bcc') or '').strip()
            subject = (data.get('subject') or '').strip()
            body_html = (data.get('body') or '').strip()
            in_reply_to = (data.get('in_reply_to') or '').strip()
            references = (data.get('references') or '').strip()
            draft_id_raw = data.get('draft_id')
            try:
                draft_id = int(draft_id_raw) if draft_id_raw else None
            except (TypeError, ValueError):
                draft_id = None
            has_attachments = False
        else:
            data = request.form
            to = (data.get('to') or '').strip()
            cc = (data.get('cc') or '').strip()
            bcc = (data.get('bcc') or '').strip()
            subject = (data.get('subject') or '').strip()
            body_html = (data.get('body') or '').strip()
            in_reply_to = (data.get('in_reply_to') or '').strip()
            references = (data.get('references') or '').strip()
            draft_id = data.get('draft_id', type=int)
            has_attachments = bool(request.files.getlist('attachments'))
        
        # Prüfe, ob HTML tatsächlich Text enthält (nicht nur leere Tags)
        def has_real_text_in_html(html_content):
            """Prüft, ob HTML tatsächlich Text enthält, nicht nur leere Tags."""
            if not html_content or not html_content.strip():
                return False
            
            # Entferne alle HTML-Tags und prüfe, ob noch Text übrig ist
            import re
            text_only = re.sub(r'<[^>]+>', '', html_content)
            text_only = re.sub(r'&nbsp;', ' ', text_only)  # Ersetze &nbsp; durch Leerzeichen
            text_only = re.sub(r'\s+', ' ', text_only)  # Normalisiere Whitespace
            return text_only.strip() != ''
        
        # Prüfe, ob überhaupt ein Entwurf vorhanden ist
        has_real_html_content = has_real_text_in_html(body_html)
        has_content = bool(subject or has_real_html_content or has_attachments)
        
        if not has_content:
            return jsonify({'success': False, 'message': 'Kein Entwurf zum Speichern'}), 400
        
        # Stelle sicher, dass der Drafts-Ordner existiert
        drafts_folder = EmailFolder.query.filter_by(name='Drafts').first()
        if not drafts_folder:
            drafts_folder = EmailFolder(
                name='Drafts',
                display_name='Entwürfe',
                folder_type='standard',
                is_system=True
            )
            db.session.add(drafts_folder)
            db.session.commit()
        
        # Erstelle oder aktualisiere Entwurf
        from config import get_formatted_sender
        sender = get_formatted_sender() or current_user.email

        existing_draft = None
        if draft_id:
            existing_draft = EmailMessage.query.get(draft_id)
            if not (
                existing_draft
                and existing_draft.folder == 'Drafts'
                and existing_draft.sent_by_user_id == current_user.id
            ):
                existing_draft = None

        body_text = html_to_plain_text(body_html) if body_html else ''

        if existing_draft:
            email_record = existing_draft
            email_record.subject = subject or '(Kein Betreff)'
            email_record.sender = sender
            email_record.recipients = to or ''
            email_record.cc = cc
            email_record.bcc = bcc or None
            email_record.body_text = body_text
            email_record.body_html = body_html
            email_record.received_at = datetime.utcnow()
        else:
            email_record = EmailMessage(
                subject=subject or '(Kein Betreff)',
                sender=sender,
                recipients=to or '',
                cc=cc,
                bcc=bcc or None,
                body_text=body_text,
                body_html=body_html,
                folder='Drafts',
                is_sent=False,
                is_read=False,
                sent_by_user_id=current_user.id,
                received_at=datetime.utcnow(),
                has_attachments=False
            )
        
        # Speichere Anhänge, falls vorhanden (nur bei FormData)
        if not request.is_json and 'attachments' in request.files:
            attachments = request.files.getlist('attachments')
            for attachment in attachments:
                if attachment.filename:
                    attachment.seek(0)
                    content = attachment.read()
                    attachment.seek(0)
                    
                    # Prüfe Dateigröße
                    max_db_size = current_app.config.get('MAX_ATTACHMENT_DB_SIZE', 5 * 1024 * 1024)  # 5MB
                    attachment_size = len(content)
                    
                    if attachment_size > max_db_size:
                        # Speichere große Dateien auf der Festplatte
                        import os
                        attachments_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'email_attachments')
                        os.makedirs(attachments_dir, exist_ok=True)
                        
                        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                        safe_filename = "".join(c for c in attachment.filename if c.isalnum() or c in '._- ')
                        file_path = os.path.join(attachments_dir, f"{timestamp}_{safe_filename}")
                        
                        try:
                            with open(file_path, 'wb') as f:
                                f.write(content)
                            
                            email_attachment = EmailAttachment(
                                email=email_record,
                                filename=attachment.filename,
                                content_type=attachment.content_type or 'application/octet-stream',
                                size=attachment_size,
                                content=None,
                                file_path=file_path,
                                is_large_file=True
                            )
                        except Exception as file_error:
                            logging.error(f"Fehler beim Speichern großer Datei: {file_error}")
                            # Fallback: versuche trotzdem in DB zu speichern
                            email_attachment = EmailAttachment(
                                email=email_record,
                                filename=attachment.filename,
                                content_type=attachment.content_type or 'application/octet-stream',
                                size=attachment_size,
                                content=content,
                                file_path=None,
                                is_large_file=False
                            )
                    else:
                        email_attachment = EmailAttachment(
                            email=email_record,
                            filename=attachment.filename,
                            content_type=attachment.content_type or 'application/octet-stream',
                            size=attachment_size,
                            content=content,
                            file_path=None,
                            is_large_file=False
                        )
                    
                    db.session.add(email_attachment)
                    email_record.has_attachments = True
        
        db.session.add(email_record)
        email_record.has_attachments = bool(email_record.attachments)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Entwurf gespeichert',
            'draft_id': email_record.id
        }), 200
        
    except Exception as e:
        logging.error(f"Fehler beim Speichern des Entwurfs: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Fehler beim Speichern des Entwurfs: {str(e)}'
        }), 500


@email_bp.route('/preview/custom', methods=['POST'])
@login_required
@check_module_access('module_email')
def preview_custom_email():
    if not check_email_permission('send'):
        return jsonify({'error': translate('email.errors.unauthorized')}), 403
    
    data = request.get_json(silent=True) or request.form
    if not data:
        return jsonify({'error': translate('email.errors.invalid_data')}), 400
    
    subject = (data.get('subject') or '').strip()
    body_html = (data.get('body') or '').strip()
    reply_to_email_id_raw = str(data.get('reply_to_email_id') or '').strip()
    forward_from_email_id_raw = str(data.get('forward_from_email_id') or '').strip()

    if not body_html:
        return jsonify({'error': translate('email.errors.message_missing')}), 400

    try:
        # Antwort oder Weiterleitung: zitiertes Original in der Vorschau
        quoted_reply_html = None
        if reply_to_email_id_raw:
            try:
                original = EmailMessage.query.get(int(reply_to_email_id_raw))
                if original is not None:
                    quoted_reply_html = build_quoted_reply_html(original)
            except (ValueError, TypeError):
                pass
        elif forward_from_email_id_raw:
            try:
                original_fwd = EmailMessage.query.get(int(forward_from_email_id_raw))
                if original_fwd is not None:
                    quoted_reply_html = build_quoted_forward_html(original_fwd)
            except (ValueError, TypeError):
                pass

        # In der Vorschau Base64 verwenden, damit das Logo im Browser angezeigt wird
        active_mailbox, _ = _resolve_request_mailbox('send')
        use_mailbox_logo = True
        if active_mailbox and active_mailbox.mailbox_type == 'team' and active_mailbox.logo_filename:
            from app.utils.multi_mailboxes import get_mailbox_use_logo
            use_mailbox_logo = get_mailbox_use_logo(current_user, active_mailbox)
            if 'use_mailbox_logo' in data:
                use_mailbox_logo = str(data.get('use_mailbox_logo')).lower() in ('1', 'true', 'on', 'yes')

        rendered_html, _ = render_custom_email(
            subject, body_html, logo_cid=None, is_preview=True,
            quoted_reply_html=quoted_reply_html,
            mailbox=active_mailbox,
            use_mailbox_logo=use_mailbox_logo,
            logo_user=current_user,
        )
        return jsonify({'html': rendered_html})
    except Exception as exc:
        current_app.logger.error(f"E-Mail Vorschau Fehler: {exc}")
        return jsonify({'error': translate('email.errors.preview_failed')}), 500
