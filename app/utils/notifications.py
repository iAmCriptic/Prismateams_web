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

    vapid_claims = {"sub": "mailto:admin@yourdomain.com"}
    return converted_private_key, public_key, vapid_claims


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
            body = '1 neue Nachricht'
        else:
            body = f'{unread_count} neue Nachrichten'
        title = f'"{chat_name or "Team Chat"}"'
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

        title = "Neue Datei" if notification_type == 'new' else "Datei geändert"
        body = f"{file.name} wurde {'hochgeladen' if notification_type == 'new' else 'geändert'}"
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
            body = "1 neue E-Mail"
        else:
            body = f"{unread_count} neue E-Mails"
        title = "E-Mail"
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
        if reminder_minutes >= 60:
            hours = reminder_minutes // 60
            if hours >= 24:
                days = hours // 24
                time_text = f"in {days} Tag{'en' if days > 1 else ''}"
            else:
                time_text = f"in {hours} Stunde{'n' if hours > 1 else ''}"
        else:
            time_text = f"in {reminder_minutes} Minuten"

        title = "Termin-Erinnerung"
        body = f"{event.title} {time_text} ({date_str} um {time_str})"
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
