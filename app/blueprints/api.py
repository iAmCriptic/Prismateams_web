from flask import Blueprint, jsonify, request, url_for, session as flask_session
from flask_login import login_required, current_user, login_user
from app import db, limiter
from app.models.user import User
from app.models.chat import Chat, ChatMessage, ChatMember
from app.models.file import File, Folder
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.email import EmailMessage
from app.models.notification import PushSubscription
from app.models.api_token import ApiToken
from app.utils.notifications import register_push_subscription, send_push_notification
from app.utils.i18n import translate
from app.utils.totp import verify_totp, decrypt_secret
from app.utils.session_manager import create_session
from datetime import datetime, timedelta

api_bp = Blueprint('api', __name__)


def require_api_auth(f):
    """
    Decorator für API-Endpunkte, die entweder Session- oder Token-Authentifizierung akzeptieren.
    Setzt current_user für Token-basierte Authentifizierung.
    """
    from functools import wraps
    from flask_login import current_user
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Prüfe zuerst ob Session-basierte Authentifizierung vorhanden ist
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        
        # Prüfe Token-basierte Authentifizierung
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.replace('Bearer ', '').strip()
            api_token = ApiToken.query.filter_by(token=token).first()
            
            if api_token and not api_token.is_expired():
                user = api_token.user
                if user and user.is_active:
                    # Setze current_user für diesen Request
                    from flask_login import _request_ctx_stack
                    _request_ctx_stack.top.user = user
                    api_token.mark_as_used()
                    return f(*args, **kwargs)
        
        return jsonify({
            'success': False,
            'error': 'Authentifizierung erforderlich'
        }), 401
    
    return decorated_function


