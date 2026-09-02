import json
import logging
import re
import base64
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from flask import current_app
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from app import db, socketio
from app.models.user import User
from app.models.notification import (
    PushSubscription,
    NotificationLog,
    NotificationSettings,
    ChatNotificationSettings,
    PushDeliveryLog,
)
from app.models.chat import ChatMessage, ChatMember
from app.models.file import File
from app.models.email import EmailMessage
from app.models.calendar import CalendarEvent, EventParticipant

try:
    from pywebpush import webpush, WebPushException
    WEBPUSH_AVAILABLE = True
except ImportError:
    WEBPUSH_AVAILABLE = False
    logging.warning("pywebpush nicht verfügbar. Push-Benachrichtigungen deaktiviert.")


def _deduplicate_subscriptions(subscriptions: List[PushSubscription]) -> List[PushSubscription]:
    """Entfernt doppelte aktive Subscriptions nach Endpoint."""
    unique_by_endpoint = {}
    for subscription in subscriptions:
        existing = unique_by_endpoint.get(subscription.endpoint)
        if not existing:
            unique_by_endpoint[subscription.endpoint] = subscription
            continue
        existing_last_used = existing.last_used or existing.created_at or datetime.min
        current_last_used = subscription.last_used or subscription.created_at or datetime.min
        if current_last_used > existing_last_used:
            unique_by_endpoint[subscription.endpoint] = subscription
    return list(unique_by_endpoint.values())


def get_vapid_keys():
    """Lade VAPID Keys aus der App-Konfiguration."""
    private_key = current_app.config.get('VAPID_PRIVATE_KEY')
    public_key = current_app.config.get('VAPID_PUBLIC_KEY')

    if not private_key or not public_key:
        logging.warning("VAPID Keys nicht konfiguriert. Push-Benachrichtigungen deaktiviert.")
        return None, None, None

    converted_private_key = private_key
    try:
        if private_key and not private_key.startswith('-----BEGIN'):
            b64 = private_key.replace('-', '+').replace('_', '/')
            b64 += '=' * ((4 - len(b64) % 4) % 4)
            raw = base64.b64decode(b64)
            if len(raw) == 32:
                priv_int = int.from_bytes(raw, 'big')
                priv_obj = ec.derive_private_key(priv_int, ec.SECP256R1())
                converted_private_key = priv_obj.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ).decode('ascii')
    except Exception as e:
        logging.error(f"VAPID Private Key Konvertierung fehlgeschlagen: {e}")

    claim_email = (
        current_app.config.get('VAPID_CLAIM_EMAIL')
        or current_app.config.get('MAIL_DEFAULT_SENDER')
        or 'admin@localhost'
    )
    if isinstance(claim_email, str) and '<' in claim_email and '>' in claim_email:
        claim_email = claim_email.split('<', 1)[1].split('>', 1)[0].strip()
    claim_email = (claim_email or 'admin@localhost').strip()
    if claim_email.lower().startswith('mailto:'):
        claim_sub = claim_email
    else:
        claim_sub = f"mailto:{claim_email}"
    vapid_claims = {"sub": claim_sub}
    return converted_private_key, public_key, vapid_claims


def _user_translate(user, key: str, **kwargs) -> str:
    """Übersetzt in der Sprache des Empfängers."""
    from app.utils.i18n import translate
    lang = getattr(user, 'language', None) if user else None
    return translate(key, language=lang, **kwargs)


def sync_user_notification_flags(user: User, settings: NotificationSettings) -> None:
    """Hält Legacy-User-Flags mit NotificationSettings synchron."""
    if not user or not settings:
        return
    user.chat_notifications = bool(settings.chat_notifications_enabled)
    user.email_notifications = bool(settings.email_notifications_enabled)


