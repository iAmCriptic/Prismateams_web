import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from app import db
from app.models.user import User
from app.models.notification import PushSubscription, NotificationLog, NotificationSettings, ChatNotificationSettings
from app.models.chat import Chat, ChatMessage, ChatMember
from app.models.file import File
from app.models.email import EmailMessage
from app.models.calendar import CalendarEvent, EventParticipant

# Web Push wird später installiert
try:
    from pywebpush import webpush, WebPushException
    WEBPUSH_AVAILABLE = True
except ImportError:
    WEBPUSH_AVAILABLE = False
    logging.warning("pywebpush nicht verfügbar. Push-Benachrichtigungen deaktiviert.")

# VAPID Keys (sollten in der Produktion aus Umgebungsvariablen kommen)
VAPID_PRIVATE_KEY = "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg3A_IkCBsEOcwov69vFX3oX3bf_79cnEPX1Ova59AzY-hRANCAAQbgQK_VLZM1S-mqhdyriFulWsUqu5ihFFzUDw0wOGZT9rn3tgJPV7f_rX-6MksMMTBKeRq7NKSNeH9CB4xvo2y"
VAPID_PUBLIC_KEY = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEG4ECv1S2TNUvpqoXcq4hbpVrFKruYoRRc1A8NMDhmU_a597YCT1e3_61_ujJLDDEwSnkauzSkjXh_QgeMb6Nsg"
VAPID_CLAIMS = {
    "sub": "mailto:admin@yourdomain.com"  # E-Mail des Administrators
}


def send_push_notification(
    user_id: int,
    title: str,
    body: str,
    icon: str = "/static/img/logo.png",
    url: str = None,
    data: Dict = None
) -> bool:
    """
    Sendet eine Push-Benachrichtigung an einen Benutzer.
    
    Args:
        user_id: ID des Benutzers
        title: Titel der Benachrichtigung
        body: Text der Benachrichtigung
        icon: URL zum Icon
        url: URL zum Öffnen bei Klick
        data: Zusätzliche Daten
    
    Returns:
        bool: True wenn erfolgreich gesendet
    """
    if not WEBPUSH_AVAILABLE:
        logging.error("WebPush nicht verfügbar")
        return False
    
    user = User.query.get(user_id)
    if not user or not user.notifications_enabled:
        return False
    
    # Hole alle aktiven Subscriptions des Benutzers
    subscriptions = PushSubscription.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()
    
    if not subscriptions:
        logging.info(f"Keine Push-Subscriptions für Benutzer {user_id}")
        # Keine Push-Benachrichtigung möglich
        return False
    
    success_count = 0
    total_count = len(subscriptions)
    
    for subscription in subscriptions:
        try:
            # Bereite Payload vor
            payload = {
                "title": title,
                "body": body,
                "icon": icon,
                "url": url or "/",
                "data": data or {}
            }
            
            # Sende Push-Benachrichtigung
            webpush(
                subscription_info=subscription.to_dict(),
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            
            # Update last_used
            subscription.last_used = datetime.utcnow()
            success_count += 1
            
            logging.info(f"Push-Benachrichtigung erfolgreich gesendet an Benutzer {user_id}")
            
        except WebPushException as e:
            logging.error(f"WebPush Fehler für Benutzer {user_id}: {e}")
            
            # Deaktiviere Subscription bei Fehlern
            if e.response and e.response.status_code in [410, 404]:
                subscription.is_active = False
                logging.info(f"Push-Subscription {subscription.id} deaktiviert")
            
        except Exception as e:
            logging.error(f"Unerwarteter Fehler beim Senden der Push-Benachrichtigung: {e}")
    
    # Logge das Ergebnis nur bei erfolgreichen Push-Benachrichtigungen
    if success_count > 0:
        log_entry = NotificationLog(
            user_id=user_id,
            title=title,
            body=body,
            icon=icon,
            url=url,
            success=True,
            is_read=True  # Push-Benachrichtigungen sind automatisch "gelesen"
        )
        db.session.add(log_entry)
        db.session.commit()
    
    return success_count > 0


def get_or_create_notification_settings(user_id: int) -> NotificationSettings:
    """Holt oder erstellt Benachrichtigungseinstellungen für einen Benutzer."""
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
    chat_name: str = None
) -> int:
    """
    Sendet Push-Benachrichtigungen für eine neue Chat-Nachricht.
    
    Args:
        chat_id: ID des Chats
        sender_id: ID des Absenders
        message_content: Inhalt der Nachricht
        chat_name: Name des Chats
    
    Returns:
        int: Anzahl der gesendeten Benachrichtigungen
    """
    # Hole alle Chat-Mitglieder außer dem Absender
    members = ChatMember.query.filter_by(chat_id=chat_id).all()
    recipients = [m for m in members if m.user_id != sender_id]
    
    sender = User.query.get(sender_id)
    if not sender:
        return 0
    
    sent_count = 0
    
    for member in recipients:
        user = User.query.get(member.user_id)
        if not user:
            continue
        
        # Prüfe globale Chat-Benachrichtigungseinstellungen
        settings = get_or_create_notification_settings(user.id)
        if not settings.chat_notifications_enabled:
            continue
        
        # Prüfe Chat-spezifische Einstellungen
        chat_settings = ChatNotificationSettings.query.filter_by(
            user_id=user.id,
            chat_id=chat_id
        ).first()
        
        if chat_settings and not chat_settings.notifications_enabled:
            continue
        
        # Kürze Nachricht für Benachrichtigung
        if len(message_content) > 50:
            display_content = message_content[:47] + "..."
        else:
            display_content = message_content
        
        # Neues Format: "Gruppenname" / "Sender: Nachricht"
        title = chat_name or "Team Chat"
        body = f"{sender.full_name}: {display_content}"
        
        # Sende Push-Benachrichtigung
        if send_push_notification(
            user_id=user.id,
            title=title,
            body=body,
            url=f"/chat/{chat_id}"
        ):
            sent_count += 1
        else:
            # Fallback: Speichere Benachrichtigung für lokale Anzeige
            # aber nur wenn keine Push-Subscription vorhanden ist
            notification_log = NotificationLog(
                user_id=user.id,
                title=title,
                body=body,
                icon="/static/img/logo.png",
                url=f"/chat/{chat_id}",
                success=False,
                is_read=False
            )
            db.session.add(notification_log)
            db.session.commit()
            sent_count += 1
    
    return sent_count


