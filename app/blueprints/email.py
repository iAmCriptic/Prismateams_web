from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file, Response
from flask_login import login_required, current_user
from uuid import uuid4
from app import db, mail
from app.blueprints.sse import emit_email_sync_status
from app.models.email import EmailMessage, EmailPermission, EmailAttachment, EmailFolder
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
    try_acquire_email_sync_leader,
    heartbeat_email_sync_lock,
)
from app.utils.common import format_datetime

email_bp = Blueprint('email', __name__)
logger = logging.getLogger(__name__)

EMAIL_LIST_PER_PAGE = 50


def get_portal_display_name():
    portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
    if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
        return portal_name_setting.value
    return current_app.config.get('APP_NAME', 'Prismateams')


def html_to_plain_text(html_content: str) -> str:
    if not html_content:
        return ''

    text = re.sub(r'<\s*br\s*/?>', '\n', html_content, flags=re.IGNORECASE)
    text = re.sub(r'</\s*p\s*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return unescape(text).strip()


def build_footer_html(mailbox=None):
    """Footer für ausgehende Mails im E-Mail-Modul (Admin-Template + Absenderzeile)."""
    if mailbox is not None and (mailbox.footer_html or '').strip():
        return mailbox.footer_html.strip()

    from app.utils.email_sender import build_email_footer_html

    html = build_email_footer_html(
        user=current_user,
        app_name=get_portal_display_name(),
        sender_line=True,
    )
    if html:
        return html
    display = (current_user.full_name or '').strip() or (current_user.email or '')
    return f'<p>Gesendet von {display}</p>' if display else ''


def backfill_inline_attachments_from_imap(email_msg) -> bool:
    """
    Lädt Inline-Bilder (cid:) nachträglich aus IMAP und speichert sie als EmailAttachment,
    falls die HTML-Mail cid:-Referenzen enthält, aber keine passenden Inline-Attachments
    in der DB vorliegen (z. B. bei Mails, die vor dem Sync-Fix importiert wurden).

    Returns True, wenn mindestens ein neues Inline-Attachment persistiert wurde.
    """
    try:
        if not email_msg or not email_msg.body_html:
            return False

        html = email_msg.body_html if isinstance(email_msg.body_html, str) else \
            email_msg.body_html.decode('utf-8', errors='replace')

        cid_refs = re.findall(r'src\s*=\s*["\']?cid:([^"\'\s>]+)', html, flags=re.IGNORECASE)
        if not cid_refs:
            return False

        def _norm(v: str) -> str:
            if not v:
                return ""
            v = unescape(unquote(str(v))).strip()
            if v.lower().startswith("cid:"):
                v = v[4:]
            v = v.strip().strip('"').strip("'").strip()
            if v.startswith('<') and v.endswith('>'):
                v = v[1:-1].strip()
            return v.lower()

        needed = {_norm(c) for c in cid_refs if c}
        needed = {k for k in needed if k}
        if not needed:
            return False

        have = set()
        for att in (email_msg.attachments or []):
            if not att.is_inline or not (att.content_type or '').startswith('image/'):
                continue
            for raw in (att.content_id, att.filename):
                key = _norm(raw)
                if key:
                    have.add(key)

        missing = needed - have
        if not missing:
            return False

        if not email_msg.imap_uid or not email_msg.folder:
            return False

        mail_conn = None
        try:
            mail_conn = connect_imap(folder=email_msg.folder)
            if not mail_conn:
                return False

            status, data = mail_conn.uid('fetch', str(email_msg.imap_uid), '(RFC822)')
            if status != 'OK' or not data or not data[0]:
                return False

            raw_bytes = None
            for part in data:
                if isinstance(part, tuple) and len(part) >= 2:
                    raw_bytes = part[1]
                    break
            if not raw_bytes:
                return False

            fetched_msg = email_module.message_from_bytes(raw_bytes)
        finally:
            try:
                if mail_conn:
                    mail_conn.close()
                    mail_conn.logout()
            except Exception:
                pass

        created_any = False
        if fetched_msg.is_multipart():
            for part in fetched_msg.walk():
                content_type = part.get_content_type()
                if not content_type.startswith('image/'):
                    continue
                cid_hdr = (part.get('Content-ID', '') or '').strip().strip('<>')
                filename = part.get_filename() or ''
                keys = {_norm(cid_hdr), _norm(filename)} - {''}
                if not (keys & missing):
                    continue
                try:
                    payload = part.get_payload(decode=True)
                except Exception:
                    payload = None
                if not payload:
                    continue

                if not filename:
                    ext = content_type.split('/')[-1] if '/' in content_type else 'bin'
                    filename = f"inline_{len(email_msg.attachments or [])}.{ext}"
                try:
                    filename = truncate_filename(filename, max_length=500)
                except Exception:
                    filename = filename[:500]

                attachment = EmailAttachment(
                    email_id=email_msg.id,
                    filename=filename,
                    content_type=content_type,
                    size=len(payload),
                    content=payload,
                    file_path=None,
                    is_inline=True,
                    content_id=cid_hdr or None,
                    is_large_file=False,
                )
                db.session.add(attachment)
                created_any = True

        if created_any:
            try:
                if not email_msg.has_attachments:
                    email_msg.has_attachments = True
            except Exception:
                pass
            db.session.commit()
            try:
                db.session.refresh(email_msg)
            except Exception:
                pass
        return created_any
    except Exception as e:
        logging.error(f"backfill_inline_attachments_from_imap failed: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def replace_cid_images_in_email_html(html: str, email_msg) -> str:
    """Replace cid: image sources with data URLs from stored attachments."""
    if not html or not email_msg or not getattr(email_msg, 'attachments', None):
        return html

    placeholder_data_url = (
        "data:image/svg+xml;base64,"
        "PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48"
        "cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIg"
        "Zm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjE0IiBmaWxsPSIjNmM3NTdkIiB0ZXh0LWFuY2hvcj0ibWlk"
        "ZGxlIiBkeT0iLjNlbSI+SW1hZ2U8L3RleHQ+PC9zdmc+"
    )

    def normalize_cid_ref(value: str) -> str:
        if not value:
            return ""
        normalized = unescape(unquote(str(value))).strip()
        if normalized.lower().startswith("cid:"):
            normalized = normalized[4:]
        normalized = normalized.strip().strip('"').strip("'").strip()
        if normalized.startswith("<") and normalized.endswith(">"):
            normalized = normalized[1:-1].strip()
        return normalized.lower()

    cid_map = {}
    for attachment in email_msg.attachments:
        if not attachment.is_inline or not attachment.content_type.startswith('image/'):
            continue
        data_url = attachment.get_data_url()
        if not data_url:
            continue
        for raw_ref in (attachment.content_id, attachment.filename):
            key = normalize_cid_ref(raw_ref)
            if key:
                cid_map[key] = data_url

    def replace_src(match):
        prefix = match.group("prefix")
        quote = match.group("quote") or '"'
        cid_value = match.group("value") or ""
        key = normalize_cid_ref(cid_value)
        resolved = cid_map.get(key)
        src_value = resolved if resolved else placeholder_data_url
        return f"{prefix}{quote}{src_value}{quote}"

    return re.sub(
        r'(?P<prefix>\bsrc\s*=\s*)(?P<quote>["\']?)(?P<value>cid:[^"\'\s>]+)(?P=quote)',
        replace_src,
        html,
        flags=re.IGNORECASE,
    )


def sanitize_email_iframe_html(html: str) -> str:
    """Strip scripts and inline JS handlers before rendering in iframe (XSS mitigation)."""
    if not html:
        return html
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<script\b[^>]*/>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+on\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+href\s*=\s*["\']?\s*javascript:[^"\'>\s]+["\']?', ' href="#"', html, flags=re.IGNORECASE)
    return html


def inject_iframe_head_meta_and_base(html: str) -> str:
    """Ensure charset + base target for links; keep sender <head> intact."""
    meta_charset = '<meta charset="utf-8"/>'
    base_tag = '<base target="_blank" rel="noopener noreferrer"/>'
    has_charset = bool(re.search(r'<meta[^>]+charset', html, re.IGNORECASE))
    has_base = bool(re.search(r'<base\s', html, re.IGNORECASE))
    inject = ''
    if not has_charset:
        inject += meta_charset
    if not has_base:
        inject += base_tag
    if not inject:
        return html
    if re.search(r'<head[^>]*>', html, re.IGNORECASE):
        return re.sub(r'(<head[^>]*>)', r'\1' + inject, html, count=1, flags=re.IGNORECASE)
    if re.search(r'<html[^>]*>', html, re.IGNORECASE):
        return re.sub(
            r'(<html[^>]*>)',
            r'\1<head>' + inject + '</head>',
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    return '<head>' + inject + '</head>' + html


def inject_iframe_portal_viewer_theme(html: str, viewer_dark: bool, viewer_oled: bool) -> str:
    """Append last-in-head CSS: portal sans-serif + body colours matching the app theme.

    Helps plain-text / unstyled regions inside the iframe (no more Times New Roman).
    Sender rules with higher specificity or !important can still win where intended.
    """
    if viewer_oled:
        bg, fg, link, scheme = '#000000', '#e2e8f0', '#60a5fa', 'dark'
    elif viewer_dark:
        bg, fg, link, scheme = '#1a202c', '#e2e8f0', '#60a5fa', 'dark'
    else:
        bg, fg, link, scheme = '#ffffff', '#212529', '#0d6efd', 'light'
    css = (
        '<style type="text/css" id="portal-email-viewer-theme">'
        f'html{{color-scheme:{scheme};}}'
        f'body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif!important;'
        f'background:{bg}!important;color:{fg}!important;padding:16px!important;margin:0!important;}}'
        f'a{{color:{link}!important;}}'
        f'</style>'
    )
    if re.search(r'</head>', html, re.IGNORECASE):
        return re.sub(r'(</head>)', css + r'\1', html, count=1, flags=re.IGNORECASE)
    return css + html


def build_rich_email_iframe_document(
    raw_html: str,
    email_msg,
    viewer_dark: bool = False,
    viewer_oled: bool = False,
) -> str:
    """Build a full HTML document for srcdoc iframe — preserves sender CSS/layout.

    We do not strip/scoped-rewrite the sender's <style> blocks. A small
    last-in-head stylesheet matches the portal theme (sans-serif + body colours)
    so unstyled/plain regions are readable; sender rules can still override.
    """
    if not raw_html:
        return ''
    try:
        html = raw_html if isinstance(raw_html, str) else raw_html.decode('utf-8', errors='replace')

        html = html.replace('\u2011', '-')
        html = html.replace('\u2013', '-')
        html = html.replace('\u2014', '--')
        html = html.replace('\u2018', "'")
        html = html.replace('\u2019', "'")
        html = html.replace('\u201c', '"')
        html = html.replace('\u201d', '"')
        html = html.replace('\u2026', '...')
        html = html.replace('\ufffc', '')
        html = re.sub(r'<o:p\s*/>', '', html)
        html = re.sub(r'<o:p>.*?</o:p>', '', html, flags=re.DOTALL)
        html = re.sub(r'<w:.*?>.*?</w:.*?>', '', html, flags=re.DOTALL)
        html = re.sub(r'<m:.*?>.*?</m:.*?>', '', html, flags=re.DOTALL)
        html = re.sub(r'<v:.*?>.*?</v:.*?>', '', html, flags=re.DOTALL)

        html = replace_cid_images_in_email_html(html, email_msg)
        html = sanitize_email_iframe_html(html)

        if not re.search(r'<html[\s>]', html, re.IGNORECASE):
            # Complete document: charset + base so links open safely; avoids broken <head></head> injection.
            html = (
                '<!DOCTYPE html><html><head>'
                '<meta charset="utf-8"/>'
                '<base target="_blank" rel="noopener noreferrer"/>'
                '</head><body>' + html + '</body></html>'
            )
        else:
            if not re.search(r'<!DOCTYPE', html, re.IGNORECASE):
                html = '<!DOCTYPE html>\n' + html
            html = inject_iframe_head_meta_and_base(html)

        html = inject_iframe_portal_viewer_theme(html, viewer_dark, viewer_oled)

        return html
    except Exception as e:
        logging.error(f"build_rich_email_iframe_document: {e}")
        return ''


def process_email_body_html_for_inline_view(html_content: str, email_msg) -> str:
    """Legacy pipeline: embed HTML in portal viewer with scoped CSS (simple / fallback)."""
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

    html_content = re.sub(
        r'<a([^>]*)href="([^"]*)"([^>]*)>',
        r'<a\1href="\2" target="_blank" rel="noopener noreferrer"\3>',
        html_content,
    )

    body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, flags=re.IGNORECASE | re.DOTALL)
    if body_match:
        body_content = body_match.group(1)
        html_content = re.sub(
            r'<body[^>]*>.*?</body>',
            '<div class="email-body-wrapper">' + body_content + '</div>',
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )
    else:
        if not html_content.strip().startswith('<div'):
            html_content = '<div class="email-body-wrapper">' + html_content + '</div>'

    html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE)

    def scope_style_tags(match):
        style_content = match.group(1) if match.group(1) else ''
        if not style_content.strip():
            return ''

        lines = style_content.split('\n')
        scoped_lines = []
        in_media = False

        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith('@'):
                if '@media' in line_stripped:
                    in_media = True
                    scoped_lines.append(line)
                    continue
                elif line_stripped == '}' and in_media:
                    in_media = False
                    scoped_lines.append(line)
                    continue

            if in_media:
                if '{' in line and not line_stripped.startswith('@'):
                    scoped_line = re.sub(
                        r'([^{}]+)\{',
                        r'.email-content-isolated-inner \1{',
                        line,
                    )
                    scoped_lines.append(scoped_line)
                else:
                    scoped_lines.append(line)
            else:
                if '{' in line:
                    scoped_line = re.sub(
                        r'([^{}]+)\{',
                        r'.email-content-isolated-inner \1{',
                        line,
                    )
                    scoped_lines.append(scoped_line)
                else:
                    scoped_lines.append(line)

        scoped_css = '\n'.join(scoped_lines)
        scoped_css = re.sub(
            r'\.email-content-isolated-inner\s+\.email-content-isolated-inner',
            '.email-content-isolated-inner',
            scoped_css,
        )
        scoped_css = re.sub(
            r'\.email-content-isolated-inner\s+body\s*\{',
            '.email-content-isolated-inner {',
            scoped_css,
            flags=re.IGNORECASE,
        )
        scoped_css = re.sub(
            r'\.email-content-isolated-inner\s+html\s*\{',
            '.email-content-isolated-inner {',
            scoped_css,
            flags=re.IGNORECASE,
        )

        return f'<style type="text/css">{scoped_css}</style>'

    html_content = re.sub(
        r'<style[^>]*>(.*?)</style>',
        scope_style_tags,
        html_content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not html_content.strip().startswith('<'):
        html_content = f'<div class="email-body-wrapper">{html_content}</div>'

    if not html_content.strip().startswith('<div class="email-content-isolated-inner">'):
        html_content = f'<div class="email-content-isolated-inner">{html_content}</div>'

    html_content = replace_cid_images_in_email_html(html_content, email_msg)

    return html_content


def is_simple_html_email(html_content: str) -> bool:
    """Return True if the HTML email does NOT carry its own visual styling.

    "Simple" means: plain paragraphs, basic formatting (bold/italic/lists/links),
    no <style> block, no body/table background colors, no inline background color.
    For such emails we can safely follow the portal's light/dark theme instead of
    forcing a white background (which looks out of place in dark mode).
    """
    if not html_content:
        return True
    try:
        lower = html_content.lower()
        if '<style' in lower:
            return False
        # Any explicit background color on body/table/div indicates custom styling.
        if re.search(r'background(?:-color)?\s*:\s*(?!transparent|inherit|initial|unset|none)', lower):
            return False
        if re.search(r'bgcolor\s*=', lower):
            return False
        # Large tables / layout tables usually indicate newsletter-style HTML.
        if '<table' in lower:
            # allow tiny tables (e.g. signatures) only when they don't set widths
            if re.search(r'<table[^>]*(width|style)=', lower):
                return False
        return True
    except Exception:
        return False


def extract_body_inner_html(html_content: str) -> str:
    """Extract inner body content from an HTML document.

    Returns just the contents inside <body>…</body> (or the input if no body tag)
    and strips outer <html>/<head>/<style> wrappers so the HTML can be embedded.
    """
    if not html_content:
        return ''
    content = html_content
    try:
        # Remove doctype
        content = re.sub(r'<!DOCTYPE[^>]*>', '', content, flags=re.IGNORECASE)
        # Strip head (which contains <style>, <meta>, etc. that would bleed out)
        content = re.sub(r'<head[^>]*>.*?</head>', '', content, flags=re.IGNORECASE | re.DOTALL)
        # Extract body content if present
        body_match = re.search(r'<body[^>]*>(.*?)</body>', content, flags=re.IGNORECASE | re.DOTALL)
        if body_match:
            content = body_match.group(1)
        # Remove any leftover html tags
        content = re.sub(r'</?html[^>]*>', '', content, flags=re.IGNORECASE)
        # Strip remaining <style> blocks – they would leak to the surrounding page
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.IGNORECASE | re.DOTALL)
        # Office / mso leftover
        content = re.sub(r'<o:p\s*/>', '', content)
        content = re.sub(r'<o:p>.*?</o:p>', '', content, flags=re.DOTALL)
    except Exception:
        pass
    return content.strip()


def plain_text_to_html(text: str) -> str:
    """Convert plain text to minimal HTML preserving line breaks and paragraphs."""
    if not text:
        return ''
    from markupsafe import escape as _escape
    paragraphs = re.split(r'\n{2,}', text.strip())
    out = []
    for para in paragraphs:
        if not para.strip():
            continue
        # Preserve intra-paragraph line breaks with <br>
        escaped = _escape(para).replace('\n', '<br>')
        out.append(f'<p style="margin: 0 0 1em 0;">{escaped}</p>')
    return ''.join(out)


def build_quoted_original_html(original_email, quote_kind: str = 'reply') -> str:
    """HTML-Block für Originalnachricht unter unserem formatierten Text (Antwort oder Weiterleitung).

    quote_kind: 'reply' | 'forward'
    """
    if original_email is None:
        return ''

    sender_raw = decode_header_field(original_email.sender) if original_email.sender else ''
    name_part = sender_raw
    email_part = ''
    m = re.match(r'^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$', sender_raw)
    if m:
        name_part = m.group(1).strip() or m.group(2).strip()
        email_part = m.group(2).strip()
    elif '@' in sender_raw:
        email_part = sender_raw.strip()
        name_part = sender_raw.strip()

    sent_dt = original_email.received_at or original_email.sent_at or datetime.utcnow()
    try:
        date_str = format_datetime(sent_dt, '%d.%m.%Y %H:%M')
    except Exception:
        date_str = ''

    body_inner = ''
    if original_email.body_html:
        try:
            raw_html = original_email.body_html
            if isinstance(raw_html, bytes):
                raw_html = raw_html.decode('utf-8', errors='replace')
            body_inner = extract_body_inner_html(str(raw_html))
        except Exception:
            body_inner = ''
    if not body_inner and original_email.body_text:
        body_inner = plain_text_to_html(original_email.body_text)

    if not body_inner:
        body_inner = '<p style="margin:0; color:#64748b; font-style:italic;">(leere Nachricht)</p>'

    from markupsafe import escape as _escape

    if quote_kind == 'forward':
        title = translate('email.compose.quoted.forward_title')
        subj_disp = decode_header_field(original_email.subject or '') or translate('email.compose.quoted.empty_subject')
        to_disp = decode_header_field(original_email.recipients or '') if original_email.recipients else ''
        cc_disp = decode_header_field(original_email.cc or '') if getattr(original_email, 'cc', None) else ''
        sender_line = _escape(name_part)
        if email_part and email_part.lower() != name_part.lower():
            sender_line += f' &lt;{_escape(email_part)}&gt;'
        inner = [
            f'<p style="margin:0 0 6px 0; font-weight:600;">{_escape(title)}</p>',
            f'<p style="margin:0 0 6px 0;"><strong>{_escape(translate("email.compose.quoted.forward_subject_label"))}</strong> '
            f'{_escape(subj_disp)}</p>',
            f'<p style="margin:0 0 6px 0;"><strong>{_escape(translate("email.compose.quoted.forward_date_label"))}</strong> '
            f'{_escape(date_str)}</p>',
            f'<p style="margin:0 0 6px 0;"><strong>{_escape(translate("email.compose.quoted.forward_from_label"))}</strong> '
            f'{sender_line}</p>',
        ]
        if to_disp:
            inner.append(
                f'<p style="margin:0 0 6px 0;"><strong>{_escape(translate("email.compose.quoted.forward_to_label"))}</strong> '
                f'{_escape(to_disp)}</p>'
            )
        if cc_disp:
            inner.append(
                f'<p style="margin:0;"><strong>{_escape(translate("email.compose.quoted.forward_cc_label"))}</strong> '
                f'{_escape(cc_disp)}</p>'
            )
        header_block = (
            '<div style="margin:0 0 12px 0; color:#64748b; font-size:13px; line-height:1.5;">'
            + ''.join(inner)
            + '</div>'
        )
    else:
        header_line = f"Am {_escape(date_str)} schrieb {_escape(name_part)}"
        if email_part and email_part.lower() != name_part.lower():
            header_line += f" &lt;{_escape(email_part)}&gt;"
        header_line += ":"
        header_block = (
            f'<p style="margin:0 0 12px 0; color:#64748b; font-size:13px; line-height:1.5;">{header_line}</p>'
        )

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="border-collapse:collapse; background-color:#f4f6f8; margin:0; padding:0;">'
        '<tr><td align="center" style="padding:0 16px 40px 16px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="max-width:640px; margin:0 auto; border-collapse:collapse;'
        ' font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,\'Helvetica Neue\',Arial,sans-serif;">'
        '<tr><td style="padding:8px 4px 0 4px;">'
        '<hr style="border:0; border-top:1px solid #cbd5e1; margin:0 0 16px 0;">'
        f'{header_block}'
        '<div class="quoted-original-body"'
        ' style="color:#475569; font-size:14px; line-height:1.6; word-break:break-word;'
        ' border-left:3px solid #cbd5e1; padding:4px 0 4px 14px;">'
        f'{body_inner}'
        '</div>'
        '</td></tr></table></td></tr></table>'
    )