def _resolve_push_icon(icon: str) -> str:
    try:
        from app.models.settings import SystemSettings
        from flask import url_for

        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            portal_logo_url = url_for('settings.portal_logo', filename=portal_logo_setting.value, _external=True)
            if not icon or icon == "/static/img/logo.png":
                return portal_logo_url
        if not icon or icon == "":
            return url_for('static', filename='img/logo.png', _external=True)
    except Exception as e:
        logging.warning(f"Could not load portal settings for push notification: {e}")
        if not icon or icon == "":
            try:
                from flask import url_for
                return url_for('static', filename='img/logo.png', _external=True)
            except Exception:
                return "/static/img/logo.png"
    return icon


def _push_already_delivered(subscription_id: int, dedup_key: str) -> bool:
    return PushDeliveryLog.query.filter_by(
        subscription_id=subscription_id,
        dedup_key=dedup_key,
    ).first() is not None


def _record_push_delivery(user_id: int, subscription_id: int, dedup_key: str) -> None:
    if _push_already_delivered(subscription_id, dedup_key):
        return
    db.session.add(PushDeliveryLog(
        user_id=user_id,
        subscription_id=subscription_id,
        dedup_key=dedup_key,
    ))


def upsert_notification_log(
    user_id: int,
    title: str,
    body: str,
    url: str,
    notification_type: str,
    dedup_key: str,
    source_id: Optional[int] = None,
    icon: Optional[str] = None,
) -> NotificationLog:
    """Erstellt oder aktualisiert einen ungelesenen In-App-Eintrag."""
    existing = NotificationLog.query.filter_by(
        user_id=user_id,
        dedup_key=dedup_key,
        is_read=False,
    ).first()
    if existing:
        existing.title = title
        existing.body = body
        existing.url = url
        existing.notification_type = notification_type
        existing.source_id = source_id
        if icon:
            existing.icon = icon
        existing.sent_at = datetime.utcnow()
        return existing

    log_entry = NotificationLog(
        user_id=user_id,
        title=title,
        body=body,
        url=url,
        icon=icon,
        notification_type=notification_type,
        dedup_key=dedup_key,
        source_id=source_id,
        success=True,
        is_read=False,
    )
    db.session.add(log_entry)
    return log_entry


def mark_in_app_notifications_read(
    user_id: int,
    *,
    notification_type: Optional[str] = None,
    notification_types: Optional[List[str]] = None,
    source_id: Optional[int] = None,
    dedup_key: Optional[str] = None,
    commit: bool = False,
) -> int:
    """
    Markiert passende ungelesene In-App-Benachrichtigungen als gelesen.
    Löscht Einträge nicht — sie verschwinden nur aus der „Neu“-Liste / dem Badge.
    """
    query = NotificationLog.query.filter_by(user_id=user_id, is_read=False)
    if notification_types:
        query = query.filter(NotificationLog.notification_type.in_(notification_types))
    elif notification_type is not None:
        query = query.filter_by(notification_type=notification_type)
    if source_id is not None:
        query = query.filter_by(source_id=source_id)
    if dedup_key is not None:
        query = query.filter_by(dedup_key=dedup_key)

    updated = query.update(
        {
            NotificationLog.is_read: True,
            NotificationLog.read_at: datetime.utcnow(),
        },
        synchronize_session=False,
    )
    if commit:
        db.session.commit()
    return int(updated or 0)


def notify_user(
    user_id: int,
    *,
    title: str,
    body: str,
    url: str,
    notification_type: str,
    dedup_key: str,
    push_dedup_key: Optional[str] = None,
    source_id: Optional[int] = None,
    icon: str = "/static/img/logo.png",
    data: Optional[Dict] = None,
    send_push: bool = True,
) -> bool:
    """
    Einheitlicher Benachrichtigungsweg: In-App-Log + optional Web-Push.
    """
    upsert_notification_log(
        user_id=user_id,
        title=title,
        body=body,
        url=url,
        notification_type=notification_type,
        dedup_key=dedup_key,
        source_id=source_id,
        icon=icon,
    )
    push_ok = False
    if send_push:
        push_ok = send_push_notification(
            user_id=user_id,
            title=title,
            body=body,
            icon=icon,
            url=url,
            data=data,
            dedup_key=push_dedup_key or dedup_key,
        )
    try:
        db.session.commit()
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Benachrichtigung: {e}")
        db.session.rollback()
        return False
    return push_ok or True


