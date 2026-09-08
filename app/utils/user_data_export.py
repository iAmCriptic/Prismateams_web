"""Build a machine-readable personal-data export for a single user (Art. 20).

Secrets (password hash, TOTP, recovery codes, raw session IDs, credential
material) are never included. Large binary assets are listed as metadata only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app import db


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_section(name: str, builder) -> dict[str, Any]:
    try:
        return {name: builder()}
    except Exception as exc:
        return {name: {"_error": type(exc).__name__, "_detail": str(exc)[:200]}}


def build_user_data_export(user) -> dict[str, Any]:
    """Collect user-scoped personal data into a JSON-serializable dict."""
    payload: dict[str, Any] = {
        "export_meta": {
            "schema": "prismateams.user_data_export.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user.id,
            "note": (
                "This archive contains personal data associated with your account. "
                "Secrets (passwords, 2FA secrets, session tokens) are excluded. "
                "File contents are listed as metadata only."
            ),
        }
    }

    payload.update(_safe_section("profile", lambda: _export_profile(user)))
    payload.update(_safe_section("teams", lambda: _export_teams(user)))
    payload.update(_safe_section("sessions", lambda: _export_sessions(user)))
    payload.update(_safe_section("cookie_consent", lambda: _export_cookie_consent(user)))
    payload.update(_safe_section("passkeys", lambda: _export_passkeys(user)))
    payload.update(_safe_section("api_tokens", lambda: _export_api_tokens(user)))
    payload.update(_safe_section("notifications", lambda: _export_notifications(user)))
    payload.update(_safe_section("contacts", lambda: _export_contacts(user)))
    payload.update(_safe_section("calendar", lambda: _export_calendar(user)))
    payload.update(_safe_section("files", lambda: _export_files(user)))
    payload.update(_safe_section("chat", lambda: _export_chat(user)))
    payload.update(_safe_section("bookings", lambda: _export_bookings(user)))
    payload.update(_safe_section("inventory", lambda: _export_inventory(user)))
    payload.update(_safe_section("surveys", lambda: _export_surveys(user)))

    return payload


def export_user_data_json_bytes(user) -> bytes:
    data = build_user_data_export(user)
    return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _export_profile(user) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "profile_picture": user.profile_picture,
        "language": user.language,
        "preferred_layout": user.preferred_layout,
        "dark_mode": bool(user.dark_mode),
        "oled_mode": bool(getattr(user, "oled_mode", False)),
        "accent_color": user.accent_color,
        "accent_gradient": user.accent_gradient,
        "is_active": bool(user.is_active),
        "is_admin": bool(user.is_admin),
        "is_guest": bool(getattr(user, "is_guest", False)),
        "guest_username": getattr(user, "guest_username", None),
        "guest_expires_at": _iso(getattr(user, "guest_expires_at", None)),
        "google_email": getattr(user, "google_email", None),
        "google_linked_at": _iso(getattr(user, "google_linked_at", None)),
        "totp_enabled": bool(getattr(user, "totp_enabled", False)),
        "notifications_enabled": bool(getattr(user, "notifications_enabled", True)),
        "created_at": _iso(user.created_at),
        "updated_at": _iso(user.updated_at),
        "last_login": _iso(user.last_login),
        "last_seen": _iso(getattr(user, "last_seen", None)),
        "password_changed_at": _iso(getattr(user, "password_changed_at", None)),
    }


def _export_teams(user) -> list[dict[str, Any]]:
    from app.models.team import TeamMember

    rows = []
    for membership in TeamMember.query.filter_by(user_id=user.id).all():
        team = membership.team
        rows.append({
            "team_id": membership.team_id,
            "team_name": team.name if team else None,
            "joined_at": _iso(membership.joined_at),
        })
    return rows


def _export_sessions(user) -> list[dict[str, Any]]:
    from app.models.user_session import UserSession

    rows = []
    for session in UserSession.query.filter_by(user_id=user.id).order_by(UserSession.last_activity.desc()).limit(200).all():
        sid = session.session_id or ""
        rows.append({
            "id": session.id,
            "session_id_suffix": sid[-8:] if len(sid) >= 8 else sid,
            "ip_address": session.ip_address,
            "user_agent": session.user_agent,
            "created_at": _iso(session.created_at),
            "last_activity": _iso(session.last_activity),
            "is_active": bool(session.is_active),
        })
    return rows


def _export_cookie_consent(user) -> list[dict[str, Any]]:
    from app.models.cookie_consent import CookieConsentLog

    rows = []
    for row in (
        CookieConsentLog.query.filter_by(user_id=user.id)
        .order_by(CookieConsentLog.created_at.desc())
        .limit(100)
        .all()
    ):
        rows.append({
            "id": row.id,
            "anon_id_suffix": (row.anon_id or "")[-8:],
            "consent_version": row.consent_version,
            "necessary": bool(row.necessary),
            "functional": bool(row.functional),
            "analytics": bool(row.analytics),
            "created_at": _iso(row.created_at),
        })
    return rows


def _export_passkeys(user) -> list[dict[str, Any]]:
    from app.models.passkey import UserPasskey

    rows = []
    for pk in UserPasskey.query.filter_by(user_id=user.id).all():
        rows.append({
            "id": pk.id,
            "device_label": pk.device_label,
            "aaguid": pk.aaguid,
            "backed_up": bool(pk.backed_up),
            "transports": pk.transports,
            "created_at": _iso(pk.created_at),
            "last_used_at": _iso(pk.last_used_at),
        })
    return rows


def _export_api_tokens(user) -> list[dict[str, Any]]:
    from app.models.api_token import ApiToken

    rows = []
    for token in ApiToken.query.filter_by(user_id=user.id).all():
        rows.append({
            "id": token.id,
            "name": token.name,
            "prefix": token.token_prefix,
            "created_at": _iso(token.created_at),
            "last_used_at": _iso(token.last_used_at),
            "expires_at": _iso(token.expires_at),
        })
    return rows


def _export_notifications(user) -> dict[str, Any]:
    from app.models.notification import (
        NotificationSettings,
        ChatNotificationSettings,
        PushSubscription,
        NotificationLog,
    )

    settings = NotificationSettings.query.filter_by(user_id=user.id).first()
    settings_payload = None
    if settings:
        settings_payload = {
            "chat_notifications_enabled": settings.chat_notifications_enabled,
            "file_notifications_enabled": settings.file_notifications_enabled,
            "file_new_notifications": settings.file_new_notifications,
            "file_modified_notifications": settings.file_modified_notifications,
            "email_notifications_enabled": settings.email_notifications_enabled,
            "calendar_notifications_enabled": settings.calendar_notifications_enabled,
            "calendar_all_events": settings.calendar_all_events,
            "calendar_participating_only": settings.calendar_participating_only,
            "calendar_not_participating": settings.calendar_not_participating,
            "calendar_no_response": settings.calendar_no_response,
            "booking_notifications_enabled": settings.booking_notifications_enabled,
            "booking_message_notifications_enabled": settings.booking_message_notifications_enabled,
            "kanban_notifications_enabled": settings.kanban_notifications_enabled,
            "kanban_upload_notifications": settings.kanban_upload_notifications,
            "kanban_change_notifications": settings.kanban_change_notifications,
            "kanban_checklist_notifications": settings.kanban_checklist_notifications,
            "reminder_times": settings.get_reminder_times(),
            "updated_at": _iso(settings.updated_at),
        }

    muted_chats = [
        {"chat_id": row.chat_id, "notifications_enabled": row.notifications_enabled}
        for row in ChatNotificationSettings.query.filter_by(user_id=user.id).all()
    ]

    push = []
    for sub in PushSubscription.query.filter_by(user_id=user.id).all():
        push.append({
            "id": sub.id,
            "endpoint": getattr(sub, "endpoint", None),
            "user_agent": getattr(sub, "user_agent", None),
            "created_at": _iso(getattr(sub, "created_at", None)),
        })

    logs = []
    for log in (
        NotificationLog.query.filter_by(user_id=user.id)
        .order_by(NotificationLog.sent_at.desc())
        .limit(200)
        .all()
    ):
        logs.append({
            "id": log.id,
            "title": log.title,
            "body": log.body,
            "notification_type": log.notification_type,
            "url": log.url,
            "sent_at": _iso(log.sent_at),
        })

    return {
        "settings": settings_payload,
        "chat_overrides": muted_chats,
        "push_subscriptions": push,
        "recent_notification_logs": logs,
    }


def _export_contacts(user) -> dict[str, Any]:
    from app.models.contact import Contact, ContactFavorite

    created = [
        {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "phone": c.phone,
            "notes": c.notes,
            "visibility": c.visibility,
            "team_id": c.team_id,
            "created_at": _iso(c.created_at),
            "updated_at": _iso(c.updated_at),
        }
        for c in Contact.query.filter_by(created_by=user.id).order_by(Contact.id).all()
    ]
    favorites = [
        {"contact_id": f.contact_id, "created_at": _iso(f.created_at)}
        for f in ContactFavorite.query.filter_by(user_id=user.id).all()
    ]
    return {"created": created, "favorites": favorites}


def _export_calendar(user) -> dict[str, Any]:
    from app.models.calendar import Calendar, CalendarEvent, EventParticipant

    owned = [
        {
            "id": cal.id,
            "name": cal.name,
            "color": getattr(cal, "color", None),
            "created_at": _iso(getattr(cal, "created_at", None)),
        }
        for cal in Calendar.query.filter_by(owner_id=user.id).all()
    ]

    created_events = []
    for event in (
        CalendarEvent.query.filter_by(created_by=user.id)
        .order_by(CalendarEvent.id.desc())
        .limit(2000)
        .all()
    ):
        created_events.append({
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "location": event.location,
            "start_time": _iso(event.start_time),
            "end_time": _iso(event.end_time),
            "calendar_id": event.calendar_id,
            "created_at": _iso(event.created_at),
        })

    participations = []
    for part in EventParticipant.query.filter_by(user_id=user.id).all():
        participations.append({
            "event_id": part.event_id,
            "status": part.status,
            "responded_at": _iso(getattr(part, "responded_at", None)),
        })

    return {
        "owned_calendars": owned,
        "created_events": created_events,
        "participations": participations,
    }


def _export_files(user) -> dict[str, Any]:
    from app.models.file import File

    uploaded = []
    for f in (
        File.query.filter_by(uploaded_by=user.id, is_current=True)
        .order_by(File.id.desc())
        .limit(5000)
        .all()
    ):
        uploaded.append({
            "id": f.id,
            "name": f.name,
            "original_name": f.original_name,
            "folder_id": f.folder_id,
            "file_size": f.file_size,
            "mime_type": f.mime_type,
            "space": getattr(f, "space", None),
            "team_id": getattr(f, "team_id", None),
            "deleted_at": _iso(getattr(f, "deleted_at", None)),
            "created_at": _iso(f.created_at),
            "updated_at": _iso(f.updated_at),
        })
    return {"uploaded_current_versions": uploaded, "note": "Binary file contents are not included."}


def _export_chat(user) -> dict[str, Any]:
    from app.models.chat import ChatMember, ChatMessage, ChatPin

    memberships = [
        {
            "chat_id": m.chat_id,
            "joined_at": _iso(m.joined_at),
            "last_read_at": _iso(m.last_read_at),
        }
        for m in ChatMember.query.filter_by(user_id=user.id).all()
    ]

    messages = []
    for msg in (
        ChatMessage.query.filter_by(sender_id=user.id)
        .order_by(ChatMessage.id.desc())
        .limit(5000)
        .all()
    ):
        messages.append({
            "id": msg.id,
            "chat_id": msg.chat_id,
            "content": getattr(msg, "content", None) or getattr(msg, "message", None) or getattr(msg, "text", None),
            "created_at": _iso(msg.created_at),
            "edited_at": _iso(getattr(msg, "edited_at", None)),
        })

    pins = [
        {"chat_id": p.chat_id, "created_at": _iso(getattr(p, "created_at", None))}
        for p in ChatPin.query.filter_by(user_id=user.id).all()
    ]

    return {
        "memberships": memberships,
        "messages_sent": list(reversed(messages)),
        "pinned_chats": pins,
    }


def _export_bookings(user) -> dict[str, Any]:
    from app.models.booking import BookingRequest

    by_email = []
    if user.email:
        for req in BookingRequest.query.filter_by(email=user.email).order_by(BookingRequest.id.desc()).limit(500).all():
            by_email.append(_booking_row(req))

    accepted = []
    for req in BookingRequest.query.filter_by(accepted_by=user.id).order_by(BookingRequest.id.desc()).limit(500).all():
        accepted.append(_booking_row(req))

    rejected = []
    for req in BookingRequest.query.filter_by(rejected_by=user.id).order_by(BookingRequest.id.desc()).limit(500).all():
        rejected.append(_booking_row(req))

    return {
        "requests_with_my_email": by_email,
        "accepted_by_me": accepted,
        "rejected_by_me": rejected,
    }


def _booking_row(req) -> dict[str, Any]:
    return {
        "id": req.id,
        "form_id": req.form_id,
        "event_name": req.event_name,
        "applicant_name": req.applicant_name,
        "email": req.email,
        "status": req.status,
        "event_date": _iso(req.event_date),
        "created_at": _iso(req.created_at),
        "accepted_at": _iso(req.accepted_at),
        "rejected_at": _iso(req.rejected_at),
        "rejection_reason": req.rejection_reason,
    }


def _export_inventory(user) -> dict[str, Any]:
    from app.models.inventory import Checkout, ProductFavorite, SavedFilter

    as_borrower = []
    for checkout in (
        Checkout.query.filter(
            db.or_(Checkout.borrower_id == user.id, Checkout.created_by == user.id)
        )
        .order_by(Checkout.id.desc())
        .limit(1000)
        .all()
    ):
        as_borrower.append({
            "id": checkout.id,
            "checkout_number": checkout.checkout_number,
            "event_name": checkout.event_name,
            "borrower_name": checkout.borrower_name,
            "borrower_id": checkout.borrower_id,
            "contact_email": checkout.contact_email,
            "created_by": checkout.created_by,
            "status": checkout.status,
            "start_date": _iso(checkout.start_date),
            "end_date": _iso(checkout.end_date),
            "created_at": _iso(checkout.created_at),
        })

    favorites = [
        {"product_id": f.product_id, "created_at": _iso(getattr(f, "created_at", None))}
        for f in ProductFavorite.query.filter_by(user_id=user.id).all()
    ]
    filters = [
        {
            "id": sf.id,
            "name": sf.name,
            "created_at": _iso(getattr(sf, "created_at", None)),
        }
        for sf in SavedFilter.query.filter_by(user_id=user.id).all()
    ]

    return {
        "checkouts": as_borrower,
        "product_favorites": favorites,
        "saved_filters": filters,
    }


def _export_surveys(user) -> dict[str, Any]:
    from app.models.survey import SurveyResponse

    clauses = [SurveyResponse.user_id == user.id]
    if user.email:
        clauses.append(SurveyResponse.respondent_email == user.email)

    responses = []
    for resp in (
        SurveyResponse.query.filter(db.or_(*clauses))
        .order_by(SurveyResponse.id.desc())
        .limit(500)
        .all()
    ):
        answers = []
        for ans in resp.answers:
            answers.append({
                "question_id": ans.question_id,
                "value_text": ans.value_text,
                "value_json": ans.get_value_json(),
                "file_path": ans.file_path,
            })
        responses.append({
            "id": resp.id,
            "survey_id": resp.survey_id,
            "respondent_email": resp.respondent_email,
            "user_id": resp.user_id,
            "status": resp.status,
            "submitted_at": _iso(resp.submitted_at),
            "created_at": _iso(resp.created_at),
            "answers": answers,
        })
    return {"responses": responses}