def build_quoted_reply_html(original_email) -> str:
    """Zitat-Block für Antworten (Original unter dem Portal-Text)."""
    return build_quoted_original_html(original_email, 'reply')


def build_quoted_forward_html(original_email) -> str:
    """Zitat-Block für Weiterleitungen (gleiche Darstellung wie Antwort, eigener Kopf)."""
    return build_quoted_original_html(original_email, 'forward')


def render_custom_email(subject: str, body_html: str, logo_cid: str = None, is_preview: bool = False,
                        quoted_reply_html: str = None, mailbox=None, use_html_design: bool = True,
                        use_mailbox_logo: bool = True, logo_user=None):
    body_html = body_html or ''
    footer_html = build_footer_html(mailbox=mailbox)
    
    if footer_html:
        combined_html = body_html + '<p style="margin-top: 1em;"></p>' + footer_html
    else:
        combined_html = body_html

    # Plain / ohne Design-Wrapper: formatierter Body + Footer, kein Layout-Template
    if not use_html_design:
        plain_body = html_to_plain_text(combined_html)
        if quoted_reply_html:
            quoted_plain = html_to_plain_text(quoted_reply_html)
            if quoted_plain:
                plain_body = (plain_body + '\n\n--\n' + quoted_plain).strip()
            quoted_block = f'<div class="quoted-reply">{quoted_reply_html}</div>'
            return combined_html + quoted_block, plain_body
        return combined_html, plain_body

    app_name = get_portal_display_name()
    from app.utils.multi_mailboxes import get_mailbox_logo_data
    logo_bytes, _, _ = get_mailbox_logo_data(
        mailbox, user=logo_user, use_logo=use_mailbox_logo
    )
    logo_base64 = None
    if logo_bytes:
        import base64 as _b64
        logo_base64 = _b64.b64encode(logo_bytes).decode('ascii')
    else:
        logo_base64 = get_logo_base64()
    current_year = datetime.utcnow().year

    # In der Vorschau Base64 verwenden (CID funktioniert nicht ohne echte E-Mail)
    # Beim Versenden CID verwenden (funktioniert mit Anhang)
    use_base64_for_preview = is_preview or logo_cid is None

    rendered_html = render_template(
        'emails/custom_mail.html',
        app_name=app_name,
        logo_base64=logo_base64 if use_base64_for_preview else None,
        logo_cid=logo_cid if not use_base64_for_preview else None,
        subject=subject,
        body_html=Markup(combined_html),
        current_year=current_year,
        quoted_reply_html=Markup(quoted_reply_html) if quoted_reply_html else None
    )

    plain_body = html_to_plain_text(combined_html)
    disclaimer_plain = ("Diese E-Mail enthält sensible Inhalte und ist nur für den genannten Empfänger bestimmt. "
                        "Sollten Sie nicht der adressierte Nutzer sein, wenden Sie sich bitte an den Versender und löschen Sie diese E-Mail.")
    copyright_plain = f"© {current_year} {app_name}. Alle Rechte vorbehalten."

    plain_sections = [section for section in [plain_body, disclaimer_plain, copyright_plain] if section]
    # Append plain-text version of the quoted reply (for mail clients that fall back to text)
    if quoted_reply_html:
        quoted_plain = html_to_plain_text(quoted_reply_html)
        if quoted_plain:
            plain_sections.append('--\n' + quoted_plain)
    rendered_plain = '\n\n'.join(plain_sections)

    return rendered_html, rendered_plain


def decode_header_field(field):
    """Decode email header field properly with multiple fallback strategies."""
    if not field:
        return ''
    
    try:
        from email.header import decode_header
        decoded_parts = decode_header(field)
        decoded_string = ''
        
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                if encoding:
                    try:
                        decoded_string += part.decode(encoding, errors='ignore')
                        continue
                    except (UnicodeDecodeError, LookupError):
                        pass
                
                for fallback_encoding in ['utf-8', 'latin-1', 'cp1252', 'ascii']:
                    try:
                        decoded_string += part.decode(fallback_encoding, errors='ignore')
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                else:
                    decoded_string += part.decode('ascii', errors='replace')
            else:
                decoded_string += str(part)
        
        result = decoded_string.strip()
        if not result:
            return str(field) if field else ''
        return result
        
    except Exception as e:
        try:
            return str(field) if field else ''
        except:
            return 'Unknown'


def truncate_filename(filename, max_length=500):
    """
    Kürzt einen Dateinamen auf die maximale Länge, behält dabei die Dateiendung.
    
    Args:
        filename: Der zu kürzende Dateiname
        max_length: Maximale Länge (Standard: 500 Zeichen)
    
    Returns:
        Gekürzter Dateiname
    """
    if not filename or len(filename) <= max_length:
        return filename
    
    # Behalte Dateiendung und kürze den Namen
    if '.' in filename:
        name, ext = filename.rsplit('.', 1)
        max_name_length = max_length - len(ext) - 1  # -1 für den Punkt
        if max_name_length < 1:
            # Falls die Endung zu lang ist, kürze einfach den ganzen Namen
            return filename[:max_length]
        return name[:max_name_length] + '.' + ext
    else:
        return filename[:max_length]


def _is_placeholder_imap_config(imap_server, username, password):
    """Return True if IMAP config still contains example/placeholder values."""
    values = [str(v).strip().lower() for v in (imap_server, username, password) if v]
    if not values:
        return True

    placeholder_markers = (
        'example.com',
        'imap.example.com',
        'smtp.example.com',
        'your-',
        'your_',
        'changeme',
        'change-me',
    )
    return any(any(marker in value for marker in placeholder_markers) for value in values)


def _format_imap_error(exc):
    """IMAP-Fehler lesbar machen (oft bytes in Exception-Args)."""
    parts = []
    for arg in getattr(exc, 'args', ()) or ():
        if isinstance(arg, bytes):
            parts.append(arg.decode('utf-8', errors='replace'))
        elif arg is not None:
            parts.append(str(arg))
    if parts:
        return ' '.join(parts).strip()
    if isinstance(exc, bytes):
        return exc.decode('utf-8', errors='replace')
    return str(exc)


def _imap_error_is_transient(exc):
    """True bei temporären Provider-/Verbindungsfehlern (Retry sinnvoll)."""
    text = _format_imap_error(exc).upper()
    markers = (
        'TOO MANY',
        'CONNECTION',
        'TIMEOUT',
        'TIMED OUT',
        'TEMPORAR',
        'UNAVAILABLE',
        'TRY AGAIN',
        'RATE',
        'LIMIT',
        'BUSY',
        'EOF',
        'BROKEN PIPE',
        'RESET',
        'SSL',
    )
    return any(m in text for m in markers) or isinstance(
        exc, (TimeoutError, OSError, ConnectionError, imaplib.IMAP4.abort)
    )


def _open_imap_connection(timeout=20, mailbox=None):
    """
    Öffnet eine IMAP-Verbindung aus App-Config oder Mailbox-Credentials (ohne Ordner-Select).
    Raises bei Fehler.
    """
    import ssl
    from app.utils.multi_mailboxes import get_mailbox_imap_config

    cfg = get_mailbox_imap_config(mailbox)
    imap_server = cfg.get('server')
    imap_port = int(cfg.get('port') or 993)
    imap_use_ssl = cfg.get('use_ssl', True)
    username = cfg.get('user')
    password = cfg.get('password')
    auth_type = cfg.get('auth_type') or 'password'
    timeout = int(current_app.config.get('MAIL_TIMEOUT', timeout) or timeout)

    if not imap_server or not username:
        raise RuntimeError('IMAP-Konfiguration unvollständig')

    if auth_type != 'oauth' and not password:
        raise RuntimeError('IMAP-Konfiguration unvollständig')

    if auth_type != 'oauth' and _is_placeholder_imap_config(imap_server, username, password):
        raise RuntimeError('IMAP enthält Platzhalterwerte')

    if imap_use_ssl:
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(imap_server, imap_port, ssl_context=ctx, timeout=timeout)
    else:
        conn = imaplib.IMAP4(imap_server, imap_port, timeout=timeout)
        try:
            conn.starttls(ssl_context=ssl.create_default_context())
        except Exception:
            # Server ohne STARTTLS auf Klartext-Port
            pass

    if auth_type == 'oauth' and mailbox is not None:
        from app.utils.mailbox_oauth import get_valid_access_token, imap_authenticate_xoauth2
        token = get_valid_access_token(mailbox)
        imap_authenticate_xoauth2(conn, username, token)
    else:
        conn.login(username, password)
    return conn, imap_server, imap_port


def probe_imap_connection(timeout=20, retries=3, wait_for_sync_seconds=8, mailbox=None):
    """
    Prüft IMAP Login + INBOX (für Einstellungs-Test).

    Versucht kurz, den Sync-Lock zu bekommen (weniger Parallel-Logins),
    retryt bei transienten Provider-Fehlern.

    Returns:
        (ok: bool, message: str, meta: dict)
    """
    last_error = None
    sync_was_busy = False

    def _do_probe():
        conn = None
        try:
            conn, server, port = _open_imap_connection(timeout=timeout, mailbox=mailbox)
            status, _ = conn.select('INBOX', readonly=True)
            if status != 'OK':
                status, _ = conn.select('"INBOX"', readonly=True)
            if status != 'OK':
                status, _ = conn.select('INBOX')
            if status != 'OK':
                return False, f"INBOX konnte nicht geöffnet werden (Status: {status})", {
                    'server': server, 'port': port,
                }
            return True, f"{server}:{port}", {'server': server, 'port': port}
        finally:
            _imap_logout(conn)

    def _run_attempts():
        nonlocal last_error
        attempts = max(1, int(retries))
        for attempt in range(attempts):
            try:
                ok, msg, meta = _do_probe()
                if ok and sync_was_busy:
                    meta = dict(meta or {})
                    meta['sync_was_busy'] = True
                return ok, msg, meta
            except Exception as e:
                last_error = e
                if attempt + 1 < attempts and _imap_error_is_transient(e):
                    time.sleep(1.2 * (attempt + 1))
                    continue
                hint = ''
                if sync_was_busy:
                    hint = ' (Sync parallel — ggf. Verbindungs-Limit des Providers)'
                return False, _format_imap_error(e) + hint, {}
        return False, _format_imap_error(last_error) if last_error else 'IMAP-Test fehlgeschlagen', {}

    # Warte auf freien Sync-Lock, halte ihn während des Probes
    deadline = time.time() + max(0, float(wait_for_sync_seconds))
    while True:
        with acquire_email_sync_lock(timeout=0) as acquired:
            if acquired:
                return _run_attempts()
            sync_was_busy = True

        if time.time() >= deadline:
            # Letzter Versuch ohne exklusiven Lock
            return _run_attempts()
        time.sleep(0.75)


def _imap_logout(mail_conn):
    """Schließt und loggt eine IMAP-Verbindung aus (best effort)."""
    if not mail_conn:
        return
    try:
        mail_conn.close()
    except Exception:
        pass
    try:
        mail_conn.logout()
    except Exception:
        pass


def _send_flask_message_via_smtp(msg, smtp_cfg: dict):
    """Sendet eine Flask-Mail Message über dynamische SMTP-Credentials (Multi-Postfach)."""
    import ssl as ssl_mod

    server = smtp_cfg.get('server')
    port = int(smtp_cfg.get('port') or 587)
    user = smtp_cfg.get('user')
    password = smtp_cfg.get('password')
    use_ssl = bool(smtp_cfg.get('use_ssl', False))
    use_tls = bool(smtp_cfg.get('use_tls', True)) and not use_ssl
    auth_type = smtp_cfg.get('auth_type') or 'password'
    mailbox_obj = smtp_cfg.get('mailbox')
    if not server or not user:
        raise RuntimeError('SMTP-Konfiguration des Postfachs unvollständig')
    if auth_type != 'oauth' and not password:
        raise RuntimeError('SMTP-Konfiguration des Postfachs unvollständig')

    # Flask-Mail baut die MIME-Message lazy über .message
    mime = getattr(msg, 'message', None)
    if mime is None:
        raise RuntimeError('E-Mail-Nachricht konnte nicht aufgebaut werden')

    recipients = list(msg.recipients or [])
    if msg.cc:
        recipients.extend(msg.cc)
    if msg.bcc:
        recipients.extend(msg.bcc)

    timeout = int(current_app.config.get('MAIL_TIMEOUT', 20) or 20)
    context = ssl_mod.create_default_context()

    def _login(smtp):
        if auth_type == 'oauth' and mailbox_obj is not None:
            from app.utils.mailbox_oauth import get_valid_access_token, smtp_authenticate_xoauth2
            token = get_valid_access_token(mailbox_obj)
            smtp_authenticate_xoauth2(smtp, user, token)
        else:
            smtp.login(user, password)

    if use_ssl:
        with smtplib.SMTP_SSL(server, port, timeout=timeout, context=context) as smtp:
            _login(smtp)
            smtp.send_message(mime, from_addr=user, to_addrs=recipients)
    else:
        with smtplib.SMTP(server, port, timeout=timeout) as smtp:
            if use_tls:
                smtp.starttls(context=context)
            _login(smtp)
            smtp.send_message(mime, from_addr=user, to_addrs=recipients)


