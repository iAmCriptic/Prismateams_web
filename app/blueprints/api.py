from flask import Blueprint, jsonify, request, url_for
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.chat import Chat, ChatMessage, ChatMember
from app.models.file import File, Folder
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.email import EmailMessage
from app.models.notification import PushSubscription
from app.utils.notifications import register_push_subscription, send_push_notification
from datetime import datetime

api_bp = Blueprint('api', __name__)


# User API
@api_bp.route('/users', methods=['GET'])
@login_required
def get_users():
    """Get all active users."""
    users = User.query.filter_by(is_active=True).all()
    return jsonify([{
        'id': user.id,
        'email': user.email,
        'full_name': user.full_name,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_admin': user.is_admin,
        'profile_picture': url_for('settings.profile_picture', filename=user.profile_picture) if user.profile_picture else None
    } for user in users])


@api_bp.route('/users/<int:user_id>', methods=['GET'])
@login_required
def get_user(user_id):
    """Get a specific user."""
    user = User.query.get_or_404(user_id)
    return jsonify({
        'id': user.id,
        'email': user.email,
        'full_name': user.full_name,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'phone': user.phone,
        'is_admin': user.is_admin,
        'profile_picture': url_for('settings.profile_picture', filename=user.profile_picture) if user.profile_picture else None,
        'accent_color': user.accent_color,
        'dark_mode': user.dark_mode
    })


# Chat API
@api_bp.route('/chats', methods=['GET'])
@login_required
def get_chats():
    """Get all chats for current user."""
    memberships = ChatMember.query.filter_by(user_id=current_user.id).all()
    chats = []
    
    for membership in memberships:
        chat = membership.chat
        # Get unread count
        unread_count = ChatMessage.query.filter(
            ChatMessage.chat_id == chat.id,
            ChatMessage.created_at > membership.last_read_at,
            ChatMessage.sender_id != current_user.id
        ).count()
        
        # Get last message
        last_message = ChatMessage.query.filter_by(
            chat_id=chat.id,
            is_deleted=False
        ).order_by(ChatMessage.created_at.desc()).first()
        
        # Get display name (for private chats, show only other person's name)
        display_name = chat.name
        if chat.is_direct_message and not chat.is_main_chat:
            # Get the other member (not the current user)
            members = ChatMember.query.filter_by(chat_id=chat.id).all()
            for member in members:
                if member.user_id != current_user.id:
                    display_name = member.user.full_name
                    break
        
        chats.append({
            'id': chat.id,
            'name': display_name,
            'is_main_chat': chat.is_main_chat,
            'is_direct_message': chat.is_direct_message,
            'unread_count': unread_count,
            'last_message': {
                'content': last_message.content,
                'created_at': last_message.created_at.isoformat(),
                'sender': last_message.sender.full_name
            } if last_message else None
        })
    
    return jsonify(chats)


@api_bp.route('/chats/<int:chat_id>/messages', methods=['GET'])
@login_required
def get_messages(chat_id):
    """Get messages from a chat."""
    # Check membership
    membership = ChatMember.query.filter_by(
        chat_id=chat_id,
        user_id=current_user.id
    ).first()
    
    if not membership:
        return jsonify({'error': 'Nicht autorisiert'}), 403
    
    # Check if we want messages since a specific ID
    since_id = request.args.get('since', type=int)
    
    query = ChatMessage.query.filter_by(
        chat_id=chat_id,
        is_deleted=False
    )
    
    if since_id:
        query = query.filter(ChatMessage.id > since_id)
    
    messages = query.order_by(ChatMessage.created_at).all()
    
    from app.utils import get_local_time
    
    return jsonify([{
        'id': msg.id,
        'sender_id': msg.sender_id,
        'sender_name': msg.sender.full_name if msg.sender else 'Unbekannter Benutzer',
        'sender': msg.sender.full_name if msg.sender else 'Unbekannter Benutzer',  # Alias for compatibility
        'content': msg.content,
        'message_type': msg.message_type,
        'media_url': msg.media_url,
        'created_at': get_local_time(msg.created_at).isoformat()
    } for msg in messages])


@api_bp.route('/users/<int:user_id>/status', methods=['GET'])
@login_required
def get_user_status(user_id):
    """Get online status of a user."""
    user = User.query.get_or_404(user_id)
    return jsonify({
        'id': user.id,
        'is_online': user.is_online(),
        'last_seen': user.last_seen.isoformat() if user.last_seen else None
    })


