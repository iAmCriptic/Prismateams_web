from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app
from flask_login import login_required, current_user
from app import db
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.chat import Chat, ChatMessage, ChatMember
from app.models.user import User
from app.models.file import Folder
from app.utils.notifications import enqueue_chat_notification
from app.utils.access_control import check_module_access, get_guest_accessible_items
from app.utils.dashboard_events import emit_dashboard_update_multiple
from app.utils.i18n import translate
from app.utils.chat_visibility import visible_chat_user_filters, selectable_chat_user_filters
from datetime import datetime
from werkzeug.utils import secure_filename
from sqlalchemy import and_
import os
import json

chat_bp = Blueprint('chat', __name__)


def allowed_file(filename):
    """Check if file extension is allowed."""
    ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'webp',
        'mp4', 'webm', 'mov', 'avi',
        'ogg', 'mp3', 'wav', 'm4a', 'aac',
        'pdf', 'txt', 'csv', 'json', 'zip', '7z', 'rar',
        'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'
    }
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _resolve_message_type(filename, mimetype):
    ext = filename.rsplit('.', 1)[1].lower()
    mimetype = (mimetype or '').lower()
    if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'} or mimetype.startswith('image/'):
        return 'image'
    if ext in {'mp4', 'mov', 'avi'} or mimetype.startswith('video/'):
        return 'video'
    if ext in {'mp3', 'wav', 'm4a', 'aac', 'ogg'} or mimetype.startswith('audio/') or filename.startswith('voice_message'):
        return 'voice'
    if ext == 'webm':
        return 'voice' if mimetype.startswith('audio/') or filename.startswith('voice_message') else 'video'
    return 'file'


def _has_structured_message_content(message_type, metadata):
    if not isinstance(metadata, dict):
        return False
    if message_type == 'folder_link':
        folder_id = metadata.get('folder_id')
        folder_name = (metadata.get('folder_name') or '').strip()
        try:
            has_folder_id = int(folder_id) > 0
        except (TypeError, ValueError):
            has_folder_id = False
        return has_folder_id or bool(folder_name)
    if message_type == 'calendar_event':
        return bool((metadata.get('title') or '').strip())
    if message_type == 'poll':
        question = (metadata.get('question') or '').strip()
        options = metadata.get('options') if isinstance(metadata.get('options'), list) else []
        valid_options = [
            option for option in options
            if isinstance(option, dict) and (option.get('text') or '').strip()
        ]
        return bool(question and len(valid_options) >= 2)
    return False


