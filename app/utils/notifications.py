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

# VAPID Keys aus Config laden
from flask import current_app
import re
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def get_vapid_keys():
    """Lade VAPID Keys aus der App-Konfiguration."""
    private_key = current_app.config.get('VAPID_PRIVATE_KEY')
    public_key = current_app.config.get('VAPID_PUBLIC_KEY')
    
    if not private_key or not public_key:
        logging.warning("VAPID Keys nicht konfiguriert. Push-Benachrichtigungen deaktiviert.")
        return None, None, None
    
    # DEBUG: Logge die ursprünglichen Keys
    logging.info(f"VAPID Private Key (erste 20 Zeichen): {private_key[:20]}...")
    logging.info(f"VAPID Public Key (erste 20 Zeichen): {public_key[:20]}...")
    
    # Konvertiere base64url Private Key zu PEM (SEC1 Format für pywebpush)
    converted_private_key = private_key
    
    try:
        if private_key and not private_key.startswith('-----BEGIN'):
            # base64url zu base64 konvertieren
            b64 = private_key.replace('-', '+').replace('_', '/')
            b64 += '=' * ((4 - len(b64) % 4) % 4)
            
            # Dekodiere zu RAW (32 Bytes für EC Private Key)
            raw = base64.b64decode(b64)
            if len(raw) == 32:
                # Erstelle EC Private Key aus RAW
                priv_int = int.from_bytes(raw, 'big')
                priv_obj = ec.derive_private_key(priv_int, ec.SECP256R1())
                # Verwende SEC1 Format (TraditionalOpenSSL) - das funktioniert!
                converted_private_key = priv_obj.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ).decode('ascii')
                logging.info("VAPID Private Key erfolgreich zu SEC1 PEM konvertiert")
            else:
                logging.error(f"VAPID Private Key hat unerwartete Länge: {len(raw)} Bytes (erwartet: 32)")
    except Exception as e:
        logging.error(f"VAPID Private Key Konvertierung fehlgeschlagen: {e}")
        # Verwende Original-Key als Fallback

    vapid_claims = {
        "sub": "mailto:admin@yourdomain.com"  # E-Mail des Administrators
    }
    
    return converted_private_key, public_key, vapid_claims


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
    Optimiert für serverbasiertes Push-System mit verbessertem Error Handling.
    
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
    
    # Lade VAPID Keys aus Config
    vapid_private_key, vapid_public_key, vapid_claims = get_vapid_keys()
    if not vapid_private_key:
        logging.error("VAPID Keys nicht konfiguriert - Push-Benachrichtigungen deaktiviert")
        print("VAPID Keys nicht konfiguriert - Push-Benachrichtigungen deaktiviert")
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
        return False
    
    logging.info(f"Gefunden {len(subscriptions)} Push-Subscriptions für Benutzer {user_id}")
    
    # Lade Portal-Name und Logo aus Datenbank für Standard-Werte
    try:
        from app.models.settings import SystemSettings
        from flask import url_for, current_app
        
        # Portal-Name aus Datenbank (wenn title nicht angegeben oder Standard)
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        
        # Portal-Logo aus Datenbank
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            # Portal-Logo URL erstellen
            portal_logo_url = url_for('settings.portal_logo', filename=portal_logo_setting.value, _external=True)
            if not icon or icon == "/static/img/logo.png":
                icon = portal_logo_url
        else:
            # Fallback zu statischem Logo
            if not icon or icon == "":
                icon = url_for('static', filename='img/logo.png', _external=True)
    except Exception as e:
        logging.warning(f"Could not load portal settings for push notification: {e}")
        # Fallback zu statischem Logo
        if not icon or icon == "":
            try:
                icon = url_for('static', filename='img/logo.png', _external=True)
            except:
                icon = "/static/img/logo.png"
    
    success_count = 0
    total_count = len(subscriptions)
    
    # Bereite Payload vor (einmal für alle Subscriptions)
    payload = {
        "title": title,
        "body": body,
        "icon": icon,
        "url": url or "/",
        "data": data or {}
    }
    
    def ensure_padded_base64url(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return value
        v = value.strip()
        # Belasse urlsafe-Zeichen, füge nur Padding hinzu
        padding = (4 - (len(v) % 4)) % 4
        if padding:
            v += '=' * padding
        return v

    for subscription in subscriptions:
        try:
            # Subscription vorbereiten: korrekte Base64url-Padding hinzufügen
            sub_info = subscription.to_dict()
            if 'keys' in sub_info:
                sub_info['keys'] = dict(sub_info['keys'])
                sub_info['keys']['p256dh'] = ensure_padded_base64url(sub_info['keys'].get('p256dh'))
                sub_info['keys']['auth'] = ensure_padded_base64url(sub_info['keys'].get('auth'))

            # Sende Push-Benachrichtigung - verwende base64url-Key direkt
            # pywebpush kann base64url-Keys direkt verarbeiten
            original_private_key = current_app.config.get('VAPID_PRIVATE_KEY')
            webpush(
                subscription_info=sub_info,
                data=json.dumps(payload),
                vapid_private_key=original_private_key,
                vapid_claims=vapid_claims,
                ttl=86400  # 24 Stunden TTL
            )
            
            # Update last_used
            subscription.last_used = datetime.utcnow()
            success_count += 1
            
            logging.info(f"Push-Benachrichtigung erfolgreich gesendet an Benutzer {user_id}")
            
        except WebPushException as e:
            logging.error(f"WebPush Fehler für Benutzer {user_id}: {e}")
            
            # Deaktiviere Subscription bei permanenten Fehlern
            if e.response and e.response.status_code in [410, 404, 400]:
                subscription.is_active = False
                logging.info(f"Push-Subscription {subscription.id} deaktiviert (Status: {e.response.status_code})")
                # Sofort in Datenbank speichern
                try:
                    db.session.commit()
                except Exception as commit_error:
                    logging.error(f"Fehler beim Speichern der Subscription-Deaktivierung: {commit_error}")
            
        except Exception as e:
            logging.error(f"Unerwarteter Fehler beim Senden der Push-Benachrichtigung: {e}")
    
    # Logge das Ergebnis nur bei erfolgreichen Push-Benachrichtigungen
    if success_count > 0:
        try:
            log_entry = NotificationLog(
                user_id=user_id,
                title=title,
                body=body,
                icon=icon,
                url=url,
                success=True,
                is_read=True  # Server-Push-Benachrichtigungen sind automatisch "gelesen"
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            logging.error(f"Fehler beim Loggen der Push-Benachrichtigung: {e}")
            db.session.rollback()
    
    # Commit alle Änderungen
    try:
        db.session.commit()
    except Exception as e:
        logging.error(f"Fehler beim Committen der Push-Subscription Änderungen: {e}")
        db.session.rollback()
    
    logging.info(f"Push-Benachrichtigung Ergebnis: {success_count}/{total_count} erfolgreich")
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
    chat_name: str = None,
    message_id: int = None
) -> int:
    """
    Sendet zusammengefasste Push-Benachrichtigungen für neue Chat-Nachrichten.
    Eine Benachrichtigung pro Chat mit Anzahl der ungelesenen Nachrichten.
    
    Args:
        chat_id: ID des Chats
        sender_id: ID des Absenders
        message_content: Inhalt der Nachricht
        chat_name: Name des Chats
        message_id: ID der Nachricht (für Duplikat-Vermeidung)
    
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
        
        # Zähle ungelesene Nachrichten in diesem Chat
        unread_count = ChatMessage.query.filter(
            ChatMessage.chat_id == chat_id,
            ChatMessage.sender_id != user.id,
            ChatMessage.created_at > member.last_read_at,
            ChatMessage.is_deleted == False
        ).count()
        
        if unread_count == 0:
            continue  # Keine ungelesenen Nachrichten
        
        # Prüfe ob bereits eine Benachrichtigung für diesen Chat in den letzten 30 Sekunden gesendet wurde
        # Wenn ja, prüfe ob sich die Anzahl der ungelesenen Nachrichten erhöht hat
        existing_notification = NotificationLog.query.filter_by(
            user_id=user.id,
            url=f"/chat/{chat_id}",
            success=True
        ).filter(
            NotificationLog.sent_at >= datetime.utcnow() - timedelta(seconds=30)
        ).order_by(NotificationLog.sent_at.desc()).first()
        
        if existing_notification:
            # Extrahiere die alte Anzahl aus dem Body der letzten Benachrichtigung
            old_body = existing_notification.body or ""
            # Suche nach "X neue Nachricht(en)" - unterstützt sowohl Singular als auch Plural
            old_count_match = re.search(r'(\d+)\s+neue\s+Nachricht(?:en)?', old_body)
            old_count = int(old_count_match.group(1)) if old_count_match else 0
            
            # Wenn die Anzahl gleich geblieben ist, überspringe (verhindert Duplikate bei gleichzeitigen Nachrichten)
            if old_count >= unread_count:
                logging.info(f"Chat-Benachrichtigung übersprungen: Anzahl unverändert ({old_count} -> {unread_count})")
                continue
            # Wenn die Anzahl erhöht wurde, sende eine neue Benachrichtigung mit aktualisierter Anzahl
        
        # Erstelle zusammengefasste Benachrichtigung
        if unread_count == 1:
            title = f'"{chat_name or "Team Chat"}"'
            body = f'1 neue Nachricht'
        else:
            title = f'"{chat_name or "Team Chat"}"'
            body = f'{unread_count} neue Nachrichten'
        
        # Sende Server-Push-Benachrichtigung
        push_success = send_push_notification(
            user_id=user.id,
            title=title,
            body=body,
            url=f"/chat/{chat_id}",
            data={'chat_id': chat_id, 'unread_count': unread_count}
        )
        
        if push_success:
            logging.info(f"Chat-Push-Benachrichtigung erfolgreich gesendet an Benutzer {user.id}")
        else:
            logging.warning(f"Chat-Push-Benachrichtigung fehlgeschlagen für Benutzer {user.id}")
        
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
            url=f"/files/view/{file_id}",
            data={'file_id': file_id, 'file_name': file.name, 'type': 'file', 'action': notification_type}
        ):
            sent_count += 1
    
    return sent_count


def send_email_notification(
    email_id: int
) -> int:
    """
    Sendet zusammengefasste Push-Benachrichtigungen für neue E-Mails.
    Eine Benachrichtigung pro Benutzer mit Anzahl der ungelesenen E-Mails.
    
    Args:
        email_id: ID der E-Mail
    
    Returns:
        int: Anzahl der gesendeten Benachrichtigungen
    """
    print(f"=== UTILS: E-MAIL-BENACHRICHTIGUNG START ===")
    print(f"UTILS: E-Mail-Benachrichtigung für E-Mail ID: {email_id}")
    
    # Verwende flush() um sicherzustellen, dass die E-Mail in der Datenbank verfügbar ist
    try:
        db.session.flush()
        email = EmailMessage.query.get(email_id)
        if not email:
            print(f"UTILS: E-Mail mit ID {email_id} nicht gefunden")
            return 0
        
        print(f"UTILS: E-Mail gefunden: {email.subject}")
    except Exception as e:
        print(f"UTILS: Fehler beim Laden der E-Mail: {e}")
        return 0
    
    # Hole alle Benutzer mit aktivierten E-Mail-Benachrichtigungen
    try:
        users = User.query.join(NotificationSettings).filter(
            NotificationSettings.email_notifications_enabled == True
        ).all()
        
        print(f"UTILS: {len(users)} Benutzer mit aktivierten E-Mail-Benachrichtigungen gefunden")
    except Exception as e:
        print(f"UTILS: Fehler beim Laden der Benutzer: {e}")
        return 0
    
    sent_count = 0
    
    for user in users:
        print(f"UTILS: Verarbeite Benutzer {user.id} ({user.username})")
        
        # Zähle ungelesene E-Mails
        unread_count = EmailMessage.query.filter(
            EmailMessage.is_read == False,
            EmailMessage.is_sent == False  # Nur empfangene E-Mails
        ).count()
        
        print(f"UTILS: {unread_count} ungelesene E-Mails für Benutzer {user.id}")
        
        if unread_count == 0:
            print(f"UTILS: Keine ungelesenen E-Mails für Benutzer {user.id}")
            continue  # Keine ungelesenen E-Mails
        
        # Prüfe ob bereits eine E-Mail-Benachrichtigung in den letzten 30 Sekunden gesendet wurde
        # Wenn ja, prüfe ob sich die Anzahl der ungelesenen E-Mails erhöht hat
        existing_notification = NotificationLog.query.filter_by(
            user_id=user.id,
            url="/email/",
            success=True
        ).filter(
            NotificationLog.sent_at >= datetime.utcnow() - timedelta(seconds=30)
        ).order_by(NotificationLog.sent_at.desc()).first()
        
        if existing_notification:
            # Extrahiere die alte Anzahl aus dem Body der letzten Benachrichtigung
            old_body = existing_notification.body or ""
            # Suche nach "X neue E-Mail(s)" - unterstützt sowohl Singular als auch Plural
            old_count_match = re.search(r'(\d+)\s+neue\s+E-Mail(?:s)?', old_body)
            old_count = int(old_count_match.group(1)) if old_count_match else 0
            
            # Wenn die Anzahl gleich geblieben ist, überspringe (verhindert Duplikate bei gleichzeitigen E-Mails)
            if old_count >= unread_count:
                print(f"UTILS: E-Mail-Benachrichtigung übersprungen: Anzahl unverändert ({old_count} -> {unread_count})")
                continue
            # Wenn die Anzahl erhöht wurde, sende eine neue Benachrichtigung mit aktualisierter Anzahl
        
        # Erstelle zusammengefasste Benachrichtigung
        if unread_count == 1:
            title = "E-Mail"
            body = "1 neue E-Mail"
        else:
            title = "E-Mail"
            body = f"{unread_count} neue E-Mails"
        
        print(f"UTILS: Erstelle Benachrichtigung: {title} - {body}")
        
        # Sende Server-Push-Benachrichtigung
        try:
            push_success = send_push_notification(
                user_id=user.id,
                title=title,
                body=body,
                url="/email/",
                data={'unread_count': unread_count, 'type': 'email'}
            )
            
            if push_success:
                logging.info(f"E-Mail-Push-Benachrichtigung erfolgreich gesendet an Benutzer {user.id}")
            else:
                logging.warning(f"E-Mail-Push-Benachrichtigung fehlgeschlagen für Benutzer {user.id}")
        except Exception as e:
            logging.error(f"Fehler beim Senden der E-Mail-Push-Benachrichtigung für Benutzer {user.id}: {e}")
        
        sent_count += 1
    
    print(f"=== UTILS: E-MAIL-BENACHRICHTIGUNG ENDE - {sent_count} Benachrichtigungen gesendet ===")
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
            url=f"/calendar/view/{event_id}",
            data={'event_id': event_id, 'event_title': event.title, 'type': 'calendar', 'reminder_minutes': reminder_minutes}
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
        print(f"=== UTILS: PUSH-SUBSCRIPTION REGISTRIERUNG ===")
        print(f"UTILS: Registriere Push-Subscription für Benutzer {user_id}")
        print(f"UTILS: Subscription-Daten: {subscription_data}")
        
        endpoint = subscription_data.get('endpoint')
        keys = subscription_data.get('keys', {})

        # Normalisiere Schlüssel auf base64url (pywebpush erwartet urlsafe, ohne Padding)
        def to_base64url(value: str) -> str:
            if not isinstance(value, str):
                return value
            v = value.strip()
            # wenn bereits urlsafe, nur Padding entfernen
            v = v.replace('+', '-').replace('/', '_')
            v = v.rstrip('=')
            return v

        if 'p256dh' in keys:
            keys['p256dh'] = to_base64url(keys['p256dh'])
        if 'auth' in keys:
            keys['auth'] = to_base64url(keys['auth'])
        
        print(f"UTILS: Endpoint: {endpoint}")
        print(f"UTILS: Keys: {keys}")
        
        if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
            print("UTILS: Fehler: Endpoint oder Keys fehlen")
            print(f"UTILS: Endpoint vorhanden: {bool(endpoint)}")
            print(f"UTILS: p256dh Key vorhanden: {bool(keys.get('p256dh'))}")
            print(f"UTILS: auth Key vorhanden: {bool(keys.get('auth'))}")
            return False
        
        # Prüfe ob Subscription bereits existiert
        existing = PushSubscription.query.filter_by(
            user_id=user_id,
            endpoint=endpoint
        ).first()
        
        if existing:
            print(f"UTILS: Update bestehende Push-Subscription für Benutzer {user_id}")
            # Update bestehende Subscription
            existing.p256dh_key = keys['p256dh']
            existing.auth_key = keys['auth']
            existing.last_used = datetime.utcnow()
            existing.is_active = True
        else:
            print(f"UTILS: Erstelle neue Push-Subscription für Benutzer {user_id}")
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
        print(f"UTILS: Push-Subscription erfolgreich registriert für Benutzer {user_id}")
        
        # Verifiziere dass die Subscription gespeichert wurde
        saved_subscription = PushSubscription.query.filter_by(
            user_id=user_id,
            endpoint=endpoint
        ).first()
        
        if saved_subscription:
            print(f"=== UTILS: PUSH-SUBSCRIPTION ERFOLGREICH VERIFIZIERT ===")
            print(f"UTILS: Push-Subscription erfolgreich verifiziert für Benutzer {user_id}")
            print(f"UTILS: Verifizierte Subscription ID: {saved_subscription.id}")
            return True
        else:
            print(f"=== UTILS: PUSH-SUBSCRIPTION VERIFIZIERUNG FEHLGESCHLAGEN ===")
            print(f"UTILS: Fehler: Push-Subscription konnte nicht verifiziert werden für Benutzer {user_id}")
            return False
        
    except Exception as e:
        logging.error(f"Fehler beim Registrieren der Push-Subscription: {e}")
        print(f"=== UTILS: EXCEPTION BEI PUSH-SUBSCRIPTION REGISTRIERUNG ===")
        print(f"UTILS: Fehler beim Registrieren der Push-Subscription: {e}")
        import traceback
        print(f"UTILS: Exception Stack: {traceback.format_exc()}")
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


def cleanup_failed_subscriptions():
    """Bereinigt fehlgeschlagene Push-Subscriptions basierend auf WebPush-Fehlern."""
    try:
        # Deaktiviere alle Subscriptions die alt sind (älter als 1 Stunde)
        # Diese werden beim nächsten Test automatisch neu erstellt
        old_subscriptions = PushSubscription.query.filter_by(is_active=True).all()
        
        deactivated_count = 0
        for subscription in old_subscriptions:
            # Prüfe ob Subscription alt ist (älter als 1 Stunde)
            if subscription.created_at < datetime.utcnow() - timedelta(hours=1):
                subscription.is_active = False
                deactivated_count += 1
        
        if deactivated_count > 0:
            db.session.commit()
            logging.info(f"{deactivated_count} alte Push-Subscriptions deaktiviert")
            
    except Exception as e:
        logging.error(f"Fehler beim Bereinigen alter Subscriptions: {e}")

def deactivate_failed_subscription(subscription_id, error_type="410"):
    """Deaktiviert eine spezifische fehlgeschlagene Subscription."""
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
