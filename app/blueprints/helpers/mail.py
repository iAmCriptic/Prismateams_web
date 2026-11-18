"""E-Mail-Vorlagen und Versand für das Modul Helferverwaltung."""

from __future__ import annotations

import re

from flask import current_app

from app.services.helpers_service import calculate_event_vouchers


def build_helper_placeholders(event, helper):
    """Erstellt Platzhalter-Dictionary für die Helfer-Schichtplan-Mail."""
    shift_vouchers, helper_vouchers = calculate_event_vouchers(event)
    v_info = helper_vouchers.get(helper.id, {'food': 0, 'drinks': 0, 'hours': 0.0})

    lines = []
    for s in helper.shifts:
        area_name = s.area.name if s.area else '—'
        date_str = s.date.strftime('%d.%m.%Y') if s.date else ''
        time_str = f'{s.start_time or ""}' + (f'–{s.end_time}' if s.end_time else '')
        role_str = f' ({s.role_label})' if s.role_label else ''
        sv = shift_vouchers.get(s.id, {'food': 0, 'drinks': 0})
        parts = [p for p in (s.day_label, date_str, time_str) if p]
        lines.append(
            f'- {" ".join(parts)}: {area_name}{role_str} | {s.hours} Std. '
            f'(Essen: {sv["food"]}, Getränke: {sv["drinks"]})'
        )

    shifts_list = '\n'.join(lines) if lines else 'Noch keine Schichten zugewiesen.'

    return {
        'first_name': helper.first_name or '',
        'last_name': helper.last_name or '',
        'full_name': helper.full_name,
        'email': helper.email or '',
        'phone': helper.phone or '',
        'tshirt_size': helper.tshirt_size or '—',
        'allergies': helper.allergies or 'Keine',
        'event_name': event.name or '',
        'total_hours': str(round(v_info.get('hours', 0.0), 2)),
        'food_vouchers': str(v_info.get('food', 0)),
        'drinks_vouchers': str(v_info.get('drinks', 0)),
        'shifts_list': shifts_list,
    }


def render_helper_mail(template_text, placeholders):
    if not template_text:
        return ''

    def replace(match):
        key = match.group(1).strip()
        return placeholders.get(key, match.group(0))

    return re.sub(r'@?\{\{\s*([a-zA-Z0-9_\-]+)\s*\}\}', replace, template_text)


def send_helper_schedule_mail(event, helper):
    """Sendet dem Helfer seinen Schichtplan & Details per E-Mail."""
    from flask_mail import Message
    from app import mail

    if not helper.email:
        raise ValueError('Keine E-Mail-Adresse hinterlegt.')

    placeholders = build_helper_placeholders(event, helper)
    subject = render_helper_mail(
        event.mail_template_subject or 'Dein Schichtplan für {{ event_name }}',
        placeholders,
    )
    body_text = render_helper_mail(
        event.mail_template_body or '{{ shifts_list }}',
        placeholders,
    )

    mailbox = event.mailbox if event.mailbox_id else None
    if mailbox and mailbox.is_active:
        from app.blueprints.email.compose import _send_flask_message_via_smtp
        from app.utils.multi_mailboxes import get_mailbox_smtp_config

        smtp_cfg = get_mailbox_smtp_config(mailbox)
        sender_email = mailbox.smtp_username or mailbox.name
        if '@' not in (sender_email or '') and mailbox.display_name and '@' in mailbox.display_name:
            sender_email = mailbox.display_name
        sender = (mailbox.display_name, sender_email) if mailbox.display_name else sender_email

        msg = Message(
            subject=subject,
            sender=sender,
            recipients=[helper.email],
            body=body_text,
        )
        _send_flask_message_via_smtp(msg, smtp_cfg)
        return True

    sender = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME')
    msg = Message(
        subject=subject,
        sender=sender,
        recipients=[helper.email],
        body=body_text,
    )
    mail.send(msg)
    return True
