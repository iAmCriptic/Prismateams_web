import html
import os
import re
from flask import current_app, has_request_context, request, url_for
from app.models.booking_personal import BookingPersonalEvent, BookingPersonalEntry


_URL_PATTERN = re.compile(
    r'(?P<url>(?:https?://|mailto:)[^\s<>"\']+|www\.[^\s<>"\']+)',
    re.IGNORECASE,
)
_TRAILING_PUNCT = '.,;:!?)]}\'"'


def _resolve_base_url():
    """Ermittelt die externe Basis-URL für anklickbare Links in E-Mails."""
    raw = (
        current_app.config.get('BASE_URL')
        or current_app.config.get('PUBLIC_BASE_URL')
        or (request.url_root if has_request_context() else '')
        or ''
    )
    return str(raw).strip().rstrip('/')


def get_available_placeholders(event, entry=None):
    """Gibt ein Dictionary aller verfügbaren Platzhalter für ein Event/Eintrag zurück."""
    base_url = _resolve_base_url()

    form_link = ''
    overview_link = ''
    custom = {}
    if entry:
        if getattr(entry, 'form_token', None):
            form_rel = url_for('booking_personal.public_form', token=entry.form_token)
            form_link = f"{base_url}{form_rel}" if base_url else form_rel
        if getattr(entry, 'overview_token', None):
            overview_rel = url_for('booking_personal.public_overview', token=entry.overview_token)
            overview_link = f"{base_url}{overview_rel}" if base_url else overview_rel
        custom = entry.get_custom_data() if hasattr(entry, 'get_custom_data') else {}
    else:
        form_link = f"{base_url}/booking-personal/form/BEISPIEL-TOKEN" if base_url else "/booking-personal/form/BEISPIEL-TOKEN"
        overview_link = f"{base_url}/booking-personal/overview/BEISPIEL-TOKEN" if base_url else "/booking-personal/overview/BEISPIEL-TOKEN"

    placeholders = {
        'act_name': (entry.name if entry else '') or custom.get('project_name') or 'Künstler/Act',
        'name': (entry.name if entry else '') or custom.get('project_name') or 'Künstler/Act',
        'contact_name': custom.get('contact_name') or (entry.name if entry else '') or 'Künstler/Ansprechpartner',
        'event_name': (event.name if event else '') or 'Veranstaltung',
        'email': (entry.email if entry else '') or custom.get('mail') or 'artist@example.com',
        'phone': (entry.phone if entry else '') or custom.get('phone') or '+49 123 456789',
        'gage': custom.get('gage') or '€0.00',
        'area': custom.get('bereich') or 'Main Stage',
        'bereich': custom.get('bereich') or 'Main Stage',
        'form_link': form_link,
        'overview_link': overview_link,
    }

    # Beliebige Custom-Field-Keys ergänzen
    if custom:
        for k, v in custom.items():
            if k not in placeholders:
                placeholders[k] = str(v) if v is not None else ''

    return placeholders


def render_template_string(template_text, placeholders):
    """Ersetzt {{ key }} oder @{{ key }} durch den entsprechenden Wert."""
    if not template_text:
        return ''

    def replace(match):
        key = match.group(1).strip()
        return placeholders.get(key, match.group(0))

    return re.sub(r'@?\{\{\s*([a-zA-Z0-9_\-]+)\s*\}\}', replace, template_text)


def _linkify_escaped_text(escaped_text):
    """Wandelt URLs in bereits HTML-escaptem Text in anklickbare <a>-Links um."""
    def _replace(match):
        raw = match.group('url')
        trimmed = raw.rstrip(_TRAILING_PUNCT)
        trailing = raw[len(trimmed):]
        if not trimmed:
            return raw
        href = trimmed if trimmed.lower().startswith(('http://', 'https://', 'mailto:')) else f'https://{trimmed}'
        return (
            f'<a href="{href}" target="_blank" rel="noopener noreferrer" '
            f'style="color: #0369a1; text-decoration: underline; word-break: break-all;">'
            f'{trimmed}</a>{trailing}'
        )

    return _URL_PATTERN.sub(_replace, escaped_text)