def connect_imap(folder='INBOX', mailbox=None):
    """Connect to IMAP server with robust error handling.
    
    Args:
        folder: IMAP folder to select (default: 'INBOX')
        mailbox: optional Mailbox model (None = Hauptpostfach aus App-Config)
    
    Returns:
        IMAP connection object or None if connection failed
    """
    try:
        mail_conn, _, _ = _open_imap_connection(timeout=30, mailbox=mailbox)
        
        logging.debug(f"Selecting folder: {folder}")
        status, messages = mail_conn.select(folder)
        if status != 'OK':
            try:
                status, messages = mail_conn.select(f'"{folder}"')
            except Exception:
                pass
            if status != 'OK':
                logging.warning(f"Could not select folder '{folder}', status: {status}")
                mail_conn.select('INBOX')
        
        logging.debug("IMAP connection established successfully")
        return mail_conn
    except imaplib.IMAP4.error as e:
        error_msg = _format_imap_error(e).encode('ascii', errors='replace').decode('ascii')
        logging.error(f"IMAP authentication error: {error_msg}")
        return None
    except Exception as e:
        error_msg = _format_imap_error(e).encode('ascii', errors='replace').decode('ascii')
        logging.error(f"IMAP connection failed: {error_msg}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        return None


def _select_imap_folder(mail_conn, folder_name):
    """Select IMAP folder; returns (ok: bool, messages/error payload)."""
    status, messages = mail_conn.select(folder_name)
    if status != 'OK':
        try:
            status, messages = mail_conn.select(f'"{folder_name}"')
        except Exception:
            pass
    return status == 'OK', messages


def is_sent_folder(folder_name):
    """
    Prüft, ob ein Ordner-Name ein Gesendet-Ordner ist.
    Unterstützt verschiedene IMAP-Server und deren Ordner-Namen.
    
    Args:
        folder_name: Der Name des IMAP-Ordners
        
    Returns:
        True wenn es sich um einen Gesendet-Ordner handelt, sonst False
    """
    if not folder_name:
        return False
    
    folder_name = folder_name.strip()
    
    # Liste aller möglichen Gesendet-Ordner-Namen verschiedener IMAP-Server
    sent_folder_names = [
        'Sent',                    # Standard
        'Sent Messages',           # Infomaniak, einige andere
        'Gesendet',                # Deutsche Variante
        'Gesendete Nachrichten',   # Infomaniak (deutsch)
        'Sent Items',              # Microsoft Outlook/Exchange
        'INBOX.Sent',              # Einige IMAP-Server (z.B. Dovecot)
        'INBOX/Sent',              # Alternative Struktur
        'INBOX\\Sent',             # Windows-Pfad-Struktur (selten)
        '[Gmail]/Sent Mail',
        '[Google Mail]/Sent Mail',
        '[Gmail]/Gesendet',
        '[Google Mail]/Gesendet',
    ]
    
    if folder_name in sent_folder_names:
        return True
    leaf = folder_name.replace('\\', '/').rsplit('/', 1)[-1].strip().lower()
    return leaf in ('sent', 'sent mail', 'sent messages', 'sent items', 'gesendet', 'gesendete nachrichten')


# Gmail-Namespace-Root (nicht auswählbar) – Kinder wie [Gmail]/Trash müssen bleiben
_GMAIL_NAMESPACE_ROOTS = frozenset({
    '[Gmail]',
    '[Google Mail]',
    '&XfJT0ZAB-',  # historisch / lokalisierte Roots
    '&XfJSI-',
})

_GMAIL_LEAF_ROLES = {
    'trash': 'Trash',
    'bin': 'Trash',
    'papierkorb': 'Trash',
    'drafts': 'Drafts',
    'entwürfe': 'Drafts',
    'entwuerfe': 'Drafts',
    'spam': 'Spam',
    'junk': 'Spam',
    'sent': 'Sent',
    'sent mail': 'Sent',
    'gesendet': 'Sent',
    'archive': 'Archive',
    'archiv': 'Archive',
    'all mail': 'All Mail',
    'alle nachrichten': 'All Mail',
    'starred': 'Starred',
    'markiert': 'Starred',
    'important': 'Important',
    'wichtig': 'Important',
}


def decode_imap_modutf7(value: str) -> str:
    """IMAP Modified UTF-7 (z. B. Entw&APw-rfe → Entwürfe) dekodieren."""
    if not value or '&' not in value:
        return value or ''
    import base64
    import re

    def _repl(match):
        body = match.group(1)
        if body == '':
            return '&'
        raw = body.replace(',', '/')
        pad = '=' * (-len(raw) % 4)
        try:
            return base64.b64decode(raw + pad).decode('utf-16-be')
        except Exception:
            return match.group(0)

    try:
        return re.sub(r'&([^-]*)-', _repl, value)
    except Exception:
        return value


def _imap_folder_leaf(folder_name: str) -> str:
    leaf = (folder_name or '').replace('\\', '/').rsplit('/', 1)[-1].strip()
    return decode_imap_modutf7(leaf)


def gmail_folder_role(folder_name: str):
    """Mappt Gmail/Google-Mail-Sonderordner auf Rollen (Trash, Sent, …) oder None."""
    if not folder_name:
        return None
    name = folder_name.strip()
    if name in _GMAIL_NAMESPACE_ROOTS:
        return None
    lower = name.lower()
    if not (
        lower.startswith('[gmail]/')
        or lower.startswith('[google mail]/')
        or name.startswith('&')
    ):
        return None
    leaf = _imap_folder_leaf(name).lower()
    # Umlaute normalisieren
    leaf_ascii = (
        leaf.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    )
    return _GMAIL_LEAF_ROLES.get(leaf) or _GMAIL_LEAF_ROLES.get(leaf_ascii)


def is_standard_mail_folder(folder_name: str) -> bool:
    """Ob Ordner als Standardordner (nicht Custom) behandelt wird."""
    if not folder_name:
        return False
    name = folder_name.strip()
    if name == 'INBOX' or is_sent_folder(name):
        return True
    if name in (
        'Drafts', 'Trash', 'Deleted Messages', 'Spam', 'Junk',
        'Archive', 'Archives', 'All Mail', 'Starred', 'Important',
    ):
        return True
    return gmail_folder_role(name) is not None


def is_gmail_namespace_root(folder_name: str) -> bool:
    return (folder_name or '').strip() in _GMAIL_NAMESPACE_ROOTS


def find_sent_folder(mail_conn):
    """Find the Sent folder name on IMAP server (auto-detect)."""
    try:
        status, folders = mail_conn.list()
        if status != 'OK':
            return None
        
        for folder_info in folders:
            try:
                folder_name, _ = _parse_imap_list_line(folder_info)
                if folder_name and is_sent_folder(folder_name):
                    return folder_name
            except Exception:
                continue
        
        # Fallback: Versuche 'Sent' direkt
        try:
            status, _ = mail_conn.select('Sent')
            if status == 'OK':
                return 'Sent'
        except:
            pass
        
        return None
    except Exception as e:
        logging.error(f"Error finding Sent folder: {e}")
        return None


def save_email_to_imap_sent(msg):
    """Save sent email to IMAP Sent folder.
    
    Returns:
        tuple: (success: bool, folder_name: str|None) - Erfolg und Name des Gesendet-Ordners
    """
    try:
        imap_server = current_app.config.get('IMAP_SERVER')
        imap_port = current_app.config.get('IMAP_PORT', 993)
        imap_use_ssl = current_app.config.get('IMAP_USE_SSL', True)
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([imap_server, username, password]):
            logging.warning("IMAP configuration missing, cannot save to Sent folder")
            return False, None
        
        # Verbindung herstellen
        try:
            if imap_use_ssl:
                mail_conn = imaplib.IMAP4_SSL(imap_server, imap_port, timeout=30)
            else:
                mail_conn = imaplib.IMAP4(imap_server, imap_port, timeout=30)
            
            mail_conn.login(username, password)
        except Exception as conn_error:
            logging.error(f"Fehler beim Verbinden mit IMAP zum Speichern der gesendeten E-Mail: {conn_error}")
            return False, None
        
        # Sent-Ordner finden
        sent_folder = find_sent_folder(mail_conn)
        if not sent_folder:
            logging.warning("Sent folder not found on IMAP server, cannot save email")
            try:
                mail_conn.close()
            except:
                pass
            try:
                mail_conn.logout()
            except:
                pass
            return False, None
        
        # E-Mail als RFC822-String konvertieren
        email_string = msg.as_string()
        email_bytes = email_string.encode('utf-8')
        
        # E-Mail im Sent-Ordner speichern
        try:
            mail_conn.select(sent_folder)
            result = mail_conn.append(sent_folder, None, None, email_bytes)
            
            if result[0] == 'OK':
                logging.info(f"Email saved to IMAP Sent folder '{sent_folder}'")
                try:
                    mail_conn.close()
                except:
                    pass
                try:
                    mail_conn.logout()
                except:
                    pass
                return True, sent_folder
            else:
                logging.warning(f"Failed to save email to IMAP Sent folder: {result}")
                try:
                    mail_conn.close()
                except:
                    pass
                try:
                    mail_conn.logout()
                except:
                    pass
                return False, sent_folder
        except Exception as e:
            logging.error(f"Error saving email to IMAP Sent folder: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            try:
                mail_conn.close()
            except:
                pass
            try:
                mail_conn.logout()
            except:
                pass
            return False, sent_folder
            
    except Exception as e:
        logging.error(f"Error connecting to IMAP to save sent email: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        return False, None


def _parse_imap_list_line(folder_info):
    """
    Parse IMAP LIST response line.
    Supports both:
      (\\HasNoChildren) "/" INBOX
      (\\HasNoChildren) "/" "Sent Messages"
    Returns (folder_name, separator) or (None, '/') if unusable.
    """
    import re
    if isinstance(folder_info, bytes):
        folder_str = folder_info.decode('utf-8', errors='ignore')
    else:
        folder_str = str(folder_info)

    match = re.match(
        r'''^\s*\(.*\)\s+("(?P<sep1>[^"]*)"|(?P<sep2>\S+))\s+("(?P<name1>.*)"|(?P<name2>\S+))\s*$''',
        folder_str,
    )
    if not match:
        parts = folder_str.split('"')
        if len(parts) >= 3:
            sep = (parts[1] or '/').strip() or '/'
            name = (parts[-2] or '').strip()
            if name and name not in ('/', '.'):
                return name, sep
        return None, '/'

    sep = match.group('sep1') if match.group('sep1') is not None else (match.group('sep2') or '/')
    sep = (sep or '/').strip() or '/'
    name = match.group('name1') if match.group('name1') is not None else match.group('name2')
    name = (name or '').strip()
    if not name or name in ('/', '.'):
        return None, sep
    return name, sep


def sync_imap_folders(mailbox=None):
    """Sync IMAP folders from server to database."""
    mailbox_id = mailbox.id if mailbox is not None else None
    mail_conn = None
    try:
        mail_conn = connect_imap('INBOX', mailbox=mailbox)
        if not mail_conn:
            logging.error("IMAP-Verbindung fehlgeschlagen beim Synchronisieren der Ordner")
            return False, "IMAP-Verbindung fehlgeschlagen"
    except Exception as conn_error:
        logging.error(f"Fehler beim Verbinden mit IMAP für Ordner-Sync: {conn_error}")
        return False, f"IMAP-Verbindungsfehler: {str(conn_error)}"
    
    try:
        list_rows = []
        status, folders = mail_conn.list()
        if status == 'OK' and folders:
            list_rows.extend(folders)
        else:
            logging.warning("IMAP LIST (root) fehlgeschlagen oder leer: %s", status)

        # Gmail: Sonderordner liegen unter [Gmail] / [Google Mail] – explizit nachlisten
        for ns in ('[Gmail]', '[Google Mail]'):
            try:
                st, more = mail_conn.list(f'"{ns}"', '*')
                if st == 'OK' and more:
                    list_rows.extend(more)
                    logging.info("IMAP LIST unter %s: %s Einträge", ns, len(more))
            except Exception as ns_err:
                logging.debug("IMAP LIST %s übersprungen: %s", ns, ns_err)

        if not list_rows:
            return False, "Ordner-Liste konnte nicht abgerufen werden"

        # Deduplizieren nach Rohzeile
        seen_raw = set()
        unique_rows = []
        for row in list_rows:
            key = row if isinstance(row, (bytes, str)) else repr(row)
            if key in seen_raw:
                continue
            seen_raw.add(key)
            unique_rows.append(row)
        
        synced_folders = []
        skipped_folders = []
        
        logging.info(f"Processing {len(unique_rows)} folders from IMAP server (mailbox_id={mailbox_id})")
        skip_gmail_on_main = False
        if mailbox_id is None:
            try:
                from app.utils.multi_mailboxes import is_email_multi_enabled
                skip_gmail_on_main = bool(is_email_multi_enabled())
            except Exception:
                skip_gmail_on_main = False
        
        for folder_info in unique_rows:
            try:
                folder_name, separator = _parse_imap_list_line(folder_info)
                folder_str = folder_info.decode('utf-8', errors='ignore') if isinstance(folder_info, bytes) else str(folder_info)
                if not folder_name:
                    skipped_folders.append(folder_str)
                    logging.debug(f"Skipping unparsable/invalid folder line: '{folder_str}'")
                    continue

                logging.info(f"Found folder: '{folder_name}'")

                # Nur den Gmail-Root überspringen, nicht [Gmail]/Trash usw.
                if is_gmail_namespace_root(folder_name):
                    logging.debug(f"Skipping Gmail namespace root: '{folder_name}'")
                    continue

                # Bei Multi-Postfach: Gmail-/Google-Mail-Namespaces nicht ins Hauptpostfach
                if skip_gmail_on_main and _is_provider_namespace_folder(folder_name):
                    logging.debug(
                        "Skipping provider namespace folder on Hauptpostfach: %s",
                        folder_name,
                    )
                    continue
                
                is_system = is_standard_mail_folder(folder_name)
                display_name = EmailFolder.get_folder_display_name(folder_name)

                parent_folder = None
                if separator in folder_name:
                    parent_candidate = folder_name.rsplit(separator, 1)[0]
                    # Gmail-Root nicht als Parent speichern (sonst hängen Kinder an fehlendem Knoten)
                    if parent_candidate and parent_candidate != folder_name and not is_gmail_namespace_root(parent_candidate):
                        parent_folder = parent_candidate
                    else:
                        parent_folder = None

                now = datetime.utcnow()
                folder_type = 'standard' if is_system else 'custom'
                folder_payload = {
                    'name': folder_name,
                    'display_name': display_name,
                    'folder_type': folder_type,
                    'is_system': is_system,
                    'parent_folder': parent_folder,
                    'separator': separator,
                    'last_synced': now,
                    'created_at': now,
                    'mailbox_id': mailbox_id,
                }

                try:
                    existing_folder = _find_email_folder(folder_name, mailbox_id)
                    if existing_folder:
                        existing_folder.display_name = display_name
                        existing_folder.folder_type = folder_type
                        existing_folder.is_system = is_system
                        existing_folder.parent_folder = parent_folder
                        existing_folder.separator = separator
                        existing_folder.last_synced = now
                        logging.debug(f"Updated existing folder: '{folder_name}'")
                    else:
                        db.session.add(EmailFolder(**folder_payload))
                        logging.info(f"Added new folder: '{folder_name}' ({display_name})")
                    synced_folders.append(folder_name)
                except IntegrityError:
                    db.session.rollback()
                    existing_folder = _find_email_folder(folder_name, mailbox_id)
                    if existing_folder:
                        existing_folder.last_synced = datetime.utcnow()
                        synced_folders.append(folder_name)
                        logging.debug(f"Recovered folder after IntegrityError: '{folder_name}'")
                    else:
                        logging.warning(f"IntegrityError without existing folder for '{folder_name}' – retrying insert")
                        try:
                            db.session.add(EmailFolder(
                                name=folder_name,
                                display_name=display_name,
                                folder_type=folder_type,
                                is_system=is_system,
                                parent_folder=parent_folder,
                                separator=separator,
                                last_synced=datetime.utcnow(),
                                mailbox_id=mailbox_id,
                            ))
                            db.session.flush()
                            synced_folders.append(folder_name)
                            logging.info(f"Inserted folder after retry: '{folder_name}'")
                        except IntegrityError as retry_error:
                            db.session.rollback()
                            logging.error(f"Failed to insert folder '{folder_name}' after retry: {retry_error}")
                            continue
                        
            except Exception as e:
                logging.error(f"Fehler beim Verarbeiten des Ordners '{folder_str if 'folder_str' in locals() else folder_info}': {e}")
                continue
        
        logging.info(f"Synced {len(synced_folders)} folders, skipped {len(skipped_folders)} invalid folders")
        
        invalid_folder_names = ['/', '']
        for invalid_name in invalid_folder_names:
            invalid_folders = (
                EmailFolder.query.filter_by(name=invalid_name)
                .filter(_folder_mailbox_filter(mailbox_id))
                .all()
            )
            for invalid_folder in invalid_folders:
                logging.info(f"Removing invalid folder '{invalid_name}' from database")
                db.session.delete(invalid_folder)
        
        db.session.commit()
        if mailbox_id is None:
            _cleanup_main_mailbox_folder_pollution()
        
        # Schließe IMAP-Verbindung sicher
        if mail_conn:
            try:
                mail_conn.close()
            except Exception as close_error:
                logging.debug(f"Fehler beim Schließen der IMAP-Verbindung: {close_error}")
            try:
                mail_conn.logout()
            except Exception as logout_error:
                logging.debug(f"Fehler beim Logout von IMAP: {logout_error}")
        
        return True, f"{len(synced_folders)} Ordner synchronisiert"
        
    except Exception as e:
        logging.error(f"Folder sync failed: {str(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        
        # Stelle sicher, dass IMAP-Verbindung geschlossen wird
        if mail_conn:
            try:
                mail_conn.close()
            except:
                pass
            try:
                mail_conn.logout()
            except:
                pass
        
        return False, f"Ordner-Sync-Fehler: {str(e)}"


def sync_emails_from_folder(folder_name, mail_conn=None, mailbox=None):
    """Sync emails from a specific IMAP folder with bidirectional support.

    Args:
        folder_name: IMAP-Ordnername
        mail_conn: Optionale bestehende IMAP-Verbindung (wird nicht geschlossen).
                   Wenn None, wird eine neue Verbindung geöffnet und am Ende geschlossen.
        mailbox: Optional Mailbox model (None = Hauptpostfach)
    """
    mailbox_id = mailbox.id if mailbox is not None else None
    owns_connection = mail_conn is None
    try:
        if owns_connection:
            mail_conn = connect_imap(folder_name, mailbox=mailbox)
            if not mail_conn:
                logging.error(f"IMAP-Verbindung fehlgeschlagen für Ordner '{folder_name}'")
                return False, f"IMAP-Verbindung fehlgeschlagen für Ordner '{folder_name}'"
        else:
            ok, messages = _select_imap_folder(mail_conn, folder_name)
            if not ok:
                error_msg = ''
                try:
                    if messages and len(messages) > 0:
                        if isinstance(messages[0], bytes):
                            error_msg = messages[0].decode('utf-8', errors='ignore')
                        else:
                            error_msg = str(messages[0])
                except Exception:
                    error_msg = 'Unbekannter Fehler'
                is_archive_folder = folder_name in ['Archive', 'Archives']
                if "doesn't exist" in error_msg or "Mailbox doesn't exist" in error_msg or "NONEXISTENT" in error_msg:
                    if is_archive_folder:
                        logging.debug(
                            "IMAP folder '%s' does not exist on server, skipping sync: %s",
                            folder_name, error_msg,
                        )
                    else:
                        logging.info(
                            "IMAP folder '%s' does not exist on server, skipping sync: %s",
                            folder_name, error_msg,
                        )
                    return True, f"Ordner '{folder_name}' existiert nicht auf dem Server, übersprungen"
                logging.warning("IMAP folder selection failed for '%s': %s", folder_name, error_msg)
                return True, f"Ordner '{folder_name}' konnte nicht geöffnet werden, übersprungen: {error_msg}"
    except Exception as conn_error:
        logging.error(f"Fehler beim Verbinden mit IMAP für Ordner '{folder_name}': {conn_error}")
        if owns_connection:
            _imap_logout(mail_conn)
        return False, f"IMAP-Verbindungsfehler: {str(conn_error)}"
    
    stats = {
        'new_emails': 0,
        'updated_emails': 0,
        'moved_emails': 0,
        'deleted_emails': 0,
        'skipped_emails': 0,
        'errors': 0
    }
    
    try:
        # Haupt-Synchronisations-Logik
        # Versuche Ordner zu öffnen (bei owns_connection bereits selected; nochmals absichern)
        status, messages = mail_conn.select(folder_name)
        if status != 'OK':
            # Versuche mit Anführungszeichen (für Ordner mit Leerzeichen)
            try:
                status, messages = mail_conn.select(f'"{folder_name}"')
            except Exception as quote_error:
                logging.debug(f"Could not select folder '{folder_name}' with quotes: {quote_error}")
            
            if status != 'OK':
                # Ordner existiert nicht auf dem Server - überspringen, aber in DB behalten
                error_msg = ''
                try:
                    if messages and len(messages) > 0:
                        if isinstance(messages[0], bytes):
                            error_msg = messages[0].decode('utf-8', errors='ignore')
                        else:
                            error_msg = str(messages[0])
                except Exception:
                    error_msg = 'Unbekannter Fehler'
                
                # Prüfe ob es sich um einen Archiv-Ordner handelt (Archive oder Archives)
                is_archive_folder = folder_name in ['Archive', 'Archives']
                if "doesn't exist" in error_msg or "Mailbox doesn't exist" in error_msg or "NONEXISTENT" in error_msg:
                    if is_archive_folder:
                        logging.debug(f"IMAP folder '{folder_name}' does not exist on server, skipping sync (normal for empty archive folders): {error_msg}")
                    else:
                        logging.info(f"IMAP folder '{folder_name}' does not exist on server, skipping sync: {error_msg}")
                    if owns_connection:
                        _imap_logout(mail_conn)
                    return True, f"Ordner '{folder_name}' existiert nicht auf dem Server, übersprungen"
                else:
                    logging.warning(f"IMAP folder selection failed for '{folder_name}': {error_msg}")
                    if owns_connection:
                        _imap_logout(mail_conn)
                    return True, f"Ordner '{folder_name}' konnte nicht geöffnet werden, übersprungen: {error_msg}"
    except Exception as e:
        logging.error(f"Exception while selecting folder '{folder_name}': {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        if owns_connection:
            _imap_logout(mail_conn)
        return True, f"Ordner '{folder_name}' konnte nicht geöffnet werden, übersprungen: {str(e)}"
    
    # Haupt-Synchronisations-Logik
    try:
        # Ermittle die höchste bereits synchronisierte UID für diesen Ordner + Postfach
        highest_uid = None
        try:
            highest_uid_result = db.session.query(
                func.max(cast(EmailMessage.imap_uid, Integer))
            ).filter_by(folder=folder_name, mailbox_id=mailbox_id).scalar()
            if highest_uid_result:
                highest_uid = int(highest_uid_result)
                logging.debug(f"Highest UID for folder '{folder_name}' mailbox={mailbox_id}: {highest_uid}")
        except Exception as e:
            logging.debug(f"Could not determine highest UID for folder '{folder_name}': {e}")
        
        # Initialisiere Variablen
        all_seq_numbers = []
        seq_to_uid = {}
        
        # Verwende search() für Sequenznummern (zuverlässiger als uid_search)
        status, messages = mail_conn.search(None, 'ALL')
        if status != 'OK':
            logging.error(f"IMAP search failed for folder '{folder_name}': {messages}")
            if owns_connection:
                _imap_logout(mail_conn)
            return False, f"E-Mail-Suche in Ordner '{folder_name}' fehlgeschlagen: {messages[0].decode() if messages else 'Unbekannter Fehler'}"
        
        all_seq_numbers = messages[0].split() if messages[0] else []
        logging.info(f"Found {len(all_seq_numbers)} total emails in folder '{folder_name}'")
        
        if len(all_seq_numbers) == 0:
            logging.info(f"No emails found in folder '{folder_name}' on server")
            if owns_connection:
                _imap_logout(mail_conn)
            return True, f"Ordner '{folder_name}': Keine E-Mails vorhanden"
        
        # Hole UIDs für alle E-Mails
        # Verwende FETCH mit UID für alle Sequenznummern auf einmal
        if len(all_seq_numbers) > 0:
            try:
                first_seq = all_seq_numbers[0].decode() if isinstance(all_seq_numbers[0], bytes) else str(all_seq_numbers[0])
                last_seq = all_seq_numbers[-1].decode() if isinstance(all_seq_numbers[-1], bytes) else str(all_seq_numbers[-1])
                seq_range = f"{first_seq}:{last_seq}" if len(all_seq_numbers) > 1 else first_seq
                status, uid_data = mail_conn.fetch(seq_range, '(UID)')
                
                # Erstelle Mapping von Sequenznummer zu UID
                if status == 'OK' and uid_data:
                    import re
                    for item in uid_data:
                        uid_info = None
                        # Handle both tuple and bytes formats
                        if isinstance(item, tuple) and len(item) > 0:
                            # Format: (b'1 (UID 123)', b'...')
                            uid_info = item[0].decode('utf-8', errors='ignore') if isinstance(item[0], bytes) else str(item[0])
                        elif isinstance(item, bytes):
                            # Format: b'1 (UID 123)' - direct bytes object
                            uid_info = item.decode('utf-8', errors='ignore')
                        elif isinstance(item, str):
                            # Format: '1 (UID 123)' - direct string
                            uid_info = item
                        
                        if uid_info:
                            # Parse: "1 (UID 123)" -> seq=1, uid=123
                            match = re.search(r'(\d+)\s+\(UID\s+(\d+)\)', uid_info)
                            if match:
                                seq_num = match.group(1)
                                uid_num = match.group(2)
                                seq_to_uid[seq_num] = uid_num
                
                # Falls Batch-Abfrage nicht alle UIDs zurückgegeben hat, hole sie einzeln
                if len(seq_to_uid) < len(all_seq_numbers):
                    logging.debug(f"Batch UID fetch returned {len(seq_to_uid)} UIDs, but {len(all_seq_numbers)} emails exist. Fetching remaining UIDs individually...")
                    for seq_bytes in all_seq_numbers:
                        seq_str = seq_bytes.decode() if isinstance(seq_bytes, bytes) else str(seq_bytes)
                        if seq_str not in seq_to_uid:
                            try:
                                status_single, uid_data_single = mail_conn.fetch(seq_str, '(UID)')
                                if status_single == 'OK' and uid_data_single:
                                    import re
                                    for item in uid_data_single:
                                        uid_info = None
                                        # Handle both tuple and bytes formats
                                        if isinstance(item, tuple) and len(item) > 0:
                                            uid_info = item[0].decode('utf-8', errors='ignore') if isinstance(item[0], bytes) else str(item[0])
                                        elif isinstance(item, bytes):
                                            uid_info = item.decode('utf-8', errors='ignore')
                                        elif isinstance(item, str):
                                            uid_info = item
                                        
                                        if uid_info:
                                            match = re.search(r'\(UID\s+(\d+)\)', uid_info)
                                            if match:
                                                seq_to_uid[seq_str] = match.group(1)
                                                break
                            except Exception as single_fetch_error:
                                logging.debug(f"Failed to fetch UID for sequence {seq_str}: {single_fetch_error}")
                                # Fallback: Verwende Sequenznummer als UID
                                seq_to_uid[seq_str] = seq_str
                
                logging.debug(f"Created UID mapping for {len(seq_to_uid)} emails in folder '{folder_name}'")
            except Exception as uid_fetch_error:
                logging.warning(f"Failed to fetch UIDs for folder '{folder_name}': {uid_fetch_error}")
                # Falls UID-Abfrage komplett fehlschlägt, verwende Sequenznummern als Fallback
                for seq_bytes in all_seq_numbers:
                    seq_str = seq_bytes.decode() if isinstance(seq_bytes, bytes) else str(seq_bytes)
                    seq_to_uid[seq_str] = seq_str
                logging.debug(f"Using sequence numbers as UID fallback for {len(seq_to_uid)} emails")
        
        # Filtere nach neuen E-Mails (UID > highest_uid)
        logging.info(f"Filtering emails for folder '{folder_name}': highest_uid={highest_uid}, seq_to_uid mapping has {len(seq_to_uid)} entries")
        
        if highest_uid:
            email_seqs = []
            emails_without_uid = []
            
            for seq_bytes in all_seq_numbers:
                seq_str = seq_bytes.decode() if isinstance(seq_bytes, bytes) else str(seq_bytes)
                uid_str = seq_to_uid.get(seq_str)
                if uid_str:
                    try:
                        email_uid = int(uid_str)
                        if email_uid > highest_uid:
                            email_seqs.append(seq_bytes)
                    except (ValueError, AttributeError):
                        # Falls UID nicht als Integer geparst werden kann, prüfe ob E-Mail existiert
                        emails_without_uid.append(seq_bytes)
                else:
                    # Falls keine UID im Mapping, prüfe ob E-Mail bereits in DB existiert
                    emails_without_uid.append(seq_bytes)
            
            # Für E-Mails ohne UID: Prüfe ob sie bereits in DB existieren
            if emails_without_uid:
                logging.info(f"Checking {len(emails_without_uid)} emails without UID mapping in folder '{folder_name}'")
                for seq_bytes in emails_without_uid:
                    seq_str = seq_bytes.decode() if isinstance(seq_bytes, bytes) else str(seq_bytes)
                    try:
                        status_test, msg_data_test = mail_conn.fetch(seq_str, '(RFC822)')
                        if status_test == 'OK' and msg_data_test:
                            raw_email_test = msg_data_test[0][1]
                            email_msg_test = email_module.message_from_bytes(raw_email_test)
                            message_id_test = email_msg_test.get('Message-ID', '')
                            if message_id_test:
                                existing = EmailMessage.query.filter_by(
                                    message_id=message_id_test,
                                    mailbox_id=mailbox_id,
                                ).first()
                                if not existing:
                                    email_seqs.append(seq_bytes)
                                    logging.info(f"Email with sequence {seq_str} (Message-ID: {message_id_test[:50]}) not in database, adding to sync list")
                            else:
                                # Keine Message-ID - füge zur Sicherheit hinzu
                                email_seqs.append(seq_bytes)
                                logging.info(f"Email with sequence {seq_str} has no Message-ID, adding to sync list")
                    except Exception as e:
                        logging.debug(f"Error checking email with sequence {seq_str}: {e}")
                        # Bei Fehler, füge zur Sicherheit hinzu (besser zu viel als zu wenig)
                        email_seqs.append(seq_bytes)
            
            logging.info(f"Found {len(email_seqs)} new emails in folder '{folder_name}' with UID > {highest_uid} (or without UID mapping)")
            email_ids = email_seqs
        else:
            # Erste Synchronisation: Verwende alle Sequenznummern
            email_ids = all_seq_numbers
            logging.info(f"First sync for folder '{folder_name}', processing all {len(email_ids)} emails")
        
        # Für die Prüfung gelöschter E-Mails: Hole alle UIDs vom Server (nur wenn nicht erste Sync)
        # WICHTIG: Nur prüfen, wenn seq_to_uid vollständig ist (alle E-Mails haben UIDs)
        if highest_uid and len(seq_to_uid) > 0 and len(seq_to_uid) == len(all_seq_numbers):
            # Nur wenn wir schon E-Mails haben UND das UID-Mapping vollständig ist, prüfen wir auf gelöschte
            current_imap_uids = set(seq_to_uid.values())
            
            # Optimierte Prüfung: Nur UIDs abfragen statt alle E-Mails
            existing_uids = db.session.query(EmailMessage.imap_uid).filter_by(
                folder=folder_name,
                mailbox_id=mailbox_id,
            ).filter(EmailMessage.imap_uid.isnot(None)).all()
            existing_uid_set = {str(uid[0]) for uid in existing_uids if uid[0]}
            
            for existing_uid in existing_uid_set:
                if existing_uid not in current_imap_uids:
                    # E-Mail existiert nicht mehr auf Server
                    email_obj = EmailMessage.query.filter_by(
                        imap_uid=existing_uid,
                        folder=folder_name,
                        mailbox_id=mailbox_id,
                    ).first()
                    if email_obj:
                        # Prüfe ob E-Mail in einen anderen Ordner verschoben wurde
                        other_folder_email = EmailMessage.query.filter_by(
                            message_id=email_obj.message_id,
                            mailbox_id=mailbox_id,
                        ).filter(EmailMessage.folder != folder_name).first()
                        
                        if other_folder_email:
                            # E-Mail wurde in einen anderen Ordner verschoben
                            db.session.delete(email_obj)
                            stats['moved_emails'] += 1
                        else:
                            # E-Mail wurde auf Server gelöscht - markiere als gelöscht (aber lösche NICHT aus DB)
                            # Nur markieren, nicht löschen, damit Benutzer sie noch sehen können
                            email_obj.is_deleted_imap = True
                            email_obj.last_imap_sync = datetime.utcnow()
                            stats['deleted_emails'] += 1
        else:
            # UID-Mapping ist nicht vollständig - keine Prüfung auf gelöschte E-Mails
            # (verhindert, dass E-Mails fälschlicherweise gelöscht werden)
            if highest_uid:
                logging.debug(f"Skipping deleted email check for folder '{folder_name}' - UID mapping incomplete ({len(seq_to_uid)}/{len(all_seq_numbers)})")

        if len(email_ids) == 0:
            logging.info(f"No new emails to sync in folder '{folder_name}' (all {len(all_seq_numbers)} emails already in database or filtered out)")
            emails_to_process = []
        else:
            # Bei erster Synchronisation: Nur die letzten N E-Mails verarbeiten
            if not highest_uid:
                is_special_folder = is_standard_mail_folder(folder_name)
                max_emails = 100 if not is_special_folder else 30
                emails_to_process = email_ids[-max_emails:] if len(email_ids) > max_emails else email_ids
                logging.debug(f"First sync: Processing {len(emails_to_process)} emails from folder '{folder_name}' (max: {max_emails})")
            else:
                emails_to_process = email_ids
                logging.debug(f"Processing {len(emails_to_process)} new emails from folder '{folder_name}'")
        
        for idx, email_id in enumerate(emails_to_process, 1):
            # Initialisiere Variablen für Exception-Handler
            subject = "Unknown"
            sender = "Unknown"
            imap_uid_str = None
            
            try:
                # Konvertiere email_id zu String (Sequenznummer)
                email_id_str = email_id.decode() if isinstance(email_id, bytes) else str(email_id)
                
                # Hole UID aus dem Mapping
                imap_uid_str = seq_to_uid.get(email_id_str)
                if not imap_uid_str:
                    # Falls UID nicht im Mapping, versuche sie direkt abzurufen
                    try:
                        status_uid, uid_data = mail_conn.fetch(email_id_str, '(UID)')
                        if status_uid == 'OK' and uid_data:
                            for item in uid_data:
                                uid_info = None
                                # Handle both tuple and bytes formats
                                if isinstance(item, tuple) and len(item) > 0:
                                    uid_info = item[0].decode('utf-8', errors='ignore') if isinstance(item[0], bytes) else str(item[0])
                                elif isinstance(item, bytes):
                                    uid_info = item.decode('utf-8', errors='ignore')
                                elif isinstance(item, str):
                                    uid_info = item
                                
                                if uid_info:
                                    import re
                                    match = re.search(r'\(UID\s+(\d+)\)', uid_info)
                                    if match:
                                        imap_uid_str = match.group(1)
                                        break
                    except:
                        pass
                
                if not imap_uid_str:
                    logging.debug(f"Could not determine UID for sequence {email_id_str}, skipping")
                    stats['errors'] += 1
                    continue
                
                # FLAGS abrufen um Gelesen-Status zu bestimmen
                is_read_imap = False
                try:
                    flags_status, flags_result = mail_conn.fetch(email_id_str, '(FLAGS)')
                    
                    if flags_status == 'OK' and flags_result and len(flags_result) > 0:
                        flags_entry = flags_result[0]
                        # FLAGS können als Tuple oder Bytes kommen
                        if isinstance(flags_entry, tuple) and len(flags_entry) > 1:
                            # Format: (b'1 (FLAGS (\\Seen))', b'...')
                            flags_str = flags_entry[0].decode('utf-8', errors='ignore') if isinstance(flags_entry[0], bytes) else str(flags_entry[0])
                        elif isinstance(flags_entry, tuple):
                            flags_str = flags_entry[0].decode('utf-8', errors='ignore') if isinstance(flags_entry[0], bytes) else str(flags_entry[0])
                        else:
                            flags_str = flags_entry.decode('utf-8', errors='ignore') if isinstance(flags_entry, bytes) else str(flags_entry)
                        
                        # Prüfe ob \Seen Flag vorhanden ist
                        is_read_imap = '\\Seen' in flags_str or '\\SEEN' in flags_str
                except Exception as flags_error:
                    logging.debug(f"Failed to fetch FLAGS for email {imap_uid_str} from folder '{folder_name}': {flags_error}")
                    # Weiter mit is_read_imap = False
                
                # RFC822 (E-Mail-Inhalt) abrufen
                status, msg_data = mail_conn.fetch(email_id_str, '(RFC822)')
                
                if status != 'OK' or not msg_data:
                    logging.debug(f"Failed to fetch email {imap_uid_str} from folder '{folder_name}': {msg_data}")
                    stats['errors'] += 1
                    continue
                
                raw_email = msg_data[0][1]
                email_msg = email_module.message_from_bytes(raw_email)
                
                sender_raw = email_msg.get('From', '')
                sender = decode_header_field(sender_raw)
                if not sender:
                    sender = "Unknown Sender"
                
                subject_raw = email_msg.get('Subject', '')
                subject = decode_header_field(subject_raw)
                if not subject:
                    subject = "(No Subject)"
                
                date_str = email_msg.get('Date', '')
                message_id = email_msg.get('Message-ID', '')
                
                recipients_raw = email_msg.get('To', '')
                recipients = decode_header_field(recipients_raw)
                
                cc_raw = email_msg.get('Cc', '')
                cc = decode_header_field(cc_raw)
                
                bcc_raw = email_msg.get('Bcc', '')
                bcc = decode_header_field(bcc_raw)
                
                # imap_uid_str wurde bereits oben bestimmt
                
                if not message_id:
                    # Wichtig für Move-Sync: Fallback-ID muss über Ordner hinweg stabil sein.
                    # Sonst wird dieselbe Mail nach Verschieben als neue Mail erkannt.
                    try:
                        stable_fingerprint = '|'.join([
                            (sender or '').strip().lower(),
                            (recipients or '').strip().lower(),
                            (subject or '').strip().lower(),
                            (date_str or '').strip().lower(),
                        ])
                        digest = hashlib.sha1(stable_fingerprint.encode('utf-8', errors='ignore')).hexdigest()
                        message_id = f"<generated-{digest}@local>"
                    except Exception:
                        message_id = f"<generated-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}@local>"
                    logging.debug(f"Generated stable message_id for email without Message-ID: {message_id}")
                
                received_at = datetime.utcnow()
                try:
                    from email.utils import parsedate_to_datetime
                    received_at = parsedate_to_datetime(date_str)
                except:
                    pass
                
                # Bestimme is_read Status für Updates:
                # 1. E-Mails im "Sent"-Ordner sind immer als gelesen markiert
                # 2. Andere Ordner: basierend auf IMAP FLAGS (\Seen)
                is_sent_folder_flag = is_sent_folder(folder_name)
                if is_sent_folder_flag:
                    is_read_status = True
                else:
                    is_read_status = is_read_imap
                
                existing_in_folder = EmailMessage.query.filter_by(
                    imap_uid=imap_uid_str,
                    folder=folder_name,
                    mailbox_id=mailbox_id,
                ).first()
                
                if existing_in_folder:
                    try:
                        existing_in_folder.last_imap_sync = datetime.utcnow()
                        # Stelle sicher, dass E-Mail nicht als gelöscht markiert ist (wiederherstellen falls nötig)
                        if existing_in_folder.is_deleted_imap:
                            existing_in_folder.is_deleted_imap = False
                            logging.debug(f"Restoring email {imap_uid_str} in folder '{folder_name}' - was marked as deleted but found on server")
                        existing_in_folder.last_imap_sync = datetime.utcnow()
                        existing_in_folder.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                        existing_in_folder.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                        stats['updated_emails'] += 1
                        db.session.commit()
                        continue
                    except Exception as update_error:
                        if "MySQL server has gone away" in str(update_error) or "ConnectionResetError" in str(update_error):
                            logging.debug("Database connection lost during update, attempting to reconnect...")
                            db.session.rollback()
                            db.session.close()
                            db.session = db.create_scoped_session()
                            existing_in_folder = EmailMessage.query.filter_by(
                                imap_uid=imap_uid_str,
                                folder=folder_name,
                                mailbox_id=mailbox_id,
                            ).first()
                            if existing_in_folder:
                                existing_in_folder.last_imap_sync = datetime.utcnow()
                                existing_in_folder.is_deleted_imap = False
                                existing_in_folder.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                                existing_in_folder.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                                stats['updated_emails'] += 1
                                db.session.commit()
                                logging.debug("Database reconnection successful for update")
                            continue
                        else:
                            raise update_error
                
                existing_by_message_id = EmailMessage.query.filter_by(
                    message_id=message_id,
                    mailbox_id=mailbox_id,
                ).first()
                if existing_by_message_id:
                    if existing_by_message_id.folder == folder_name:
                        try:
                            existing_by_message_id.last_imap_sync = datetime.utcnow()
                            existing_by_message_id.is_deleted_imap = False
                            existing_by_message_id.imap_uid = imap_uid_str
                            existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                            existing_by_message_id.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                            stats['updated_emails'] += 1
                            db.session.commit()
                            continue
                        except Exception as update_error:
                            if "MySQL server has gone away" in str(update_error) or "ConnectionResetError" in str(update_error):
                                logging.debug("Database connection lost during update, attempting to reconnect...")
                                db.session.rollback()
                                db.session.close()
                                db.session = db.create_scoped_session()
                                existing_by_message_id = EmailMessage.query.filter_by(
                                    message_id=message_id,
                                    mailbox_id=mailbox_id,
                                ).first()
                                if existing_by_message_id and existing_by_message_id.folder == folder_name:
                                    existing_by_message_id.last_imap_sync = datetime.utcnow()
                                    existing_by_message_id.is_deleted_imap = False
                                    existing_by_message_id.imap_uid = imap_uid_str
                                    existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                                    existing_by_message_id.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                                    stats['updated_emails'] += 1
                                    db.session.commit()
                                    logging.debug("Database reconnection successful for update")
                                continue
                            else:
                                raise update_error
                    else:
                        try:
                            existing_by_message_id.folder = folder_name
                            existing_by_message_id.imap_uid = imap_uid_str
                            existing_by_message_id.last_imap_sync = datetime.utcnow()
                            existing_by_message_id.is_deleted_imap = False
                            existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP beim Ordnerwechsel
                            existing_by_message_id.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                            stats['moved_emails'] += 1
                            db.session.commit()
                            continue
                        except Exception as move_error:
                            if "MySQL server has gone away" in str(move_error) or "ConnectionResetError" in str(move_error):
                                logging.debug("Database connection lost during move, attempting to reconnect...")
                                db.session.rollback()
                                db.session.close()
                                db.session = db.create_scoped_session()
                                existing_by_message_id = EmailMessage.query.filter_by(
                                    message_id=message_id,
                                    mailbox_id=mailbox_id,
                                ).first()
                                if existing_by_message_id:
                                    existing_by_message_id.folder = folder_name
                                    existing_by_message_id.imap_uid = imap_uid_str
                                    existing_by_message_id.last_imap_sync = datetime.utcnow()
                                    existing_by_message_id.is_deleted_imap = False
                                    existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP beim Ordnerwechsel
                                    existing_by_message_id.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                                    stats['moved_emails'] += 1
                                    db.session.commit()
                                    logging.debug("Database reconnection successful for move")
                                continue
                            else:
                                raise move_error
                
                # Globale Message-ID existiert evtl. in anderem Postfach – für dieses Postfach neu anlegen.
                # Unique auf message_id: Suffix nur wenn Kollision mit anderem mailbox_id.
                insert_message_id = message_id
                global_collision = EmailMessage.query.filter_by(message_id=message_id).first()
                if global_collision is not None and global_collision.mailbox_id != mailbox_id:
                    suffix = f"mb{mailbox_id if mailbox_id is not None else 0}"
                    insert_message_id = f"{message_id}#{suffix}"
                    # Falls schon vorhanden (Re-Sync), wie existing behandeln
                    existing_suffixed = EmailMessage.query.filter_by(
                        message_id=insert_message_id,
                        mailbox_id=mailbox_id,
                    ).first()
                    if existing_suffixed:
                        existing_suffixed.folder = folder_name
                        existing_suffixed.imap_uid = imap_uid_str
                        existing_suffixed.last_imap_sync = datetime.utcnow()
                        existing_suffixed.is_deleted_imap = False
                        existing_suffixed.is_read = is_read_status
                        existing_suffixed.is_sent = is_sent_folder_flag
                        stats['updated_emails'] += 1
                        db.session.commit()
                        continue
                message_id = insert_message_id

                body_text = ""
                body_html = ""
                has_attachments = False
                attachments_data = []
                
                if email_msg.is_multipart():
                    for part in email_msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = part.get('Content-Disposition', '')
                        content_id_header = (part.get('Content-ID', '') or '').strip()

                        # Inline-Bilder aus multipart/related haben oft KEIN Content-Disposition,
                        # nur einen Content-ID-Header. Diese Parts müssen trotzdem als Attachment
                        # gespeichert werden, sonst können cid:-Referenzen im HTML nie aufgelöst werden.
                        is_related_inline = (
                            bool(content_id_header)
                            and not content_type.startswith('text/')
                            and not content_type.startswith('multipart/')
                            and 'attachment' not in content_disposition
                            and 'inline' not in content_disposition
                        )

                        if (
                            ('attachment' in content_disposition or 'inline' in content_disposition)
                            and not content_type.startswith('text/')
                        ) or is_related_inline:
                            has_attachments = True
                            if is_related_inline:
                                content_disposition = (content_disposition or '') + '; inline'
                            
                            try:
                                filename = part.get_filename()
                                if not filename:
                                    extension = content_type.split('/')[-1] if '/' in content_type else 'bin'
                                    filename = f"attachment_{len(attachments_data)}.{extension}"
                                
                                if filename:
                                    try:
                                        from email.header import decode_header
                                        decoded_filename = decode_header(filename)
                                        if decoded_filename and decoded_filename[0][0]:
                                            filename = decoded_filename[0][0]
                                    except:
                                        pass
                                    
                                    # Kürze Dateinamen auf maximal 500 Zeichen (Datenbanklimit)
                                    filename = truncate_filename(filename, max_length=500)
                                
                                try:
                                    payload = None
                                    try:
                                        payload = part.get_payload(decode=True)
                                    except Exception as decode_error:
                                        logging.error(f"Failed to decode attachment '{filename}': {decode_error}")
                                        has_attachments = True
                                        continue
                                    
                                    if payload:
                                        attachment_size = len(payload)
                                        
                                        max_db_size = 1 * 1024 * 1024
                                        
                                        if attachment_size > max_db_size:
                                            import os
                                            
                                            attachments_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'attachments')
                                            os.makedirs(attachments_dir, exist_ok=True)
                                            
                                            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                                            safe_filename = "".join(c for c in filename if c.isalnum() or c in '._- ')
                                            file_path = os.path.join(attachments_dir, f"{timestamp}_{safe_filename}")
                                            
                                            try:
                                                with open(file_path, 'wb') as f:
                                                    f.write(payload)
                                                logging.debug(f"Large attachment saved to disk: {file_path}")
                                                
                                                attachments_data.append({
                                                    'filename': filename,
                                                    'content_type': content_type,
                                                    'content': None,
                                                    'file_path': file_path,
                                                    'size': attachment_size,
                                                    'is_inline': 'inline' in content_disposition,
                                                    'content_id': part.get('Content-ID', '').strip('<>'),
                                                    'is_large_file': True
                                                })
                                            except Exception as file_error:
                                                logging.error(f"Error saving large file to disk: {file_error}")
                                                attachments_data.append({
                                                    'filename': filename,
                                                    'content_type': content_type,
                                                    'content': payload,
                                                    'file_path': None,
                                                    'size': attachment_size,
                                                    'is_inline': 'inline' in content_disposition,
                                                    'content_id': part.get('Content-ID', '').strip('<>'),
                                                    'is_large_file': False
                                                })
                                        else:
                                            attachments_data.append({
                                                'filename': filename,
                                                'content_type': content_type,
                                                'content': payload,
                                                'file_path': None,
                                                'size': attachment_size,
                                                'is_inline': 'inline' in content_disposition,
                                                'content_id': part.get('Content-ID', '').strip('<>'),
                                                'is_large_file': False
                                            })
                                        
                                        logging.debug(f"Added attachment: '{filename}' ({attachment_size / (1024*1024):.2f} MB) - {'disk' if attachment_size > max_db_size else 'database'}")
                                except MemoryError as mem_error:
                                    logging.error(f"Memory error processing attachment '{filename}': {mem_error}. Email will be saved without this attachment.")
                                    has_attachments = True
                                    continue
                                except Exception as payload_error:
                                    logging.error(f"Error getting payload for attachment '{filename}': {payload_error}. Email will be saved without this attachment.")
                                    has_attachments = True
                                    continue
                            except Exception as e:
                                logging.error(f"Error processing attachment '{filename if 'filename' in locals() else 'unknown'}': {e}. Email will be saved without this attachment.")
                                has_attachments = True
                                continue
                        
                        if content_type == "text/plain":
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    import chardet
                                    detected = chardet.detect(payload)
                                    encoding = detected.get('encoding', 'utf-8')
                                    decoded_text = payload.decode(encoding, errors='ignore')
                                    if decoded_text.strip():
                                        body_text = decoded_text
                            except:
                                pass
                        elif content_type == "text/html":
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    import chardet
                                    detected = chardet.detect(payload)
                                    encoding = detected.get('encoding', 'utf-8')
                                    decoded_html = payload.decode(encoding, errors='ignore')
                                    if decoded_html.strip():
                                        if body_html:
                                            body_html += "\n" + decoded_html
                                        else:
                                            body_html = decoded_html
                            except Exception as e:
                                logging.error(f"Error processing HTML part: {e}")
                                pass
                else:
                    content_type = email_msg.get_content_type()
                    try:
                        payload = email_msg.get_payload(decode=True)
                        if payload:
                            import chardet
                            detected = chardet.detect(payload)
                            encoding = detected.get('encoding', 'utf-8')
                            decoded_content = payload.decode(encoding, errors='ignore')
                            
                            if content_type == "text/html":
                                if decoded_content.strip():
                                    body_html = decoded_content
                            else:
                                if decoded_content.strip():
                                    body_text = decoded_content
                    except Exception as e:
                        logging.error(f"Error processing single part email: {e}")
                        pass
                
                
                html_max_length = current_app.config.get('EMAIL_HTML_MAX_LENGTH', 0)
                text_max_length = current_app.config.get('EMAIL_TEXT_MAX_LENGTH', 10000)
                
                if html_max_length > 0 and body_html and len(body_html) > html_max_length:
                    body_html = body_html[:html_max_length]
                
                if text_max_length > 0 and body_text and len(body_text) > text_max_length:
                    body_text = body_text[:text_max_length]

                # Booking-Thread: Antworten auf Buchungsmails nicht in der normalen Inbox zeigen
                try:
                    from app.utils.booking_messages import try_route_inbound_email
                    routed = try_route_inbound_email(
                        email_msg,
                        message_id=message_id,
                        sender=sender,
                        subject=subject,
                        recipients=recipients or '',
                        body_text=body_text or '',
                        body_html=body_html or '',
                    )
                    if routed:
                        stats['skipped_emails'] += 1
                        logging.info(
                            f"Email {message_id} routed to booking thread, skipped inbox "
                            f"(folder={folder_name})"
                        )
                        continue
                except Exception as booking_route_error:
                    logging.error(f"Booking email routing failed: {booking_route_error}")
                
                # Bestimme is_read Status:
                # 1. E-Mails im "Sent"-Ordner sind immer als gelesen markiert (man hat sie selbst versendet)
                # 2. Andere Ordner: basierend auf IMAP FLAGS (\Seen)
                is_sent_folder_flag = is_sent_folder(folder_name)
                if is_sent_folder_flag:
                    is_read_status = True
                else:
                    is_read_status = is_read_imap
                
                email_entry = EmailMessage(
                    message_id=message_id,
                    sender=sender,
                    subject=subject,
                    recipients=recipients or 'Unknown',
                    cc=cc,
                    bcc=bcc,
                    body_text=body_text if body_text else '',
                    body_html=body_html if body_html else '',
                    has_attachments=has_attachments,
                    folder=folder_name,
                    imap_uid=imap_uid_str,
                    last_imap_sync=datetime.utcnow(),
                    is_deleted_imap=False,
                    received_at=received_at,
                    is_read=is_read_status,
                    is_sent=is_sent_folder_flag,
                    mailbox_id=mailbox_id,
                )
                
                try:
                    db.session.add(email_entry)
                    db.session.flush()
                except IntegrityError as integrity_error:
                    if "Duplicate entry" in str(integrity_error) or "1062" in str(integrity_error):
                        logging.debug(f"Email with message_id '{message_id}' already exists in another folder, skipping")
                        stats['skipped_emails'] += 1
                        db.session.rollback()
                        continue
                    else:
                        raise
                
                for attachment_data in attachments_data:
                    try:
                        attachment_size = attachment_data['size']
                        filename = truncate_filename(attachment_data['filename'], max_length=500)
                        
                        if attachment_size > 1 * 1024 * 1024:
                            logging.info(f"Processing large attachment: '{filename}' ({attachment_size / (1024*1024):.2f} MB) - from disk")
                        
                        attachment = EmailAttachment(
                            email_id=email_entry.id,
                            filename=filename,
                            content_type=attachment_data['content_type'],
                            size=attachment_size,
                            content=attachment_data.get('content'),
                            file_path=attachment_data.get('file_path'),
                            is_inline=attachment_data['is_inline'],
                            content_id=attachment_data['content_id'] if attachment_data['content_id'] else None,
                            is_large_file=attachment_data.get('is_large_file', False)
                        )
                        
                        db.session.add(attachment)
                        
                        if attachment_size > 1 * 1024 * 1024:
                            try:
                                db.session.flush()
                                logging.debug(f"Successfully flushed attachment '{filename}' ({attachment_size / (1024*1024):.2f} MB) to database")
                            except Exception as flush_error:
                                logging.debug(f"Flush failed for '{filename}', will commit with email: {flush_error}")
                    except Exception as e:
                        logging.error(f"Error saving attachment '{attachment_data['filename']}' ({attachment_data['size'] / (1024*1024):.2f} MB): {e}")
                        import traceback
                        logging.error(f"Traceback: {traceback.format_exc()}")
                        continue
                
                try:
                    db.session.commit()
                    stats['new_emails'] += 1
                except Exception as commit_error:
                    if "Duplicate entry" in str(commit_error) or "1062" in str(commit_error):
                        logging.debug(f"Email with message_id '{message_id}' already exists, skipping duplicate")
                        stats['skipped_emails'] += 1
                        db.session.rollback()
                        continue
                    if "MySQL server has gone away" in str(commit_error) or "ConnectionResetError" in str(commit_error):
                        logging.debug("Database connection lost, attempting to reconnect...")
                        db.session.rollback()
                        db.session.close()
                        db.session = db.create_scoped_session()
                        db.session.add(email_entry)
                        db.session.flush()
                        for attachment_data in attachments_data:
                            try:
                                attachment = EmailAttachment(
                                    email_id=email_entry.id,
                                    filename=attachment_data['filename'],
                                    content_type=attachment_data['content_type'],
                                    size=attachment_data['size'],
                                    content=attachment_data.get('content'),
                                    file_path=attachment_data.get('file_path'),
                                    is_inline=attachment_data['is_inline'],
                                    content_id=attachment_data['content_id'] if attachment_data['content_id'] else None,
                                    is_large_file=attachment_data.get('is_large_file', False)
                                )
                                db.session.add(attachment)
                            except Exception as e:
                                logging.error(f"Error saving attachment {attachment_data['filename']}: {e}")
                                continue
                        db.session.commit()
                        stats['new_emails'] += 1
                        logging.debug("Database reconnection successful")
                    else:
                        raise commit_error
            except Exception as e:
                stats['errors'] += 1
                subject_display = subject if 'subject' in locals() and subject else "Unknown"
                logging.error(f"Error saving email '{subject_display}': {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                db.session.rollback()
                continue
                
            except MemoryError as mem_error:
                stats['errors'] += 1
                logging.error(f"Memory error syncing email from folder '{folder_name}': {mem_error}")
                db.session.rollback()
                continue
            except Exception as e:
                stats['errors'] += 1
                logging.error(f"Error syncing email from folder '{folder_name}': {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                db.session.rollback()
                continue
        
        db.session.commit()
        
        # Schließe IMAP-Verbindung sicher
        try:
            if owns_connection:
                _imap_logout(mail_conn)
        except Exception as close_error:
            logging.debug(f"Fehler beim Schließen der IMAP-Verbindung: {close_error}")
        
        # Navbar-/Dashboard-Badge: immer aktuellen Unread-Stand pushen
        try:
            from app.utils.email_counts import emit_email_unread_update
            emit_email_unread_update()
        except Exception as e:
            logging.error(f"Fehler beim Senden der Dashboard-Updates für E-Mails: {e}")

        if stats['new_emails'] > 0:
            try:
                last_email = EmailMessage.query.filter_by(is_sent=False).order_by(EmailMessage.id.desc()).first()
                if last_email:
                    send_email_notification(last_email.id)
            except Exception as e:
                logging.error(f"Fehler beim Senden der E-Mail-Benachrichtigung: {e}")

        sync_details = []
        if stats['new_emails'] > 0:
            sync_details.append(f"{stats['new_emails']} neu")
        if stats['updated_emails'] > 0:
            sync_details.append(f"{stats['updated_emails']} übersprungen")
        if stats['moved_emails'] > 0:
            sync_details.append(f"{stats['moved_emails']} verschoben")
        if stats['deleted_emails'] > 0:
            sync_details.append(f"{stats['deleted_emails']} gelöscht")
        
        if sync_details:
            result_msg = f"Ordner '{folder_name}': {', '.join(sync_details)}"
        else:
            result_msg = f"Ordner '{folder_name}': Keine Änderungen"
        
        return True, result_msg
        
    except Exception as e:
        logging.error(f"Email sync from folder failed: {str(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        
        # Stelle sicher, dass IMAP-Verbindung geschlossen wird (nur eigene)
        if owns_connection:
            _imap_logout(mail_conn)
        
        return False, f"E-Mail-Sync-Fehler für Ordner '{folder_name}': {str(e)}"


def cleanup_old_emails():
    """Lösche alte E-Mails basierend auf der konfigurierten Speicherdauer."""
    try:
        # Hole Speicherdauer aus Einstellungen
        storage_setting = SystemSettings.query.filter_by(key='email_storage_days').first()
        storage_days = 0
        if storage_setting and storage_setting.value:
            try:
                storage_days = int(storage_setting.value)
            except ValueError:
                storage_days = 0
        
        # Wenn Speicherdauer 0 ist, keine Bereinigung
        if storage_days <= 0:
            logging.debug("E-Mail-Bereinigung deaktiviert (Speicherdauer = 0)")
            return 0
        
        # Berechne das Datum, ab dem E-Mails gelöscht werden sollen
        cutoff_date = datetime.utcnow() - timedelta(days=storage_days)
        
        # Finde E-Mails, die älter als die Speicherdauer sind
        old_emails = EmailMessage.query.filter(
            EmailMessage.created_at < cutoff_date
        ).all()
        
        deleted_count = 0
        for email in old_emails:
            try:
                # Lösche auch alle Anhänge (wird durch cascade automatisch gemacht)
                db.session.delete(email)
                deleted_count += 1
            except Exception as e:
                logging.error(f"Fehler beim Löschen der E-Mail {email.id}: {e}")
                continue
        
        if deleted_count > 0:
            db.session.commit()
            logging.info(f"E-Mail-Bereinigung: {deleted_count} E-Mails gelöscht (älter als {storage_days} Tage)")
        else:
            logging.debug(f"E-Mail-Bereinigung: Keine E-Mails zum Löschen gefunden (älter als {storage_days} Tage)")
        
        return deleted_count
        
    except Exception as e:
        logging.error(f"Fehler bei der E-Mail-Bereinigung: {e}", exc_info=True)
        db.session.rollback()
        return 0


def sync_emails_from_server(mailbox=None):
    """Sync emails from IMAP server to database with folder support.

    mailbox=None → Hauptpostfach (App-Config).
    """
    label = f"mailbox#{mailbox.id}" if mailbox is not None else "main"
    logger.info(f"E-Mail-Synchronisation wird gestartet ({label})")
    
    shared_conn = None
    try:
        from app.utils.multi_mailboxes import get_mailbox_imap_config
        cfg = get_mailbox_imap_config(mailbox)
        imap_server = cfg.get('server')
        username = cfg.get('user')
        password = cfg.get('password')
        auth_type = (getattr(mailbox, 'auth_type', None) or 'password') if mailbox is not None else 'password'
        # OAuth-Postfächer haben kein IMAP-Passwort – Platzhalter-Check nur für Passwort-Auth
        if auth_type != 'oauth' and _is_placeholder_imap_config(imap_server, username, password):
            message = "IMAP ist nicht konfiguriert (Platzhalterwerte erkannt) - Synchronisation übersprungen"
            logger.warning(message)
            return False, message
        if not imap_server or not username:
            message = "IMAP-Konfiguration unvollständig (Server/Benutzer fehlen)"
            logging.warning(message)
            return False, message

        # Synchronisiere zuerst die Ordner-Liste
        folder_success, folder_message = sync_imap_folders(mailbox=mailbox)
        if not folder_success:
            logging.warning(f"Ordner-Sync-Warnung: {folder_message}")
            # Weiter mit Standard-Ordnern, auch wenn Ordner-Sync fehlschlägt
            logging.info("Verwende Standard-Ordner als Fallback")
        
        mailbox_id = mailbox.id if mailbox is not None else None
        # Hole Ordner aus Datenbank
        folder_rows = (
            db.session.query(EmailFolder.name, EmailFolder.display_name)
            .filter(_folder_mailbox_filter(mailbox_id))
            .all()
        )
        if not folder_rows:
            # Fallback: Verwende Standard-Ordner
            folder_rows = [('INBOX', 'Posteingang')]
            logging.info("Keine Ordner in Datenbank gefunden, verwende Standard-Ordner")
        
        logging.info(f"Syncing emails from {len(folder_rows)} folders: {[name for (name, _) in folder_rows]}")
        
        # Eine IMAP-Session für alle Ordner (weniger Logins, schneller, Provider-freundlicher)
        shared_conn = connect_imap('INBOX', mailbox=mailbox)
        if not shared_conn:
            message = "IMAP-Verbindung fehlgeschlagen - Synchronisation abgebrochen"
            logging.error(message)
            return False, message

        total_synced = 0
        total_new = 0
        folder_results = []
        successful_folders = 0
        failed_folders = 0
        
        for (folder_name, display_name) in folder_rows:
            try:
                heartbeat_email_sync_lock()
                logging.info(f"Syncing folder: '{folder_name}' ({display_name})")
                success, message = sync_emails_from_folder(
                    folder_name, mail_conn=shared_conn, mailbox=mailbox
                )
                if success:
                    successful_folders += 1
                    import re
                    # Suche nach verschiedenen Mustern für Anzahl
                    match = re.search(r'(\d+)\s+(neu|new)', message, re.IGNORECASE)
                    if match:
                        count = int(match.group(1))
                        total_new += count
                    # Auch nach "E-Mails" suchen
                    match = re.search(r'(\d+)\s+E-Mails', message, re.IGNORECASE)
                    if match:
                        count = int(match.group(1))
                        total_synced += count
                    folder_results.append(f"{display_name}: {message}")
                    logging.info(f"✓ Ordner '{folder_name}' erfolgreich synchronisiert: {message}")
                else:
                    failed_folders += 1
                    logging.warning(f"✗ Ordner '{folder_name}' konnte nicht synchronisiert werden: {message}")
                    folder_results.append(f"{display_name}: Fehler - {message}")
            except Exception as folder_error:
                failed_folders += 1
                logging.error(f"Fehler beim Synchronisieren des Ordners '{folder_name}': {folder_error}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                folder_results.append(f"{display_name}: Fehler - {str(folder_error)}")
                continue
        
        logger.info(f"E-Mail-Synchronisation wurde beendet: {successful_folders} Ordner erfolgreich, {failed_folders} Ordner fehlgeschlagen")
        
        # Erstelle Ergebnis-Meldung
        if total_new > 0:
            result_msg = f"{total_new} neue E-Mails aus {successful_folders} Ordnern synchronisiert"
        elif total_synced > 0:
            result_msg = f"{total_synced} E-Mails aus {successful_folders} Ordnern synchronisiert"
        elif successful_folders > 0:
            result_msg = f"{successful_folders} Ordner synchronisiert (keine neuen E-Mails)"
        else:
            result_msg = "Keine E-Mails synchronisiert"
        
        if failed_folders > 0:
            result_msg += f" ({failed_folders} Ordner fehlgeschlagen)"
        
        return True, result_msg
    except Exception as e:
        logging.error(f"Kritischer Fehler in sync_emails_from_server: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"E-Mail-Synchronisation Fehler: {e}", exc_info=True)
        return False, f"Kritischer Fehler: {str(e)}"
    finally:
        if shared_conn is not None:
            _imap_logout(shared_conn)


def sync_all_configured_mailboxes():
    """Sync Hauptpostfach + alle aktiven Multi-Postfächer (wenn Multi aktiv)."""
    results = []
    ok_main, msg_main = sync_emails_from_server(mailbox=None)
    results.append(('main', ok_main, msg_main))

    try:
        from app.utils.multi_mailboxes import get_active_sync_mailboxes, is_email_multi_enabled
        if is_email_multi_enabled():
            for mb in get_active_sync_mailboxes():
                try:
                    ok, msg = sync_emails_from_server(mailbox=mb)
                    results.append((f'mailbox#{mb.id}', ok, msg))
                except Exception as exc:
                    logging.error(f"Multi-Postfach-Sync fehlgeschlagen ({mb.id}): {exc}")
                    results.append((f'mailbox#{mb.id}', False, str(exc)))
    except Exception as exc:
        logging.error(f"Multi-Postfach-Sync Setup-Fehler: {exc}")

    any_ok = any(r[1] for r in results)
    summary = '; '.join(f'{name}: {msg}' for name, _, msg in results)
    return any_ok, summary


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


def _email_list_page_url(folder_name: str, page: int, search_query: str = '', mailbox_id=None):
    """Build folder list URL preserving search and mailbox filters."""
    from app.utils.multi_mailboxes import is_email_multi_enabled

    kwargs = {'folder_name': folder_name, 'page': page}
    if search_query:
        kwargs['q'] = search_query
    if is_email_multi_enabled():
        kwargs['mailbox'] = mailbox_id or 'main'
    return url_for('email.folder_view', **kwargs)


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


@email_bp.route('/')
@login_required
@check_module_access('module_email')
def index():
    """Email inbox with folder support."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    current_folder = request.args.get('folder', 'INBOX')
    search_query = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int) or 1
    active_mailbox, mailbox_id = _resolve_request_mailbox('read')
    pagination = _emails_for_folder(
        current_folder, search_query, mailbox_id=mailbox_id, page=page
    )
    emails = pagination.items
    _restore_false_deleted_flags(emails, current_folder)

    folder_obj = _find_email_folder(current_folder, mailbox_id)
    folder_display_name = folder_obj.display_name if folder_obj else current_folder

    folders, folder_tree = _folder_tree_context(mailbox_id=mailbox_id)

    try:
        from app.utils.notifications import mark_in_app_notifications_read
        mark_in_app_notifications_read(
            current_user.id,
            notification_type='email',
        )
    except Exception:
        pass

    db.session.commit()

    from app.utils.email_counts import count_unread_emails_by_folder
    from app.utils.multi_mailboxes import is_email_multi_enabled, get_accessible_mailboxes

    multi_on = is_email_multi_enabled()
    accessible = get_accessible_mailboxes(current_user) if multi_on else []
    mailbox_folder_trees = {}
    mailbox_unread_counts = {}
    if multi_on:
        mailbox_folder_trees, mailbox_unread_counts = _multi_mailbox_sidebar_trees(
            current_user, accessible
        )

    return render_template(
        'email/index.html',
        emails=emails,
        pagination=pagination,
        email_prev_url=(
            _email_list_page_url(current_folder, pagination.prev_num, search_query, mailbox_id)
            if pagination.has_prev else None
        ),
        email_next_url=(
            _email_list_page_url(current_folder, pagination.next_num, search_query, mailbox_id)
            if pagination.has_next else None
        ),
        folders=folders,
        folder_tree=folder_tree,
        folder_unread_counts=count_unread_emails_by_folder(
            user=current_user, mailbox_id=mailbox_id
        ),
        current_folder=current_folder,
        folder_display_name=folder_display_name,
        search_query=search_query,
        color_dot_choices=[c for c in COLOR_DOT_CHOICES.keys() if c not in ('', 'none')],
        email_multi_enabled=multi_on,
        accessible_mailboxes=accessible,
        active_mailbox=active_mailbox,
        active_mailbox_id=mailbox_id,
        mailbox_folder_trees=mailbox_folder_trees,
        mailbox_unread_counts=mailbox_unread_counts,
    )


@email_bp.route('/folder/<imap_folder:folder_name>')
@login_required
@check_module_access('module_email')
def folder_view(folder_name):
    """View emails in a specific folder."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))

    # Converter dekodiert bereits; unquote bleibt harmlos für Alt-Links
    folder_name = unquote(folder_name or '')
    
    # Reject invalid folder names
    if not folder_name or folder_name.strip() == '' or folder_name == '/':
        flash(translate('email.flash.invalid_folder_name'), 'danger')
        return redirect(url_for('email.index'))

    active_mailbox, mailbox_id = _resolve_request_mailbox('read')
    
    # Check if folder exists, if not redirect to index
    folder_obj = _find_email_folder(folder_name, mailbox_id)
    if not folder_obj:
        existing_emails = (
            EmailMessage.query.filter_by(folder=folder_name)
            .filter(_message_mailbox_filter(mailbox_id))
            .count()
        )
        if existing_emails > 0:
            logging.warning(f"Folder '{folder_name}' exists in emails but not in folders table")
        flash(f'Ordner "{folder_name}" nicht gefunden.', 'warning')
        return redirect(url_for('email.index', mailbox=mailbox_id or 'main'))
    
    search_query = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int) or 1
    pagination = _emails_for_folder(
        folder_name, search_query, mailbox_id=mailbox_id, page=page
    )
    emails = pagination.items
    _restore_false_deleted_flags(emails, folder_name)
    
    logging.info(f"Viewing folder '{folder_name}' with {len(emails)} emails (page {pagination.page}/{pagination.pages or 1})")

    folders, folder_tree = _folder_tree_context(mailbox_id=mailbox_id)
    folder_display_name = folder_obj.display_name if folder_obj else folder_name

    from app.utils.email_counts import count_unread_emails_by_folder
    from app.utils.multi_mailboxes import is_email_multi_enabled, get_accessible_mailboxes

    multi_on = is_email_multi_enabled()
    accessible = get_accessible_mailboxes(current_user) if multi_on else []
    mailbox_folder_trees = {}
    mailbox_unread_counts = {}
    if multi_on:
        mailbox_folder_trees, mailbox_unread_counts = _multi_mailbox_sidebar_trees(
            current_user, accessible
        )

    return render_template(
        'email/index.html',
        emails=emails,
        pagination=pagination,
        email_prev_url=(
            _email_list_page_url(folder_name, pagination.prev_num, search_query, mailbox_id)
            if pagination.has_prev else None
        ),
        email_next_url=(
            _email_list_page_url(folder_name, pagination.next_num, search_query, mailbox_id)
            if pagination.has_next else None
        ),
        folders=folders,
        folder_tree=folder_tree,
        folder_unread_counts=count_unread_emails_by_folder(
            user=current_user, mailbox_id=mailbox_id
        ),
        current_folder=folder_name,
        folder_display_name=folder_display_name,
        search_query=search_query,
        color_dot_choices=[c for c in COLOR_DOT_CHOICES.keys() if c not in ('', 'none')],
        email_multi_enabled=multi_on,
        accessible_mailboxes=accessible,
        active_mailbox=active_mailbox,
        active_mailbox_id=mailbox_id,
        mailbox_folder_trees=mailbox_folder_trees,
        mailbox_unread_counts=mailbox_unread_counts,
    )


@email_bp.route('/view/<int:email_id>')
@login_required
@check_module_access('module_email')
def view_email(email_id):
    """View a specific email."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    email_msg = EmailMessage.query.get_or_404(email_id)

    # Multi-Postfach: kein Zugriff auf fremde Postfächer
    if email_msg.mailbox_id is not None:
        from app.utils.multi_mailboxes import user_has_mailbox_access, is_email_multi_enabled
        if is_email_multi_enabled():
            mb = email_msg.mailbox
            if not mb or not user_has_mailbox_access(current_user, mb, 'read'):
                flash(translate('email.flash.no_read_permission'), 'danger')
                return redirect(url_for('email.index'))
    
    # Wenn es sich um einen Entwurf handelt, weiterleiten zur Bearbeitungsseite
    if email_msg.folder == 'Drafts':
        # Prüfe, ob der Benutzer Zugriff auf diesen Entwurf hat
        if email_msg.sent_by_user_id == current_user.id:
            return redirect(url_for('email.compose', draft_id=email_id))
        else:
            flash('Sie haben keinen Zugriff auf diesen Entwurf.', 'danger')
            return redirect(url_for('email.index'))
    
    if not email_msg.is_read:
        email_msg.is_read = True
        try:
            from app.utils.notifications import mark_in_app_notifications_read
            mark_in_app_notifications_read(
                current_user.id,
                notification_type='email',
            )
        except Exception:
            pass
        db.session.commit()
        try:
            from app.utils.email_counts import emit_email_unread_update
            emit_email_unread_update(current_user.id)
        except Exception:
            pass
    else:
        try:
            from app.utils.notifications import mark_in_app_notifications_read
            mark_in_app_notifications_read(
                current_user.id,
                notification_type='email',
                commit=True,
            )
        except Exception:
            pass
    
    
    raw_html = None
    if email_msg.body_html:
        try:
            if isinstance(email_msg.body_html, bytes):
                raw_html = email_msg.body_html.decode('utf-8', errors='replace')
            else:
                raw_html = str(email_msg.body_html)
        except Exception as e:
            logging.error(f"HTML decode error: {e}")
            raw_html = None

    # Inline-Bilder (cid:) nachladen, falls sie bei einem früheren Sync nicht erfasst wurden
    if raw_html and re.search(r'src\s*=\s*["\']?cid:', raw_html, flags=re.IGNORECASE):
        try:
            backfill_inline_attachments_from_imap(email_msg)
        except Exception as backfill_err:
            logging.debug(f"Inline backfill skipped: {backfill_err}")

    is_simple_html = is_simple_html_email(raw_html) if raw_html else True

    html_iframe_html = None
    html_content = None

    if raw_html:
        if not is_simple_html:
            # Rich HTML: full document in sandboxed iframe so sender CSS/layout stay intact
            viewer_dark = bool(
                current_user.is_authenticated and getattr(current_user, 'dark_mode', False)
            )
            viewer_oled = bool(
                current_user.is_authenticated and getattr(current_user, 'oled_mode', False)
            )
            html_iframe_html = build_rich_email_iframe_document(
                raw_html, email_msg, viewer_dark=viewer_dark, viewer_oled=viewer_oled
            )
            if not html_iframe_html:
                try:
                    html_content = process_email_body_html_for_inline_view(raw_html, email_msg)
                except Exception as e:
                    logging.error(f"HTML inline fallback error: {e}")
                    html_content = None
        else:
            try:
                html_content = process_email_body_html_for_inline_view(raw_html, email_msg)
            except Exception as e:
                logging.error(f"HTML processing error: {e}")
                html_content = None

    return render_template(
        'email/view.html',
        email=email_msg,
        html_content=html_content,
        html_iframe_html=html_iframe_html,
        is_simple_html=is_simple_html
    )


@email_bp.route('/print/<int:email_id>')
@login_required
@check_module_access('module_email')
def print_email_pdf(email_id):
    """Druck-PDF einer einzelnen E-Mail (Portal-Layout)."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))

    email_msg = EmailMessage.query.get_or_404(email_id)
    if email_msg.folder == 'Drafts':
        flash(translate('email.flash.draft_no_print'), 'warning')
        return redirect(url_for('email.compose', draft_id=email_id))

    from app.utils.email_pdf_generator import generate_email_print_pdf, safe_email_pdf_filename

    inline_preview = request.args.get('inline') == '1'
    pdf_buffer = generate_email_print_pdf(email_msg)
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=not inline_preview,
        download_name=safe_email_pdf_filename(email_msg),
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
            
            original_html = html_content
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
    return render_template('email/compose.html', **ctx)


@email_bp.route('/attachment/<int:attachment_id>')
@login_required
@check_module_access('module_email')
def download_attachment(attachment_id):
    """Download an email attachment with support for large files."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('email.index'))
    
    attachment = EmailAttachment.query.get_or_404(attachment_id)
    email_msg = attachment.email
    if not email_msg:
        flash(translate('email.flash.attachment_not_found'), 'danger')
        return redirect(url_for('email.index'))
    
    try:
        if attachment.size > 1 * 1024 * 1024:
            logging.info(f"Downloading large attachment: '{attachment.filename}' ({attachment.size / (1024*1024):.2f} MB)")
        
        if attachment.is_large_file and attachment.file_path:
            import os
            if os.path.exists(attachment.file_path):
                def generate():
                    with open(attachment.file_path, 'rb') as f:
                        while True:
                            data = f.read(8192)
                            if not data:
                                break
                            yield data
                
                response = Response(generate(), mimetype=attachment.content_type)
                import urllib.parse
                encoded_filename = urllib.parse.quote(attachment.filename.encode('utf-8'))
                response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
                response.headers['Content-Length'] = str(attachment.size)
                response.headers['Accept-Ranges'] = 'bytes'
                return response
            else:
                flash(translate('email.flash.attachment_file_not_found'), 'danger')
                return redirect(url_for('email.view_email', email_id=email_msg.id))
        else:
            content = attachment.get_content()
            if not content:
                flash(translate('email.flash.attachment_corrupted'), 'danger')
                return redirect(url_for('email.index'))
            
            file_obj = io.BytesIO(content)
            
            response = send_file(
                file_obj,
                as_attachment=True,
                download_name=attachment.filename,
                mimetype=attachment.content_type
            )
            
            import urllib.parse
            encoded_filename = urllib.parse.quote(attachment.filename.encode('utf-8'))
            response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
            
            response.headers['Content-Length'] = str(attachment.size)
            response.headers['Accept-Ranges'] = 'bytes'
            
            return response
        
    except Exception as e:
        logging.error(f"Error downloading attachment {attachment_id} ({attachment.filename}): {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        flash(f'Fehler beim Herunterladen des Anhangs: {str(e)}', 'danger')
        return redirect(url_for('email.view_email', email_id=email_msg.id))


def _compose_multi_context():
    from app.utils.multi_mailboxes import (
        is_email_multi_enabled,
        get_accessible_mailboxes,
        is_email_html_design_default,
        get_mailbox_use_logo,
    )
    active_mailbox, mailbox_id = _resolve_request_mailbox('send')
    use_mailbox_logo = True
    team_logo_available = False
    if active_mailbox and active_mailbox.mailbox_type == 'team' and active_mailbox.logo_filename:
        team_logo_available = True
        use_mailbox_logo = get_mailbox_use_logo(current_user, active_mailbox)
    return {
        'email_multi_enabled': is_email_multi_enabled(),
        'accessible_mailboxes': get_accessible_mailboxes(current_user, 'send') if is_email_multi_enabled() else [],
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
            
            # Füge Logo als ANHANG hinzu (wie andere Anhänge) - WICHTIG: Vor anderen Anhängen
            if logo_data and logo_mime_type and logo_cid:
                image_type = logo_mime_type.split('/')[1] if '/' in logo_mime_type else 'png'
                if image_type == 'jpeg' or image_type == 'jpg':
                    attachment_filename = 'logo.jpg'
                elif image_type == 'png':
                    attachment_filename = 'logo.png'
                elif image_type == 'gif':
                    attachment_filename = 'logo.gif'
                else:
                    attachment_filename = 'logo.png'
                
                # KRITISCH: Verwende msg.attach() - dies stellt sicher, dass das Logo in der Struktur bleibt
                # Die Manipulation mit CID und inline erfolgt später in send_email_with_lock()
                msg.attach(attachment_filename, logo_mime_type, logo_data)
                
                
                # KRITISCH: Manipuliere die Message-Struktur direkt, um CID und inline zu setzen
                # Flask-Mail erstellt die Struktur beim ersten Zugriff auf msg.msg
                # Wir müssen nach msg.attach() die Struktur manipulieren
                if hasattr(msg, 'msg') and msg.msg:
                    # Flask-Mail erstellt möglicherweise msg.msg erst beim ersten Zugriff
                    # Wir müssen es jetzt erzeugen, damit wir es manipulieren können
                    try:
                        _ = msg.msg.get_content_type()
                    except:
                        pass
                
                # Setze CID und inline disposition auf dem Logo-Attachment
                if hasattr(msg, 'msg') and hasattr(msg.msg, 'get_payload'):
                    parts = msg.msg.get_payload()
                    if isinstance(parts, list):
                        logo_found = False
                        for part in parts:
                            if (hasattr(part, 'get_content_type') and 
                                part.get_content_type() == logo_mime_type and
                                hasattr(part, 'get') and 
                                part.get('Content-Disposition', '').find(attachment_filename) != -1):
                                logo_found = True
                                # Setze Content-ID und inline disposition
                                part.add_header('Content-ID', f'<{logo_cid}>')
                                # Entferne alte Content-Disposition und setze neue
                                old_disp = part.get('Content-Disposition', '')
                                if old_disp:
                                    part.replace_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                else:
                                    part.add_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                
                                logging.info(f"Logo als inline attachment mit CID markiert: {attachment_filename}")
                                break
            
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
            
            # Stelle sicher, dass Logo-Attachment nach allen anderen Anhängen mit CID markiert ist
            # (wird auch in send_email_with_lock() nochmal geprüft, aber hier sicherstellen)
            if logo_data and logo_mime_type and logo_cid:
                # Warte, bis msg.msg erstellt wurde (nach allen anderen attach()-Aufrufen)
                if hasattr(msg, 'msg') and msg.msg:
                    try:
                        _ = msg.msg.get_content_type()
                    except:
                        pass
                    
                    # Setze CID und inline disposition auf dem Logo-Attachment
                    if hasattr(msg.msg, 'get_payload'):
                        parts = msg.msg.get_payload()
                        if isinstance(parts, list):
                            image_type = logo_mime_type.split('/')[1] if '/' in logo_mime_type else 'png'
                            if image_type == 'jpeg' or image_type == 'jpg':
                                attachment_filename = 'logo.jpg'
                            elif image_type == 'png':
                                attachment_filename = 'logo.png'
                            elif image_type == 'gif':
                                attachment_filename = 'logo.gif'
                            else:
                                attachment_filename = 'logo.png'
                            
                            for part in parts:
                                if (hasattr(part, 'get_content_type') and 
                                    part.get_content_type() == logo_mime_type and
                                    hasattr(part, 'get') and 
                                    part.get('Content-Disposition', '').find(attachment_filename) != -1):
                                    # Setze Content-ID, falls noch nicht gesetzt
                                    if not part.get('Content-ID'):
                                        part.add_header('Content-ID', f'<{logo_cid}>')
                                    # Stelle sicher, dass es inline ist
                                    disp = part.get('Content-Disposition', '')
                                    if 'attachment' in disp and 'inline' not in disp:
                                        try:
                                            part.replace_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                        except:
                                            part.add_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                    elif not disp:
                                        part.add_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                    
                                    logging.info(f"Logo-Attachment nach allen Anhängen mit CID markiert: {attachment_filename}")
                                    break
            
            
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
                        original_attachment_ids=','.join(attachment_ids) if attachment_ids else ''
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
        rendered_html, _ = render_custom_email(
            subject, body_html, logo_cid=None, is_preview=True,
            quoted_reply_html=quoted_reply_html
        )
        return jsonify({'html': rendered_html})
    except Exception as exc:
        current_app.logger.error(f"E-Mail Vorschau Fehler: {exc}")
        return jsonify({'error': translate('email.errors.preview_failed')}), 500


@email_bp.route('/sync', methods=['POST'])
@login_required
@check_module_access('module_email')
def sync_emails():
    """Sync emails from IMAP server (always runs in a background thread)."""
    if not check_email_permission('read'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept', '').startswith('application/json'):
            return jsonify({'success': False, 'error': 'Nicht autorisiert'}), 403
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('email.index'))
    
    is_async_request = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.headers.get('Accept', '').startswith('application/json')
    )
    current_folder = request.form.get('folder') or None
    _, mailbox_id = _resolve_request_mailbox('read')
    folder_label = None
    if current_folder:
        folder_obj = _find_email_folder(current_folder, mailbox_id)
        folder_label = folder_obj.display_name if folder_obj else current_folder

    # Always background — never run IMAP in the request worker
    user_id = current_user.id
    job_id = f"{user_id}-{uuid4().hex}"
    app_instance = current_app._get_current_object()
    sync_mailbox_id = mailbox_id
    
    def emit_status(status: str, message: str, level: str = 'info', **extras):
        payload = {
            'jobId': job_id,
            'status': status,
            'message': message,
            'level': level,
            'folder': current_folder,
            'folderLabel': folder_label,
            'mailboxId': sync_mailbox_id,
        }
        if extras:
            payload.update(extras)
        # SSE-Update senden (funktioniert mit mehreren Gunicorn-Workern)
        emit_email_sync_status(user_id, 'sync_status', payload)
    
    def sync_in_background():
        with app_instance.app_context():
            start_msg = 'Synchronisation gestartet.'
            if sync_mailbox_id:
                start_msg = 'Postfach-Synchronisation gestartet (inkl. Ordner).'
            elif folder_label:
                start_msg = f"Synchronisation für '{folder_label}' gestartet."
            emit_status('started', start_msg, 'info', shouldRefresh=False)
            
            try:
                from app.models.email import Mailbox as MailboxModel
                mb_obj = MailboxModel.query.get(sync_mailbox_id) if sync_mailbox_id else None
                # Non-blocking Lock — sofort „läuft bereits“ statt 60s warten
                with acquire_email_sync_lock(timeout=0) as acquired:
                    if acquired:
                        if mb_obj is not None:
                            logger.info(
                                "E-Mail-Synchronisation wird gestartet (vollständiges Postfach, mailbox=%s)",
                                sync_mailbox_id,
                            )
                            success, message = sync_emails_from_server(mailbox=mb_obj)
                            logger.info(
                                "E-Mail-Synchronisation wurde beendet (mailbox=%s)",
                                sync_mailbox_id,
                            )
                        elif current_folder:
                            logger.info(
                                "E-Mail-Synchronisation wird gestartet (Ordner: %s)",
                                folder_label or current_folder,
                            )
                            sync_imap_folders(mailbox=None)
                            success, message = sync_emails_from_folder(
                                current_folder, mailbox=None
                            )
                            logger.info(
                                "E-Mail-Synchronisation wurde beendet (Ordner: %s)",
                                folder_label or current_folder,
                            )
                        else:
                            # Nur Hauptpostfach synchronisieren
                            success, message = sync_emails_from_server(mailbox=None)
                        
                        if success:
                            emit_status('success', message, 'success', shouldRefresh=True)
                        else:
                            emit_status('error', message, 'danger', shouldRefresh=False)
                    else:
                        logger.debug("E-Mail-Synchronisation: Bereits in einem anderen Worker aktiv")
                        emit_status('warning', 'Synchronisation läuft bereits in einem anderen Worker. Bitte warten Sie einen Moment.', 'warning', shouldRefresh=False)
            except Exception as exc:
                app_instance.logger.error(f"E-Mail-Synchronisation Fehler: {exc}", exc_info=True)
                emit_status('error', str(exc), 'danger', shouldRefresh=False)
    
    thread = threading.Thread(target=sync_in_background, name=f"email-sync-{job_id}")
    thread.daemon = True
    thread.start()

    if not is_async_request:
        flash(translate('email.flash.sync_started'), 'info')
        target_endpoint = 'email.folder_view' if current_folder else 'email.index'
        target_kwargs = {'folder_name': current_folder} if current_folder else {}
        if mailbox_id:
            target_kwargs['mailbox'] = mailbox_id
        return redirect(url_for(target_endpoint, **target_kwargs))
    
    response_message = 'Synchronisation gestartet.'
    if sync_mailbox_id:
        response_message = 'Postfach-Synchronisation gestartet (inkl. Ordner).'
    elif folder_label:
        response_message = f"Synchronisation für '{folder_label}' gestartet."
    
    return jsonify({
        'success': True,
        'jobId': job_id,
        'message': response_message,
        'folder': current_folder,
        'folderLabel': folder_label,
        'mailboxId': sync_mailbox_id,
    }), 202


def _wants_json_response():
    """Detect if client expects JSON rather than HTML redirect."""
    if request.is_json:
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.headers.get('Accept', '')
    if 'application/json' in accept and 'text/html' not in accept:
        return True
    return False


@email_bp.route('/delete/<int:email_id>', methods=['POST'])
@login_required
@check_module_access('module_email')
def delete_email(email_id):
    """Delete email from both portal and IMAP."""
    if not check_email_permission('read'):
        if _wants_json_response():
            return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403
        return jsonify({'error': translate('email.errors.unauthorized')}), 403

    email = EmailMessage.query.get_or_404(email_id)
    original_folder = email.folder

    imap_warning = None
    if email.imap_uid:
        success, message = delete_email_from_imap(email.imap_uid, email.folder)
        if not success:
            imap_warning = message

    db.session.delete(email)
    db.session.commit()

    unread_count = 0
    by_folder = {}
    try:
        from app.utils.email_counts import count_unread_emails_by_folder, emit_email_unread_update
        unread_count = emit_email_unread_update(current_user.id) or 0
        by_folder = count_unread_emails_by_folder()
    except Exception:
        pass

    if _wants_json_response():
        payload = {
            'success': True,
            'message': translate('email.flash.deleted'),
            'folder': original_folder,
            'email_id': email_id,
            'unread_count': unread_count,
            'by_folder': by_folder,
        }
        if imap_warning:
            payload['imap_warning'] = imap_warning
        return jsonify(payload)

    if imap_warning:
        flash(f'WARNING: E-Mail konnte nicht in IMAP gelöscht werden: {imap_warning}', 'warning')
    flash(translate('email.flash.deleted'), 'success')
    return redirect(url_for('email.folder_view', folder_name=original_folder))


@email_bp.route('/move/<int:email_id>', methods=['POST'])
@login_required
@check_module_access('module_email')
def move_email(email_id):
    """Move email to another folder in both portal and IMAP (JSON or classic form)."""
    if not check_email_permission('read'):
        if _wants_json_response():
            return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403
        return jsonify({'error': translate('email.errors.unauthorized')}), 403

    email = EmailMessage.query.get_or_404(email_id)
    payload = request.get_json(silent=True) or {}
    new_folder = (
        request.form.get('folder')
        or request.values.get('folder')
        or payload.get('folder')
    )

    if not new_folder:
        if _wants_json_response():
            return jsonify({'success': False, 'error': translate('email.flash.target_folder_not_specified')}), 400
        flash(translate('email.flash.target_folder_not_specified'), 'danger')
        return redirect(url_for('email.folder_view', folder_name=email.folder))

    if new_folder == email.folder:
        if _wants_json_response():
            return jsonify({'success': True, 'message': 'Bereits in Zielordner', 'folder': new_folder, 'email_id': email.id})
        return redirect(url_for('email.folder_view', folder_name=new_folder))

    target_folder_obj = EmailFolder.query.filter_by(name=new_folder).first()
    if not target_folder_obj:
        if _wants_json_response():
            return jsonify({'success': False, 'error': f"Zielordner '{new_folder}' nicht gefunden"}), 404
        flash(f"Zielordner '{new_folder}' nicht gefunden", 'danger')
        return redirect(url_for('email.folder_view', folder_name=email.folder))

    imap_warning = None
    if email.imap_uid:
        imap_result = imap_move_message(email.imap_uid, email.folder, new_folder)
        if not imap_result.get('success'):
            imap_warning = imap_result.get('message')
            if _wants_json_response():
                return jsonify({
                    'success': False,
                    'error': f"IMAP-Verschiebung fehlgeschlagen: {imap_warning}",
                    'retryable': imap_result.get('retryable', False),
                }), 502

    old_folder = email.folder
    email.folder = new_folder
    email.last_imap_sync = datetime.utcnow()
    db.session.commit()

    by_folder = {}
    unread_count = 0
    try:
        from app.utils.email_counts import count_unread_emails_by_folder, emit_email_unread_update
        unread_count = emit_email_unread_update(current_user.id) or 0
        by_folder = count_unread_emails_by_folder()
    except Exception:
        pass

    if _wants_json_response():
        return jsonify({
            'success': True,
            'message': f'E-Mail nach {new_folder} verschoben',
            'folder': new_folder,
            'previous_folder': old_folder,
            'email_id': email.id,
            'imap_warning': imap_warning,
            'unread_count': unread_count,
            'by_folder': by_folder,
        })

    if imap_warning:
        flash(f'WARNING: E-Mail konnte nicht in IMAP verschoben werden: {imap_warning}', 'warning')
    flash(f'E-Mail wurde erfolgreich von {old_folder} nach {new_folder} verschoben.', 'success')
    return redirect(url_for('email.folder_view', folder_name=new_folder))


@email_bp.route('/messages/<int:email_id>/read-state', methods=['POST'])
@login_required
@check_module_access('module_email')
def set_email_read_state(email_id):
    """Mark email as read or unread (IMAP-synchronised)."""
    if not check_email_permission('read'):
        return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403

    email = EmailMessage.query.get_or_404(email_id)
    payload = request.get_json(silent=True) or {}
    state = (payload.get('state') or request.form.get('state') or '').strip().lower()
    if state not in ('read', 'unread'):
        return jsonify({'success': False, 'error': "Ungültiger Status (erwartet 'read' oder 'unread')"}), 400

    seen = state == 'read'
    imap_warning = None
    if email.imap_uid:
        imap_result = imap_mark_seen(email.imap_uid, email.folder, seen=seen)
        if not imap_result.get('success'):
            imap_warning = imap_result.get('message')

    email.is_read = seen
    db.session.commit()

    unread_count = 0
    by_folder = {}
    try:
        from app.utils.email_counts import count_unread_emails_by_folder, emit_email_unread_update
        unread_count = emit_email_unread_update(current_user.id) or 0
        by_folder = count_unread_emails_by_folder()
    except Exception:
        pass

    return jsonify({
        'success': True,
        'state': state,
        'email_id': email.id,
        'is_read': email.is_read,
        'imap_warning': imap_warning,
        'unread_count': unread_count,
        'by_folder': by_folder,
    })


@email_bp.route('/messages/<int:email_id>/color-dot', methods=['POST'])
@login_required
@check_module_access('module_email')
def set_email_color_dot(email_id):
    """Set/clear the colored label (dot) for an email."""
    if not check_email_permission('read'):
        return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403

    email = EmailMessage.query.get_or_404(email_id)
    payload = request.get_json(silent=True) or {}
    color = (payload.get('color') or request.form.get('color') or '').strip().lower()

    if color not in COLOR_DOT_CHOICES:
        return jsonify({'success': False, 'error': f"Unbekannte Farbe: {color}"}), 400

    # Remove previous keyword on server if a different one was set
    previous_keyword = email.imap_color_keyword
    new_keyword = COLOR_DOT_CHOICES.get(color)

    imap_status = None
    imap_message = None
    keyword_supported = None
    if email.imap_uid:
        if previous_keyword and previous_keyword != new_keyword:
            remove_result = imap_set_keyword(email.imap_uid, email.folder, previous_keyword, enabled=False)
            imap_status = remove_result.get('imap_status')
            imap_message = remove_result.get('message')
            keyword_supported = remove_result.get('keyword_supported', keyword_supported)
        if new_keyword:
            add_result = imap_set_keyword(email.imap_uid, email.folder, new_keyword, enabled=True)
            imap_status = add_result.get('imap_status')
            imap_message = add_result.get('message')
            keyword_supported = add_result.get('keyword_supported', keyword_supported)

    email.color_dot = color if color and color != 'none' else None
    email.imap_color_keyword = new_keyword if keyword_supported else None
    email.last_flag_sync_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'email_id': email.id,
        'color': email.color_dot,
        'imap_status': imap_status,
        'imap_message': imap_message,
        'keyword_supported': keyword_supported,
    })


@email_bp.route('/folders', methods=['POST'])
@login_required
@check_module_access('module_email')
def create_folder():
    """Create a new IMAP folder (optionally as subfolder of parent)."""
    if not check_email_permission('read'):
        return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403

    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or request.form.get('name') or '').strip()
    parent = (payload.get('parent') or request.form.get('parent') or '').strip()
    separator = (payload.get('separator') or request.form.get('separator') or '/').strip() or '/'

    if not name:
        return jsonify({'success': False, 'error': 'Ordnername fehlt'}), 400

    invalid_chars = set('\\"')
    if any(ch in name for ch in invalid_chars):
        return jsonify({'success': False, 'error': 'Ungültige Zeichen im Ordnernamen'}), 400

    if parent:
        parent_obj = EmailFolder.query.filter_by(name=parent).first()
        if not parent_obj:
            return jsonify({'success': False, 'error': f"Übergeordneter Ordner '{parent}' nicht gefunden"}), 404
        separator = parent_obj.separator or separator
        full_path = f"{parent}{separator}{name}"
    else:
        full_path = name

    existing = EmailFolder.query.filter_by(name=full_path).first()
    if existing:
        return jsonify({'success': False, 'error': f"Ordner '{full_path}' existiert bereits"}), 409

    result = imap_create_folder(full_path)
    if not result.get('success'):
        return jsonify({
            'success': False,
            'error': result.get('message'),
            'retryable': result.get('retryable', False),
        }), 502

    now = datetime.utcnow()
    new_folder = EmailFolder(
        name=full_path,
        display_name=name,
        folder_type='custom',
        is_system=False,
        parent_folder=parent or None,
        separator=separator,
        created_at=now,
        last_synced=now,
    )
    db.session.add(new_folder)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': result.get('message'),
        'folder': {
            'name': new_folder.name,
            'display_name': new_folder.display_name,
            'parent_folder': new_folder.parent_folder,
            'separator': new_folder.separator,
            'folder_type': new_folder.folder_type,
            'is_system': new_folder.is_system,
        },
    })


@email_bp.route('/folders/delete', methods=['POST', 'DELETE'])
@login_required
@check_module_access('module_email')
def delete_folder():
    """Delete a custom IMAP folder (folder name in JSON body or query param)."""
    if not check_email_permission('read'):
        return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403

    payload = request.get_json(silent=True) or {}
    folder_name = (
        payload.get('name')
        or request.values.get('name')
        or request.args.get('name')
        or ''
    ).strip()
    if not folder_name:
        return jsonify({'success': False, 'error': 'Ordnername fehlt'}), 400

    folder_obj = EmailFolder.query.filter_by(name=folder_name).first()
    if not folder_obj:
        return jsonify({'success': False, 'error': f"Ordner '{folder_name}' nicht gefunden"}), 404
    if folder_obj.is_system or folder_obj.folder_type == 'standard':
        return jsonify({'success': False, 'error': 'Systemordner können nicht gelöscht werden'}), 400

    force = bool(request.args.get('force') or payload.get('force'))

    contained_children = EmailFolder.query.filter_by(parent_folder=folder_name).count()
    contained_emails = EmailMessage.query.filter_by(folder=folder_name).count()
    if (contained_children or contained_emails) and not force:
        return jsonify({
            'success': False,
            'requires_confirmation': True,
            'error': f"Ordner enthält {contained_emails} E-Mails und {contained_children} Unterordner. Bestätigen Sie mit force=true.",
            'emails_count': contained_emails,
            'children_count': contained_children,
        }), 409

    result = imap_delete_folder(folder_name)
    if not result.get('success'):
        return jsonify({
            'success': False,
            'error': result.get('message'),
            'retryable': result.get('retryable', False),
        }), 502

    # Remove child folders and emails bound to this folder locally
    if contained_children:
        EmailFolder.query.filter_by(parent_folder=folder_name).delete(synchronize_session=False)
    if contained_emails:
        EmailMessage.query.filter_by(folder=folder_name).delete(synchronize_session=False)
    db.session.delete(folder_obj)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': result.get('message'),
        'folder': folder_name,
    })


def delete_email_from_imap(email_id, folder_name):
    """Delete email from IMAP server."""
    # Validiere email_id
    if not email_id:
        return False, "Ungültige E-Mail-ID (leer oder None)"
    
    # Konvertiere zu String und prüfe, ob es eine gültige UID ist
    try:
        uid_str = str(email_id).strip()
        if not uid_str or uid_str == 'None' or uid_str == '':
            return False, "Ungültige E-Mail-ID (leer)"
        # Prüfe, ob es eine Zahl ist (UIDs sind normalerweise Zahlen)
        int(uid_str)
    except (ValueError, AttributeError):
        return False, f"Ungültige E-Mail-ID Format: {email_id}"
    
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        status, messages = mail_conn.select(folder_name)
        if status != 'OK':
            mail_conn.logout()
            return False, f"Ordner '{folder_name}' konnte nicht geöffnet werden"
        
        # Versuche, die E-Mail als gelöscht zu markieren
        # Verwende UID STORE statt STORE, da wir mit UIDs arbeiten
        status, response = mail_conn.uid('STORE', uid_str, '+FLAGS', '\\Deleted')
        if status != 'OK':
            mail_conn.logout()
            error_msg = str(response) if response else "Unbekannter Fehler"
            return False, f"E-Mail konnte nicht als gelöscht markiert werden: {error_msg}"
        
        # Lösche die E-Mail endgültig
        status, response = mail_conn.expunge()
        if status != 'OK':
            mail_conn.logout()
            return False, f"E-Mail konnte nicht gelöscht werden: {response}"
        
        mail_conn.close()
        mail_conn.logout()
        return True, "E-Mail erfolgreich gelöscht"
        
    except Exception as e:
        try:
            mail_conn.logout()
        except:
            pass
        logging.error(f"IMAP delete failed: {str(e)}")
        return False, f"Lösch-Fehler: {str(e)}"


def move_email_in_imap(email_id, from_folder, to_folder):
    """Move email between IMAP folders."""
    # Validiere email_id
    if not email_id:
        return False, "Ungültige E-Mail-ID (leer oder None)"
    
    # Konvertiere zu String und prüfe, ob es eine gültige UID ist
    try:
        uid_str = str(email_id).strip()
        if not uid_str or uid_str == 'None' or uid_str == '':
            return False, "Ungültige E-Mail-ID (leer)"
        # Prüfe, ob es eine Zahl ist (UIDs sind normalerweise Zahlen)
        int(uid_str)
    except (ValueError, AttributeError):
        return False, f"Ungültige E-Mail-ID Format: {email_id}"
    
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        status, messages = mail_conn.select(from_folder)
        if status != 'OK':
            if from_folder != 'INBOX':
                status, messages = mail_conn.select('INBOX')
                if status != 'OK':
                    mail_conn.logout()
                    return False, f"Quellordner '{from_folder}' und INBOX konnten nicht geöffnet werden"
        
        # Verwende UID COPY statt COPY, da wir mit UIDs arbeiten
        status, response = mail_conn.uid('COPY', uid_str, to_folder)
        if status != 'OK':
            try:
                mail_conn.create(to_folder)
                status, response = mail_conn.uid('COPY', uid_str, to_folder)
                if status != 'OK':
                    mail_conn.logout()
                    return False, f"E-Mail konnte nicht nach '{to_folder}' kopiert werden (auch nach Ordner-Erstellung nicht)"
            except Exception as e:
                mail_conn.logout()
                return False, f"E-Mail konnte nicht nach '{to_folder}' kopiert werden: {str(e)}"
        
        # Verwende UID STORE statt STORE, da wir mit UIDs arbeiten
        status, response = mail_conn.uid('STORE', uid_str, '+FLAGS', '\\Deleted')
        if status != 'OK':
            mail_conn.logout()
            error_msg = str(response) if response else "Unbekannter Fehler"
            return False, f"E-Mail konnte nicht als gelöscht markiert werden: {error_msg}"
        
        status, response = mail_conn.expunge()
        if status != 'OK':
            mail_conn.logout()
            return False, f"E-Mail konnte nicht verschoben werden: {response}"
        
        mail_conn.close()
        mail_conn.logout()
        return True, f"E-Mail erfolgreich nach '{to_folder}' verschoben"
        
    except Exception as e:
        try:
            mail_conn.logout()
        except:
            pass
        logging.error(f"IMAP move failed: {str(e)}")
        return False, f"Verschieb-Fehler: {str(e)}"


# ---------------------------------------------------------------------------
# IMAP service operations (mail-manager Großupdate)
# Unified helpers that consolidate connect / select / execute / logout flows
# ---------------------------------------------------------------------------

SYSTEM_FOLDER_NAMES = {
    'INBOX', 'Sent', 'Sent Messages', 'Sent Items', 'Gesendet',
    'Gesendete Nachrichten', 'Drafts', 'Entwürfe',
    'Trash', 'Deleted Messages', 'Papierkorb',
    'Spam', 'Junk',
    'Archive', 'Archives', 'Archiv',
}

COLOR_DOT_CHOICES = {
    '': None,
    'none': None,
    'red': '$PrismaColorRed',
    'orange': '$PrismaColorOrange',
    'yellow': '$PrismaColorYellow',
    'green': '$PrismaColorGreen',
    'blue': '$PrismaColorBlue',
    'purple': '$PrismaColorPurple',
    'pink': '$PrismaColorPink',
    'gray': '$PrismaColorGray',
}


def _imap_error_payload(message, retryable=False, code=None):
    return {
        'success': False,
        'message': message,
        'retryable': retryable,
        'imap_status': code,
    }


def _imap_success_payload(message, extra=None):
    payload = {
        'success': True,
        'message': message,
        'imap_status': 'OK',
    }
    if extra:
        payload.update(extra)
    return payload


def _imap_select_folder(mail_conn, folder_name):
    """Select folder with fallback to quoted name. Returns (ok, status)."""
    try:
        status, _ = mail_conn.select(folder_name)
        if status == 'OK':
            return True, status
        try:
            status, _ = mail_conn.select(f'"{folder_name}"')
            if status == 'OK':
                return True, status
        except Exception:
            pass
        return False, status
    except Exception:
        return False, 'ERROR'


def _encode_imap_folder(name):
    """Encode folder path for IMAP LIST/CREATE/DELETE commands (IMAP UTF-7 simplified)."""
    # Our UI passes us UTF-8 strings; imaplib happily accepts them but quoting helps
    # with spaces or special characters.
    if name and (' ' in name or '/' in name or '.' in name):
        return f'"{name}"'
    return name


def imap_create_folder(folder_path):
    """Create an IMAP folder (supports nested paths with '/' or server separator)."""
    if not folder_path or not folder_path.strip():
        return _imap_error_payload("Ordnerpfad darf nicht leer sein")

    folder_path = folder_path.strip()

    mail_conn = connect_imap()
    if not mail_conn:
        return _imap_error_payload("IMAP-Verbindung fehlgeschlagen", retryable=True)

    try:
        encoded = _encode_imap_folder(folder_path)
        status, response = mail_conn.create(encoded)
        if status != 'OK':
            text = ''
            try:
                text = b''.join([r for r in response if isinstance(r, bytes)]).decode('utf-8', errors='ignore')
            except Exception:
                text = str(response)
            if 'ALREADYEXISTS' in text.upper() or 'already' in text.lower():
                return _imap_success_payload(f"Ordner '{folder_path}' existiert bereits")
            return _imap_error_payload(f"Ordner konnte nicht erstellt werden: {text}", code=status)

        # Subscribe to folder so it shows in IMAP clients
        try:
            mail_conn.subscribe(encoded)
        except Exception:
            pass

        return _imap_success_payload(f"Ordner '{folder_path}' erstellt")
    except Exception as e:
        logging.error(f"imap_create_folder failed: {e}")
        return _imap_error_payload(f"Ordnererstellung fehlgeschlagen: {str(e)}", retryable=True)
    finally:
        try:
            mail_conn.logout()
        except Exception:
            pass


def imap_delete_folder(folder_path):
    """Delete an IMAP folder (must be empty on most servers)."""
    if not folder_path or not folder_path.strip():
        return _imap_error_payload("Ordnerpfad darf nicht leer sein")
    folder_path = folder_path.strip()

    if folder_path in SYSTEM_FOLDER_NAMES:
        return _imap_error_payload("Systemordner können nicht gelöscht werden")

    mail_conn = connect_imap()
    if not mail_conn:
        return _imap_error_payload("IMAP-Verbindung fehlgeschlagen", retryable=True)

    try:
        encoded = _encode_imap_folder(folder_path)
        try:
            mail_conn.unsubscribe(encoded)
        except Exception:
            pass
        status, response = mail_conn.delete(encoded)
        if status != 'OK':
            text = ''
            try:
                text = b''.join([r for r in response if isinstance(r, bytes)]).decode('utf-8', errors='ignore')
            except Exception:
                text = str(response)
            return _imap_error_payload(f"Ordner konnte nicht gelöscht werden: {text}", code=status)
        return _imap_success_payload(f"Ordner '{folder_path}' gelöscht")
    except Exception as e:
        logging.error(f"imap_delete_folder failed: {e}")
        return _imap_error_payload(f"Ordnerlöschung fehlgeschlagen: {str(e)}", retryable=True)
    finally:
        try:
            mail_conn.logout()
        except Exception:
            pass


def imap_move_message(uid, from_folder, to_folder):
    """Move a message (thin wrapper around move_email_in_imap returning structured payload)."""
    if not uid:
        return _imap_error_payload("Ungültige IMAP-UID")
    if not to_folder:
        return _imap_error_payload("Zielordner fehlt")
    ok, msg = move_email_in_imap(uid, from_folder or 'INBOX', to_folder)
    if ok:
        return _imap_success_payload(msg)
    retryable = 'Verbindung' in (msg or '')
    return _imap_error_payload(msg, retryable=retryable)


def imap_mark_seen(uid, folder, seen=True):
    """Mark a message as seen/unseen on IMAP."""
    if not uid:
        return _imap_error_payload("Ungültige IMAP-UID")
    try:
        uid_str = str(uid).strip()
        int(uid_str)
    except (ValueError, AttributeError):
        return _imap_error_payload(f"Ungültige UID: {uid}")

    mail_conn = connect_imap()
    if not mail_conn:
        return _imap_error_payload("IMAP-Verbindung fehlgeschlagen", retryable=True)

    try:
        ok, status = _imap_select_folder(mail_conn, folder or 'INBOX')
        if not ok:
            return _imap_error_payload(f"Ordner '{folder}' konnte nicht geöffnet werden", code=status)
        flag_op = '+FLAGS' if seen else '-FLAGS'
        status, response = mail_conn.uid('STORE', uid_str, flag_op, '\\Seen')
        if status != 'OK':
            return _imap_error_payload(
                f"Gelesen-Status konnte nicht aktualisiert werden: {response}",
                code=status,
            )
        return _imap_success_payload("Gelesen-Status aktualisiert")
    except Exception as e:
        logging.error(f"imap_mark_seen failed: {e}")
        return _imap_error_payload(f"Gelesen-Status-Fehler: {str(e)}", retryable=True)
    finally:
        try:
            mail_conn.close()
        except Exception:
            pass
        try:
            mail_conn.logout()
        except Exception:
            pass


def imap_set_keyword(uid, folder, keyword, enabled=True):
    """Add/remove a custom IMAP keyword. Returns success payload even when server
    rejects the keyword (treat as local-only) so the caller can fall back cleanly."""
    if not uid:
        return _imap_error_payload("Ungültige IMAP-UID")
    if not keyword:
        return _imap_error_payload("Kein Schlüsselwort angegeben")

    try:
        uid_str = str(uid).strip()
        int(uid_str)
    except (ValueError, AttributeError):
        return _imap_error_payload(f"Ungültige UID: {uid}")

    mail_conn = connect_imap()
    if not mail_conn:
        return _imap_error_payload("IMAP-Verbindung fehlgeschlagen", retryable=True)

    try:
        ok, status = _imap_select_folder(mail_conn, folder or 'INBOX')
        if not ok:
            return _imap_error_payload(f"Ordner '{folder}' konnte nicht geöffnet werden", code=status)
        flag_op = '+FLAGS' if enabled else '-FLAGS'
        status, response = mail_conn.uid('STORE', uid_str, flag_op, keyword)
        if status != 'OK':
            # Keyword unsupported: return soft payload so caller keeps local state only
            return {
                'success': True,
                'imap_status': status,
                'message': 'Server unterstützt Keyword nicht, lokal gespeichert',
                'keyword_supported': False,
            }
        return {
            'success': True,
            'imap_status': 'OK',
            'message': 'Keyword aktualisiert',
            'keyword_supported': True,
        }
    except Exception as e:
        logging.error(f"imap_set_keyword failed: {e}")
        return {
            'success': True,
            'imap_status': 'ERROR',
            'message': f'Keyword nicht unterstützt: {str(e)} – lokal gespeichert',
            'keyword_supported': False,
        }
    finally:
        try:
            mail_conn.close()
        except Exception:
            pass
        try:
            mail_conn.logout()
        except Exception:
            pass


# SSE-basierte Live-Updates (siehe app/blueprints/sse.py)
# Socket.IO wurde durch Server-Sent Events ersetzt für bessere Multi-Worker-Kompatibilität


def email_sync_scheduler(app):
    """Background thread for automatic email synchronization every 15 minutes."""
    logger.info("E-Mail-Sync-Scheduler Thread gestartet, warte 30 Sekunden vor erster Synchronisation...")
    # Warte 30 Sekunden nach App-Start, bevor die erste Synchronisation startet
    time.sleep(30)
    
    while True:
        lock_acquired = False
        try:
            with app.app_context():
                # Non-blocking: Leader-Thread wartet nicht hinter manuellem Sync
                with acquire_email_sync_lock(timeout=0) as acquired:
                    lock_acquired = acquired
                    if acquired:
                        try:
                            success, message = sync_all_configured_mailboxes()
                            if success:
                                logger.debug("Auto-sync: %s", message)
                            else:
                                logger.error("Auto-sync failed: %s", message)
                        except Exception as sync_error:
                            logger.error(f"Fehler während der Synchronisation: {sync_error}", exc_info=True)
                    else:
                        logger.debug("E-Mail-Synchronisation wird bereits von anderem Worker durchgeführt, überspringe...")
        except Exception as e:
            logger.error(f"E-Mail-Sync-Scheduler Fehler: {e}", exc_info=True)
        finally:
            if lock_acquired:
                logger.debug("E-Mail-Synchronisation abgeschlossen, warte 15 Minuten bis zur nächsten...")
        
        # Nach jeder Synchronisation 15 Minuten warten
        time.sleep(900)


sync_thread = None
_sync_started = False
_sync_lock = threading.Lock()
_email_sync_leader = None
_leader_heartbeat_stop = threading.Event()


def _leader_heartbeat_loop():
    """Hält email_sync_leader-Lock frisch (Stale-Detection)."""
    while not _leader_heartbeat_stop.wait(30):
        held = _email_sync_leader
        if held is None:
            break
        try:
            held.heartbeat()
        except Exception as e:
            logging.debug("Leader-Heartbeat fehlgeschlagen: %s", e)


def start_email_sync(app):
    """Start the background email synchronization thread (nur ein Worker = Leader)."""
    global sync_thread, _sync_started, _email_sync_leader
    
    # Prüfe zuerst, ob bereits ein Thread mit diesem Namen läuft (auch nach Reload)
    existing_threads = [t for t in threading.enumerate() if t.name == "email-sync-scheduler" and t.is_alive()]
    if existing_threads:
        logger.debug(
            "E-Mail-Sync-Thread läuft bereits (gefunden %s Thread(s)), überspringe Neustart",
            len(existing_threads),
        )
        return
    
    from pathlib import Path
    lock_dir = str(Path(app.instance_path) / 'locks')
    
    # Verwende Lock, um Thread-Erstellung zu synchronisieren
    with _sync_lock:
        # Doppelte Prüfung innerhalb des Locks
        existing_threads = [t for t in threading.enumerate() if t.name == "email-sync-scheduler" and t.is_alive()]
        if existing_threads:
            logger.debug(
                "E-Mail-Sync-Thread läuft bereits (zweite Prüfung, %s Thread(s)), überspringe Neustart",
                len(existing_threads),
            )
            return
        
        if _sync_started:
            logger.debug("E-Mail-Sync-Thread wird bereits gestartet, überspringe Neustart")
            return

        leader = try_acquire_email_sync_leader(lock_dir=lock_dir)
        if leader is None:
            logger.info("E-Mail-Sync-Leader bereits aktiv — dieser Worker startet keinen Scheduler")
            return

        _email_sync_leader = leader
        _leader_heartbeat_stop.clear()
        hb_thread = threading.Thread(
            target=_leader_heartbeat_loop,
            daemon=True,
            name="email-sync-leader-hb",
        )
        hb_thread.start()
        
        _sync_started = True
        sync_thread = threading.Thread(target=email_sync_scheduler, args=(app,), daemon=True, name="email-sync-scheduler")
        sync_thread.start()
        logger.info("E-Mail Auto-Sync gestartet (Leader, alle 15 Minuten)")
