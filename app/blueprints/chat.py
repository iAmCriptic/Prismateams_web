from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app
from flask_login import login_required, current_user
from app import db
from app.models.chat import Chat, ChatMessage, ChatMember
from app.models.user import User
from app.utils.notifications import send_chat_notification
from app.utils.access_control import check_module_access
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
@check_module_access('module_chat')
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
@check_module_access('module_chat')
def view_chat(chat_id):
    """View a specific chat."""
    # Special handling: If chat_id is 1, load the actual main chat
    # This ensures /chat/1 always shows the main chat, even if it has a different ID
    if chat_id == 1:
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if main_chat:
            # Use the actual main chat ID for all operations, but keep URL as /chat/1
            actual_chat_id = main_chat.id
        else:
            flash('Haupt-Chat nicht gefunden.', 'danger')
            return redirect(url_for('chat.index'))
    else:
        actual_chat_id = chat_id
    
    chat = Chat.query.get_or_404(actual_chat_id)
    
    # Check if user is a member
    membership = ChatMember.query.filter_by(
        chat_id=actual_chat_id,
        user_id=current_user.id
    ).first()
    
    if not membership:
        flash('Sie sind kein Mitglied dieses Chats.', 'danger')
        return redirect(url_for('chat.index'))
    
    # Get all messages
    messages = ChatMessage.query.filter_by(
        chat_id=actual_chat_id,
        is_deleted=False
    ).order_by(ChatMessage.created_at).all()
    
    # Update last read timestamp
    membership.last_read_at = datetime.utcnow()
    # Update user's last_seen for online status
    current_user.last_seen = datetime.utcnow()
    db.session.commit()
    
    # Get chat members - use ChatMember as base to ensure all members are included
    chat_memberships = ChatMember.query.filter_by(chat_id=actual_chat_id).all()
    member_ids = [cm.user_id for cm in chat_memberships]
    members = User.query.filter(User.id.in_(member_ids)).all() if member_ids else []
    
    return render_template(
        'chat/view.html',
        chat=chat,
        messages=messages,
        members=members
    )


@chat_bp.route('/<int:chat_id>/send', methods=['POST'])
@login_required
@check_module_access('module_chat')
def send_message(chat_id):
    """Send a message in a chat."""
    # Special handling: If chat_id is 1, use the actual main chat ID
    if chat_id == 1:
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if main_chat:
            actual_chat_id = main_chat.id
        else:
            return jsonify({'error': 'Haupt-Chat nicht gefunden'}), 404
    else:
        actual_chat_id = chat_id
    
    chat = Chat.query.get_or_404(actual_chat_id)
    
    # Check if user is a member
    membership = ChatMember.query.filter_by(
        chat_id=actual_chat_id,
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
        
        # Use absolute path with UPLOAD_FOLDER config
        project_root = os.path.dirname(current_app.root_path)
        upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'chat')
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        # Store only the filename for URL generation
        media_url = filename
        
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
        chat_id=actual_chat_id,
        sender_id=current_user.id,
        content=content,
        message_type=message_type,
        media_url=media_url
    )
    
    db.session.add(message)
    db.session.commit()
    
    # Sende Push-Benachrichtigungen an andere Chat-Mitglieder
    try:
        sent_count = send_chat_notification(
            chat_id=actual_chat_id,
            sender_id=current_user.id,
            message_content=content or f"[{message_type}]",
            chat_name=chat.name,
            message_id=message.id  # WICHTIG: Für Duplikat-Vermeidung
        )
        print(f"Push-Benachrichtigungen gesendet: {sent_count}")
    except Exception as e:
        print(f"Fehler beim Senden der Push-Benachrichtigungen: {e}")
    
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from app.utils import get_local_time
        return jsonify({
            'id': message.id,
            'sender_id': current_user.id,
            'sender': current_user.full_name,
            'content': message.content,
            'message_type': message.message_type,
            'media_url': message.media_url,
            'created_at': get_local_time(message.created_at).isoformat()
        })
    
    # Always redirect to /chat/1 for main chat to keep URL consistent
    redirect_chat_id = 1 if chat.is_main_chat else chat_id
    return redirect(url_for('chat.view_chat', chat_id=redirect_chat_id))