# Authentication API
@api_bp.route('/auth/login', methods=['POST'])
@limiter.limit("5 per 15 minutes")
def api_login():
    """
    API-Login mit 2FA-Unterstützung.
    
    Request Body (JSON):
    {
        "email": "user@example.com",
        "password": "password123",
        "totp_code": "123456",  // Optional, nur wenn 2FA aktiviert ist
        "remember": true,        // Optional
        "return_token": false    // Optional, gibt API-Token zurück statt Session
    }
    
    Response (2FA erforderlich):
    {
        "success": false,
        "requires_2fa": true,
        "message": "2FA-Code erforderlich"
    }
    
    Response (Erfolg):
    {
        "success": true,
        "user": {
            "id": 1,
            "email": "user@example.com",
            "full_name": "Max Mustermann",
            "is_admin": false
        },
        "token": "..."  // Nur wenn return_token=true
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Keine Daten übermittelt'
            }), 400
        
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        totp_code = data.get('totp_code', '').strip()
        remember = data.get('remember', False)
        return_token = data.get('return_token', False)
        
        if not email or not password:
            return jsonify({
                'success': False,
                'error': 'E-Mail und Passwort sind erforderlich'
            }), 400
        
        # Unterstütze @gast.system.local Format für Gast-Accounts
        user = None
        if email.endswith('@gast.system.local'):
            guest_username = email.replace('@gast.system.local', '')
            user = User.query.filter_by(guest_username=guest_username, is_guest=True).first()
        else:
            user = User.query.filter_by(email=email).first()
        
        # Prüfe ob Account gesperrt ist (Rate Limiting)
        if user and user.failed_login_until and datetime.utcnow() < user.failed_login_until:
            remaining_seconds = int((user.failed_login_until - datetime.utcnow()).total_seconds())
            return jsonify({
                'success': False,
                'error': f'Account gesperrt. Bitte warten Sie {remaining_seconds} Sekunden.',
                'account_locked': True,
                'remaining_seconds': remaining_seconds
            }), 423  # 423 Locked
        
        # Prüfe Credentials
        if not user or not user.check_password(password):
            # Erhöhe fehlgeschlagene Versuche
            if user:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= 5:
                    user.failed_login_until = datetime.utcnow() + timedelta(minutes=15)
                    user.failed_login_attempts = 0
                db.session.commit()
            return jsonify({
                'success': False,
                'error': 'Ungültige Zugangsdaten'
            }), 401
        
        # Reset fehlgeschlagene Versuche bei erfolgreichem Passwort-Check
        user.failed_login_attempts = 0
        user.failed_login_until = None
        
        # Prüfe Ablaufzeit für Gast-Accounts
        if user.is_guest and user.guest_expires_at:
            if datetime.utcnow() > user.guest_expires_at:
                db.session.delete(user)
                db.session.commit()
                return jsonify({
                    'success': False,
                    'error': 'Gast-Account ist abgelaufen'
                }), 401
        
        if not user.is_active:
            return jsonify({
                'success': False,
                'error': 'Account ist nicht aktiviert'
            }), 403
        
        # 2FA-Verifizierung (wenn aktiviert)
        if user.totp_enabled and user.totp_secret:
            if not totp_code:
                # 2FA erforderlich, aber kein Code übermittelt
                return jsonify({
                    'success': False,
                    'requires_2fa': True,
                    'message': '2FA-Code erforderlich',
                    'error': 'Bitte geben Sie den 2FA-Code ein'
                }), 200  # 200 damit Client weiß, dass Credentials korrekt waren
            
            # Verifiziere TOTP-Code
            if not verify_totp(user.totp_secret, totp_code):
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= 5:
                    user.failed_login_until = datetime.utcnow() + timedelta(minutes=15)
                    user.failed_login_attempts = 0
                db.session.commit()
                return jsonify({
                    'success': False,
                    'requires_2fa': True,
                    'error': 'Ungültiger 2FA-Code'
                }), 401
        
        # Gast-Accounts benötigen keine E-Mail-Bestätigung
        # Normale Accounts: Check if email confirmation is required (nicht für Admins)
        if not user.is_guest and not user.is_email_confirmed and not user.is_admin:
            # E-Mail-Bestätigung erforderlich
            return jsonify({
                'success': False,
                'requires_email_confirmation': True,
                'error': 'E-Mail-Bestätigung erforderlich'
            }), 403
        
        # Update last login
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        # Log user in (erstellt Session-Cookie)
        login_user(user, remember=remember)
        
        # Erstelle Session für Session-Management (nur wenn Session-basiert, nicht bei Token)
        if not return_token:
            create_session(user.id)
        
        # Bereite Response vor
        response_data = {
            'success': True,
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_admin': user.is_admin,
                'is_guest': user.is_guest,
                'profile_picture': url_for('settings.profile_picture', filename=user.profile_picture) if user.profile_picture else None,
                'accent_color': user.accent_color,
                'dark_mode': user.dark_mode,
                'totp_enabled': user.totp_enabled
            }
        }
        
        # Wenn Token angefordert wurde, erstelle API-Token
        if return_token:
            token = ApiToken.create_token(
                user_id=user.id,
                name='API Login',
                expires_in_days=30
            )
            response_data['token'] = token.token
            response_data['token_expires_at'] = token.expires_at.isoformat() if token.expires_at else None
        
        return jsonify(response_data), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/auth/logout', methods=['POST'])
def api_logout():
    """
    API-Logout.
    Unterstützt sowohl Session- als auch Token-basierte Authentifizierung.
    """
    from flask_login import logout_user
    from app.utils.session_manager import revoke_session_by_id
    
    # Prüfe ob Session-basierte Authentifizierung
    if current_user.is_authenticated:
        # Revoke current session
        session_id = flask_session.get('session_id')
        if session_id:
            revoke_session_by_id(session_id)
        logout_user()
    
    # Prüfe ob Token-basierte Authentifizierung
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.replace('Bearer ', '').strip()
        api_token = ApiToken.query.filter_by(token=token).first()
        if api_token:
            # Lösche Token (oder markiere als inaktiv)
            db.session.delete(api_token)
            db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Erfolgreich abgemeldet'
    }), 200


@api_bp.route('/auth/verify-token', methods=['POST'])
def api_verify_token():
    """
    Verifiziert einen API-Token.
    
    Request Body (JSON):
    {
        "token": "api_token_here"
    }
    
    Response:
    {
        "success": true,
        "user": {...}
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Keine Daten übermittelt'
            }), 400
        
        token = data.get('token', '').strip()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Token erforderlich'
            }), 400
        
        # Prüfe Token
        api_token = ApiToken.query.filter_by(token=token, expires_at=None).first()
        if not api_token:
            # Prüfe auch nicht-abgelaufene Token
            api_token = ApiToken.query.filter_by(token=token).first()
            if not api_token or api_token.is_expired():
                return jsonify({
                    'success': False,
                    'error': 'Ungültiger oder abgelaufener Token'
                }), 401
        
        # Prüfe ob User noch aktiv ist
        user = api_token.user
        if not user or not user.is_active:
            return jsonify({
                'success': False,
                'error': 'Benutzer ist nicht aktiv'
            }), 401
        
        # Markiere Token als verwendet
        api_token.mark_as_used()
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_admin': user.is_admin,
                'is_guest': user.is_guest,
                'profile_picture': url_for('settings.profile_picture', filename=user.profile_picture) if user.profile_picture else None,
                'accent_color': user.accent_color,
                'dark_mode': user.dark_mode,
                'totp_enabled': user.totp_enabled
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# User API
@api_bp.route('/users', methods=['GET'])
@login_required
def get_users():
    """Get all active users, excluding guest accounts."""
    users = User.query.filter(
        User.is_active == True,
        ~User.is_guest,
        User.email != 'anonymous@system.local'
    ).all()
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
            # Get the other member (not the current user), excluding guest accounts
            members = ChatMember.query.filter_by(chat_id=chat.id).join(User).filter(
                ~User.is_guest,
                User.email != 'anonymous@system.local'
            ).all()
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
        return jsonify({'error': translate('api.errors.unauthorized')}), 403
    
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
        return jsonify({'error': translate('api.errors.unauthorized')}), 403
    
    # Get all chat members - use ChatMember as base to ensure all members are included
    # Filter out guest accounts (system accounts that should not be visible)
    chat_memberships = ChatMember.query.filter_by(chat_id=chat_id).all()
    member_ids = [cm.user_id for cm in chat_memberships]
    if member_ids:
        members = User.query.filter(
            User.id.in_(member_ids),
            ~User.is_guest,
            User.email != 'anonymous@system.local'
        ).all()
    else:
        members = []
    
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
            return jsonify({'error': translate('api.errors.subscription_data_missing')}), 400
        
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
            return jsonify({'error': translate('api.errors.registration_error'), 'success': False}), 500
            
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


