"""Helpers for booking request e-mail message threads."""

from __future__ import annotations

import logging
import re
import uuid
from email.utils import parseaddr

from flask import current_app

from app import db

BOOKING_SUBJECT_RE = re.compile(r'\[Buchung\s*#(\d+)\]', re.IGNORECASE)


def normalize_message_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if not value.startswith('<'):
        value = f'<{value}>'
    return value


def extract_email_address(raw: str | None) -> str:
    if not raw:
        return ''
    _, addr = parseaddr(raw)
    return (addr or raw).strip()


def booking_subject_tag(request_id: int) -> str:
    return f'[Buchung #{request_id}]'


def ensure_booking_subject(subject: str, request_id: int) -> str:
    subject = (subject or '').strip()
    tag = booking_subject_tag(request_id)
    if tag.lower() in subject.lower():
        return subject
    if subject:
        return f'{subject} {tag}'
    return tag


def generate_booking_message_id(request_id: int) -> str:
    mail_user = (current_app.config.get('MAIL_USERNAME') or 'booking@localhost').strip()
    domain = mail_user.split('@')[-1] if '@' in mail_user else 'localhost'
    return f'<booking-{request_id}-{uuid.uuid4().hex}@{domain}>'


def get_thread_headers(booking_request) -> dict:
    """Build In-Reply-To / References from last outbound message."""
    from app.models.booking import BookingRequestMessage

    last = (
        BookingRequestMessage.query
        .filter_by(request_id=booking_request.id)
        .filter(BookingRequestMessage.message_id.isnot(None))
        .order_by(BookingRequestMessage.created_at.desc())
        .first()
    )
    if not last or not last.message_id:
        return {}

    mid = normalize_message_id(last.message_id)
    headers = {'In-Reply-To': mid, 'References': mid}
    return headers


def apply_thread_headers(msg, booking_request, message_id: str | None = None) -> str:
    """Set Message-ID and reply headers on a Flask-Mail Message. Returns message_id used."""
    message_id = normalize_message_id(message_id) or generate_booking_message_id(booking_request.id)
    if not hasattr(msg, 'extra_headers') or msg.extra_headers is None:
        msg.extra_headers = {}
    msg.extra_headers['Message-ID'] = message_id

    thread = get_thread_headers(booking_request)
    for key, value in thread.items():
        msg.extra_headers[key] = value

    # Keep Flask-Mail's msgId in sync if present
    try:
        msg.msgId = message_id
    except Exception:
        pass

    return message_id


def save_outbound_message(
    booking_request,
    *,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    message_id: str,
    in_reply_to: str | None = None,
    from_email: str | None = None,
    created_by: int | None = None,
):
    from app.models.booking import BookingRequestMessage
    from config import get_formatted_sender

    row = BookingRequestMessage(
        request_id=booking_request.id,
        direction='outbound',
        subject=subject,
        body_text=body_text or '',
        body_html=body_html,
        from_email=from_email or extract_email_address(get_formatted_sender() or current_app.config.get('MAIL_USERNAME')),
        to_email=booking_request.email,
        message_id=normalize_message_id(message_id),
        in_reply_to=normalize_message_id(in_reply_to),
        is_read=True,
        created_by=created_by,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _collect_reference_ids(email_msg) -> list[str]:
    ids = []
    for header in ('In-Reply-To', 'References'):
        raw = email_msg.get(header) or ''
        for part in re.findall(r'<[^>]+>', raw):
            mid = normalize_message_id(part)
            if mid and mid not in ids:
                ids.append(mid)
        # bare ids without brackets
        if raw and '<' not in raw:
            mid = normalize_message_id(raw.split()[0])
            if mid and mid not in ids:
                ids.append(mid)
    return ids


def resolve_booking_request_for_inbound(email_msg, message_id: str | None = None):
    """Find BookingRequest for an inbound mail via Message-ID chain or subject tag."""
    from app.models.booking import BookingRequest, BookingRequestMessage

    mid = normalize_message_id(message_id or email_msg.get('Message-ID'))
    if mid:
        existing = BookingRequestMessage.query.filter_by(message_id=mid).first()
        if existing:
            return existing.request, 'existing_message_id'

    for ref in _collect_reference_ids(email_msg):
        parent = BookingRequestMessage.query.filter_by(message_id=ref).first()
        if parent:
            return parent.request, 'in_reply_to'

    subject = email_msg.get('Subject') or ''
    match = BOOKING_SUBJECT_RE.search(subject)
    if match:
        request_id = int(match.group(1))
        booking_request = BookingRequest.query.get(request_id)
        if booking_request:
            return booking_request, 'subject_tag'

    return None, None


def try_route_inbound_email(
    email_msg,
    *,
    message_id: str,
    sender: str,
    subject: str,
    recipients: str,
    body_text: str,
    body_html: str,
) -> bool:
    """
    If this mail belongs to a booking thread, store as BookingRequestMessage
    and return True (caller should NOT create EmailMessage for inbox).
    """
    from app.models.booking import BookingRequestMessage

    mid = normalize_message_id(message_id)
    if mid and BookingRequestMessage.query.filter_by(message_id=mid).first():
        # Already stored (e.g. our own outbound mirrored in Sent) — keep out of inbox
        logging.info(f"Skipping inbox for known booking message_id {mid}")
        return True

    booking_request, reason = resolve_booking_request_for_inbound(email_msg, mid)
    if not booking_request:
        return False

    # Don't treat Sent-folder echoes without In-Reply-To as inbound guest mail unless subject matched
    refs = _collect_reference_ids(email_msg)
    if not refs and reason == 'subject_tag':
        # Still allow subject-tag matching for clients that drop headers
        pass

    in_reply_to = normalize_message_id((email_msg.get('In-Reply-To') or '').split()[0] if email_msg.get('In-Reply-To') else None)
    if not in_reply_to and refs:
        in_reply_to = refs[0]

    row = BookingRequestMessage(
        request_id=booking_request.id,
        direction='inbound',
        subject=subject,
        body_text=body_text or '',
        body_html=body_html or None,
        from_email=extract_email_address(sender),
        to_email=extract_email_address(recipients),
        message_id=mid,
        in_reply_to=in_reply_to,
        is_read=False,
    )
    db.session.add(row)
    try:
        db.session.commit()
        logging.info(
            f"Routed inbound email to booking request {booking_request.id} via {reason} "
            f"(message_id={mid})"
        )
        try:
            from app.utils.notifications import send_booking_message_notification
            send_booking_message_notification(booking_request, row)
        except Exception as notify_error:
            logging.error(f"Booking message notification failed: {notify_error}")
        return True
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to route booking inbound email: {e}")
        # If duplicate message_id, still suppress inbox
        if mid and BookingRequestMessage.query.filter_by(message_id=mid).first():
            return True
        return False


def unread_inbound_count(request_id: int) -> int:
    from app.models.booking import BookingRequestMessage

    return (
        BookingRequestMessage.query
        .filter_by(request_id=request_id, direction='inbound', is_read=False)
        .count()
    )


def mark_messages_read(request_id: int) -> None:
    from app.models.booking import BookingRequestMessage

    (
        BookingRequestMessage.query
        .filter_by(request_id=request_id, direction='inbound', is_read=False)
        .update({'is_read': True})
    )
    db.session.commit()