@chat_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_chat')
def create_chat():
    """Create a new group chat or private chat."""
    if request.method == 'POST':
        chat_type = request.form.get('chat_type', 'group')
        is_private = (chat_type == 'private')
        
        if is_private:
            # Private Chat: nur ein Mitglied
            member_id = request.form.get('member')
            if not member_id:
                flash('Bitte wählen Sie eine Person für den privaten Chat aus.', 'danger')
                return redirect(url_for('chat.create_chat'))
            
            member_id = int(member_id)
            if member_id == current_user.id:
                flash('Sie können keinen privaten Chat mit sich selbst erstellen.', 'warning')
                return redirect(url_for('chat.create_chat'))
            
            # Prüfe ob bereits ein privater Chat mit dieser Person existiert
            other_user = User.query.get_or_404(member_id)
            existing_dm = Chat.query.filter_by(is_direct_message=True).join(ChatMember).filter(
                ChatMember.user_id.in_([current_user.id, member_id])
            ).group_by(Chat.id).having(db.func.count(ChatMember.id) == 2).first()
            
            if existing_dm:
                flash(f'Ein privater Chat mit {other_user.full_name} existiert bereits.', 'info')
                return redirect(url_for('chat.view_chat', chat_id=existing_dm.id))
            
            # Erstelle privaten Chat - Name wird nur der andere Benutzer sein
            # (wird im Template dynamisch angepasst, damit jeder den Namen der anderen Person sieht)
            chat_name = f"{current_user.full_name}, {other_user.full_name}"
            new_chat = Chat(
                name=chat_name,
                is_main_chat=False,
                is_direct_message=True,
                created_by=current_user.id
            )
            db.session.add(new_chat)
            db.session.flush()
            
            # Füge beide Benutzer als Mitglieder hinzu
            member1 = ChatMember(chat_id=new_chat.id, user_id=current_user.id)
            member2 = ChatMember(chat_id=new_chat.id, user_id=member_id)
            db.session.add_all([member1, member2])
            
            db.session.commit()
            
            flash(f'Privater Chat mit {other_user.full_name} wurde erstellt.', 'success')
            return redirect(url_for('chat.view_chat', chat_id=new_chat.id))
        
        else:
            # Gruppen-Chat
            name = request.form.get('name', '').strip()
            member_ids = request.form.getlist('members')
            
            if not name:
                flash('Bitte geben Sie einen Namen ein.', 'danger')
                return redirect(url_for('chat.create_chat'))
            
            if not member_ids:
                flash('Bitte wählen Sie mindestens ein Mitglied aus.', 'danger')
                return redirect(url_for('chat.create_chat'))
            
            # Create new group chat
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
            
            flash(f'Gruppen-Chat "{name}" wurde erstellt.', 'success')
            return redirect(url_for('chat.view_chat', chat_id=new_chat.id))
    
    # Get all active users
    users = User.query.filter_by(is_active=True).all()
    return render_template('chat/create.html', users=users)


@chat_bp.route('/direct/<int:user_id>')
@login_required
@check_module_access('module_chat')
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


@chat_bp.route('/media/<path:filename>')
@login_required
@check_module_access('module_chat')
def serve_media(filename):
    """Serve uploaded chat media files (images, videos, audio)."""
    try:
        project_root = os.path.dirname(current_app.root_path)
        # Handle avatars in subdirectory
        if filename.startswith('avatars/'):
            directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'chat', 'avatars')
            filename = filename.replace('avatars/', '', 1)
        else:
            directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'chat')
        full_path = os.path.join(directory, filename)
        
        if not os.path.isfile(full_path):
            return jsonify({'error': 'File not found'}), 404
        
        return send_from_directory(directory, filename)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@chat_bp.route('/<int:chat_id>/update', methods=['POST'])
@login_required
@check_module_access('module_chat')
def update_chat(chat_id):
    """Update chat settings (name, description, avatar)."""
    # Special handling: If chat_id is 1, use the actual main chat ID
    if chat_id == 1:
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if main_chat:
            actual_chat_id = main_chat.id
        else:
            return jsonify({'error': 'Haupt-Chat nicht gefunden'}), 404
    else:
        actual_chat_id = chat_id
    
    chat = Chat.query.get_or_404(actual_chat_id)
    
    # Check if user is a member
    membership = ChatMember.query.filter_by(
        chat_id=actual_chat_id,
        user_id=current_user.id
    ).first()
    
    if not membership:
        return jsonify({'error': 'Nicht autorisiert'}), 403
    
    # Check if user is creator or admin (only they can update)
    if chat.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Nur der Ersteller oder ein Administrator kann den Chat bearbeiten'}), 403
    
    # Update name
    if 'name' in request.form:
        new_name = request.form.get('name', '').strip()
        if new_name:
            chat.name = new_name
    
    # Update description
    if 'description' in request.form:
        chat.description = request.form.get('description', '').strip()
    
    # Handle avatar upload
    if 'avatar' in request.files:
        avatar_file = request.files['avatar']
        if avatar_file and avatar_file.filename and allowed_file(avatar_file.filename):
            # Delete old avatar if exists
            if chat.group_avatar:
                project_root = os.path.dirname(current_app.root_path)
                old_avatar_path = os.path.join(
                    project_root, 
                    current_app.config['UPLOAD_FOLDER'], 
                    'chat', 
                    'avatars', 
                    chat.group_avatar
                )
                if os.path.exists(old_avatar_path):
                    try:
                        os.remove(old_avatar_path)
                    except:
                        pass
            
            # Save new avatar
            filename = secure_filename(avatar_file.filename)
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{filename}"
            
            project_root = os.path.dirname(current_app.root_path)
            avatar_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'chat', 'avatars')
            os.makedirs(avatar_dir, exist_ok=True)
            filepath = os.path.join(avatar_dir, filename)
            avatar_file.save(filepath)
            chat.group_avatar = filename
    
    # Handle avatar removal
    if 'remove_avatar' in request.form and request.form.get('remove_avatar') == '1':
        if chat.group_avatar:
            project_root = os.path.dirname(current_app.root_path)
            avatar_path = os.path.join(
                project_root, 
                current_app.config['UPLOAD_FOLDER'], 
                'chat', 
                'avatars', 
                chat.group_avatar
            )
            if os.path.exists(avatar_path):
                try:
                    os.remove(avatar_path)
                except:
                    pass
            chat.group_avatar = None
    
    chat.updated_at = datetime.utcnow()
    db.session.commit()
    
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'message': 'Chat erfolgreich aktualisiert',
            'chat': {
                'id': chat.id,
                'name': chat.name,
                'description': chat.description,
                'group_avatar': chat.group_avatar
            }
        })
    
    flash('Chat erfolgreich aktualisiert', 'success')
    # Always redirect to /chat/1 for main chat to keep URL consistent
    redirect_chat_id = 1 if chat.is_main_chat else chat_id
    return redirect(url_for('chat.view_chat', chat_id=redirect_chat_id))