def send_file_notification(
    file_id: int,
    notification_type: str = 'new'  # 'new' oder 'modified'
) -> int:
    """
    Sendet Push-Benachrichtigungen für neue oder geänderte Dateien.
    
    Args:
        file_id: ID der Datei
        notification_type: Art der Benachrichtigung ('new' oder 'modified')
    
    Returns:
        int: Anzahl der gesendeten Benachrichtigungen
    """
    file = File.query.get(file_id)
    if not file:
        return 0
    
    # Hole alle Benutzer mit aktivierten Datei-Benachrichtigungen
    users = User.query.join(NotificationSettings).filter(
        NotificationSettings.file_notifications_enabled == True
    ).all()
    
    sent_count = 0
    
    for user in users:
        settings = get_or_create_notification_settings(user.id)
        
        # Prüfe spezifische Datei-Benachrichtigungseinstellungen
        if notification_type == 'new' and not settings.file_new_notifications:
            continue
        if notification_type == 'modified' and not settings.file_modified_notifications:
            continue
        
        # Überspringe den Uploader
        if user.id == file.uploader_id:
            continue
        
        title = f"Neue Datei" if notification_type == 'new' else f"Datei geändert"
        body = f"{file.name} wurde {'hochgeladen' if notification_type == 'new' else 'geändert'}"
        
        if send_push_notification(
            user_id=user.id,
            title=title,
            body=body,
            url=f"/files/view/{file_id}"
        ):
            sent_count += 1
    
    return sent_count


def send_email_notification(
    email_id: int
) -> int:
    """
    Sendet Push-Benachrichtigungen für neue E-Mails.
    
    Args:
        email_id: ID der E-Mail
    
    Returns:
        int: Anzahl der gesendeten Benachrichtigungen
    """
    email = EmailMessage.query.get(email_id)
    if not email:
        return 0
    
    # Hole alle Benutzer mit aktivierten E-Mail-Benachrichtigungen
    users = User.query.join(NotificationSettings).filter(
        NotificationSettings.email_notifications_enabled == True
    ).all()
    
    sent_count = 0
    
    for user in users:
        title = "Neue E-Mail"
        body = f"Von: {email.sender} - Betreff: {email.subject[:50]}..."
        
        if send_push_notification(
            user_id=user.id,
            title=title,
            body=body,
            url=f"/email/view/{email_id}"
        ):
            sent_count += 1
    
    return sent_count


