from flask import Blueprint, render_template, redirect, url_for, session
from flask_login import login_required, current_user
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.chat import ChatMessage, ChatMember
from app.models.email import EmailMessage, EmailPermission
from datetime import datetime
from sqlalchemy import and_

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard')
@login_required
def index():
    """Main dashboard view."""
    
    # Sicherstelle, dass der aktuelle Benutzer E-Mail-Berechtigungen hat
    if current_user.is_admin:
        current_user.ensure_email_permissions()
    
    # Get upcoming events (next 3)
    upcoming_events = CalendarEvent.query.filter(
        CalendarEvent.start_time >= datetime.utcnow()
    ).order_by(CalendarEvent.start_time).limit(3).all()
    
    # Get unread chat messages
    user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
    chat_ids = [membership.chat_id for membership in user_chats]
    
    unread_messages = []
    for membership in user_chats:
        messages = ChatMessage.query.filter(
            and_(
                ChatMessage.chat_id == membership.chat_id,
                ChatMessage.created_at > membership.last_read_at,
                ChatMessage.sender_id != current_user.id,
                ChatMessage.is_deleted == False
            )
        ).order_by(ChatMessage.created_at.desc()).limit(5).all()
        unread_messages.extend(messages)
    
    # Sort by newest first and limit to 5
    unread_messages = sorted(unread_messages, key=lambda x: x.created_at, reverse=True)[:5]
    
    # Get recent emails
    recent_emails = []
    email_perm = EmailPermission.query.filter_by(user_id=current_user.id).first()
    if email_perm and email_perm.can_read:
        recent_emails = EmailMessage.query.filter_by(
            is_sent=False
        ).order_by(EmailMessage.received_at.desc()).limit(5).all()
    
    # Prüfe ob Setup gerade abgeschlossen wurde
    setup_completed = session.pop('setup_completed', False)
    
    return render_template(
        'dashboard/index.html',
        upcoming_events=upcoming_events,
        unread_messages=unread_messages,
        recent_emails=recent_emails,
        setup_completed=setup_completed
    )