def plain_text_to_email_html(body_text):
    """Formatiert Klartext-Nachricht als HTML-Absätze mit anklickbaren Links."""
    normalized = (body_text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not normalized:
        return ''

    paragraphs = re.split(r'\n{2,}', normalized)
    html_parts = []
    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        escaped = html.escape(stripped, quote=True)
        linked = _linkify_escaped_text(escaped)
        html_parts.append(f'<p>{linked.replace(chr(10), "<br>")}</p>')
    return ''.join(html_parts)


def get_event_logo_data(event):
    """
    Lädt das Event-Logo (header_image_path) von der Festplatte.
    Gibt (bytes, mime_type, is_event_logo) zurück oder fällt auf das Portal-Logo zurück.
    """
    mime_types = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
    }

    rel_url = getattr(event, 'header_image_path', None) if event is not None else None
    if rel_url and str(rel_url).startswith('/uploads/'):
        upload_root = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        project_root = os.path.dirname(current_app.root_path)
        rel = str(rel_url).replace('/uploads/', '', 1).lstrip('/')
        disk_candidates = [
            os.path.join(upload_root, rel),
            os.path.join(project_root, upload_root, rel),
        ]
        for disk_path in disk_candidates:
            if os.path.isfile(disk_path):
                try:
                    with open(disk_path, 'rb') as f:
                        data = f.read()
                    if data:
                        ext = os.path.splitext(disk_path)[1].lower()
                        return data, mime_types.get(ext, 'image/png'), True
                except Exception:
                    pass

    from app.utils.email_sender import get_logo_data
    portal_data, portal_mime, _ = get_logo_data()
    return portal_data, portal_mime, False


def send_booking_personal_mail(event, entry, recipient_email, subject, body_text):
    """
    Versendet eine E-Mail im Portal-HTML-Design (mit Event-Logo und anklickbaren Links)
    über das mit dem Event verknüpfte Postfach (Mailbox) oder das Hauptpostfach.
    """
    from flask_mail import Message
    from app.utils.email_sender import render_portal_email
    from app.blueprints.email.compose import _send_flask_message_via_smtp

    logo_data, logo_mime_type, is_event_logo = get_event_logo_data(event)
    logo_cid = ('event_logo' if is_event_logo else 'portal_logo') if (logo_data and logo_mime_type) else None

    body_html = plain_text_to_email_html(body_text)
    html_content, _ = render_portal_email(
        'emails/custom_mail.html',
        body_html=body_html,
        subject=subject,
        logo_cid=logo_cid,
        recipient_email=recipient_email,
        recipient_name=(entry.name if entry else None),
    )

    mailbox = event.mailbox if (event and event.mailbox_id) else None

    if mailbox and mailbox.is_active:
        from app.utils.multi_mailboxes import get_mailbox_smtp_config

        smtp_cfg = get_mailbox_smtp_config(mailbox)
        sender_email = mailbox.smtp_username or mailbox.name
        if '@' not in sender_email and mailbox.display_name and '@' in mailbox.display_name:
            sender_email = mailbox.display_name
        sender = (mailbox.display_name, sender_email)
    else:
        from app.utils.multi_mailboxes import get_main_smtp_config

        smtp_cfg = get_main_smtp_config()
        sender = smtp_cfg.get('sender') or smtp_cfg.get('user')

    msg = Message(
        subject=subject,
        sender=sender,
        recipients=[recipient_email],
        body=body_text,
        html=html_content,
    )

    if logo_data and logo_mime_type and logo_cid:
        ext_map = {
            'image/png': 'png',
            'image/jpeg': 'jpg',
            'image/gif': 'gif',
            'image/webp': 'webp',
            'image/svg+xml': 'svg',
        }
        ext = ext_map.get(logo_mime_type, 'png')
        msg.attach(
            f'{logo_cid}.{ext}',
            logo_mime_type,
            logo_data,
            disposition='inline',
            headers={'Content-ID': f'<{logo_cid}>'},
        )

    _send_flask_message_via_smtp(msg, smtp_cfg)