@api_bp.route('/users/update-last-seen', methods=['POST'])
@login_required
def update_last_seen():
    """Update current user's last_seen timestamp."""
    try:
        current_user.update_last_seen()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/chats/<int:chat_id>/members', methods=['GET'])
@login_required
def get_chat_members(chat_id):
    """Get members of a chat."""
    # Check membership
    membership = ChatMember.query.filter_by(
        chat_id=chat_id,
        user_id=current_user.id
    ).first()
    
    if not membership:
        return jsonify({'error': 'Nicht autorisiert'}), 403
    
    # Get all chat members - use ChatMember as base to ensure all members are included
    chat_memberships = ChatMember.query.filter_by(chat_id=chat_id).all()
    member_ids = [cm.user_id for cm in chat_memberships]
    members = User.query.filter(User.id.in_(member_ids)).all() if member_ids else []
    
    chat = Chat.query.get_or_404(chat_id)
    
    return jsonify([{
        'id': member.id,
        'full_name': member.full_name,
        'email': member.email,
        'phone': member.phone,
        'profile_picture': url_for('settings.profile_picture', filename=member.profile_picture) if member.profile_picture else None,
        'is_admin': member.is_admin,
        'is_creator': member.id == chat.created_by,
        'is_online': member.is_online()
    } for member in members])


# Calendar API
@api_bp.route('/events', methods=['GET'])
@login_required
def get_events():
    """Get all calendar events."""
    events = CalendarEvent.query.order_by(CalendarEvent.start_time).all()
    
    result = []
    for event in events:
        participation = EventParticipant.query.filter_by(
            event_id=event.id,
            user_id=current_user.id
        ).first()
        
        result.append({
            'id': event.id,
            'title': event.title,
            'description': event.description,
            'start_time': event.start_time.isoformat(),
            'end_time': event.end_time.isoformat(),
            'location': event.location,
            'created_by': event.creator.full_name,
            'participation_status': participation.status if participation else 'pending'
        })
    
    return jsonify(result)


@api_bp.route('/events/<int:event_id>', methods=['GET'])
@login_required
def get_event(event_id):
    """Get a specific event."""
    event = CalendarEvent.query.get_or_404(event_id)
    participants = EventParticipant.query.filter_by(event_id=event_id).all()
    
    return jsonify({
        'id': event.id,
        'title': event.title,
        'description': event.description,
        'start_time': event.start_time.isoformat(),
        'end_time': event.end_time.isoformat(),
        'location': event.location,
        'created_by': event.creator.full_name,
        'participants': [{
            'user_id': p.user_id,
            'user_name': p.user.full_name,
            'status': p.status
        } for p in participants]
    })


# Files API
@api_bp.route('/files', methods=['GET'])
@login_required
def get_files():
    """Get files in a folder."""
    folder_id = request.args.get('folder_id', type=int)
    
    files = File.query.filter_by(
        folder_id=folder_id,
        is_current=True
    ).order_by(File.name).all()
    
    return jsonify([{
        'id': file.id,
        'name': file.name,
        'size': file.file_size,
        'mime_type': file.mime_type,
        'version': file.version_number,
        'uploaded_by': file.uploader.full_name,
        'uploaded_at': file.created_at.isoformat()
    } for file in files])


@api_bp.route('/folders', methods=['GET'])
@login_required
def get_folders():
    """Get subfolders in a folder."""
    parent_id = request.args.get('parent_id', type=int)
    
    folders = Folder.query.filter_by(parent_id=parent_id).order_by(Folder.name).all()
    
    return jsonify([{
        'id': folder.id,
        'name': folder.name,
        'created_at': folder.created_at.isoformat()
    } for folder in folders])


# Dashboard API
@api_bp.route('/dashboard/stats', methods=['GET'])
@login_required
def get_dashboard_stats():
    """Get dashboard statistics."""
    # Upcoming events count
    upcoming_events = CalendarEvent.query.filter(
        CalendarEvent.start_time >= datetime.utcnow()
    ).count()
    
    # Unread messages count
    user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
    unread_count = 0
    for membership in user_chats:
        count = ChatMessage.query.filter(
            ChatMessage.chat_id == membership.chat_id,
            ChatMessage.created_at > membership.last_read_at,
            ChatMessage.sender_id != current_user.id
        ).count()
        unread_count += count
    
    # Unread emails count
    unread_emails = EmailMessage.query.filter_by(is_read=False, is_sent=False).count()
    
    # Total files
    total_files = File.query.filter_by(is_current=True).count()
    
    return jsonify({
        'upcoming_events': upcoming_events,
        'unread_messages': unread_count,
        'unread_emails': unread_emails,
        'total_files': total_files
    })