@chat_bp.route('/<int:chat_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_chat')
def delete_chat(chat_id):
    """Delete a chat (main chat cannot be deleted)."""
    # Special handling: If chat_id is 1, use the actual main chat ID
    if chat_id == 1:
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if main_chat:
            actual_chat_id = main_chat.id
        else:
            return jsonify({'error': 'Haupt-Chat nicht gefunden'}), 404
    else:
        actual_chat_id = chat_id
    
    chat = Chat.query.get_or_404(actual_chat_id)
    
    # Prevent deletion of main chat
    if chat.is_main_chat:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Der Haupt-Chat kann nicht gelöscht werden'}), 400
        flash('Der Haupt-Chat kann nicht gelöscht werden', 'danger')
        return redirect(url_for('chat.view_chat', chat_id=1))
    
    # Check if user is creator or admin
    if chat.created_by != current_user.id and not current_user.is_admin:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Nur der Ersteller oder ein Administrator kann den Chat löschen'}), 403
        flash('Nur der Ersteller oder ein Administrator kann den Chat löschen', 'danger')
        redirect_chat_id = 1 if chat.is_main_chat else chat_id
        return redirect(url_for('chat.view_chat', chat_id=redirect_chat_id))
    
    # Delete chat (cascade will handle messages and members)
    db.session.delete(chat)
    db.session.commit()
    
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Chat erfolgreich gelöscht'})
    
    flash('Chat erfolgreich gelöscht', 'success')
    return redirect(url_for('chat.index'))


@chat_bp.route('/<int:chat_id>/settings', methods=['GET', 'POST'])
@login_required
@check_module_access('module_chat')
def chat_settings(chat_id):
    """Chat settings page."""
    # Special handling: If chat_id is 1, use the actual main chat ID
    if chat_id == 1:
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if main_chat:
            actual_chat_id = main_chat.id
        else:
            flash('Haupt-Chat nicht gefunden.', 'danger')
            return redirect(url_for('chat.index'))
    else:
        actual_chat_id = chat_id
    
    chat = Chat.query.get_or_404(actual_chat_id)
    
    # Check if user is a member
    membership = ChatMember.query.filter_by(
        chat_id=actual_chat_id,
        user_id=current_user.id
    ).first()
    
    if not membership:
        flash('Sie sind kein Mitglied dieses Chats.', 'danger')
        return redirect(url_for('chat.index'))
    
    # Check if user is creator or admin (only they can access settings)
    if chat.created_by != current_user.id and not current_user.is_admin:
        flash('Nur der Ersteller oder ein Administrator kann die Chat-Einstellungen bearbeiten', 'danger')
        redirect_chat_id = 1 if chat.is_main_chat else chat_id
        return redirect(url_for('chat.view_chat', chat_id=redirect_chat_id))
    
    if request.method == 'POST':
        return update_chat(chat_id)
    
    # Get chat members
    chat_memberships = ChatMember.query.filter_by(chat_id=chat_id).all()
    member_ids = [cm.user_id for cm in chat_memberships]
    members = User.query.filter(User.id.in_(member_ids)).all() if member_ids else []
    
    return render_template(
        'chat/settings.html',
        chat=chat,
        members=members
    )



