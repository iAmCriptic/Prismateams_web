"""HTML/iframe/footer/quote rendering for the email module."""

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

from app.blueprints.email.imap_client import connect_imap, decode_header_field

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
    """Strip scripts, handlers and risky embeds before iframe srcdoc (XSS mitigation)."""
    if not html:
        return html
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<script\b[^>]*/>', '', html, flags=re.IGNORECASE)
    html = re.sub(
        r'<(iframe|object|embed|applet|form)\b[^>]*>.*?</\1>',
        '',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r'<(iframe|object|embed|applet|form)\b[^>]*/?>',
        '',
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r'<meta\b[^>]*http-equiv\s*=\s*["\']?refresh[^>]*>',
        '',
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(r'\s+on\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', html, flags=re.IGNORECASE)
    html = re.sub(
        r'\s+(href|src|xlink:href|action)\s*=\s*["\']?\s*javascript:[^"\'>\s]*["\']?',
        ' href="#"',
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r'\s+srcdoc\s*=\s*("[^"]*"|\'[^\']*\')',
        '',
        html,
        flags=re.IGNORECASE,
    )
    return html


def sanitize_email_inline_html(html: str) -> str:
    """Bleach-Sanitize für Inline-|safe-Darstellung im Portal-DOM."""
    if not html:
        return html
    try:
        import bleach

        # Kein CSSSanitizer/tinycss2 nötig: Style-Attribute und <style> entfernen.
        html = re.sub(r'<style\b[^>]*>.*?</style>', '', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\s+style\s*=\s*("[^"]*"|\'[^\']*\')', '', html, flags=re.IGNORECASE)
        html = re.sub(r'\s+on\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', html, flags=re.IGNORECASE)

        allowed_tags = {
            'a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'code', 'col', 'colgroup',
            'div', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li',
            'ol', 'p', 'pre', 'span', 'strong', 'sub', 'sup', 'table', 'tbody', 'td',
            'tfoot', 'th', 'thead', 'tr', 'u', 'ul', 'font', 'center',
        }
        allowed_attributes = {
            '*': ['class', 'id', 'align', 'dir', 'lang'],
            'a': ['href', 'title', 'target', 'rel'],
            'img': ['src', 'alt', 'title', 'width', 'height'],
            'table': ['width', 'border', 'cellpadding', 'cellspacing', 'bgcolor'],
            'td': ['colspan', 'rowspan', 'width', 'height', 'bgcolor', 'valign'],
            'th': ['colspan', 'rowspan', 'width', 'height', 'bgcolor', 'valign'],
            'col': ['width', 'span'],
            'colgroup': ['span'],
            'font': ['color', 'face', 'size'],
        }
        return bleach.clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attributes,
            protocols=['http', 'https', 'mailto', 'cid', 'data'],
            strip=True,
            strip_comments=True,
        )
    except Exception as exc:
        logging.error('sanitize_email_inline_html failed: %s', exc)
        from markupsafe import escape
        return f'<div class="email-content-isolated-inner">{escape(html)}</div>'


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

    return sanitize_email_inline_html(html_content)


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
    logo_bytes, logo_mime, _ = get_mailbox_logo_data(
        mailbox, user=logo_user, use_logo=use_mailbox_logo
    )
    logo_base64 = None
    if logo_bytes:
        import base64 as _b64
        mime = logo_mime or 'image/png'
        logo_base64 = f"data:{mime};base64,{_b64.b64encode(logo_bytes).decode('ascii')}"
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