def send_push_notification(
    user_id: int,
    title: str,
    body: str,
    icon: str = "/static/img/logo.png",
    url: str = None,
    data: Dict = None,
    dedup_key: Optional[str] = None,
) -> bool:
    """Sendet Web-Push an alle aktiven Geräte (max. 1× pro Gerät und dedup_key)."""
    if not WEBPUSH_AVAILABLE:
        logging.error("WebPush nicht verfügbar")
        return False

    vapid_private_key, _, vapid_claims = get_vapid_keys()
    if not vapid_private_key:
        logging.error("VAPID Keys nicht konfiguriert")
        return False

    user = User.query.get(user_id)
    if not user or not user.notifications_enabled:
        return False

    subscriptions = PushSubscription.query.filter_by(user_id=user_id, is_active=True).all()
    subscriptions = _deduplicate_subscriptions(subscriptions)
    if not subscriptions:
        logging.info(f"Keine Push-Subscriptions für Benutzer {user_id}")
        return False

    icon = _resolve_push_icon(icon)
    payload = {
        "title": title,
        "body": body,
        "icon": icon,
        "url": url or "/",
        "data": data or {},
    }
    push_dedup = dedup_key or f"generic:{user_id}:{title}:{body}:{url or '/'}"
    original_private_key = current_app.config.get('VAPID_PRIVATE_KEY')
    success_count = 0

    def ensure_padded_base64url(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return value
        v = value.strip()
        padding = (4 - (len(v) % 4)) % 4
        if padding:
            v += '=' * padding
        return v

    for subscription in subscriptions:
        if _push_already_delivered(subscription.id, push_dedup):
            continue
        try:
            sub_info = subscription.to_dict()
            if 'keys' in sub_info:
                sub_info['keys'] = dict(sub_info['keys'])
                sub_info['keys']['p256dh'] = ensure_padded_base64url(sub_info['keys'].get('p256dh'))
                sub_info['keys']['auth'] = ensure_padded_base64url(sub_info['keys'].get('auth'))

            webpush(
                subscription_info=sub_info,
                data=json.dumps(payload),
                vapid_private_key=original_private_key,
                vapid_claims=vapid_claims,
                ttl=86400,
            )
            subscription.last_used = datetime.utcnow()
            _record_push_delivery(user_id, subscription.id, push_dedup)
            success_count += 1
        except WebPushException as e:
            logging.error(f"WebPush Fehler für Benutzer {user_id}: {e}")
            if e.response and e.response.status_code in [410, 404, 400]:
                subscription.is_active = False
        except Exception as e:
            logging.error(f"Unerwarteter Fehler beim Senden der Push-Benachrichtigung: {e}")

    return success_count > 0


def get_or_create_notification_settings(user_id: int) -> NotificationSettings:
    settings = NotificationSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = NotificationSettings(user_id=user_id)
        db.session.add(settings)
        db.session.commit()
    return settings


def send_chat_notification(
    chat_id: int,
    sender_id: int,
    message_content: str,
    chat_name: str = None,
    message_id: int = None,
) -> int:
    members = ChatMember.query.filter_by(chat_id=chat_id).all()
    recipients = [m for m in members if m.user_id != sender_id]
    sender = User.query.get(sender_id)
    if not sender:
        return 0

    sent_count = 0
    for member in recipients:
        user = User.query.get(member.user_id)
        if not user or not user.notifications_enabled or not user.chat_notifications:
            continue

        from app.utils.access_control import has_module_access
        if not has_module_access(user, 'module_chat'):
            continue

        settings = get_or_create_notification_settings(user.id)
        if not settings.chat_notifications_enabled:
            continue

        chat_settings = ChatNotificationSettings.query.filter_by(
            user_id=user.id, chat_id=chat_id
        ).first()
        if chat_settings and not chat_settings.notifications_enabled:
            continue

        unread_count = ChatMessage.query.filter(
            ChatMessage.chat_id == chat_id,
            ChatMessage.sender_id != user.id,
            ChatMessage.created_at > (member.last_read_at or member.joined_at or datetime.min),
            ChatMessage.is_deleted == False,
        ).count()
        if unread_count == 0:
            continue

        if unread_count == 1:
            body = _user_translate(user, 'notifications.chat.body_one')
        else:
            body = _user_translate(user, 'notifications.chat.body_many', count=unread_count)
        chat_label = chat_name or _user_translate(user, 'notifications.chat.default_name')
        title = _user_translate(user, 'notifications.chat.title', chat_name=chat_label)
        in_app_key = f"chat:{chat_id}"
        push_key = f"chat:{chat_id}:msg:{message_id}" if message_id else in_app_key

        if notify_user(
            user.id,
            title=title,
            body=body,
            url=f"/chat/{chat_id}",
            notification_type='chat',
            dedup_key=in_app_key,
            push_dedup_key=push_key,
            source_id=chat_id,
            data={'chat_id': chat_id, 'unread_count': unread_count, 'type': 'chat'},
        ):
            sent_count += 1

    return sent_count


def enqueue_chat_notification(
    chat_id: int,
    sender_id: int,
    message_content: str,
    chat_name: str = None,
    message_id: int = None,
):
    app = current_app._get_current_object()

    def _run_in_background():
        with app.app_context():
            try:
                send_chat_notification(
                    chat_id=chat_id,
                    sender_id=sender_id,
                    message_content=message_content,
                    chat_name=chat_name,
                    message_id=message_id,
                )
            except Exception as exc:
                logging.error(f"Asynchroner Chat-Push fehlgeschlagen: {exc}")

    try:
        socketio.start_background_task(_run_in_background)
    except Exception as exc:
        logging.warning(f"Background-Task konnte nicht gestartet werden, fallback synchron: {exc}")
        send_chat_notification(
            chat_id=chat_id,
            sender_id=sender_id,
            message_content=message_content,
            chat_name=chat_name,
            message_id=message_id,
        )


def send_file_notification(file_id: int, notification_type: str = 'new') -> int:
    from app.utils.access_control import has_module_access

    file = File.query.get(file_id)
    if not file:
        return 0

    users = User.query.join(NotificationSettings).filter(
        NotificationSettings.file_notifications_enabled == True
    ).all()
    sent_count = 0

    for user in users:
        if not user.notifications_enabled:
            continue
        if not has_module_access(user, 'module_files'):
            continue
        settings = get_or_create_notification_settings(user.id)
        if notification_type == 'new' and not settings.file_new_notifications:
            continue
        if notification_type == 'modified' and not settings.file_modified_notifications:
            continue
        if user.id == file.uploader_id:
            continue

        if notification_type == 'new':
            title = _user_translate(user, 'notifications.file.new_title')
            body = _user_translate(user, 'notifications.file.new_body', name=file.name)
        else:
            title = _user_translate(user, 'notifications.file.modified_title')
            body = _user_translate(user, 'notifications.file.modified_body', name=file.name)
        dedup_key = f"file:{file_id}:{notification_type}"

        if notify_user(
            user.id,
            title=title,
            body=body,
            url=f"/files/view/{file_id}",
            notification_type='file',
            dedup_key=dedup_key,
            source_id=file_id,
            data={'file_id': file_id, 'file_name': file.name, 'type': 'file', 'action': notification_type},
        ):
            sent_count += 1

    return sent_count


def send_kanban_notification(
    board_id: int,
    actor_id: int,
    event_kind: str,
    card_id: int,
    *,
    detail: Optional[str] = None,
    push_suffix: Optional[str] = None,
) -> int:
    """Benachrichtigt Board-Mitglieder über Kanban-Ereignisse."""
    from app.models.kanban import KanbanBoard, KanbanCard
    from app.utils.access_control import has_module_access
    from app.utils.kanban_access import get_board_member_roles

    if not actor_id or event_kind not in ('upload', 'change', 'checklist'):
        return 0

    board = KanbanBoard.query.get(board_id)
    card = KanbanCard.query.get(card_id)
    if not board or not card:
        return 0

    actor = User.query.get(actor_id)
    if not actor:
        return 0

    member_roles = get_board_member_roles(board)
    sent_count = 0
    actor_name = actor.full_name or actor.email or str(actor_id)
    board_title = board.title or ''
    card_title = card.title or ''
    url = f'/kanban/board/{board_id}'
    in_app_key = f'kanban:{board_id}:{card_id}:{event_kind}'
    push_key = push_suffix if push_suffix else f'{in_app_key}:{int(datetime.utcnow().timestamp() * 1000)}'

    toggle_attr = {
        'upload': 'kanban_upload_notifications',
        'change': 'kanban_change_notifications',
        'checklist': 'kanban_checklist_notifications',
    }[event_kind]

    title_key = f'notifications.kanban.{event_kind}_title'
    body_key = f'notifications.kanban.{event_kind}_body'

    for user_id in member_roles:
        if user_id == actor_id:
            continue
        user = User.query.get(user_id)
        if not user or not user.is_active or not user.notifications_enabled:
            continue
        if not has_module_access(user, 'module_kanban'):
            continue

        settings = get_or_create_notification_settings(user.id)
        if not settings.kanban_notifications_enabled:
            continue
        if not getattr(settings, toggle_attr, True):
            continue

        title = _user_translate(user, title_key, board=board_title)
        body_kwargs = {
            'board': board_title,
            'card': card_title,
            'actor': actor_name,
        }
        if detail:
            body_kwargs['item'] = detail
            body_kwargs['filename'] = detail
        body = _user_translate(user, body_key, **body_kwargs)

        if notify_user(
            user.id,
            title=title,
            body=body,
            url=url,
            notification_type='kanban',
            dedup_key=in_app_key,
            push_dedup_key=push_key,
            source_id=card_id,
            data={
                'board_id': board_id,
                'card_id': card_id,
                'event_kind': event_kind,
                'type': 'kanban',
            },
        ):
            sent_count += 1

    return sent_count


def enqueue_kanban_notification(
    board_id: int,
    actor_id: int,
    event_kind: str,
    card_id: int,
    *,
    detail: Optional[str] = None,
    push_suffix: Optional[str] = None,
):
    app = current_app._get_current_object()

    def _run_in_background():
        with app.app_context():
            try:
                send_kanban_notification(
                    board_id=board_id,
                    actor_id=actor_id,
                    event_kind=event_kind,
                    card_id=card_id,
                    detail=detail,
                    push_suffix=push_suffix,
                )
            except Exception as exc:
                logging.error(f'Asynchroner Kanban-Push fehlgeschlagen: {exc}')

    try:
        socketio.start_background_task(_run_in_background)
    except Exception as exc:
        logging.warning(f'Background-Task konnte nicht gestartet werden, fallback synchron: {exc}')
        send_kanban_notification(
            board_id=board_id,
            actor_id=actor_id,
            event_kind=event_kind,
            card_id=card_id,
            detail=detail,
            push_suffix=push_suffix,
        )


def send_email_notification(email_id: int) -> int:
    try:
        db.session.flush()
        email = EmailMessage.query.get(email_id)
        if not email:
            return 0
    except Exception as e:
        logging.error(f"Fehler beim Laden der E-Mail: {e}")
        return 0

    try:
        users = User.query.join(NotificationSettings).filter(
            NotificationSettings.email_notifications_enabled == True
        ).all()
    except Exception as e:
        logging.error(f"Fehler beim Laden der Benutzer: {e}")
        return 0

    sent_count = 0
    for user in users:
        if not user.notifications_enabled or not user.email_notifications:
            continue

        from app.utils.access_control import has_module_access
        if not has_module_access(user, 'module_email'):
            continue

        unread_count = EmailMessage.query.filter(
            EmailMessage.is_read == False,
            EmailMessage.is_sent == False,
        ).count()
        if unread_count == 0:
            continue

        if unread_count == 1:
            body = _user_translate(user, 'notifications.email.body_one')
        else:
            body = _user_translate(user, 'notifications.email.body_many', count=unread_count)
        title = _user_translate(user, 'notifications.email.title')
        in_app_key = "email:unread"
        push_key = f"email:{email_id}"

        try:
            if notify_user(
                user.id,
                title=title,
                body=body,
                url="/email/",
                notification_type='email',
                dedup_key=in_app_key,
                push_dedup_key=push_key,
                source_id=email_id,
                data={'unread_count': unread_count, 'type': 'email', 'email_id': email_id},
            ):
                sent_count += 1
        except Exception as e:
            logging.error(f"E-Mail-Benachrichtigung fehlgeschlagen für Benutzer {user.id}: {e}")

    return sent_count


def send_calendar_notification(event_id: int, reminder_minutes: int = 30) -> int:
    event = CalendarEvent.query.get(event_id)
    if not event:
        return 0

    users = User.query.join(NotificationSettings).filter(
        NotificationSettings.calendar_notifications_enabled == True
    ).all()
    sent_count = 0

    for user in users:
        if not user.notifications_enabled:
            continue

        from app.utils.access_control import has_module_access
        if not has_module_access(user, 'module_calendar'):
            continue

        settings = get_or_create_notification_settings(user.id)
        user_reminder_times = set()
        for t in (settings.get_reminder_times() or []):
            try:
                user_reminder_times.add(int(t))
            except (TypeError, ValueError):
                continue
        try:
            if int(reminder_minutes) not in user_reminder_times:
                continue
        except (TypeError, ValueError):
            continue

        participation = EventParticipant.query.filter_by(
            event_id=event_id, user_id=user.id
        ).first()

        should_notify = False
        if settings.calendar_all_events:
            should_notify = True
        else:
            if participation:
                if participation.status == 'accepted' and settings.calendar_participating_only:
                    should_notify = True
                elif participation.status == 'declined' and settings.calendar_not_participating:
                    should_notify = True
                elif participation.status == 'pending' and settings.calendar_no_response:
                    should_notify = True
            elif settings.calendar_no_response:
                should_notify = True

        if not should_notify:
            continue

        time_str = event.start_time.strftime('%H:%M')
        date_str = event.start_time.strftime('%d.%m.%Y')
        if reminder_minutes >= 1440:
            days = reminder_minutes // 1440
            time_key = 'notifications.calendar.in_day_one' if days == 1 else 'notifications.calendar.in_days'
            time_text = _user_translate(user, time_key, count=days)
        elif reminder_minutes >= 60:
            hours = reminder_minutes // 60
            time_key = 'notifications.calendar.in_hour_one' if hours == 1 else 'notifications.calendar.in_hours'
            time_text = _user_translate(user, time_key, count=hours)
        else:
            time_text = _user_translate(user, 'notifications.calendar.in_minutes', count=reminder_minutes)

        title = _user_translate(user, 'notifications.calendar.reminder_title')
        body = _user_translate(
            user,
            'notifications.calendar.reminder_body',
            title=event.title,
            time_text=time_text,
            date=date_str,
            time=time_str,
        )
        dedup_key = f"calendar:{event_id}:{reminder_minutes}"

        if notify_user(
            user.id,
            title=title,
            body=body,
            url=f"/calendar/view/{event_id}",
            notification_type='calendar',
            dedup_key=dedup_key,
            source_id=event_id,
            data={
                'event_id': event_id,
                'event_title': event.title,
                'type': 'calendar',
                'reminder_minutes': reminder_minutes,
            },
        ):
            sent_count += 1

    return sent_count


def _iter_booking_notification_recipients(preference_attr: str):
    """Aktive User mit Booking-Zugang und aktivierter Preference."""
    from app.utils.access_control import has_module_access

    users = User.query.filter_by(is_active=True).all()
    for user in users:
        if getattr(user, 'is_guest', False):
            continue
        if not user.notifications_enabled:
            continue
        if not has_module_access(user, 'module_booking'):
            continue
        settings = get_or_create_notification_settings(user.id)
        if not getattr(settings, preference_attr, True):
            continue
        yield user


def send_booking_request_notification(booking_request) -> int:
    """In-App-Glocke + Push bei neuer Buchungsanfrage (laut Benachrichtigungseinstellung)."""
    form = booking_request.form
    if not form:
        return 0

    from flask import url_for

    event_label = booking_request.event_name or f"#{booking_request.id}"
    applicant = booking_request.applicant_name or booking_request.email or ""
    try:
        url = url_for('booking.request_detail', request_id=booking_request.id)
    except Exception:
        url = f"/booking/request/{booking_request.id}"

    sent_count = 0
    for user in _iter_booking_notification_recipients('booking_notifications_enabled'):
        title = _user_translate(user, 'notifications.booking.request_title')
        body = _user_translate(
            user,
            'notifications.booking.request_body',
            event=event_label,
            applicant=applicant,
        )
        dedup_key = f"booking_request:{booking_request.id}:{user.id}"
        if notify_user(
            user.id,
            title=title,
            body=body,
            url=url,
            notification_type='booking',
            dedup_key=dedup_key,
            source_id=booking_request.id,
            data={
                'booking_request_id': booking_request.id,
                'form_id': form.id,
                'type': 'booking',
            },
        ):
            sent_count += 1

    return sent_count


def send_booking_message_notification(booking_request, message=None) -> int:
    """In-App-Glocke + Push bei neuer Nachricht des Antragstellers."""
    if not booking_request:
        return 0

    from flask import url_for

    event_label = booking_request.event_name or f"#{booking_request.id}"
    applicant = booking_request.applicant_name or booking_request.email or ""
    try:
        url = url_for('booking.request_detail', request_id=booking_request.id)
    except Exception:
        url = f"/booking/request/{booking_request.id}"

    preview = ''
    if message is not None:
        preview = (getattr(message, 'body_text', None) or getattr(message, 'subject', None) or '').strip()
        if len(preview) > 120:
            preview = preview[:117] + '…'

    message_id = getattr(message, 'id', None) if message is not None else None
    sent_count = 0
    for user in _iter_booking_notification_recipients('booking_message_notifications_enabled'):
        title = _user_translate(user, 'notifications.booking.message_title')
        if preview:
            body = _user_translate(
                user,
                'notifications.booking.message_body_preview',
                event=event_label,
                applicant=applicant,
                preview=preview,
            )
        else:
            body = _user_translate(
                user,
                'notifications.booking.message_body',
                event=event_label,
                applicant=applicant,
            )
        dedup_key = (
            f"booking_message:{booking_request.id}:{message_id}:{user.id}"
            if message_id
            else f"booking_message:{booking_request.id}:{user.id}:{datetime.utcnow().timestamp()}"
        )
        if notify_user(
            user.id,
            title=title,
            body=body,
            url=url,
            notification_type='booking',
            dedup_key=dedup_key,
            source_id=booking_request.id,
            data={
                'booking_request_id': booking_request.id,
                'booking_message_id': message_id,
                'type': 'booking_message',
            },
        ):
            sent_count += 1

    return sent_count


def schedule_calendar_reminders():
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if 'calendar_events' not in inspector.get_table_names():
            logging.warning("Tabelle 'calendar_events' existiert nicht.")
            return

        now = datetime.utcnow()
        future_events = CalendarEvent.query.filter(
            CalendarEvent.start_time > now,
            CalendarEvent.start_time <= now + timedelta(days=7),
        ).all()

        reminder_candidates = db.session.query(NotificationSettings.reminder_times).filter(
            NotificationSettings.calendar_notifications_enabled == True,
            NotificationSettings.reminder_times.isnot(None),
            NotificationSettings.reminder_times != "[]",
        ).all()

        reminder_times = set()
        for reminder_row in reminder_candidates:
            raw = reminder_row[0]
            try:
                parsed_times = json.loads(raw) if raw else []
            except Exception:
                parsed_times = []
            for value in parsed_times:
                try:
                    reminder_times.add(int(value))
                except (TypeError, ValueError):
                    continue

        for event in future_events:
            for reminder_minutes in reminder_times:
                reminder_time = event.start_time - timedelta(minutes=reminder_minutes)
                if abs((reminder_time - now).total_seconds()) <= 300:
                    send_calendar_notification(event.id, reminder_minutes)
    except Exception as e:
        logging.error(f"Fehler beim Planen von Kalender-Erinnerungen: {e}", exc_info=True)


def register_push_subscription(user_id: int, subscription_data: Dict) -> bool:
    try:
        endpoint = subscription_data.get('endpoint')
        keys = subscription_data.get('keys', {})

        def to_base64url(value: str) -> str:
            if not isinstance(value, str):
                return value
            v = value.strip().replace('+', '-').replace('/', '_').rstrip('=')
            return v

        if 'p256dh' in keys:
            keys['p256dh'] = to_base64url(keys['p256dh'])
        if 'auth' in keys:
            keys['auth'] = to_base64url(keys['auth'])

        if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
            return False

        existing = PushSubscription.query.filter_by(user_id=user_id, endpoint=endpoint).first()
        if existing:
            existing.p256dh_key = keys['p256dh']
            existing.auth_key = keys['auth']
            existing.last_used = datetime.utcnow()
            existing.is_active = True
            if subscription_data.get('user_agent'):
                existing.user_agent = subscription_data.get('user_agent')
        else:
            db.session.add(PushSubscription(
                user_id=user_id,
                endpoint=endpoint,
                p256dh_key=keys['p256dh'],
                auth_key=keys['auth'],
                user_agent=subscription_data.get('user_agent'),
            ))

        # Deaktiviere andere Subscriptions mit gleichem Endpoint (anderer DB-Eintrag)
        duplicates = PushSubscription.query.filter(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint,
            PushSubscription.is_active == True,
        ).all()
        if len(duplicates) > 1:
            duplicates.sort(key=lambda s: s.last_used or s.created_at or datetime.min, reverse=True)
            for dup in duplicates[1:]:
                dup.is_active = False

        user = User.query.get(user_id)
        if user:
            user.notifications_enabled = True

        db.session.commit()
        return PushSubscription.query.filter_by(user_id=user_id, endpoint=endpoint, is_active=True).first() is not None
    except Exception as e:
        logging.error(f"Fehler beim Registrieren der Push-Subscription: {e}")
        db.session.rollback()
        return False


def reset_user_push_subscriptions(user_id: int) -> int:
    """Deaktiviert alle Push-Subscriptions eines Nutzers."""
    subscriptions = PushSubscription.query.filter_by(user_id=user_id, is_active=True).all()
    count = 0
    for sub in subscriptions:
        sub.is_active = False
        count += 1
    db.session.commit()
    return count


def cleanup_inactive_subscriptions():
    cutoff_date = datetime.utcnow() - timedelta(days=30)
    inactive_subscriptions = PushSubscription.query.filter(
        PushSubscription.last_used < cutoff_date,
        PushSubscription.is_active == True,
    ).all()
    for subscription in inactive_subscriptions:
        subscription.is_active = False
    db.session.commit()
    logging.info(f"{len(inactive_subscriptions)} inaktive Push-Subscriptions deaktiviert")


def cleanup_failed_subscriptions():
    try:
        stale_inactive = PushSubscription.query.filter(
            PushSubscription.is_active == False,
            PushSubscription.last_used < datetime.utcnow() - timedelta(days=60),
        ).all()
        if stale_inactive:
            for subscription in stale_inactive:
                db.session.delete(subscription)
            db.session.commit()
            logging.info(f"{len(stale_inactive)} inaktive Push-Subscriptions entfernt")
    except Exception as e:
        logging.error(f"Fehler beim Bereinigen fehlgeschlagener Subscriptions: {e}")


def deactivate_failed_subscription(subscription_id, error_type="410"):
    try:
        subscription = PushSubscription.query.get(subscription_id)
        if subscription and subscription.is_active:
            subscription.is_active = False
            db.session.commit()
            logging.info(f"Push-Subscription {subscription_id} deaktiviert (Fehler: {error_type})")
            return True
    except Exception as e:
        logging.error(f"Fehler beim Deaktivieren der Subscription {subscription_id}: {e}")
    return False