@api_bp.route('/files/recent', methods=['GET'])
@login_required
def get_recent_files():
    """Get recent files edited by current user."""
    files = File.query.filter_by(
        uploaded_by=current_user.id
    ).order_by(File.updated_at.desc()).limit(3).all()
    
    return jsonify([{
        'id': file.id,
        'name': file.name,
        'original_name': file.original_name,
        'updated_at': file.updated_at.isoformat(),
        'mime_type': file.mime_type,
        'url': url_for('files.view_file', file_id=file.id)
    } for file in files])


# Push Notifications API
@api_bp.route('/push/subscribe', methods=['POST'])
@login_required
def subscribe_push():
    """Register push subscription for current user."""
    try:
        print(f"=== API: PUSH-SUBSCRIPTION REGISTRIERUNG ===")
        print(f"API: Push-Subscription Registrierung für Benutzer {current_user.id}")
        print(f"API: Request Headers: {dict(request.headers)}")
        print(f"API: Request Method: {request.method}")
        print(f"API: Request Content-Type: {request.content_type}")
        
        data = request.get_json()
        print(f"API: Empfangene Daten: {data}")
        
        # Unterstütze sowohl altes als auch neues Format
        if 'subscription' in data:
            # Altes Format: {subscription: {...}, user_agent: '...'}
            subscription_data = data.get('subscription')
            user_agent = data.get('user_agent', '')
        else:
            # Neues Format: direkt die Subscription-Daten
            subscription_data = data
            user_agent = data.get('user_agent', '')
        
        if not subscription_data:
            print("API: Fehler: Subscription-Daten fehlen")
            return jsonify({'error': 'Subscription-Daten fehlen'}), 400
        
        print(f"API: Subscription-Daten: {subscription_data}")
        print(f"API: Subscription Endpoint: {subscription_data.get('endpoint')}")
        print(f"API: Subscription Keys: {subscription_data.get('keys')}")
        
        # Registriere Push-Subscription
        success = register_push_subscription(current_user.id, subscription_data)
        
        if success:
            print(f"=== API: PUSH-SUBSCRIPTION ERFOLGREICH REGISTRIERT ===")
            print(f"API: Push-Subscription erfolgreich registriert für Benutzer {current_user.id}")
            return jsonify({'message': 'Push-Subscription erfolgreich registriert', 'success': True})
        else:
            print(f"=== API: PUSH-SUBSCRIPTION REGISTRIERUNG FEHLGESCHLAGEN ===")
            print(f"API: Fehler bei der Push-Subscription Registrierung für Benutzer {current_user.id}")
            return jsonify({'error': 'Fehler bei der Registrierung', 'success': False}), 500
            
    except Exception as e:
        print(f"=== API: EXCEPTION BEI PUSH-SUBSCRIPTION REGISTRIERUNG ===")
        print(f"API: Exception bei Push-Subscription Registrierung: {e}")
        print(f"API: Exception Details: {str(e)}")
        import traceback
        print(f"API: Exception Stack: {traceback.format_exc()}")
        return jsonify({'error': str(e), 'success': False}), 500


