import re
from flask import current_app, url_for
from app import db
from app.models.email import Mailbox
from app.models.booking_personal import BookingPersonalEvent, BookingPersonalEntry


def get_available_placeholders(event, entry=None):
    """Gibt ein Dictionary aller verfügbaren Platzhalter für ein Event/Eintrag zurück."""
    base_url = current_app.config.get('BASE_URL', '').rstrip('/')

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


def send_booking_personal_mail(event, entry, recipient_email, subject, body_text):
    """
    Versendet eine E-Mail über das mit dem Event verknüpfte Postfach (Mailbox)
    oder fällt auf den Flask-Mail-Standardmailer zurück.
    """
    from flask_mail import Message
    from app import mail

    mailbox = event.mailbox if event.mailbox_id else None

    # Falls eine Mailbox zugewiesen ist, verwende deren SMTP-Konfiguration
    if mailbox and mailbox.is_active:
        from app.utils.multi_mailboxes import get_mailbox_smtp_config
        from app.blueprints.email.compose import _send_flask_message_via_smtp

        smtp_cfg = get_mailbox_smtp_config(mailbox)
        sender_email = mailbox.smtp_username or mailbox.name
        if '@' not in sender_email and mailbox.display_name and '@' in mailbox.display_name:
            sender_email = mailbox.display_name
        msg = Message(
            subject=subject,
            sender=(mailbox.display_name, sender_email),
            recipients=[recipient_email],
            body=body_text
        )
        _send_flask_message_via_smtp(msg, smtp_cfg)
    else:
        msg = Message(
            subject=subject,
            recipients=[recipient_email],
            body=body_text
        )
        mail.send(msg)
