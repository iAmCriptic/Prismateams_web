import re
from flask import current_app, url_for
from app import db
from app.models.email import Mailbox
from app.models.booking_personal import BookingPersonalEvent, BookingPersonalEntry


def get_available_placeholders(event, entry):
    """Gibt ein Dictionary aller verfügbaren Platzhalter für ein Event/Eintrag zurück."""
    base_url = current_app.config.get('BASE_URL', '').rstrip('/')
    
    # Formular-Link
    form_rel = url_for('booking_personal.public_form', token=entry.form_token)
    form_link = f"{base_url}{form_rel}" if base_url else form_rel

    # Zusage-Übersichtslink
    overview_rel = url_for('booking_personal.public_overview', token=entry.overview_token)
    overview_link = f"{base_url}{overview_rel}" if base_url else overview_rel

    custom = entry.get_custom_data()

    placeholders = {
        'act_name': entry.name or custom.get('project_name') or 'Künstler/Act',
        'name': entry.name or custom.get('project_name') or 'Künstler/Act',
        'contact_name': custom.get('contact_name') or entry.name or 'Künstler/Ansprechpartner',
        'event_name': event.name or 'Veranstaltung',
        'email': entry.email or custom.get('mail') or '',
        'phone': entry.phone or custom.get('phone') or '',
        'gage': custom.get('gage') or '€0.00',
        'area': custom.get('bereich') or '',
        'bereich': custom.get('bereich') or '',
        'form_link': form_link,
        'overview_link': overview_link,
    }

    # Beliebige Custom-Field-Keys ergänzen
    for k, v in custom.items():
        if k not in placeholders:
            placeholders[k] = str(v) if v is not None else ''

    return placeholders


def render_template_string(template_text, placeholders):
    """Ersetzt {{ key }} durch den entsprechenden Wert."""
    if not template_text:
        return ''
    
    def replace(match):
        key = match.group(1).strip()
        return placeholders.get(key, match.group(0))

    return re.sub(r'\{\{\s*([a-zA-Z0-9_\-]+)\s*\}\}', replace, template_text)


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