@api_bp.route('/push/unsubscribe', methods=['POST'])
@login_required
def unsubscribe_push():
    """Unregister push subscription for current user."""
    try:
        # Deaktiviere alle Push-Subscriptions des Benutzers
        subscriptions = PushSubscription.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).all()
        
        for subscription in subscriptions:
            subscription.is_active = False
        
        db.session.commit()
        
        return jsonify({'message': 'Push-Subscription erfolgreich deaktiviert'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Entfernt: doppelte /push/test Route, siehe weiter unten test_push_notification


@api_bp.route('/push/status', methods=['GET'])
@login_required
def push_status():
    """Get push notification status for current user."""
    try:
        # Prüfe ob aktive Subscriptions existieren
        active_subscriptions = PushSubscription.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).count()
        
        return jsonify({
            'has_subscription': active_subscriptions > 0,
            'subscription_count': active_subscriptions,
            'notifications_enabled': current_user.notifications_enabled,
            'chat_notifications': current_user.chat_notifications
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Notification Settings API
@api_bp.route('/notifications/settings', methods=['GET'])
@login_required
def get_notification_settings():
    """Hole Benachrichtigungseinstellungen des aktuellen Benutzers."""
    try:
        from app.utils.notifications import get_or_create_notification_settings
        
        settings = get_or_create_notification_settings(current_user.id)
        
        return jsonify({
            'chat_notifications_enabled': settings.chat_notifications_enabled,
            'file_notifications_enabled': settings.file_notifications_enabled,
            'file_new_notifications': settings.file_new_notifications,
            'file_modified_notifications': settings.file_modified_notifications,
            'email_notifications_enabled': settings.email_notifications_enabled,
            'calendar_notifications_enabled': settings.calendar_notifications_enabled,
            'calendar_all_events': settings.calendar_all_events,
            'calendar_participating_only': settings.calendar_participating_only,
            'calendar_not_participating': settings.calendar_not_participating,
            'calendar_no_response': settings.calendar_no_response,
            'reminder_times': settings.get_reminder_times()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/notifications/settings', methods=['POST'])
@login_required
def update_notification_settings():
    """Aktualisiere Benachrichtigungseinstellungen des aktuellen Benutzers."""
    try:
        from app.utils.notifications import get_or_create_notification_settings
        
        data = request.get_json()
        settings = get_or_create_notification_settings(current_user.id)
        
        # Update settings
        settings.chat_notifications_enabled = data.get('chat_notifications_enabled', True)
        settings.file_notifications_enabled = data.get('file_notifications_enabled', True)
        settings.file_new_notifications = data.get('file_new_notifications', True)
        settings.file_modified_notifications = data.get('file_modified_notifications', True)
        settings.email_notifications_enabled = data.get('email_notifications_enabled', True)
        settings.calendar_notifications_enabled = data.get('calendar_notifications_enabled', True)
        settings.calendar_all_events = data.get('calendar_all_events', False)
        settings.calendar_participating_only = data.get('calendar_participating_only', True)
        settings.calendar_not_participating = data.get('calendar_not_participating', False)
        settings.calendar_no_response = data.get('calendar_no_response', False)
        
        # Update reminder times
        reminder_times = data.get('reminder_times', [])
        settings.set_reminder_times(reminder_times)
        
        db.session.commit()
        
        return jsonify({'message': 'Benachrichtigungseinstellungen aktualisiert'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/notifications/chat/<int:chat_id>', methods=['POST'])
@login_required
def update_chat_notification_settings(chat_id):
    """Aktualisiere Chat-spezifische Benachrichtigungseinstellungen."""
    try:
        from app.models.notification import ChatNotificationSettings
        
        data = request.get_json()
        enabled = data.get('enabled', True)
        
        # Prüfe ob Chat existiert und Benutzer Mitglied ist
        from app.models.chat import ChatMember
        membership = ChatMember.query.filter_by(
            chat_id=chat_id,
            user_id=current_user.id
        ).first()
        
        if not membership:
            return jsonify({'error': 'Nicht autorisiert'}), 403
        
        # Hole oder erstelle Chat-Einstellungen
        chat_settings = ChatNotificationSettings.query.filter_by(
            user_id=current_user.id,
            chat_id=chat_id
        ).first()
        
        if not chat_settings:
            chat_settings = ChatNotificationSettings(
                user_id=current_user.id,
                chat_id=chat_id,
                notifications_enabled=enabled
            )
            db.session.add(chat_settings)
        else:
            chat_settings.notifications_enabled = enabled
        
        db.session.commit()
        
        return jsonify({'message': 'Chat-Benachrichtigungseinstellungen aktualisiert'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Polling-Endpoint entfernt - Server-Push-System verwendet

# VAPID Public Key Endpoint
@api_bp.route('/push/vapid-key', methods=['GET'])
@login_required
def get_vapid_public_key():
    """Gibt den VAPID Public Key für Push-Subscriptions zurück."""
    try:
        from flask import current_app
        public_key = current_app.config.get('VAPID_PUBLIC_KEY')

        if not public_key:
            print("VAPID Public Key nicht konfiguriert")
            return jsonify({
                'error': 'VAPID Keys nicht konfiguriert', 
                'message': 'Bitte konfigurieren Sie VAPID Keys in der .env Datei'
            }), 500

        # Unterstütze verschiedene Formate: PEM (-----BEGIN PUBLIC KEY-----) oder bereits Base64URL
        try:
            import re, base64
            key_out = public_key.strip()
            if 'BEGIN PUBLIC KEY' in key_out:
                # Entferne PEM-Header/Trailer und Whitespaces
                pem_b64_any = re.sub(r"-----BEGIN PUBLIC KEY-----|-----END PUBLIC KEY-----|\\n|\n|\r|\s", "", key_out)
                # Einige Generatoren liefern im PEM bereits base64url-Zeichen - in Standard-Base64 überführen
                pem_b64_std = pem_b64_any.replace('-', '+').replace('_', '/')
                # Padding ergänzen
                missing = len(pem_b64_std) % 4
                if missing:
                    pem_b64_std += '=' * (4 - missing)
                # Dekodiere DER SubjectPublicKeyInfo
                der = base64.b64decode(pem_b64_std)
                # Sehr einfache Extraktion des EC Public Key (uncompressed 65 bytes, beginnt mit 0x04)
                # Suche nach erstem 0x04 gefolgt von 64 weiteren Bytes
                idx = der.find(b"\x04")
                raw = None
                if idx != -1 and idx + 65 <= len(der):
                    candidate = der[idx:idx+65]
                    if len(candidate) == 65:
                        raw = candidate
                # Fallback: manchmal enthält BIT STRING ein Präfix 0x03 <len> 0x00 0x04...
                if raw is None:
                    try:
                        # finde BIT STRING (0x03), überspringe Länge und 1 Byte unused-bits
                        bit_idx = der.find(b"\x03")
                        if bit_idx != -1 and bit_idx + 3 < len(der):
                            # Länge-Byte kann lange Form sein; handle nur kurze Form (<128)
                            bit_len = der[bit_idx+1]
                            offset = bit_idx + 2  # nach Länge
                            # ein Byte 'unused bits'
                            unused = der[offset]
                            point_start = offset + 1
                            if point_start < len(der) and der[point_start] == 0x04 and point_start + 65 <= len(der):
                                raw = der[point_start:point_start+65]
                    except Exception:
                        pass
                if raw is None:
                    raise ValueError('Konnte EC Public Key (65 Bytes) nicht aus PEM extrahieren')
                # URL-safe Base64 ohne Padding
                key_out = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
            else:
                # Angenommen bereits base64url
                key_out = key_out.strip()
            return jsonify({'public_key': key_out})
        except Exception as e:
            print(f"VAPID Key Normalisierung fehlgeschlagen: {e}")
            return jsonify({'error': 'VAPID Key Formatfehler', 'message': str(e)}), 500
        
    except Exception as e:
        print(f"VAPID Key Fehler: {e}")
        return jsonify({'error': str(e), 'message': 'Fehler beim Laden der VAPID Keys'}), 500

# Test Push Notification Endpoint
@api_bp.route('/push/test', methods=['POST'])
@login_required
def test_push_notification():
    """Sendet eine Test-Push-Benachrichtigung an den aktuellen Benutzer."""
    try:
        # Prüfe VAPID-Konfiguration frühzeitig und liefere sinnvolle Fehlermeldung statt 500
        from flask import current_app
        vapid_priv = current_app.config.get('VAPID_PRIVATE_KEY')
        vapid_pub = current_app.config.get('VAPID_PUBLIC_KEY')
        if not vapid_priv or not vapid_pub:
            return jsonify({
                'success': False,
                'message': 'VAPID Keys sind nicht konfiguriert. Bitte `VAPID_PUBLIC_KEY` und `VAPID_PRIVATE_KEY` in .env setzen oder `vapid_keys.json` bereitstellen.',
                'action_required': 'configure_vapid'
            }), 400
        
        # Cooldown-Check: Verhindere zu häufige Tests (max. alle 2 Minuten)
        from flask import session
        import time
        current_time = time.time()
        last_test_time = session.get('last_push_test_time', 0)
        cooldown_duration = 120  # 2 Minuten in Sekunden
        
        if current_time - last_test_time < cooldown_duration:
            remaining_time = int(cooldown_duration - (current_time - last_test_time))
            return jsonify({
                'success': False,
                'message': f'Bitte warten Sie {remaining_time} Sekunden vor dem nächsten Test.',
                'cooldown': True,
                'remaining_seconds': remaining_time,
                'total_cooldown': cooldown_duration
            }), 429  # Too Many Requests
        
        # Update last test time
        session['last_push_test_time'] = current_time
        
        # Bereinige fehlgeschlagene Subscriptions vor dem Test
        from app.utils.notifications import cleanup_failed_subscriptions, send_push_notification
        from app.models.notification import PushSubscription
        cleanup_failed_subscriptions()
        
        # Prüfe ob User Push-Subscriptions hat
        subscriptions = PushSubscription.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).all()
        
        if not subscriptions:
            return jsonify({
                'success': False, 
                'message': 'Keine aktiven Push-Subscriptions gefunden. Bitte registrieren Sie sich zuerst für Push-Benachrichtigungen.',
                'action_required': 'subscribe'
            }), 400
        
        # Sende Test-Push-Benachrichtigung
        try:
            success = send_push_notification(
                user_id=current_user.id,
                title="Test-Benachrichtigung",
                body="Dies ist eine Test-Push-Benachrichtigung vom Team Portal.",
                url="/dashboard/",
                data={'type': 'test', 'timestamp': datetime.utcnow().isoformat()}
            )
            
            if success:
                return jsonify({
                    'success': True, 
                    'message': f'Test-Benachrichtigung erfolgreich gesendet an {len(subscriptions)} Gerät(e)'
                })
            else:
                return jsonify({
                    'success': False, 
                    'message': 'Test-Benachrichtigung konnte nicht gesendet werden. Bitte prüfen Sie Ihre Push-Subscriptions.'
                }), 400
                
        except Exception as push_error:
            logging.error(f"Push-Send-Fehler: {push_error}")
            return jsonify({
                'success': False,
                'message': f'Fehler beim Senden: {str(push_error)[:100]}...'
            }), 500
            
    except Exception as e:
        print(f"Test-Push Fehler: {e}")
        return jsonify({'error': str(e), 'message': 'Interner Server-Fehler beim Senden der Test-Benachrichtigung'}), 500


@api_bp.route('/notifications/mark-read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Markiere eine Benachrichtigung als gelesen."""
    try:
        from app.models.notification import NotificationLog
        
        notification = NotificationLog.query.filter_by(
            id=notification_id,
            user_id=current_user.id
        ).first()
        
        if not notification:
            return jsonify({'error': 'Benachrichtigung nicht gefunden'}), 404
        
        # Markiere als gelesen statt zu löschen
        notification.mark_as_read()
        
        return jsonify({'message': 'Benachrichtigung als gelesen markiert'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Dashboard Update APIs
@api_bp.route('/chat/unread-count', methods=['GET'])
@login_required
def get_unread_chat_count():
    """Hole Anzahl UNGELESENER Chat-Nachrichten (basierend auf last_read_at)."""
    try:
        from app.models.chat import ChatMessage, ChatMember
        
        # Hole alle Chat-Mitgliedschaften des Benutzers mit last_read_at
        user_chat_members = ChatMember.query.filter_by(user_id=current_user.id).all()
        
        unread_count = 0
        for member in user_chat_members:
            # Zähle Nachrichten in diesem Chat, die nach dem letzten Lesen erstellt wurden
            # und nicht vom aktuellen Benutzer stammen
            chat_unread = ChatMessage.query.filter(
                ChatMessage.chat_id == member.chat_id,
                ChatMessage.sender_id != current_user.id,
                ChatMessage.created_at > member.last_read_at,
                ChatMessage.is_deleted == False
            ).count()
            unread_count += chat_unread
        
        return jsonify({'count': unread_count})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/email/unread-count', methods=['GET'])
@login_required
def get_unread_email_count():
    """Hole Anzahl ungelesener E-Mails."""
    try:
        unread_count = EmailMessage.query.filter_by(
            is_read=False
        ).count()
        
        return jsonify({'count': unread_count})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/calendar/upcoming-count', methods=['GET'])
@login_required
def get_upcoming_events_count():
    """Hole Anzahl anstehender Termine."""
    try:
        from datetime import datetime, timedelta
        
        # Termine der nächsten 7 Tage
        now = datetime.utcnow()
        week_from_now = now + timedelta(days=7)
        
        upcoming_count = CalendarEvent.query.filter(
            CalendarEvent.start_time > now,
            CalendarEvent.start_time <= week_from_now
        ).count()
        
        return jsonify({'count': upcoming_count})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500



