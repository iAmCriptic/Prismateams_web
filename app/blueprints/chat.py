from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.chat import Chat, ChatMessage, ChatMember
from app.models.user import User
from datetime import datetime
from werkzeug.utils import secure_filename
import os

chat_bp = Blueprint('chat', __name__)


def allowed_file(filename):
    """Check if file extension is allowed."""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'ogg', 'mp3', 'wav', 'm4a'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@chat_bp.route('/')
@login_required
def index():
    """List all chats for current user."""
    # Get all chats where user is a member
    memberships = ChatMember.query.filter_by(user_id=current_user.id).all()
    chats = [membership.chat for membership in memberships]
    
    # Separate main chat, group chats, and direct messages
    main_chat = next((c for c in chats if c.is_main_chat), None)
    group_chats = [c for c in chats if not c.is_main_chat and not c.is_direct_message]
    direct_chats = [c for c in chats if c.is_direct_message]
    
    return render_template(
        'chat/index.html',
        main_chat=main_chat,
        group_chats=group_chats,
        direct_chats=direct_chats
    )


@chat_bp.route('/<int:chat_id>')
@login_required
def view_chat(chat_id):
    """View a specific chat."""
    chat = Chat.query.get_or_404(chat_id)
    
    # Check if user is a member
    membership = ChatMember.query.filter_by(
        chat_id=chat_id,
        user_id=current_user.id
    ).first()
    
    if not membership:
        flash('Sie sind kein Mitglied dieses Chats.', 'danger')
        return redirect(url_for('chat.index'))
    
    # Get all messages
    messages = ChatMessage.query.filter_by(
        chat_id=chat_id,
        is_deleted=False
    ).order_by(ChatMessage.created_at).all()
    
    # Update last read timestamp
    membership.last_read_at = datetime.utcnow()
    db.session.commit()
    
    # Get chat members
    members = User.query.join(ChatMember).filter(
        ChatMember.chat_id == chat_id
    ).all()
    
    return render_template(
        'chat/view.html',
        chat=chat,
        messages=messages,
        members=members
    )


@chat_bp.route('/<int:chat_id>/send', methods=['POST'])
@login_required
def send_message(chat_id):
    """Send a message in a chat."""
    chat = Chat.query.get_or_404(chat_id)
    
    # Check if user is a member
    membership = ChatMember.query.filter_by(
        chat_id=chat_id,
        user_id=current_user.id
    ).first()
    
    if not membership:
        return jsonify({'error': 'Nicht autorisiert'}), 403
    
    content = request.form.get('content', '').strip()
    file = request.files.get('file')
    
    message_type = 'text'
    media_url = None
    
    # Handle file upload
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join('uploads', 'chat', filename)
        file.save(filepath)
        media_url = filepath
        
        # Determine message type based on file extension
        ext = filename.rsplit('.', 1)[1].lower()
        if ext in {'png', 'jpg', 'jpeg', 'gif'}:
            message_type = 'image'
        elif ext in {'mp4', 'webm', 'ogg'}:
            message_type = 'video'
        elif ext in {'mp3', 'wav', 'm4a'}:
            message_type = 'voice'
    
    if not content and not media_url:
        return jsonify({'error': 'Nachricht darf nicht leer sein'}), 400
    
    # Create message
    message = ChatMessage(
        chat_id=chat_id,
        sender_id=current_user.id,
        content=content,
        message_type=message_type,
        media_url=media_url
    )
    
    db.session.add(message)
    db.session.commit()
    
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'id': message.id,
            'sender': current_user.full_name,
            'content': message.content,
            'message_type': message.message_type,
            'media_url': message.media_url,
            'created_at': message.created_at.isoformat()
        })
    
    return redirect(url_for('chat.view_chat', chat_id=chat_id))


@chat_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_chat():
    """Create a new group chat."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        member_ids = request.form.getlist('members')
        
        if not name:
            flash('Bitte geben Sie einen Namen ein.', 'danger')
            return redirect(url_for('chat.create_chat'))
        
        # Create new chat
        new_chat = Chat(
            name=name,
            is_main_chat=False,
            is_direct_message=False,
            created_by=current_user.id
        )
        db.session.add(new_chat)
        db.session.flush()
        
        # Add creator as member
        creator_member = ChatMember(
            chat_id=new_chat.id,
            user_id=current_user.id
        )
        db.session.add(creator_member)
        
        # Add selected members
        for member_id in member_ids:
            if int(member_id) != current_user.id:
                member = ChatMember(
                    chat_id=new_chat.id,
                    user_id=int(member_id)
                )
                db.session.add(member)
        
        db.session.commit()
        
        flash(f'Chat "{name}" wurde erstellt.', 'success')
        return redirect(url_for('chat.view_chat', chat_id=new_chat.id))
    
    # Get all active users
    users = User.query.filter_by(is_active=True).all()
    return render_template('chat/create.html', users=users)


@chat_bp.route('/direct/<int:user_id>')
@login_required
def direct_message(user_id):
    """Start or continue a direct message with a user."""
    other_user = User.query.get_or_404(user_id)
    
    if user_id == current_user.id:
        flash('Sie können keinen Chat mit sich selbst starten.', 'warning')
        return redirect(url_for('chat.index'))
    
    # Check if DM already exists
    existing_dm = Chat.query.filter_by(is_direct_message=True).join(ChatMember).filter(
        ChatMember.user_id.in_([current_user.id, user_id])
    ).group_by(Chat.id).having(db.func.count(ChatMember.id) == 2).first()
    
    if existing_dm:
        return redirect(url_for('chat.view_chat', chat_id=existing_dm.id))
    
    # Create new DM
    dm_chat = Chat(
        name=f"{current_user.full_name}, {other_user.full_name}",
        is_main_chat=False,
        is_direct_message=True,
        created_by=current_user.id
    )
    db.session.add(dm_chat)
    db.session.flush()
    
    # Add both users as members
    member1 = ChatMember(chat_id=dm_chat.id, user_id=current_user.id)
    member2 = ChatMember(chat_id=dm_chat.id, user_id=user_id)
    db.session.add_all([member1, member2])
    db.session.commit()
    
    return redirect(url_for('chat.view_chat', chat_id=dm_chat.id))



