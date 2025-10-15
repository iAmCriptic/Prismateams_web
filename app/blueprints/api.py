from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.chat import Chat, ChatMessage, ChatMember
from app.models.file import File, Folder
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.email import EmailMessage
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
    
    return jsonify([{
        'id': msg.id,
        'sender_id': msg.sender_id,
        'sender_name': msg.sender.full_name,
        'sender': msg.sender.full_name,  # Alias for compatibility
        'content': msg.content,
        'message_type': msg.message_type,
        'media_url': msg.media_url,
        'created_at': msg.created_at.isoformat()
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



