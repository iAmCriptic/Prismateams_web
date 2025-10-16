from flask import Blueprint, jsonify, request
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
        'profile_picture': user.profile_picture
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
        'profile_picture': user.profile_picture,
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
        
        chats.append({
            'id': chat.id,
            'name': chat.name,
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
        'sender_name': msg.sender.full_name,
        'sender': msg.sender.full_name,  # Alias for compatibility
        'content': msg.content,
        'message_type': msg.message_type,
        'media_url': msg.media_url,
        'created_at': get_local_time(msg.created_at).isoformat()
    } for msg in messages])


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


# Push Notifications API
@api_bp.route('/push/subscribe', methods=['POST'])
@login_required
def subscribe_push():
    """Register push subscription for current user."""
    try:
        data = request.get_json()
        subscription_data = data.get('subscription')
        user_agent = data.get('user_agent', '')
        
        if not subscription_data:
            return jsonify({'error': 'Subscription-Daten fehlen'}), 400
        
        # Registriere Push-Subscription
        success = register_push_subscription(current_user.id, subscription_data)
        
        if success:
            return jsonify({'message': 'Push-Subscription erfolgreich registriert'})
        else:
            return jsonify({'error': 'Fehler bei der Registrierung'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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


@api_bp.route('/push/test', methods=['POST'])
@login_required
def test_push():
    """Send test push notification to current user."""
    try:
        success = send_push_notification(
            user_id=current_user.id,
            title='Test-Benachrichtigung',
            body='Dies ist eine Test-Benachrichtigung vom Team Portal.',
            url='/dashboard'
        )
        
        if success:
            return jsonify({'message': 'Test-Benachrichtigung gesendet'})
        else:
            return jsonify({'error': 'Keine aktive Push-Subscription gefunden'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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


@api_bp.route('/notifications/pending', methods=['GET'])
@login_required
def get_pending_notifications():
    """Hole ausstehende Benachrichtigungen für den aktuellen Benutzer."""
    try:
        from app.models.notification import NotificationLog
        
        # Hole nur ungelesene Benachrichtigungen der letzten 24 Stunden
        from datetime import datetime, timedelta
        since = datetime.utcnow() - timedelta(hours=24)
        
        notifications = NotificationLog.query.filter(
            NotificationLog.user_id == current_user.id,
            NotificationLog.is_read == False,
            NotificationLog.sent_at > since
        ).order_by(NotificationLog.sent_at.desc()).limit(10).all()
        
        result = []
        for notif in notifications:
            result.append({
                'id': notif.id,
                'title': notif.title,
                'body': notif.body,
                'icon': notif.icon,
                'url': notif.url,
                'sent_at': notif.sent_at.isoformat(),
                'success': notif.success
            })
        
        return jsonify({
            'notifications': result,
            'count': len(result)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
    """Hole Anzahl ungelesener Chat-Nachrichten."""
    try:
        from app.models.chat import ChatMessage, ChatMember
        from datetime import datetime, timedelta
        
        # Hole alle Chats des Benutzers
        user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
        chat_ids = [member.chat_id for member in user_chats]
        
        # Zähle nur Nachrichten der letzten 2 Stunden, die nicht vom aktuellen Benutzer sind
        # Das zeigt nur wirklich neue Nachrichten
        since = datetime.utcnow() - timedelta(hours=2)
        unread_count = ChatMessage.query.filter(
            ChatMessage.chat_id.in_(chat_ids),
            ChatMessage.sender_id != current_user.id,
            ChatMessage.created_at > since
        ).count()
        
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