def send_calendar_notification(
    event_id: int,
    reminder_minutes: int = 30
) -> int:
    """
    Sendet Push-Benachrichtigungen für Kalender-Events.
    
    Args:
        event_id: ID des Events
        reminder_minutes: Minuten vor dem Event
    
    Returns:
        int: Anzahl der gesendeten Benachrichtigungen
    """
    event = CalendarEvent.query.get(event_id)
    if not event:
        return 0
    
    # Hole alle Benutzer mit aktivierten Kalender-Benachrichtigungen
    users = User.query.join(NotificationSettings).filter(
        NotificationSettings.calendar_notifications_enabled == True
    ).all()
    
    sent_count = 0
    
    for user in users:
        settings = get_or_create_notification_settings(user.id)
        
        # Prüfe Teilnahme-Status
        participation = EventParticipant.query.filter_by(
            event_id=event_id,
            user_id=user.id
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
            elif settings.calendar_no_response:
                should_notify = True
        
        if not should_notify:
            continue
        
        # Formatiere Zeit
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
        
        title = f"Termin-Erinnerung"
        body = f"{event.title} {time_text} ({date_str} um {time_str})"
        
        if send_push_notification(
            user_id=user.id,
            title=title,
            body=body,
            url=f"/calendar/view/{event_id}"
        ):
            sent_count += 1
    
    return sent_count


def schedule_calendar_reminders():
    """
    Plant Kalender-Erinnerungen basierend auf den Benutzereinstellungen.
    Diese Funktion sollte regelmäßig (z.B. alle 5 Minuten) aufgerufen werden.
    """
    now = datetime.utcnow()
    
    # Hole alle Events in den nächsten 7 Tagen
    future_events = CalendarEvent.query.filter(
        CalendarEvent.start_time > now,
        CalendarEvent.start_time <= now + timedelta(days=7)
    ).all()
    
    for event in future_events:
        # Hole alle Benutzer mit Kalender-Benachrichtigungen
        users = User.query.join(NotificationSettings).filter(
            NotificationSettings.calendar_notifications_enabled == True
        ).all()
        
        for user in users:
            settings = get_or_create_notification_settings(user.id)
            reminder_times = settings.get_reminder_times()
            
            for reminder_minutes in reminder_times:
                reminder_time = event.start_time - timedelta(minutes=reminder_minutes)
                
                # Prüfe ob es Zeit für diese Erinnerung ist (mit 5 Minuten Toleranz)
                if abs((reminder_time - now).total_seconds()) <= 300:  # 5 Minuten
                    send_calendar_notification(event.id, reminder_minutes)


def register_push_subscription(user_id: int, subscription_data: Dict) -> bool:
    """
    Registriert eine neue Push-Subscription für einen Benutzer.
    
    Args:
        user_id: ID des Benutzers
        subscription_data: Subscription-Daten vom Browser
    
    Returns:
        bool: True wenn erfolgreich registriert
    """
    try:
        endpoint = subscription_data.get('endpoint')
        keys = subscription_data.get('keys', {})
        
        if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
            return False
        
        # Prüfe ob Subscription bereits existiert
        existing = PushSubscription.query.filter_by(
            user_id=user_id,
            endpoint=endpoint
        ).first()
        
        if existing:
            # Update bestehende Subscription
            existing.p256dh_key = keys['p256dh']
            existing.auth_key = keys['auth']
            existing.last_used = datetime.utcnow()
            existing.is_active = True
        else:
            # Erstelle neue Subscription
            new_subscription = PushSubscription(
                user_id=user_id,
                endpoint=endpoint,
                p256dh_key=keys['p256dh'],
                auth_key=keys['auth'],
                user_agent=subscription_data.get('user_agent')
            )
            db.session.add(new_subscription)
        
        db.session.commit()
        return True
        
    except Exception as e:
        logging.error(f"Fehler beim Registrieren der Push-Subscription: {e}")
        db.session.rollback()
        return False


def cleanup_inactive_subscriptions():
    """Bereinigt inaktive Push-Subscriptions."""
    from datetime import timedelta
    
    # Lösche Subscriptions die länger als 30 Tage nicht verwendet wurden
    cutoff_date = datetime.utcnow() - timedelta(days=30)
    
    inactive_subscriptions = PushSubscription.query.filter(
        PushSubscription.last_used < cutoff_date,
        PushSubscription.is_active == True
    ).all()
    
    for subscription in inactive_subscriptions:
        subscription.is_active = False
    
    db.session.commit()
    logging.info(f"{len(inactive_subscriptions)} inaktive Push-Subscriptions deaktiviert")