def _build_calendar_message_metadata(event, current_user_status='pending'):
    is_all_day = False
    if event.start_time and event.end_time:
        starts_midnight = event.start_time.hour == 0 and event.start_time.minute == 0
        ends_same_day_2359 = (
            event.end_time.date() == event.start_time.date()
            and event.end_time.hour == 23
            and event.end_time.minute == 59
        )
        ends_next_day_midnight = (
            event.end_time.date() > event.start_time.date()
            and event.end_time.hour == 0
            and event.end_time.minute == 0
        )
        is_all_day = bool(starts_midnight and (ends_same_day_2359 or ends_next_day_midnight))
    participants = EventParticipant.query.filter_by(event_id=event.id).all()
    accepted_count = sum(1 for participant in participants if participant.status == 'accepted')
    declined_count = sum(1 for participant in participants if participant.status == 'declined')
    pending_count = sum(1 for participant in participants if participant.status == 'pending')
    from app.utils import get_local_time
    return {
        'event_id': event.id,
        'title': event.title,
        'description': event.description or '',
        'location': event.location or '',
        'start_time': event.start_time.isoformat() if event.start_time else None,
        'end_time': event.end_time.isoformat() if event.end_time else None,
        'start_time_label': 'Ganztägig' if is_all_day else (get_local_time(event.start_time).strftime('%H:%M') if event.start_time else ''),
        'end_time_label': '' if is_all_day else (get_local_time(event.end_time).strftime('%H:%M') if event.end_time else ''),
        'is_all_day': is_all_day,
        'event_url': url_for('calendar.view_event', event_id=event.id),
        'accepted_count': accepted_count,
        'declined_count': declined_count,
        'pending_count': pending_count,
        'participant_count': len(participants),
        'current_user_status': current_user_status or 'pending',
    }


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
    if member_ids:
        members = User.query.filter(
            User.id.in_(member_ids),
            *visible_chat_user_filters(),
        ).all()
    else:
        members = []
    
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
        return jsonify({'error': translate('chat.errors.unauthorized')}), 403
    
    payload = request.get_json(silent=True) if request.is_json else {}
    content = (payload.get('content') if payload else request.form.get('content', '')) or ''
    content = content.strip()
    file = request.files.get('file')
    requested_message_type = (payload.get('message_type') if payload else request.form.get('message_type', 'text')) or 'text'
    requested_message_type = requested_message_type.strip().lower()
    metadata = payload.get('metadata') if payload else None
    if metadata is None:
        metadata_raw = request.form.get('metadata')
        if metadata_raw:
            try:
                metadata = json.loads(metadata_raw)
            except Exception:
                metadata = None
    
    message_type = requested_message_type if requested_message_type in {'text', 'folder_link', 'calendar_event', 'poll'} else 'text'
    media_url = None
    
    # Handle file upload
    if file and file.filename:
        if not allowed_file(file.filename):
            return jsonify({'error': 'Dateityp nicht erlaubt'}), 400
        original_filename = secure_filename(file.filename)
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
        
        message_type = _resolve_message_type(filename, file.mimetype)
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.setdefault('original_name', original_filename)
        try:
            metadata.setdefault('size_bytes', os.path.getsize(filepath))
        except Exception:
            pass
    
    if message_type == 'folder_link':
        if not isinstance(metadata, dict):
            metadata = {}
        raw_folder_id = metadata.get('folder_id')
        try:
            folder_id = int(raw_folder_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Bitte einen Ordner auswählen.'}), 400
        folder = Folder.query.get(folder_id)
        if not folder:
            return jsonify({'error': 'Ordner wurde nicht gefunden.'}), 404

        if current_user.is_guest:
            _, guest_folders = get_guest_accessible_items(current_user)
            accessible_folder_ids = {item.id for item in guest_folders}
            if folder.id not in accessible_folder_ids:
                return jsonify({'error': 'Gast Accounts haben keinen Zugriff auf diese Funktion'}), 403

        metadata = {
            'folder_id': folder.id,
            'folder_name': folder.name,
            'folder_path': folder.path,
            'folder_url': url_for('files.browse_folder', folder_id=folder.id),
        }
    if message_type == 'calendar_event':
        if not isinstance(metadata, dict):
            metadata = {}
        raw_event_id = metadata.get('event_id')
        try:
            event_id = int(raw_event_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Bitte einen Termin auswählen.'}), 400
        event = CalendarEvent.query.get(event_id)
        if not event:
            return jsonify({'error': 'Termin wurde nicht gefunden.'}), 404
        participation = EventParticipant.query.filter_by(event_id=event.id, user_id=current_user.id).first()
        if participation and participation.status == 'removed':
            return jsonify({'error': 'Sie wurden aus diesem Termin entfernt.'}), 403

        metadata = _build_calendar_message_metadata(
            event,
            participation.status if participation else 'pending',
        )

    if not content and not media_url and not _has_structured_message_content(message_type, metadata):
        return jsonify({'error': translate('chat.errors.message_empty')}), 400
    
    # Create message
    message = ChatMessage(
        chat_id=actual_chat_id,
        sender_id=current_user.id,
        content=content,
        message_type=message_type,
        media_url=media_url
    )
    if isinstance(metadata, dict):
        message.set_metadata(metadata)
    
    db.session.add(message)
    db.session.commit()
    
    # Sende Push-Benachrichtigungen an andere Chat-Mitglieder
    try:
        enqueue_chat_notification(
            chat_id=actual_chat_id,
            sender_id=current_user.id,
            message_content=content or f"[{message_type}]",
            chat_name=chat.name,
            message_id=message.id  # WICHTIG: Für Duplikat-Vermeidung
        )
        print("Chat-Push-Benachrichtigung asynchron eingeplant")
    except Exception as e:
        print(f"Fehler beim Senden der Push-Benachrichtigungen: {e}")
    
    # Sende Dashboard-Updates an alle Chat-Mitglieder (außer dem Sender)
    try:
        chat_members = ChatMember.query.filter_by(chat_id=actual_chat_id).all()
        member_ids = [cm.user_id for cm in chat_members if cm.user_id != current_user.id]
        
        if member_ids:
            # Berechne unread_count für jeden Benutzer
            for user_id in member_ids:
                user_memberships = ChatMember.query.filter_by(user_id=user_id).all()
                unread_count = 0
                for member in user_memberships:
                    chat_unread = ChatMessage.query.filter(
                        and_(
                            ChatMessage.chat_id == member.chat_id,
                            ChatMessage.sender_id != user_id,
                            ChatMessage.created_at > member.last_read_at,
                            ChatMessage.is_deleted == False
                        )
                    ).count()
                    unread_count += chat_unread
                
                # Emittiere Dashboard-Update für jeden Benutzer
                from app.utils.dashboard_events import emit_dashboard_update
                emit_dashboard_update(user_id, 'chat_update', {'count': unread_count})
    except Exception as e:
        current_app.logger.error(f"Fehler beim Senden der Dashboard-Updates für Chat: {e}")
    
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from app.utils import get_local_time
        return jsonify({
            'id': message.id,
            'sender_id': current_user.id,
            'sender': current_user.full_name,
            'content': message.content,
            'message_type': message.message_type,
            'media_url': message.media_url,
            'metadata': message.get_metadata(),
            'created_at': get_local_time(message.created_at).isoformat()
        })
    
    # Always redirect to /chat/1 for main chat to keep URL consistent
    redirect_chat_id = 1 if chat.is_main_chat else chat_id
    return redirect(url_for('chat.view_chat', chat_id=redirect_chat_id))


@chat_bp.route('/<int:chat_id>/folder-options', methods=['GET'])
@login_required
@check_module_access('module_chat')
def get_chat_folder_options(chat_id):
    """Liefert auswählbare Ordner für den Chat-Attachment-Dialog."""
    if chat_id == 1:
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if not main_chat:
            return jsonify({'error': 'Haupt-Chat nicht gefunden'}), 404
        actual_chat_id = main_chat.id
    else:
        actual_chat_id = chat_id

    membership = ChatMember.query.filter_by(chat_id=actual_chat_id, user_id=current_user.id).first()
    if not membership:
        return jsonify({'error': translate('chat.errors.unauthorized')}), 403

    if current_user.is_guest:
        _, folders = get_guest_accessible_items(current_user)
    else:
        folders = Folder.query.order_by(Folder.name.asc()).all()

    unique_folders = {folder.id: folder for folder in folders}.values()
    sorted_folders = sorted(unique_folders, key=lambda folder: (folder.path or folder.name).lower())

    return jsonify({
        'success': True,
        'is_guest': bool(current_user.is_guest),
        'folders': [
            {
                'id': folder.id,
                'name': folder.name,
                'path': folder.path,
            }
            for folder in sorted_folders
        ],
    }), 200


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
                flash(translate('chat.flash.no_self_chat'), 'warning')
                return redirect(url_for('chat.create_chat'))
            
            # Prüfe ob bereits ein privater Chat mit dieser Person existiert
            other_user = User.query.filter(
                User.id == member_id,
                *visible_chat_user_filters(),
            ).first_or_404()
            existing_dm = Chat.query.filter_by(is_direct_message=True).join(ChatMember).filter(
                ChatMember.user_id.in_([current_user.id, member_id])
            ).group_by(Chat.id).having(db.func.count(ChatMember.id) == 2).first()
            
            if existing_dm:
                flash(translate('chat.flash.private_chat_exists', name=other_user.full_name), 'info')
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
            
            flash(translate('chat.flash.private_chat_created', name=other_user.full_name), 'success')
            return redirect(url_for('chat.view_chat', chat_id=new_chat.id))
        
        else:
            # Gruppen-Chat
            name = request.form.get('name', '').strip()
            member_ids = request.form.getlist('members')
            
            if not name:
                flash(translate('chat.flash.enter_name'), 'danger')
                return redirect(url_for('chat.create_chat'))
            
            if not member_ids:
                flash(translate('chat.flash.select_member'), 'danger')
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
                    user = User.query.filter(
                        User.id == int(member_id),
                        *visible_chat_user_filters(),
                    ).first()
                    if user:
                        member = ChatMember(
                            chat_id=new_chat.id,
                            user_id=int(member_id)
                        )
                        db.session.add(member)
            
            db.session.commit()
            
            flash(translate('chat.flash.group_chat_created', name=name), 'success')
            return redirect(url_for('chat.view_chat', chat_id=new_chat.id))
    
    # Get all selectable users for chat creation, including guests.
    users = User.query.filter(*selectable_chat_user_filters(include_guests=True)).all()
    return render_template('chat/create.html', users=users)


@chat_bp.route('/direct/<int:user_id>')
@login_required
@check_module_access('module_chat')
def direct_message(user_id):
    """Start or continue a direct message with a user."""
    other_user = User.query.filter(
        User.id == user_id,
        *visible_chat_user_filters(),
    ).first_or_404()
    
    if user_id == current_user.id:
        flash(translate('chat.flash.no_self_chat'), 'warning')
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
        return jsonify({'error': translate('chat.errors.unauthorized')}), 403
    
    # Only allow updating group chats (not main chat, not direct messages)
    if chat.is_main_chat:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': translate('chat.errors.main_chat_cannot_edit')}), 400
        flash(translate('chat.flash.main_chat_cannot_edit'), 'danger')
        return redirect(url_for('chat.view_chat', chat_id=1))
    if chat.is_direct_message:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': translate('chat.errors.private_chat_cannot_edit')}), 400
        flash(translate('chat.flash.private_chat_cannot_edit'), 'danger')
        return redirect(url_for('chat.view_chat', chat_id=chat_id))
    
    # Alle Mitglieder können den Chat bearbeiten (Mitgliedschaft wurde bereits geprüft)
    
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
    
    flash(translate('chat.flash.updated'), 'success')
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
            return jsonify({'error': translate('chat.errors.main_chat_cannot_delete')}), 400
        flash('Der Haupt-Chat kann nicht gelöscht werden', 'danger')
        return redirect(url_for('chat.view_chat', chat_id=1))
    
    # Check if user is a member (Mitgliedschaft wurde bereits geprüft in view_chat, aber hier sicherstellen)
    membership = ChatMember.query.filter_by(
        chat_id=actual_chat_id,
        user_id=current_user.id
    ).first()
    
    if not membership:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': translate('chat.errors.not_member')}), 403
        flash('Sie sind kein Mitglied dieses Chats', 'danger')
        return redirect(url_for('chat.index'))
    
    # Alle Mitglieder können den Chat löschen (Mitgliedschaft wurde bereits geprüft)
    
    # Delete chat (cascade will handle messages and members)
    db.session.delete(chat)
    db.session.commit()
    
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Chat erfolgreich gelöscht'})
    
    flash(translate('chat.flash.deleted'), 'success')
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
    
    # Only allow editing group chats (not main chat, not direct messages)
    if chat.is_main_chat:
        flash(translate('chat.flash.main_chat_cannot_edit'), 'danger')
        return redirect(url_for('chat.view_chat', chat_id=1))
    if chat.is_direct_message:
        flash(translate('chat.flash.private_chat_cannot_edit'), 'danger')
        return redirect(url_for('chat.view_chat', chat_id=chat_id))
    
    # Alle Mitglieder können die Chat-Einstellungen bearbeiten (Mitgliedschaft wurde bereits geprüft)
    
    if request.method == 'POST':
        return update_chat(chat_id)
    
    # Get chat members
    chat_memberships = ChatMember.query.filter_by(chat_id=chat_id).all()
    member_ids = [cm.user_id for cm in chat_memberships]
    if member_ids:
        members = User.query.filter(
            User.id.in_(member_ids),
            *visible_chat_user_filters(),
        ).all()
    else:
        members = []
    
    return render_template(
        'chat/settings.html',
        chat=chat,
        members=members
    )