@api_bp.route('/notifications', methods=['GET'])
@login_required
def get_notifications():
    """Hole alle Benachrichtigungen für den aktuellen Benutzer."""
    try:
        from app.models.notification import NotificationLog
        from sqlalchemy import desc
        
        category = request.args.get('category', None)
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        query = NotificationLog.query.filter_by(user_id=current_user.id)
        
        if category:
            query = query.filter_by(category=category)
        
        if unread_only:
            query = query.filter_by(is_read=False)
        
        total = query.count()
        notifications = query.order_by(desc(NotificationLog.sent_at)).limit(limit).offset(offset).all()
        
        return jsonify({
            'notifications': [{
                'id': n.id,
                'title': n.title,
                'body': n.body,
                'icon': n.icon,
                'url': n.url,
                'category': n.category,
                'sent_at': n.sent_at.isoformat(),
                'is_read': n.is_read,
                'read_at': n.read_at.isoformat() if n.read_at else None
            } for n in notifications],
            'total': total,
            'limit': limit,
            'offset': offset
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/notifications/unread', methods=['GET'])
@login_required
def get_unread_notifications():
    """Hole ungelesene Benachrichtigungen für den aktuellen Benutzer."""
    try:
        from app.models.notification import NotificationLog
        from sqlalchemy import desc
        
        notifications = NotificationLog.query.filter_by(
            user_id=current_user.id,
            is_read=False
        ).order_by(desc(NotificationLog.sent_at)).limit(20).all()
        
        # Gruppiere nach Kategorie
        by_category = {}
        for n in notifications:
            if n.category not in by_category:
                by_category[n.category] = []
            by_category[n.category].append({
                'id': n.id,
                'title': n.title,
                'body': n.body,
                'icon': n.icon,
                'url': n.url,
                'sent_at': n.sent_at.isoformat()
            })
        
        return jsonify({
            'notifications': by_category,
            'total': len(notifications)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/notifications/stats', methods=['GET'])
@login_required
def get_notification_stats():
    """Hole Statistiken über Benachrichtigungen."""
    try:
        from app.models.notification import NotificationLog
        from sqlalchemy import func
        
        # Ungelesene Benachrichtigungen pro Kategorie
        stats = db.session.query(
            NotificationLog.category,
            func.count(NotificationLog.id).label('count')
        ).filter_by(
            user_id=current_user.id,
            is_read=False
        ).group_by(NotificationLog.category).all()
        
        result = {
            'by_category': {category: count for category, count in stats},
            'total_unread': sum(count for _, count in stats)
        }
        
        return jsonify(result)
        
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
            return jsonify({'error': translate('api.errors.unauthorized')}), 403
        
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
            return jsonify({'error': translate('api.errors.vapid_key_format_error'), 'message': str(e)}), 500
        
    except Exception as e:
        print(f"VAPID Key Fehler: {e}")
        return jsonify({'error': str(e), 'message': translate('api.errors.vapid_keys_load_error')}), 500

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
                category='System',
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
        return jsonify({'error': str(e), 'message': translate('api.errors.test_notification_error')}), 500


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
            return jsonify({'error': translate('api.errors.notification_not_found')}), 404
        
        # Markiere als gelesen statt zu löschen
        notification.mark_as_read()
        
        return jsonify({'message': 'Benachrichtigung als gelesen markiert'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """Markiere alle Benachrichtigungen als gelesen."""
    try:
        from app.models.notification import NotificationLog
        from datetime import datetime
        
        category = request.json.get('category', None) if request.json else None
        
        query = NotificationLog.query.filter_by(
            user_id=current_user.id,
            is_read=False
        )
        
        if category:
            query = query.filter_by(category=category)
        
        notifications = query.all()
        
        for notification in notifications:
            notification.is_read = True
            notification.read_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'marked_count': len(notifications)
        })
        
    except Exception as e:
        db.session.rollback()
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



