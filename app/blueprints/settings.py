from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, abort, current_app, send_file, g, after_this_request
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.email import EmailPermission
from app.models.settings import SystemSettings
from app.models.notification import NotificationSettings, ChatNotificationSettings, PushSubscription, NotificationLog
from app.models.chat import Chat, ChatMember
from app.models.whitelist import WhitelistEntry
from app.utils.notifications import get_or_create_notification_settings
from app.utils.backup import export_backup, import_backup, SUPPORTED_CATEGORIES
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import tempfile
from app.utils.i18n import available_languages, translate

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/')
@login_required
def index():
    """User settings page."""
    return render_template('settings/index.html', user=current_user)


@settings_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Edit user profile."""
    # Gast-Accounts können ihr Profil nicht bearbeiten
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash(translate('settings.profile.flash_guests_cannot_edit'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        current_user.first_name = request.form.get('first_name', '').strip()
        current_user.last_name = request.form.get('last_name', '').strip()
        current_user.email = request.form.get('email', '').strip().lower()
        current_user.phone = request.form.get('phone', '').strip()
        
        # Handle password change
        new_password = request.form.get('new_password', '').strip()
        if new_password:
            if len(new_password) < 8:
                flash(translate('settings.profile.flash_password_length'), 'danger')
                return render_template('settings/profile.html', user=current_user)
            current_user.set_password(new_password)
        
        # Handle profile picture upload
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename:
                # Validate file type
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
                if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    # Validate file size (5MB limit)
                    file.seek(0, 2)  # Seek to end
                    file_size = file.tell()
                    file.seek(0)  # Reset to beginning
                    
                    max_size = 5 * 1024 * 1024  # 5MB in bytes
                    if file_size > max_size:
                        flash(translate('settings.profile.flash_picture_too_large', size=file_size / (1024*1024)), 'danger')
                        return render_template('settings/profile.html', user=current_user)
                    
                    # Create filename with timestamp
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"{current_user.id}_{timestamp}_{filename}"
                    
                    # Ensure upload directory exists (absolute path)
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    # Save file
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    
                    # Delete old profile picture if it exists
                    if current_user.profile_picture:
                        try:
                            old_path = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics', current_user.profile_picture)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except OSError:
                            pass  # Ignore if file doesn't exist
                    
                    current_user.profile_picture = filename
                    flash(translate('settings.profile.flash_picture_uploaded'), 'success')
                else:
                    flash(translate('settings.profile.flash_picture_invalid_type'), 'danger')
                    return render_template('settings/profile.html', user=current_user)
        
        current_user.notifications_enabled = 'notifications_enabled' in request.form
        current_user.chat_notifications = 'chat_notifications' in request.form
        current_user.email_notifications = 'email_notifications' in request.form
        
        db.session.commit()
        flash(translate('settings.profile.flash_profile_updated'), 'success')
        return redirect(url_for('settings.profile'))
    
    return render_template('settings/profile.html', user=current_user)


@settings_bp.route('/profile/remove-picture', methods=['POST'])
@login_required
def remove_profile_picture():
    """Remove user's profile picture."""
    # Gast-Accounts können ihr Profil nicht bearbeiten
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash(translate('settings.profile.flash_guests_cannot_edit'), 'danger')
        return redirect(url_for('settings.index'))
    
    if current_user.profile_picture:
        try:
            project_root = os.path.dirname(current_app.root_path)
            upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
            file_path = os.path.join(upload_dir, current_user.profile_picture)
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass  # Ignore if file doesn't exist
    
    current_user.profile_picture = None
    db.session.commit()
    flash(translate('settings.profile.flash_picture_removed'), 'success')
    return redirect(url_for('settings.profile'))


@settings_bp.route('/profile-picture/<path:filename>')
@login_required
def profile_picture(filename):
    """Serve profile pictures."""
    try:
        from urllib.parse import unquote
        # URL-decode den Dateinamen
        filename = unquote(filename)
        
        project_root = os.path.dirname(current_app.root_path)
        directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
        full_path = os.path.join(directory, filename)
        
        if current_app.debug:
            print(f"[PROFILE PIC] Requested filename: {filename}")
            print(f"[PROFILE PIC] Full path: {full_path}")
            print(f"[PROFILE PIC] File exists: {os.path.isfile(full_path)}")
            print(f"[PROFILE PIC] Directory contents: {os.listdir(directory) if os.path.exists(directory) else 'Directory not found'}")
        
        if not os.path.isfile(full_path):
            abort(404)
            
        return send_from_directory(directory, filename)
    except FileNotFoundError:
        abort(404)


@settings_bp.route('/portal-logo/<path:filename>')
def portal_logo(filename):
    """Serve portal logo (public access)."""
    try:
        from urllib.parse import unquote
        filename = unquote(filename)
        
        project_root = os.path.dirname(current_app.root_path)
        directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
        full_path = os.path.join(directory, filename)
        
        if not os.path.isfile(full_path):
            abort(404)
            
        return send_from_directory(directory, filename)
    except FileNotFoundError:
        abort(404)


@settings_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
def notifications():
    """Benachrichtigungseinstellungen."""
    if request.method == 'POST':
        # Hole oder erstelle Benachrichtigungseinstellungen
        settings = get_or_create_notification_settings(current_user.id)
        
        # Chat-Benachrichtigungen
        settings.chat_notifications_enabled = 'chat_notifications_enabled' in request.form
        
        # Datei-Benachrichtigungen
        settings.file_notifications_enabled = 'file_notifications_enabled' in request.form
        settings.file_new_notifications = 'file_new_notifications' in request.form
        settings.file_modified_notifications = 'file_modified_notifications' in request.form
        
        # E-Mail-Benachrichtigungen
        settings.email_notifications_enabled = 'email_notifications_enabled' in request.form
        
        # Kalender-Benachrichtigungen
        settings.calendar_notifications_enabled = 'calendar_notifications_enabled' in request.form
        settings.calendar_all_events = request.form.get('calendar_event_filter') == 'all'
        settings.calendar_participating_only = 'calendar_participating_only' in request.form
        settings.calendar_not_participating = 'calendar_not_participating' in request.form
        settings.calendar_no_response = 'calendar_no_response' in request.form
        
        # Erinnerungszeiten
        reminder_times = request.form.getlist('reminder_times')
        settings.set_reminder_times([int(t) for t in reminder_times])
        
        # Chat-spezifische Einstellungen
        # Lösche alle bestehenden Chat-Einstellungen
        ChatNotificationSettings.query.filter_by(user_id=current_user.id).delete()
        
        # Erstelle neue Chat-Einstellungen
        for key, value in request.form.items():
            if key.startswith('chat_') and key != 'chat_notifications_enabled':
                chat_id = int(key.split('_')[1])
                chat_setting = ChatNotificationSettings(
                    user_id=current_user.id,
                    chat_id=chat_id,
                    notifications_enabled=True
                )
                db.session.add(chat_setting)
        
        db.session.commit()
        flash(translate('settings.notifications.flash_saved'), 'success')
        return redirect(url_for('settings.notifications'))
    
    # Hole Benachrichtigungseinstellungen
    settings = get_or_create_notification_settings(current_user.id)
    
    # Hole alle Chats des Benutzers
    memberships = ChatMember.query.filter_by(user_id=current_user.id).all()
    user_chats = [membership.chat for membership in memberships]
    
    # Hole Chat-spezifische Einstellungen
    chat_notification_settings = {}
    for chat in user_chats:
        chat_setting = ChatNotificationSettings.query.filter_by(
            user_id=current_user.id,
            chat_id=chat.id
        ).first()
        chat_notification_settings[chat.id] = chat_setting.notifications_enabled if chat_setting else True
    
    return render_template(
        'settings/notifications.html',
        settings=settings,
        user_chats=user_chats,
        chat_notification_settings=chat_notification_settings
    )


@settings_bp.route('/appearance', methods=['GET', 'POST'])
@login_required
def appearance():
    """Edit appearance settings."""
    language_codes = list(available_languages())
    selected_language = request.form.get('language') if request.method == 'POST' else current_user.language

    if request.method == 'POST':
        color_type = request.form.get('color_type', 'solid')
        accent_color = request.form.get('accent_color', '#0d6efd')
        accent_gradient = request.form.get('accent_gradient', '').strip()
        dark_mode = request.form.get('dark_mode') == 'on'
        oled_mode = request.form.get('oled_mode') == 'on'
        preferred_layout = request.form.get('preferred_layout', 'auto')

        if selected_language and selected_language not in language_codes:
            flash(translate('settings.appearance.flash_invalid_language'), 'danger')
            return redirect(url_for('settings.appearance'))

        if preferred_layout not in ['auto', 'mobile', 'desktop']:
            preferred_layout = 'auto'

        current_user.accent_color = accent_color
        current_user.dark_mode = dark_mode
        current_user.oled_mode = oled_mode if dark_mode else False
        current_user.preferred_layout = preferred_layout

        if color_type == 'gradient' and accent_gradient:
            current_user.accent_gradient = accent_gradient
        else:
            current_user.accent_gradient = None

        if selected_language:
            current_user.language = selected_language
            g.language = selected_language

        db.session.commit()
        flash(translate('settings.appearance.flash_success'), 'success')
        return redirect(url_for('settings.appearance'))

    language_options = []
    for code in language_codes:
        key = f'languages.{code}'
        label = translate(key)
        if label == key:
            label = LANGUAGE_FALLBACK_NAMES.get(code, code.upper())
        language_options.append({'code': code, 'label': label})

    return render_template('settings/appearance.html', user=current_user, language_options=language_options)


@settings_bp.route('/admin')
@login_required
def admin():
    """Admin settings page."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    return render_template('settings/admin.html')


@settings_bp.route('/admin/users')
@login_required
def admin_users():
    """Manage users and roles (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.users.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.role import UserModuleRole
    
    # Liste aller Module für Rollenanzeige
    all_modules = [
        ('module_chat', 'Chat'),
        ('module_files', 'Dateien'),
        ('module_calendar', 'Kalender'),
        ('module_email', 'E-Mail'),
        ('module_credentials', 'Zugangsdaten'),
        ('module_manuals', 'Anleitungen'),
        ('module_inventory', 'Lagerverwaltung'),
        ('module_wiki', 'Wiki'),
        ('module_booking', 'Buchungen'),
        ('module_music', 'Musik')
    ]
    
    # Get all users, excluding guest accounts (system accounts)
    active_users = User.query.filter(
        User.is_active == True,
        ~User.is_guest,
        User.email != 'anonymous@system.local'
    ).order_by(User.last_name, User.first_name).all()
    pending_users = User.query.filter(
        User.is_active == False,
        ~User.is_guest,
        User.email != 'anonymous@system.local'
    ).order_by(User.created_at.desc()).all()
    
    # Get all guest accounts
    guest_users = User.query.filter(
        User.is_guest == True
    ).order_by(User.created_at.desc()).all()
    
    # Erstelle Liste mit Benutzer-Rollen-Informationen für aktive Benutzer
    users_with_roles = []
    for user in active_users:
        # Hole Modul-Rollen für diesen Benutzer
        module_roles = {}
        user_module_roles = UserModuleRole.query.filter_by(user_id=user.id).all()
        for role in user_module_roles:
            module_roles[role.module_key] = role.has_access
        
        users_with_roles.append({
            'user': user,
            'has_full_access': user.has_full_access,
            'module_roles': module_roles
        })
    
    # Erstelle Liste mit Gast-Account-Rollen-Informationen
    guest_users_with_roles = []
    for guest in guest_users:
        # Hole Modul-Rollen für diesen Gast
        module_roles = {}
        user_module_roles = UserModuleRole.query.filter_by(user_id=guest.id).all()
        for role in user_module_roles:
            module_roles[role.module_key] = role.has_access
        
        # Hole Freigabelink-Zugriffe
        from app.models.guest import GuestShareAccess
        share_accesses = GuestShareAccess.query.filter_by(user_id=guest.id).all()
        
        guest_users_with_roles.append({
            'user': guest,
            'module_roles': module_roles,
            'share_count': len(share_accesses)
        })
    
    from datetime import datetime
    now = datetime.utcnow()
    
    return render_template('settings/admin_users.html', 
                         active_users=active_users, 
                         pending_users=pending_users,
                         users_with_roles=users_with_roles,
                         guest_users_with_roles=guest_users_with_roles,
                         all_modules=all_modules,
                         now=now)


@settings_bp.route('/admin/users/create', methods=['GET', 'POST'])
@login_required
def create_user():
    """Create a new user account (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.role import UserModuleRole
    from app.models.chat import Chat, ChatMember
    from app.models.guest import GuestShareAccess
    from app.models.file import File, Folder
    from app.models.email import EmailPermission
    from app.utils.email_sender import send_account_creation_email, generate_random_password
    from app.utils.access_control import has_module_access
    from app.utils.common import is_module_enabled
    from datetime import datetime
    import json
    
    # Prüfe ob AJAX-Request
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if request.method == 'POST':
        account_type = request.form.get('account_type', 'full')  # 'full' oder 'guest'
        
        if account_type == 'full':
            # Vollwertiger Account
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            phone = request.form.get('phone', '').strip() or None
            
            # Validierung
            if not all([first_name, last_name, email]):
                error_msg = 'Bitte füllen Sie alle Pflichtfelder aus.'
                if is_ajax:
                    from flask import jsonify
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'danger')
                return redirect(url_for('settings.create_user'))
            
            # Prüfe ob E-Mail bereits existiert
            if User.query.filter_by(email=email).first():
                error_msg = 'Diese E-Mail-Adresse ist bereits registriert.'
                if is_ajax:
                    from flask import jsonify
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'danger')
                return redirect(url_for('settings.create_user'))
            
            # Generiere zufälliges Passwort
            password = generate_random_password(8)
            
            # Erstelle Benutzer
            new_user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_active=True,
                is_email_confirmed=True,  # Admin erstellt - E-Mail ist bestätigt
                is_guest=False,
                must_change_password=True  # Benutzer muss Passwort beim ersten Login ändern
            )
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.flush()  # Flush um ID zu bekommen
            
            # Wähle Standardrollen aus SystemSettings
            default_roles_setting = SystemSettings.query.filter_by(key='default_module_roles').first()
            if default_roles_setting:
                try:
                    default_roles = json.loads(default_roles_setting.value)
                    
                    if default_roles.get('full_access', False):
                        new_user.has_full_access = True
                    else:
                        # Modulspezifische Rollen zuweisen
                        all_modules = [
                            'module_chat', 'module_files', 'module_calendar', 'module_email',
                            'module_credentials', 'module_manuals',
                            'module_inventory', 'module_wiki', 'module_booking', 'module_music'
                        ]
                        
                        for module_key in all_modules:
                            if default_roles.get(module_key, False) and is_module_enabled(module_key):
                                role = UserModuleRole(
                                    user_id=new_user.id,
                                    module_key=module_key,
                                    has_access=True
                                )
                                db.session.add(role)
                except:
                    pass  # Bei Fehler: Standard-Rollen verwenden
            
            # Erstelle E-Mail-Berechtigungen
            email_perm = EmailPermission(
                user_id=new_user.id,
                can_read=True,
                can_send=True
            )
            db.session.add(email_perm)
            
            # Commit rollen first, so has_module_access works correctly
            db.session.commit()
            
            # Füge zum Haupt-Chat hinzu (alle vollwertigen Accounts werden hinzugefügt)
            from app.models.chat import Chat, ChatMember
            if new_user.is_active and not new_user.is_guest:
                main_chat = Chat.query.filter_by(is_main_chat=True).first()
                if main_chat:
                    # Prüfe ob Benutzer bereits Mitglied ist
                    existing_member = ChatMember.query.filter_by(
                        chat_id=main_chat.id,
                        user_id=new_user.id
                    ).first()
                    if not existing_member:
                        member = ChatMember(
                            chat_id=main_chat.id,
                            user_id=new_user.id
                        )
                        db.session.add(member)
                        db.session.commit()
            
            # Sende E-Mail mit Zugangsdaten
            email_sent = send_account_creation_email(new_user, password)
            
            # Bei AJAX-Request: JSON mit Zugangsdaten zurückgeben
            if is_ajax:
                from flask import jsonify
                if email_sent:
                    return jsonify({
                        'success': True,
                        'message': f'Account für {new_user.full_name} wurde erstellt und E-Mail mit Zugangsdaten wurde gesendet.',
                        'credentials': {
                            'username': email,
                            'password': password,
                            'full_name': new_user.full_name,
                            'email_sent': True
                        }
                    })
                else:
                    return jsonify({
                        'success': True,
                        'message': f'Account für {new_user.full_name} wurde erstellt, aber E-Mail konnte nicht gesendet werden.',
                        'credentials': {
                            'username': email,
                            'password': password,
                            'full_name': new_user.full_name,
                            'email_sent': False
                        }
                    })
            
            # Normale Weiterleitung mit Flash (Fallback)
            if email_sent:
                flash(translate('settings.admin.users.flash_user_created', name=new_user.full_name), 'success')
            else:
                flash(translate('settings.admin.users.flash_email_failed', name=new_user.full_name, email=email, password=password), 'warning')
            
            return redirect(url_for('settings.admin_users'))
        
        elif account_type == 'guest':
            # Gast-Account
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            guest_username_raw = request.form.get('guest_username', '').strip()
            guest_expires_at_str = request.form.get('guest_expires_at', '').strip()
            guest_expires_at = None
            
            # Validierung: Prüfe ob alle Pflichtfelder ausgefüllt sind
            if not first_name:
                error_msg = 'Bitte geben Sie einen Vornamen ein.'
                if is_ajax:
                    from flask import jsonify
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'danger')
                return redirect(url_for('settings.create_user'))
            
            if not last_name:
                error_msg = 'Bitte geben Sie einen Nachnamen ein.'
                if is_ajax:
                    from flask import jsonify
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'danger')
                return redirect(url_for('settings.create_user'))
            
            if not guest_username_raw:
                error_msg = 'Bitte geben Sie einen Gast-Benutzernamen ein.'
                if is_ajax:
                    from flask import jsonify
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'danger')
                return redirect(url_for('settings.create_user'))
            
            # Validiere Gast-Benutzername Format (Groß-/Kleinbuchstaben, Zahlen, Punkt, Unterstrich, Bindestrich)
            import re
            if not re.match(r'^[a-zA-Z0-9._\-]+$', guest_username_raw):
                error_msg = 'Der Gast-Benutzername darf nur Buchstaben (Groß- und Kleinbuchstaben), Zahlen, Punkte, Unterstriche und Bindestriche enthalten.'
                if is_ajax:
                    from flask import jsonify
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'danger')
                return redirect(url_for('settings.create_user'))
            
            # Konvertiere zu lowercase für die Speicherung
            guest_username = guest_username_raw.lower()
            
            # Parse Ablaufzeit
            if guest_expires_at_str:
                try:
                    guest_expires_at = datetime.fromisoformat(guest_expires_at_str.replace('T', ' '))
                except:
                    error_msg = 'Ungültiges Datumsformat für Ablaufzeit.'
                    if is_ajax:
                        from flask import jsonify
                        return jsonify({'success': False, 'message': error_msg}), 400
                    flash(error_msg, 'danger')
                    return redirect(url_for('settings.create_user'))
            
            # Email-Format: {guest_username}@gast.system.local
            email = f"{guest_username}@gast.system.local"
            
            # Prüfe ob Benutzername bereits existiert
            if User.query.filter_by(guest_username=guest_username, is_guest=True).first():
                error_msg = 'Dieser Gast-Benutzername ist bereits vergeben.'
                if is_ajax:
                    from flask import jsonify
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'danger')
                return redirect(url_for('settings.create_user'))
            
            # Prüfe ob E-Mail bereits existiert
            if User.query.filter_by(email=email).first():
                error_msg = 'Dieser Gast-Account existiert bereits.'
                if is_ajax:
                    from flask import jsonify
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'danger')
                return redirect(url_for('settings.create_user'))
            
            # Generiere zufälliges Passwort
            password = generate_random_password(8)
            
            # Erstelle Gast-Benutzer
            new_user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                guest_username=guest_username,
                is_active=True,
                is_guest=True,
                guest_expires_at=guest_expires_at,
                has_full_access=False,
                can_borrow=False,
                is_email_confirmed=True  # Gast-Accounts haben keine E-Mail-Bestätigung
            )
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.flush()  # Flush um ID zu bekommen
            
            # Freigabelink-Zuweisungen - aktiviert automatisch Dateien-Modul
            share_tokens = request.form.getlist('share_tokens')
            has_file_access = False
            for share_token in share_tokens:
                # Prüfe ob es ein File oder Folder ist
                file_item = File.query.filter_by(share_token=share_token, share_enabled=True).first()
                folder_item = Folder.query.filter_by(share_token=share_token, share_enabled=True).first()
                
                if file_item:
                    share_access = GuestShareAccess(
                        user_id=new_user.id,
                        share_token=share_token,
                        share_type='file'
                    )
                    db.session.add(share_access)
                    has_file_access = True
                elif folder_item:
                    share_access = GuestShareAccess(
                        user_id=new_user.id,
                        share_token=share_token,
                        share_type='folder'
                    )
                    db.session.add(share_access)
                    has_file_access = True
            
            # Automatisch Dateien-Modul aktivieren, wenn Freigabelinks zugewiesen wurden
            if has_file_access and is_module_enabled('module_files'):
                role = UserModuleRole(
                    user_id=new_user.id,
                    module_key='module_files',
                    has_access=True
                )
                db.session.add(role)
            
            # Chat-Zuweisungen - aktiviert automatisch Chat-Modul
            chat_ids = request.form.getlist('chat_ids')
            has_chat_access = False
            for chat_id_str in chat_ids:
                try:
                    chat_id = int(chat_id_str)
                    chat = Chat.query.get(chat_id)
                    if chat:
                        member = ChatMember(
                            chat_id=chat_id,
                            user_id=new_user.id
                        )
                        db.session.add(member)
                        has_chat_access = True
                except (ValueError, TypeError):
                    pass
            
            # Automatisch Chat-Modul aktivieren, wenn Chats zugewiesen wurden
            if has_chat_access and is_module_enabled('module_chat'):
                role = UserModuleRole(
                    user_id=new_user.id,
                    module_key='module_chat',
                    has_access=True
                )
                db.session.add(role)
            
            # Modulspezifische Rollen zuweisen (ohne E-Mail, Credentials, Chats und Dateien)
            # Diese werden automatisch über Freigabelinks/Chats gesteuert
            allowed_modules = [
                'module_calendar',
                'module_manuals', 'module_inventory', 'module_wiki', 'module_music'
            ]
            
            selected_modules = request.form.getlist('allowed_modules')
            for module_key in selected_modules:
                if module_key in allowed_modules and is_module_enabled(module_key):
                    role = UserModuleRole(
                        user_id=new_user.id,
                        module_key=module_key,
                        has_access=True
                    )
                    db.session.add(role)
            
            # KEINE EmailPermission für Gäste
            # KEINE Haupt-Chat-Mitgliedschaft automatisch
            
            db.session.commit()
            
            # Bei AJAX-Request: JSON mit Zugangsdaten zurückgeben
            if is_ajax:
                from flask import jsonify
                return jsonify({
                    'success': True,
                    'message': f'Gast-Account für {new_user.full_name} wurde erstellt.',
                    'credentials': {
                        'username': email,
                        'password': password,
                        'full_name': new_user.full_name,
                        'guest_username': guest_username
                    }
                })
            
            # Normale Weiterleitung mit Flash (Fallback)
            flash(translate('settings.admin.users.flash_guest_created', name=new_user.full_name, email=email, password=password), 'success')
            return redirect(url_for('settings.admin_users'))
        else:
            error_msg = 'Ungültiger Account-Typ.'
            if is_ajax:
                from flask import jsonify
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'danger')
            return redirect(url_for('settings.create_user'))
    
    # GET: Zeige Formular
    # Hole alle verfügbaren Module (ohne E-Mail, Credentials, Chats und Dateien für Gäste)
    # Chats und Dateien werden über spezifische Zuweisungen gesteuert
    guest_modules = [
        ('module_calendar', 'Kalender'),
        ('module_manuals', 'Anleitungen'),
        ('module_inventory', 'Lagerverwaltung'),
        ('module_wiki', 'Wiki'),
        ('module_music', 'Musik')
    ]
    
    # Hole alle verfügbaren Freigabelinks
    from app.models.file import File, Folder
    shared_files = File.query.filter_by(share_enabled=True).all()
    shared_folders = Folder.query.filter_by(share_enabled=True).all()
    
    # Hole alle verfügbaren Chats (ohne Duplikate)
    # Nur einen Haupt-Chat zeigen (auch wenn mehrere existieren, zeige nur den ersten/ältesten)
    # Hole alle Chats und filtere nach is_main_chat
    all_chats_list = Chat.query.order_by(Chat.created_at).all()
    
    # Erstelle Liste ohne Duplikate: Haupt-Chat zuerst (nur einer), dann andere
    all_chats = []
    main_chat_added = False
    main_chat_ids = set()
    
    # Zuerst: Füge nur den ersten Haupt-Chat hinzu
    for chat in all_chats_list:
        if chat.is_main_chat and not main_chat_added:
            all_chats.append(chat)
            main_chat_added = True
            main_chat_ids.add(chat.id)
        elif chat.is_main_chat:
            # Weitere Haupt-Chats: Markiere sie, aber füge sie nicht hinzu
            main_chat_ids.add(chat.id)
        elif not chat.is_main_chat:
            # Normale Chats: Füge sie hinzu
            all_chats.append(chat)
    
    return render_template('settings/admin_create_user.html',
                         guest_modules=guest_modules,
                         shared_files=shared_files,
                         shared_folders=shared_folders,
                         all_chats=all_chats)


@settings_bp.route('/admin/users/<int:user_id>/activate', methods=['POST'])
@login_required
def activate_user(user_id):
    """Activate a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    user = User.query.get_or_404(user_id)
    user.is_active = True
    
    # Ensure user is added to main chat when activated (only for full accounts, not guest accounts)
    from app.models.chat import Chat, ChatMember
    if not user.is_guest and user.email != 'anonymous@system.local':
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if main_chat:
            # Check if user is already a member
            existing_membership = ChatMember.query.filter_by(
                chat_id=main_chat.id,
                user_id=user.id
            ).first()
            
            if not existing_membership:
                # Add user to main chat
                member = ChatMember(
                    chat_id=main_chat.id,
                    user_id=user.id
                )
                db.session.add(member)
    
    db.session.commit()
    
    flash(translate('settings.admin.users.flash_user_activated', name=user.full_name), 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
def deactivate_user(user_id):
    """Deactivate a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    if user_id == current_user.id:
        flash(translate('settings.admin.users.flash_cannot_deactivate_self'), 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user = User.query.get_or_404(user_id)
    
    # Super-Admins können nicht deaktiviert werden
    if user.is_super_admin:
        flash(translate('settings.admin.users.flash_cannot_deactivate_super_admin'), 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user.is_active = False
    db.session.commit()
    
    flash(translate('settings.admin.users.flash_user_deactivated', name=user.full_name), 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/users/<int:user_id>/make-admin', methods=['POST'])
@login_required
def make_admin(user_id):
    """Make a user an admin (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    user = User.query.get_or_404(user_id)
    
    # Gast-Accounts können keine Admins werden
    if hasattr(user, 'is_guest') and user.is_guest:
        flash(translate('settings.admin.users.flash_guest_cannot_be_admin'), 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user.is_admin = True
    db.session.commit()
    
    flash(translate('settings.admin.users.flash_user_made_admin', name=user.full_name), 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/users/<int:user_id>/remove-admin', methods=['POST'])
@login_required
def remove_admin(user_id):
    """Remove admin rights from a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    if user_id == current_user.id:
        flash(translate('settings.admin.users.flash_cannot_remove_admin_self'), 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user = User.query.get_or_404(user_id)
    
    # Super-Admins können ihre Rechte nicht entzogen bekommen
    if user.is_super_admin:
        flash(translate('settings.admin.users.flash_cannot_remove_super_admin'), 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user.is_admin = False
    db.session.commit()
    
    flash(translate('settings.admin.users.flash_admin_removed', name=user.full_name), 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/users/<int:user_id>/edit_guest', methods=['GET', 'POST'])
@login_required
def edit_guest_user(user_id):
    """Edit a guest account (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    user = User.query.get_or_404(user_id)
    
    # Nur Gast-Accounts können bearbeitet werden
    if not user.is_guest:
        flash('Dieser Benutzer ist kein Gast-Account.', 'danger')
        return redirect(url_for('settings.admin_users'))
    
    if request.method == 'POST':
        # Aktualisiere Name
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        
        if not first_name or not last_name:
            flash('Bitte geben Sie Vor- und Nachname ein.', 'danger')
            return redirect(url_for('settings.edit_guest_user', user_id=user_id))
        
        user.first_name = first_name
        user.last_name = last_name
        
        # Aktualisiere Ablaufzeit
        guest_expires_at_str = request.form.get('guest_expires_at', '').strip()
        if guest_expires_at_str:
            try:
                user.guest_expires_at = datetime.fromisoformat(guest_expires_at_str.replace('T', ' '))
            except:
                flash('Ungültiges Datumsformat für Ablaufzeit.', 'danger')
                return redirect(url_for('settings.edit_guest_user', user_id=user_id))
        else:
            user.guest_expires_at = None
        
        # Aktualisiere Module
        from app.models.role import UserModuleRole
        from app.utils.common import is_module_enabled
        
        # Erlaubte Module für Gäste
        allowed_modules = [
            'module_calendar',
            'module_manuals', 'module_inventory', 'module_wiki', 'module_music'
        ]
        
        # Entferne alle bestehenden Modul-Rollen (außer automatisch gesetzte)
        existing_roles = UserModuleRole.query.filter_by(user_id=user.id).all()
        for role in existing_roles:
            # Behalte automatisch gesetzte Module (module_chat, module_files) nur wenn noch Zugriff vorhanden
            if role.module_key in ['module_chat', 'module_files']:
                # Prüfe ob noch Chat/File-Zugriff vorhanden
                if role.module_key == 'module_chat':
                    from app.models.chat import ChatMember
                    has_chat = ChatMember.query.filter_by(user_id=user.id).first() is not None
                    if not has_chat:
                        db.session.delete(role)
                elif role.module_key == 'module_files':
                    from app.models.guest import GuestShareAccess
                    has_file_access = GuestShareAccess.query.filter_by(user_id=user.id).first() is not None
                    if not has_file_access:
                        db.session.delete(role)
            elif role.module_key in allowed_modules:
                # Entferne erlaubte Module - werden neu gesetzt
                db.session.delete(role)
        
        # Füge neue Module hinzu
        selected_modules = request.form.getlist('allowed_modules')
        for module_key in selected_modules:
            if module_key in allowed_modules and is_module_enabled(module_key):
                role = UserModuleRole(
                    user_id=user.id,
                    module_key=module_key,
                    has_access=True
                )
                db.session.add(role)
        
        # Aktualisiere Chat-Zuweisungen
        from app.models.chat import Chat, ChatMember
        
        # Entferne alle bestehenden Chat-Mitgliedschaften
        ChatMember.query.filter_by(user_id=user.id).delete()
        
        # Füge neue Chat-Mitgliedschaften hinzu
        chat_ids = request.form.getlist('chat_ids')
        has_chat_access = False
        for chat_id_str in chat_ids:
            try:
                chat_id = int(chat_id_str)
                chat = Chat.query.get(chat_id)
                if chat:
                    member = ChatMember(
                        chat_id=chat_id,
                        user_id=user.id
                    )
                    db.session.add(member)
                    has_chat_access = True
            except (ValueError, TypeError):
                pass
        
        # Aktualisiere Chat-Modul-Zugriff
        if has_chat_access and is_module_enabled('module_chat'):
            # Prüfe ob Chat-Modul-Rolle bereits existiert
            chat_role = UserModuleRole.query.filter_by(
                user_id=user.id,
                module_key='module_chat'
            ).first()
            if not chat_role:
                chat_role = UserModuleRole(
                    user_id=user.id,
                    module_key='module_chat',
                    has_access=True
                )
                db.session.add(chat_role)
        else:
            # Entferne Chat-Modul-Rolle wenn keine Chats mehr zugewiesen
            chat_role = UserModuleRole.query.filter_by(
                user_id=user.id,
                module_key='module_chat'
            ).first()
            if chat_role:
                db.session.delete(chat_role)
        
        # Aktualisiere Freigabelink-Zuweisungen
        from app.models.guest import GuestShareAccess
        from app.models.file import File, Folder
        
        # Entferne alle bestehenden Freigabelink-Zuweisungen
        GuestShareAccess.query.filter_by(user_id=user.id).delete()
        
        # Füge neue Freigabelink-Zuweisungen hinzu
        share_tokens = request.form.getlist('share_tokens')
        has_file_access = False
        for share_token in share_tokens:
            # Prüfe ob es ein File oder Folder ist
            file_item = File.query.filter_by(share_token=share_token, share_enabled=True).first()
            folder_item = Folder.query.filter_by(share_token=share_token, share_enabled=True).first()
            
            if file_item:
                share_access = GuestShareAccess(
                    user_id=user.id,
                    share_token=share_token,
                    share_type='file'
                )
                db.session.add(share_access)
                has_file_access = True
            elif folder_item:
                share_access = GuestShareAccess(
                    user_id=user.id,
                    share_token=share_token,
                    share_type='folder'
                )
                db.session.add(share_access)
                has_file_access = True
        
        # Aktualisiere Dateien-Modul-Zugriff
        if has_file_access and is_module_enabled('module_files'):
            # Prüfe ob Dateien-Modul-Rolle bereits existiert
            file_role = UserModuleRole.query.filter_by(
                user_id=user.id,
                module_key='module_files'
            ).first()
            if not file_role:
                file_role = UserModuleRole(
                    user_id=user.id,
                    module_key='module_files',
                    has_access=True
                )
                db.session.add(file_role)
        else:
            # Entferne Dateien-Modul-Rolle wenn keine Freigabelinks mehr zugewiesen
            file_role = UserModuleRole.query.filter_by(
                user_id=user.id,
                module_key='module_files'
            ).first()
            if file_role:
                db.session.delete(file_role)
        
        db.session.commit()
        
        flash(f'Gast-Account für {user.full_name} wurde erfolgreich aktualisiert.', 'success')
        return redirect(url_for('settings.admin_users'))
    
    # GET: Zeige Bearbeitungsformular
    # Hole aktuelle Module des Gastes
    from app.models.role import UserModuleRole
    current_modules = [role.module_key for role in UserModuleRole.query.filter_by(user_id=user.id).all()]
    
    # Hole aktuelle Chat-Mitgliedschaften
    from app.models.chat import ChatMember
    current_chat_ids = [member.chat_id for member in ChatMember.query.filter_by(user_id=user.id).all()]
    
    # Hole aktuelle Freigabelink-Zuweisungen
    from app.models.guest import GuestShareAccess
    current_share_tokens = [access.share_token for access in GuestShareAccess.query.filter_by(user_id=user.id).all()]
    
    # Hole alle verfügbaren Module
    guest_modules = [
        ('module_calendar', 'Kalender'),
        ('module_manuals', 'Anleitungen'),
        ('module_inventory', 'Lagerverwaltung'),
        ('module_wiki', 'Wiki'),
        ('module_music', 'Musik')
    ]
    
    # Hole alle verfügbaren Freigabelinks
    from app.models.file import File, Folder
    shared_files = File.query.filter_by(share_enabled=True).all()
    shared_folders = Folder.query.filter_by(share_enabled=True).all()
    
    # Hole alle verfügbaren Chats
    from app.models.chat import Chat
    all_chats_list = Chat.query.order_by(Chat.created_at).all()
    
    # Erstelle Liste ohne Duplikate: Haupt-Chat zuerst (nur einer), dann andere
    all_chats = []
    main_chat_added = False
    main_chat_ids = set()
    
    for chat in all_chats_list:
        if chat.is_main_chat and not main_chat_added:
            all_chats.append(chat)
            main_chat_added = True
            main_chat_ids.add(chat.id)
        elif chat.is_main_chat:
            main_chat_ids.add(chat.id)
        elif not chat.is_main_chat:
            all_chats.append(chat)
    
    return render_template('settings/admin_edit_guest.html',
                         user=user,
                         guest_modules=guest_modules,
                         current_modules=current_modules,
                         shared_files=shared_files,
                         shared_folders=shared_folders,
                         current_share_tokens=current_share_tokens,
                         all_chats=all_chats,
                         current_chat_ids=current_chat_ids)


@settings_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    """Delete a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    if user_id == current_user.id:
        flash(translate('settings.admin.users.flash_cannot_delete_self'), 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user = User.query.get_or_404(user_id)
    
    # Super-Admins können nicht gelöscht werden
    if user.is_super_admin:
        flash(translate('settings.admin.users.flash_cannot_delete_super_admin'), 'danger')
        return redirect(url_for('settings.admin_users'))
    
    # Delete profile picture
    if user.profile_picture:
        project_root = os.path.dirname(current_app.root_path)
        upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
        old_path = os.path.join(upload_dir, user.profile_picture)
        if os.path.exists(old_path):
            os.remove(old_path)
    
    # Delete guest share access entries before deleting user
    # This prevents foreign key constraint errors
    from app.models.guest import GuestShareAccess
    GuestShareAccess.query.filter_by(user_id=user_id).delete()
    
    # Delete user module roles before deleting user
    # This prevents foreign key constraint errors
    from app.models.role import UserModuleRole
    UserModuleRole.query.filter_by(user_id=user_id).delete()
    
    # Delete notification-related entries before deleting user
    # This prevents foreign key constraint errors (user_id cannot be null)
    NotificationSettings.query.filter_by(user_id=user_id).delete()
    ChatNotificationSettings.query.filter_by(user_id=user_id).delete()
    PushSubscription.query.filter_by(user_id=user_id).delete()
    NotificationLog.query.filter_by(user_id=user_id).delete()
    
    # Delete API tokens before deleting user
    from app.models.api_token import ApiToken
    ApiToken.query.filter_by(user_id=user_id).delete()
    
    # Delete inventory-related user entries
    from app.models.inventory import ProductFavorite, SavedFilter
    ProductFavorite.query.filter_by(user_id=user_id).delete()
    SavedFilter.query.filter_by(user_id=user_id).delete()
    
    # Delete wiki favorites before deleting user
    from app.models.wiki import WikiFavorite
    WikiFavorite.query.filter_by(user_id=user_id).delete()
    
    # Delete comment mentions before deleting user
    from app.models.comment import CommentMention
    CommentMention.query.filter_by(user_id=user_id).delete()
    
    # Delete music provider tokens before deleting user
    from app.models.music import MusicProviderToken
    MusicProviderToken.query.filter_by(user_id=user_id).delete()
    
    # Delete booking role assignments before deleting user
    from app.models.booking import BookingFormRoleUser
    BookingFormRoleUser.query.filter_by(user_id=user_id).delete()
    
    db.session.delete(user)
    db.session.commit()
    
    flash(translate('settings.admin.users.flash_user_deleted', name=user.full_name), 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/email-footer', methods=['GET', 'POST'])
@login_required
def admin_email_footer():
    """Configure email footer template (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        footer_template = request.form.get('footer_template', '').strip()
        
        # Save or update footer template
        existing = SystemSettings.query.filter_by(key='email_footer_template').first()
        if existing:
            existing.value = footer_template
        else:
            new_setting = SystemSettings(key='email_footer_template', value=footer_template)
            db.session.add(new_setting)
        
        db.session.commit()
        flash(translate('settings.admin.email_footer.flash_saved'), 'success')
        return redirect(url_for('settings.admin_email_footer'))
    
    # Get current footer template
    footer_template = SystemSettings.query.filter_by(key='email_footer_template').first()
    current_template = footer_template.value if footer_template else ''
    
    # Set default template if none exists
    if not current_template:
        current_template = """Mit freundlichen Grüßen
Ihr Team

---
Gesendet von <user> (<email>)
<app_name> - <date> um <time>"""
    
    return render_template('settings/admin_email_footer.html', footer_template=current_template)


@settings_bp.route('/admin/email-permissions')
@login_required
def admin_email_permissions():
    """Umleitung zur Benutzerverwaltung (E-Mail-Berechtigungen wurden in Rollenverwaltung verschoben)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    flash(translate('settings.admin.email_permissions.flash_moved_to_roles'), 'info')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/email-permissions/<int:user_id>/toggle-read', methods=['POST'])
@login_required
def toggle_email_read(user_id):
    """Toggle email read permission for a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    perm = EmailPermission.query.filter_by(user_id=user_id).first()
    if not perm:
        perm = EmailPermission(user_id=user_id, can_read=False, can_send=True)
        db.session.add(perm)
    else:
        perm.can_read = not perm.can_read
    
    db.session.commit()
    
    user = User.query.get(user_id)
    status = translate('common.active') if perm.can_read else translate('common.inactive')
    flash(translate('settings.admin.email_permissions.flash_read_toggled', name=user.full_name, status=status), 'success')
    return redirect(url_for('settings.admin_email_permissions'))


@settings_bp.route('/admin/email-permissions/<int:user_id>/toggle-send', methods=['POST'])
@login_required
def toggle_email_send(user_id):
    """Toggle email send permission for a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    perm = EmailPermission.query.filter_by(user_id=user_id).first()
    if not perm:
        perm = EmailPermission(user_id=user_id, can_read=True, can_send=False)
        db.session.add(perm)
    else:
        perm.can_send = not perm.can_send
    
    db.session.commit()
    
    user = User.query.get(user_id)
    status = translate('common.active') if perm.can_send else translate('common.inactive')
    flash(translate('settings.admin.email_permissions.flash_send_toggled', name=user.full_name, status=status), 'success')
    return redirect(url_for('settings.admin_email_permissions'))


@settings_bp.route('/admin/system', methods=['GET', 'POST'])
@login_required
def admin_system():
    """System settings (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        # Update portal name
        portal_name = request.form.get('portal_name', '').strip()
        
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        if portal_name_setting:
            portal_name_setting.value = portal_name
        else:
            portal_name_setting = SystemSettings(key='portal_name', value=portal_name)
            db.session.add(portal_name_setting)
        
        # Handle portal logo upload
        if 'portal_logo' in request.files:
            file = request.files['portal_logo']
            if file and file.filename:
                # Validate file type
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    # Validate file size (5MB limit)
                    file.seek(0, 2)  # Seek to end
                    file_size = file.tell()
                    file.seek(0)  # Reset to beginning
                    
                    max_size = 5 * 1024 * 1024  # 5MB in bytes
                    if file_size > max_size:
                        flash(translate('settings.admin.system.flash_logo_too_large', size=file_size / (1024*1024)), 'danger')
                        return redirect(url_for('settings.admin_system'))
                    
                    # Create filename with timestamp
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"portal_logo_{timestamp}_{filename}"
                    
                    # Ensure upload directory exists
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    # Save file
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    
                    # Delete old portal logo if it exists
                    old_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
                    if old_logo_setting and old_logo_setting.value:
                        try:
                            old_path = os.path.join(upload_dir, old_logo_setting.value)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except OSError:
                            pass  # Ignore if file doesn't exist
                    
                    # Update portal logo setting
                    if old_logo_setting:
                        old_logo_setting.value = filename
                    else:
                        logo_setting = SystemSettings(key='portal_logo', value=filename)
                        db.session.add(logo_setting)
                    flash(translate('settings.admin.system.flash_logo_uploaded'), 'success')
                else:
                    flash(translate('settings.admin.system.flash_logo_invalid_type'), 'danger')
                    return redirect(url_for('settings.admin_system'))
        
        # Update default accent color
        default_accent_color = request.form.get('default_accent_color', '#0d6efd').strip()
        accent_color_setting = SystemSettings.query.filter_by(key='default_accent_color').first()
        if accent_color_setting:
            accent_color_setting.value = default_accent_color
        else:
            accent_color_setting = SystemSettings(
                key='default_accent_color',
                value=default_accent_color,
                description='Standard-Akzentfarbe für neue Benutzer'
            )
            db.session.add(accent_color_setting)
        
        # Update color gradient
        color_gradient = request.form.get('color_gradient', '').strip()
        gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
        if color_gradient:
            if gradient_setting:
                gradient_setting.value = color_gradient
            else:
                gradient_setting = SystemSettings(
                    key='color_gradient',
                    value=color_gradient,
                    description='Farbverlauf für Login/Register-Seiten'
                )
                db.session.add(gradient_setting)
        else:
            # If empty, remove existing gradient setting (use default)
            if gradient_setting:
                db.session.delete(gradient_setting)
        
        db.session.commit()
        flash(translate('settings.admin.system.flash_updated'), 'success')
        return redirect(url_for('settings.admin_system'))
    
    # Get current settings
    portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
    portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
    accent_color_setting = SystemSettings.query.filter_by(key='default_accent_color').first()
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    
    portal_name = portal_name_setting.value if portal_name_setting else ''
    portal_logo = portal_logo_setting.value if portal_logo_setting else None
    default_accent_color = accent_color_setting.value if accent_color_setting else '#0d6efd'
    color_gradient = gradient_setting.value if gradient_setting else ''
    
    return render_template('settings/admin_system.html', 
                         portal_name=portal_name, 
                         portal_logo=portal_logo,
                         default_accent_color=default_accent_color,
                         color_gradient=color_gradient)


@settings_bp.route('/admin/file-settings', methods=['GET', 'POST'])
@login_required
def admin_file_settings():
    """File settings (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.file_settings.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        # Feature Flags: Dateien
        dropbox_enabled = request.form.get('files_dropbox_enabled') == 'on'
        sharing_enabled = request.form.get('files_sharing_enabled') == 'on'

        dropbox_setting = SystemSettings.query.filter_by(key='files_dropbox_enabled').first()
        if dropbox_setting:
            dropbox_setting.value = str(dropbox_enabled)
        else:
            db.session.add(SystemSettings(key='files_dropbox_enabled', value=str(dropbox_enabled)))

        sharing_setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
        if sharing_setting:
            sharing_setting.value = str(sharing_enabled)
        else:
            db.session.add(SystemSettings(key='files_sharing_enabled', value=str(sharing_enabled)))

        db.session.commit()
        flash(translate('settings.admin.file_settings.flash_updated'), 'success')
        return redirect(url_for('settings.admin_file_settings'))
    
    # Get current settings
    dropbox_setting = SystemSettings.query.filter_by(key='files_dropbox_enabled').first()
    sharing_setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
    
    files_dropbox_enabled = (dropbox_setting and str(dropbox_setting.value).lower() == 'true') or False
    files_sharing_enabled = (sharing_setting and str(sharing_setting.value).lower() == 'true') or False
    
    return render_template('settings/admin_file_settings.html', 
                           files_dropbox_enabled=files_dropbox_enabled, 
                           files_sharing_enabled=files_sharing_enabled)


@settings_bp.route('/admin/modules', methods=['GET', 'POST'])
@login_required
def admin_modules():
    """Module settings (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        # Module-Einstellungen speichern
        modules = {
            'module_chat': request.form.get('module_chat') == 'on',
            'module_files': request.form.get('module_files') == 'on',
            'module_calendar': request.form.get('module_calendar') == 'on',
            'module_email': request.form.get('module_email') == 'on',
            'module_credentials': request.form.get('module_credentials') == 'on',
            'module_manuals': request.form.get('module_manuals') == 'on',
            'module_inventory': request.form.get('module_inventory') == 'on',
            'module_wiki': request.form.get('module_wiki') == 'on',
            'module_booking': request.form.get('module_booking') == 'on',
            'module_music': request.form.get('module_music') == 'on'
        }
        
        for module_key, enabled in modules.items():
            module_setting = SystemSettings.query.filter_by(key=module_key).first()
            if module_setting:
                module_setting.value = str(enabled)
            else:
                db.session.add(SystemSettings(key=module_key, value=str(enabled), description=f'Modul {module_key} aktiviert'))
        
        db.session.commit()
        flash(translate('settings.admin_modules.flash_updated'), 'success')
        return redirect(url_for('settings.admin_modules'))
    
    # Get module settings
    from app.utils.common import is_module_enabled
    module_chat_enabled = is_module_enabled('module_chat')
    module_files_enabled = is_module_enabled('module_files')
    module_calendar_enabled = is_module_enabled('module_calendar')
    module_email_enabled = is_module_enabled('module_email')
    module_credentials_enabled = is_module_enabled('module_credentials')
    module_manuals_enabled = is_module_enabled('module_manuals')
    module_inventory_enabled = is_module_enabled('module_inventory')
    module_wiki_enabled = is_module_enabled('module_wiki')
    module_booking_enabled = is_module_enabled('module_booking')
    module_music_enabled = is_module_enabled('module_music')
    
    return render_template('settings/admin_modules.html',
                           module_chat_enabled=module_chat_enabled,
                           module_files_enabled=module_files_enabled,
                           module_calendar_enabled=module_calendar_enabled,
                           module_email_enabled=module_email_enabled,
                           module_credentials_enabled=module_credentials_enabled,
                           module_manuals_enabled=module_manuals_enabled,
                           module_inventory_enabled=module_inventory_enabled,
                           module_wiki_enabled=module_wiki_enabled,
                           module_booking_enabled=module_booking_enabled,
                           module_music_enabled=module_music_enabled)


@settings_bp.route('/admin/backup', methods=['GET', 'POST'])
@login_required
def admin_backup():
    """Backup Import/Export (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'export':
            # Export-Backup erstellen
            categories = request.form.getlist('export_categories')
            if not categories:
                flash(translate('settings.admin.backup.flash_no_export_categories'), 'danger')
                return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)
            
            try:
                # Temporäre Datei erstellen
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.prismateams', mode='w', encoding='utf-8')
                temp_path = temp_file.name
                temp_file.close()
                
                # Backup erstellen
                result = export_backup(categories, temp_path)
                
                if result['success']:
                    @after_this_request
                    def _cleanup_temp_file(response):
                        try:
                            os.unlink(temp_path)
                        except OSError as cleanup_error:
                            current_app.logger.warning(f'Temporäre Backup-Datei konnte nicht gelöscht werden: {cleanup_error}')
                        return response
                    
                    return send_file(
                        temp_path,
                        as_attachment=True,
                        download_name=f'backup_{timestamp}.prismateams',
                        mimetype='application/json'
                    )
                else:
                    os.unlink(temp_path)
                    flash(translate('settings.admin.backup.flash_export_error'), 'danger')
            except Exception as e:
                current_app.logger.error(f"Fehler beim Export: {str(e)}")
                try:
                    if 'temp_path' in locals() and os.path.exists(temp_path):
                        os.unlink(temp_path)
                except OSError as cleanup_error:
                    current_app.logger.warning(f'Temporäre Backup-Datei konnte nach Fehler nicht gelöscht werden: {cleanup_error}')
                flash(translate('settings.admin.backup.flash_export_error_detail', error=str(e)), 'danger')
        
        elif action == 'import':
            # Import-Backup hochladen
            if 'backup_file' not in request.files:
                flash(translate('settings.admin.backup.flash_no_file'), 'danger')
                return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)
            
            file = request.files['backup_file']
            if file.filename == '':
                flash(translate('settings.admin.backup.flash_no_file'), 'danger')
                return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)
            
            if not file.filename.endswith('.prismateams'):
                flash(translate('settings.admin.backup.flash_invalid_extension'), 'danger')
                return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)
            
            try:
                # Temporäre Datei speichern
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.prismateams', mode='wb')
                file.save(temp_file.name)
                temp_path = temp_file.name
                temp_file.close()
                
                # Kategorien auswählen
                import_categories = request.form.getlist('import_categories')
                if not import_categories:
                    flash(translate('settings.admin.backup.flash_no_import_categories'), 'danger')
                    os.unlink(temp_path)
                    return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)
                
                # Backup importieren
                result = import_backup(temp_path, import_categories, current_user.id)
                
                # Temporäre Datei löschen
                os.unlink(temp_path)
                
                if result['success']:
                    imported = ', '.join(result.get('imported', []))
                    flash(translate('settings.admin.backup.flash_import_success', categories=imported), 'success')
                else:
                    flash(translate('settings.admin.backup.flash_import_error', error=result.get("error", translate('common.unknown_error'))), 'danger')
            except Exception as e:
                current_app.logger.error(f"Fehler beim Import: {str(e)}")
                flash(translate('settings.admin.backup.flash_import_error', error=str(e)), 'danger')
                if 'temp_path' in locals():
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
    
    return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)


@settings_bp.route('/admin/whitelist')
@login_required
def admin_whitelist():
    """Manage whitelist entries (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    # Get all whitelist entries
    whitelist_entries = WhitelistEntry.query.order_by(WhitelistEntry.entry_type, WhitelistEntry.entry).all()
    
    return render_template('settings/admin_whitelist.html', whitelist_entries=whitelist_entries)


@settings_bp.route('/admin/whitelist/add', methods=['POST'])
@login_required
def add_whitelist_entry():
    """Add a new whitelist entry (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    entry = request.form.get('entry', '').strip()
    entry_type = request.form.get('entry_type', '')
    description = request.form.get('description', '').strip()
    
    if not entry or entry_type not in ['email', 'domain']:
        flash(translate('settings.admin.whitelist.flash_invalid_entry'), 'danger')
        return redirect(url_for('settings.admin_whitelist'))
    
    # Validate entry format
    if entry_type == 'email':
        if '@' not in entry:
            flash(translate('settings.admin.whitelist.flash_invalid_email'), 'danger')
            return redirect(url_for('settings.admin_whitelist'))
    elif entry_type == 'domain':
        if not entry.startswith('@'):
            entry = '@' + entry
    
    # Add entry
    result = WhitelistEntry.add_entry(entry, entry_type, description, current_user.id)
    
    if result:
        flash(translate('settings.admin.whitelist.flash_entry_added', entry=entry), 'success')
    else:
        flash(translate('settings.admin.whitelist.flash_entry_add_error'), 'danger')
    
    return redirect(url_for('settings.admin_whitelist'))


@settings_bp.route('/admin/whitelist/<int:entry_id>/toggle', methods=['POST'])
@login_required
def toggle_whitelist_entry(entry_id):
    """Toggle whitelist entry active status (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    result = WhitelistEntry.toggle_active(entry_id)
    
    if result:
        entry = WhitelistEntry.query.get(entry_id)
        status = translate('common.active') if entry.is_active else translate('common.inactive')
        flash(translate('settings.admin.whitelist.flash_entry_toggled', entry=entry.entry, status=status), 'success')
    else:
        flash(translate('settings.admin.whitelist.flash_entry_toggle_error'), 'danger')
    
    return redirect(url_for('settings.admin_whitelist'))


@settings_bp.route('/admin/whitelist/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_whitelist_entry(entry_id):
    """Delete a whitelist entry (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    entry = WhitelistEntry.query.get(entry_id)
    if not entry:
        flash(translate('settings.admin.whitelist.flash_entry_not_found'), 'danger')
        return redirect(url_for('settings.admin_whitelist'))
    
    result = WhitelistEntry.remove_entry(entry_id)
    
    if result:
        flash(translate('settings.admin.whitelist.flash_entry_deleted', entry=entry.entry), 'success')
    else:
        flash(translate('settings.admin.whitelist.flash_entry_delete_error'), 'danger')
    
    return redirect(url_for('settings.admin_whitelist'))


@settings_bp.route('/admin/inventory-settings', methods=['GET', 'POST'])
@login_required
def admin_inventory_settings():
    """Lagerverwaltung-Einstellungen (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        ownership_text = request.form.get('ownership_text', '').strip()
        
        # Speichere Eigentumstext in SystemSettings
        ownership_setting = SystemSettings.query.filter_by(key='inventory_ownership_text').first()
        if ownership_setting:
            ownership_setting.value = ownership_text if ownership_text else 'Eigentum der Technik'
        else:
            ownership_setting = SystemSettings(
                key='inventory_ownership_text',
                value=ownership_text if ownership_text else 'Eigentum der Technik',
                description='Text der auf öffentlichen Produktseiten angezeigt wird'
            )
            db.session.add(ownership_setting)
        
        db.session.commit()
        flash(translate('settings.admin.inventory.flash_saved'), 'success')
        return redirect(url_for('settings.admin_inventory_settings'))
    
    # Lade aktuelle Einstellungen
    ownership_setting = SystemSettings.query.filter_by(key='inventory_ownership_text').first()
    ownership_text = ownership_setting.value if ownership_setting and ownership_setting.value else 'Eigentum der Technik'
    
    return render_template('settings/admin_inventory_settings.html', ownership_text=ownership_text)


@settings_bp.route('/admin/email-module')
@login_required
def admin_email_module():
    """E-Mail-Moduleinstellungen Übersicht mit Tabs (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    # Lade Footer-Template
    footer_template = SystemSettings.query.filter_by(key='email_footer_template').first()
    current_footer = footer_template.value if footer_template else ''
    if not current_footer:
        current_footer = """Mit freundlichen Grüßen
Ihr Team

---
Gesendet von <user> (<email>)
<app_name> - <date> um <time>"""
    
    # Lade E-Mail-System-Einstellungen
    storage_setting = SystemSettings.query.filter_by(key='email_storage_days').first()
    storage_days = int(storage_setting.value) if storage_setting and storage_setting.value else 0
    
    sync_setting = SystemSettings.query.filter_by(key='email_sync_interval_minutes').first()
    sync_interval = int(sync_setting.value) if sync_setting and sync_setting.value else 30
    
    return render_template('settings/admin_email_module.html', 
                         footer_template=current_footer,
                         storage_days=storage_days,
                         sync_interval=sync_interval)


@settings_bp.route('/admin/email-settings', methods=['GET', 'POST'])
@login_required
def admin_email_settings():
    """E-Mail-System-Einstellungen (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        # Speicherdauer in Tagen (0 = unbegrenzt)
        storage_days = request.form.get('storage_days', '').strip()
        try:
            storage_days = int(storage_days) if storage_days else 0
            if storage_days < 0:
                storage_days = 0
        except ValueError:
            storage_days = 0
        
        # Synchronisationsintervall in Minuten
        sync_interval = request.form.get('sync_interval', '').strip()
        try:
            sync_interval = int(sync_interval) if sync_interval else 30
            if sync_interval < 15:
                sync_interval = 15
        except ValueError:
            sync_interval = 30
        
        # Speichere Einstellungen in SystemSettings
        storage_setting = SystemSettings.query.filter_by(key='email_storage_days').first()
        if storage_setting:
            storage_setting.value = str(storage_days)
        else:
            storage_setting = SystemSettings(
                key='email_storage_days',
                value=str(storage_days),
                description='Speicherdauer für E-Mails in Tagen (0 = unbegrenzt)'
            )
            db.session.add(storage_setting)
        
        sync_setting = SystemSettings.query.filter_by(key='email_sync_interval_minutes').first()
        if sync_setting:
            sync_setting.value = str(sync_interval)
        else:
            sync_setting = SystemSettings(
                key='email_sync_interval_minutes',
                value=str(sync_interval),
                description='Automatisches Synchronisationsintervall in Minuten'
            )
            db.session.add(sync_setting)
        
        db.session.commit()
        flash(translate('settings.admin.email_settings.flash_saved'), 'success')
        return redirect(url_for('settings.admin_email_settings'))
    
    # Lade aktuelle Einstellungen
    storage_setting = SystemSettings.query.filter_by(key='email_storage_days').first()
    storage_days = int(storage_setting.value) if storage_setting and storage_setting.value else 0
    
    sync_setting = SystemSettings.query.filter_by(key='email_sync_interval_minutes').first()
    sync_interval = int(sync_setting.value) if sync_setting and sync_setting.value else 30
    
    return render_template('settings/admin_email_settings.html', 
                         storage_days=storage_days, 
                         sync_interval=sync_interval)


@settings_bp.route('/admin/music', methods=['GET', 'POST'])
@login_required
def admin_music():
    """Musikmodul-Einstellungen (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.music import MusicSettings, MusicProviderToken
    from app.utils.music_oauth import is_provider_connected
    
    if request.method == 'POST':
        # Speichere Provider-Aktivierung
        enabled_providers = []
        available_providers = ['spotify', 'youtube', 'deezer', 'musicbrainz']
        for provider in available_providers:
            if request.form.get(f'provider_enabled_{provider}') == 'on':
                enabled_providers.append(provider)
        MusicSettings.set_enabled_providers(enabled_providers)
        
        # Speichere Provider-Reihenfolge
        provider_order_json = request.form.get('provider_order', '')
        if provider_order_json:
            import json
            try:
                provider_order = json.loads(provider_order_json)
                # Filtere nur aktivierte Provider
                provider_order = [p for p in provider_order if p in enabled_providers]
                MusicSettings.set_provider_order(provider_order)
            except:
                pass
        
        # Spotify Settings (OAuth Client ID/Secret für Benutzer-Login)
        spotify_client_id = request.form.get('spotify_client_id', '').strip()
        spotify_client_secret = request.form.get('spotify_client_secret', '').strip()
        
        spotify_id_setting = MusicSettings.query.filter_by(key='spotify_client_id').first()
        if spotify_id_setting:
            spotify_id_setting.value = spotify_client_id
        else:
            spotify_id_setting = MusicSettings(key='spotify_client_id', value=spotify_client_id, description='Spotify OAuth Client ID')
            db.session.add(spotify_id_setting)
        
        spotify_secret_setting = MusicSettings.query.filter_by(key='spotify_client_secret').first()
        if spotify_secret_setting:
            spotify_secret_setting.value = spotify_client_secret
        else:
            spotify_secret_setting = MusicSettings(key='spotify_client_secret', value=spotify_client_secret, description='Spotify Client Secret')
            db.session.add(spotify_secret_setting)
        
        # YouTube Settings (API-Key oder OAuth)
        youtube_api_key = request.form.get('youtube_api_key', '').strip()
        youtube_client_id = request.form.get('youtube_client_id', '').strip()
        youtube_client_secret = request.form.get('youtube_client_secret', '').strip()
        
        youtube_api_key_setting = MusicSettings.query.filter_by(key='youtube_api_key').first()
        if youtube_api_key_setting:
            youtube_api_key_setting.value = youtube_api_key
        else:
            youtube_api_key_setting = MusicSettings(key='youtube_api_key', value=youtube_api_key, description='YouTube API-Key (vereinfacht, kein OAuth)')
            db.session.add(youtube_api_key_setting)
        
        youtube_id_setting = MusicSettings.query.filter_by(key='youtube_client_id').first()
        if youtube_id_setting:
            youtube_id_setting.value = youtube_client_id
        else:
            youtube_id_setting = MusicSettings(key='youtube_client_id', value=youtube_client_id, description='YouTube OAuth Client ID (optional)')
            db.session.add(youtube_id_setting)
        
        youtube_secret_setting = MusicSettings.query.filter_by(key='youtube_client_secret').first()
        if youtube_secret_setting:
            youtube_secret_setting.value = youtube_client_secret
        else:
            youtube_secret_setting = MusicSettings(key='youtube_client_secret', value=youtube_client_secret, description='YouTube OAuth Client Secret (optional)')
            db.session.add(youtube_secret_setting)
        
        # Deezer Settings (App-ID optional, aber empfohlen für Rate Limits)
        deezer_app_id = request.form.get('deezer_app_id', '').strip()
        
        deezer_app_id_setting = MusicSettings.query.filter_by(key='deezer_app_id').first()
        if deezer_app_id_setting:
            deezer_app_id_setting.value = deezer_app_id
        else:
            deezer_app_id_setting = MusicSettings(key='deezer_app_id', value=deezer_app_id, description='Deezer App-ID (optional, aber empfohlen für höhere Rate Limits)')
            db.session.add(deezer_app_id_setting)
        
        # Provider-Badge-Anzeige Einstellung
        show_provider_badges = request.form.get('show_provider_badges') == 'on'
        MusicSettings.set_show_provider_badges(show_provider_badges)
        
        db.session.commit()
        flash(translate('settings.admin.music.flash_saved'), 'success')
        return redirect(url_for('settings.admin_music'))
    
    # GET: Zeige Einstellungsseite
    enabled_providers = MusicSettings.get_enabled_providers()
    provider_order = MusicSettings.get_provider_order()
    
    spotify_client_id = MusicSettings.query.filter_by(key='spotify_client_id').first()
    spotify_client_secret = MusicSettings.query.filter_by(key='spotify_client_secret').first()
    youtube_api_key = MusicSettings.query.filter_by(key='youtube_api_key').first()
    youtube_client_id = MusicSettings.query.filter_by(key='youtube_client_id').first()
    youtube_client_secret = MusicSettings.query.filter_by(key='youtube_client_secret').first()
    deezer_app_id = MusicSettings.query.filter_by(key='deezer_app_id').first()
    # Prüfe Verbindungsstatus (nur für OAuth-basierte Provider)
    spotify_connected = is_provider_connected(current_user.id, 'spotify') if current_user.is_authenticated else False
    youtube_connected = is_provider_connected(current_user.id, 'youtube') if current_user.is_authenticated else False
    
    # Redirect URIs
    spotify_redirect_uri = url_for('music.spotify_callback', _external=True)
    youtube_redirect_uri = url_for('music.youtube_callback', _external=True)
    
    # Hole Einstellung für Provider-Badge-Anzeige (auch im GET-Fall)
    show_provider_badges = MusicSettings.get_show_provider_badges()
    
    return render_template('settings/admin_music.html',
                         enabled_providers=enabled_providers,
                         provider_order=provider_order,
                         spotify_client_id=spotify_client_id.value if spotify_client_id else '',
                         spotify_client_secret=spotify_client_secret.value if spotify_client_secret else '',
                         youtube_api_key=youtube_api_key.value if youtube_api_key else '',
                         youtube_client_id=youtube_client_id.value if youtube_client_id else '',
                         youtube_client_secret=youtube_client_secret.value if youtube_client_secret else '',
                         deezer_app_id=deezer_app_id.value if deezer_app_id else '',
                         spotify_connected=spotify_connected,
                         youtube_connected=youtube_connected,
                         spotify_redirect_uri=spotify_redirect_uri,
                         youtube_redirect_uri=youtube_redirect_uri,
                         show_provider_badges=show_provider_badges)


@settings_bp.route('/admin/roles')
@login_required
def admin_roles():
    """Rollenverwaltung - Umleitung zur Benutzerverwaltung (admin only)."""
    # Leite zur kombinierten Benutzerverwaltung um
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/roles/user/<int:user_id>')
@login_required
def admin_roles_user(user_id):
    """Zeige Rollen für einen bestimmten Benutzer (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.role import UserModuleRole
    from app.models.booking import BookingFormRole, BookingFormRoleUser, BookingForm
    from flask import jsonify
    
    user = User.query.get_or_404(user_id)
    
    # Prüfe ob JSON-Format angefordert wird
    if request.args.get('format') == 'json':
        # Lade Modul-Rollen
        module_roles = {}
        user_module_roles = UserModuleRole.query.filter_by(user_id=user.id).all()
        for role in user_module_roles:
            module_roles[role.module_key] = role.has_access
        
        # Lade Buchungsrollen
        booking_roles = []
        all_booking_roles = BookingFormRole.query.join(BookingForm).all()
        for role in all_booking_roles:
            # Prüfe ob Benutzer dieser Rolle zugeordnet ist
            assignment = BookingFormRoleUser.query.filter_by(
                role_id=role.id,
                user_id=user.id
            ).first()
            
            booking_roles.append({
                'role_id': role.id,
                'role_name': role.role_name,
                'form_id': role.form_id,
                'form_title': role.form.title,
                'form_is_active': role.form.is_active,
                'is_required': role.is_required,
                'is_assigned': assignment is not None
            })
        
        # Lade E-Mail-Berechtigungen
        email_permissions = None
        email_perm = EmailPermission.query.filter_by(user_id=user.id).first()
        if email_perm:
            email_permissions = {
                'can_read': email_perm.can_read,
                'can_send': email_perm.can_send
            }
        
        return jsonify({
            'has_full_access': user.has_full_access,
            'module_roles': module_roles,
            'booking_roles': booking_roles,
            'email_permissions': email_permissions,
            'can_borrow': user.can_borrow
        })
    
    # HTML-Ansicht (falls benötigt)
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/roles/user/<int:user_id>/update', methods=['POST'])
@login_required
def admin_roles_user_update(user_id):
    """Aktualisiere Rollen für einen bestimmten Benutzer (admin only)."""
    if not current_user.is_admin:
        from flask import jsonify
        return jsonify({'success': False, 'error': 'Nicht autorisiert'}), 403
    
    from app.models.role import UserModuleRole
    from app.models.booking import BookingFormRoleUser
    from flask import jsonify
    
    user = User.query.get_or_404(user_id)
    
    # Super-Admins können nicht geändert werden
    if user.is_super_admin:
        return jsonify({'success': False, 'error': 'Hauptadministrator-Rollen können nicht geändert werden'}), 400
    
    try:
        # Aktualisiere Vollzugriff
        user.has_full_access = request.form.get('has_full_access') == 'on'
        
        # Liste aller Module
        all_modules = [
            'module_chat', 'module_files', 'module_calendar', 'module_email',
            'module_credentials', 'module_manuals',
            'module_inventory', 'module_wiki', 'module_booking', 'module_music'
        ]
        
        # Aktualisiere Modul-Rollen
        if not user.has_full_access:
            # Lösche alle bestehenden Modul-Rollen
            UserModuleRole.query.filter_by(user_id=user.id).delete()
            
            # Erstelle neue Modul-Rollen
            for module_key in all_modules:
                if request.form.get(module_key) == 'on':
                    role = UserModuleRole(
                        user_id=user.id,
                        module_key=module_key,
                        has_access=True
                    )
                    db.session.add(role)
        else:
            # Bei Vollzugriff: Lösche alle Modul-Rollen
            UserModuleRole.query.filter_by(user_id=user.id).delete()
        
        # Aktualisiere E-Mail-Berechtigungen
        email_can_read = request.form.get('email_can_read') == 'on'
        email_can_send = request.form.get('email_can_send') == 'on'
        
        email_perm = EmailPermission.query.filter_by(user_id=user.id).first()
        if email_can_read or email_can_send:
            if not email_perm:
                email_perm = EmailPermission(user_id=user.id, can_read=email_can_read, can_send=email_can_send)
                db.session.add(email_perm)
            else:
                email_perm.can_read = email_can_read
                email_perm.can_send = email_can_send
        else:
            # Wenn beide deaktiviert sind, lösche die Berechtigung
            if email_perm:
                db.session.delete(email_perm)
        
        # Aktualisiere Leihrechte
        user.can_borrow = request.form.get('can_borrow') == 'on'
        
        # Aktualisiere Buchungsrollen
        # Lösche alle bestehenden Buchungsrollen-Zuordnungen
        BookingFormRoleUser.query.filter_by(user_id=user.id).delete()
        
        # Füge neue Buchungsrollen-Zuordnungen hinzu
        booking_role_ids = request.form.getlist('booking_role')
        for role_id in booking_role_ids:
            try:
                role_id_int = int(role_id)
                assignment = BookingFormRoleUser(
                    role_id=role_id_int,
                    user_id=user.id
                )
                db.session.add(assignment)
            except ValueError:
                continue  # Ignoriere ungültige IDs
        
        db.session.commit()
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Aktualisieren der Rollen: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/admin/roles/default', methods=['GET', 'POST'])
@login_required
def admin_roles_default():
    """Konfiguriere Standardrollen für neue Benutzer (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    import json
    from app.utils.common import is_module_enabled
    
    # Liste aller Module
    all_modules = [
        ('module_chat', 'Chat'),
        ('module_files', 'Dateien'),
        ('module_calendar', 'Kalender'),
        ('module_email', 'E-Mail'),
        ('module_credentials', 'Zugangsdaten'),
        ('module_manuals', 'Anleitungen'),
        ('module_inventory', 'Lagerverwaltung'),
        ('module_wiki', 'Wiki'),
        ('module_booking', 'Buchungen'),
        ('module_music', 'Musik')
    ]
    
    if request.method == 'POST':
        # Sammle Standardrollen-Einstellungen
        default_roles = {
            'full_access': request.form.get('default_full_access') == 'on'
        }
        
        # Modulspezifische Rollen
        for module_key, _ in all_modules:
            default_roles[module_key] = request.form.get(f'default_{module_key}') == 'on'
        
        # Speichere in SystemSettings
        default_roles_setting = SystemSettings.query.filter_by(key='default_module_roles').first()
        if default_roles_setting:
            default_roles_setting.value = json.dumps(default_roles)
        else:
            default_roles_setting = SystemSettings(
                key='default_module_roles',
                value=json.dumps(default_roles),
                description='Standardrollen für neue Benutzer'
            )
            db.session.add(default_roles_setting)
        
        db.session.commit()
        flash(translate('settings.admin.roles.flash_default_saved'), 'success')
        return redirect(url_for('settings.admin_roles_default'))
    
    # GET: Lade aktuelle Standardrollen
    default_roles_setting = SystemSettings.query.filter_by(key='default_module_roles').first()
    if default_roles_setting and default_roles_setting.value:
        try:
            default_roles = json.loads(default_roles_setting.value)
        except:
            default_roles = {}
    else:
        default_roles = {}
    
    return render_template('settings/admin_roles_default.html', 
                         default_roles=default_roles,
                         all_modules=all_modules)


@settings_bp.route('/admin/booking-forms')
@login_required
def booking_forms():
    """Booking forms management (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm
    forms = BookingForm.query.order_by(BookingForm.created_at.desc()).all()
    
    return render_template('booking/admin/forms.html', forms=forms)


@settings_bp.route('/admin/booking-forms/create', methods=['GET', 'POST'])
@login_required
def booking_form_create():
    """Create a new booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        archive_days = int(request.form.get('archive_days', 30))
        enable_mailbox = request.form.get('enable_mailbox') == 'on'
        enable_shared_folder = request.form.get('enable_shared_folder') == 'on'
        
        if not title:
            flash(translate('settings.admin.booking_forms.flash_title_required'), 'danger')
            return render_template('booking/admin/form_edit.html', form=None, fields=[], all_users=User.query.filter_by(is_active=True).all())
        
        form = BookingForm(
            title=title,
            description=description or None,
            archive_days=archive_days,
            enable_mailbox=enable_mailbox,
            enable_shared_folder=enable_shared_folder,
            created_by=current_user.id,
            is_active=True
        )
        
        db.session.add(form)
        db.session.commit()
        
        flash(translate('settings.admin.booking_forms.flash_form_created', title=title), 'success')
        return redirect(url_for('settings.booking_form_edit', form_id=form.id))
    
    return render_template('booking/admin/form_edit.html', form=None, fields=[], all_users=User.query.filter_by(is_active=True).all())


@settings_bp.route('/admin/booking-forms/<int:form_id>/edit', methods=['GET', 'POST'])
@login_required
def booking_form_edit(form_id):
    """Edit a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm, BookingFormField
    
    form = BookingForm.query.get_or_404(form_id)
    
    if request.method == 'POST':
        # Prüfe ob Status-Update oder Formular-Update
        if 'is_active' in request.form:
            # Status-Update
            form.is_active = request.form.get('is_active') == 'on'
            db.session.commit()
            flash(translate('settings.admin.booking_forms.flash_status_updated'), 'success')
            return redirect(url_for('settings.booking_form_edit', form_id=form_id))
        
        # Formular-Update
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        pdf_application_text = request.form.get('pdf_application_text', '').strip()
        archive_days = int(request.form.get('archive_days', 30))
        enable_mailbox = request.form.get('enable_mailbox') == 'on'
        enable_shared_folder = request.form.get('enable_shared_folder') == 'on'
        
        if not title:
            flash(translate('settings.admin.booking_forms.flash_title_required'), 'danger')
            fields = BookingFormField.query.filter_by(form_id=form_id).order_by(BookingFormField.field_order).all()
            return render_template('booking/admin/form_edit.html', form=form, fields=fields, all_users=User.query.filter_by(is_active=True).all())
        
        form.title = title
        form.description = description or None
        form.pdf_application_text = pdf_application_text or None
        form.archive_days = archive_days
        form.enable_mailbox = enable_mailbox
        form.enable_shared_folder = enable_shared_folder
        
        db.session.commit()
        flash(translate('settings.admin.booking_forms.flash_form_updated', title=title), 'success')
        return redirect(url_for('settings.booking_form_edit', form_id=form_id))
    
    fields = BookingFormField.query.filter_by(form_id=form_id).order_by(BookingFormField.field_order).all()
    return render_template('booking/admin/form_edit.html', form=form, fields=fields, all_users=User.query.filter_by(is_active=True).all())


@settings_bp.route('/admin/booking-forms/<int:form_id>/delete', methods=['POST'])
@login_required
def booking_form_delete(form_id):
    """Delete a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm
    
    form = BookingForm.query.get_or_404(form_id)
    title = form.title
    
    db.session.delete(form)
    db.session.commit()
    
    flash(translate('settings.admin.booking_forms.flash_form_deleted', title=title), 'success')
    return redirect(url_for('settings.booking_forms'))


@settings_bp.route('/admin/booking-forms/<int:form_id>/secondary-logo/upload', methods=['POST'])
@login_required
def booking_secondary_logo_upload(form_id):
    """Upload secondary logo for booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm
    
    form = BookingForm.query.get_or_404(form_id)
    
    if 'logo' not in request.files:
        flash('Keine Datei ausgewählt.', 'danger')
        return redirect(url_for('settings.booking_form_edit', form_id=form_id))
    
    file = request.files['logo']
    if file.filename == '':
        flash('Keine Datei ausgewählt.', 'danger')
        return redirect(url_for('settings.booking_form_edit', form_id=form_id))
    
    # Validate file type
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
        # Validate file size (5MB limit)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        
        max_size = 5 * 1024 * 1024  # 5MB in bytes
        if file_size > max_size:
            flash(f'Logo ist zu groß. Maximale Größe: 5MB. Ihre Datei: {file_size / (1024*1024):.1f}MB', 'danger')
            return redirect(url_for('settings.booking_form_edit', form_id=form_id))
        
        # Create filename with timestamp
        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"secondary_logo_{form_id}_{timestamp}_{filename}"
        
        # Ensure upload directory exists
        project_root = os.path.dirname(current_app.root_path)
        upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'booking_forms', str(form_id))
        os.makedirs(upload_dir, exist_ok=True)
        
        # Delete old logo if exists
        if form.secondary_logo_path:
            old_path = os.path.join(project_root, form.secondary_logo_path)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except:
                    pass
        
        # Save file
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        # Update form with relative path
        relative_path = os.path.join('booking_forms', str(form_id), filename).replace('\\', '/')
        form.secondary_logo_path = relative_path
        db.session.commit()
        
        flash('Optionales 2. Logo wurde erfolgreich hochgeladen.', 'success')
    else:
        flash('Ungültiger Dateityp. Erlaubt: PNG, JPG, JPEG, GIF, SVG', 'danger')
    
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/secondary-logo/delete', methods=['POST'])
@login_required
def booking_secondary_logo_delete(form_id):
    """Delete secondary logo for booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm
    
    form = BookingForm.query.get_or_404(form_id)
    
    if form.secondary_logo_path:
        project_root = os.path.dirname(current_app.root_path)
        filepath = os.path.join(project_root, form.secondary_logo_path)
        
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass
        
        form.secondary_logo_path = None
        db.session.commit()
        flash('Optionales 2. Logo wurde gelöscht.', 'success')
    else:
        flash('Kein Logo vorhanden.', 'warning')
    
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/secondary-logo/<path:filename>')
@login_required
def booking_secondary_logo(form_id, filename):
    """Serve secondary logo for booking form."""
    if not current_user.is_admin:
        abort(403)
    
    try:
        from urllib.parse import unquote
        filename = unquote(filename)
        
        project_root = os.path.dirname(current_app.root_path)
        directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'booking_forms', str(form_id))
        full_path = os.path.join(directory, filename)
        
        if not os.path.isfile(full_path):
            abort(404)
        
        return send_from_directory(directory, filename)
    except FileNotFoundError:
        abort(404)


@settings_bp.route('/admin/booking-forms/<int:form_id>/fields/add', methods=['POST'])
@login_required
def booking_field_add(form_id):
    """Add a field to a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm, BookingFormField
    
    form = BookingForm.query.get_or_404(form_id)
    
    field_type = request.form.get('field_type', '').strip()
    field_label = request.form.get('field_label', '').strip()
    field_name = request.form.get('field_name', '').strip()
    placeholder = request.form.get('placeholder', '').strip()
    is_required = request.form.get('is_required') == 'on'
    field_options = request.form.get('field_options', '').strip()
    
    if not field_label:
        flash('Bezeichnung ist erforderlich.', 'danger')
        return redirect(url_for('settings.booking_form_edit', form_id=form_id))
    
    # Generate field_name if not provided
    if not field_name:
        import re
        field_name = re.sub(r'[^a-zA-Z0-9_]', '_', field_label.lower())
        field_name = re.sub(r'_+', '_', field_name)
    
    # Get max field_order
    max_order = db.session.query(db.func.max(BookingFormField.field_order)).filter_by(form_id=form_id).scalar() or 0
    
    # Parse options for select/checkbox fields
    options_json = None
    if field_type in ['select', 'checkbox'] and field_options:
        options = [opt.strip() for opt in field_options.split('\n') if opt.strip()]
        if options:
            import json
            options_json = json.dumps(options)
    
    field = BookingFormField(
        form_id=form_id,
        field_type=field_type,
        field_name=field_name,
        field_label=field_label,
        placeholder=placeholder or None,
        is_required=is_required,
        field_order=max_order + 1,
        field_options=options_json
    )
    
    db.session.add(field)
    db.session.commit()
    
    flash(f'Feld "{field_label}" wurde hinzugefügt.', 'success')
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/fields/<int:field_id>/delete', methods=['POST'])
@login_required
def booking_field_delete(form_id, field_id):
    """Delete a field from a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm, BookingFormField
    
    form = BookingForm.query.get_or_404(form_id)
    field = BookingFormField.query.filter_by(id=field_id, form_id=form_id).first_or_404()
    
    field_label = field.field_label
    db.session.delete(field)
    db.session.commit()
    
    flash(f'Feld "{field_label}" wurde gelöscht.', 'success')
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/roles/create', methods=['POST'])
@login_required
def booking_role_create(form_id):
    """Create a role for a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm, BookingFormRole
    
    form = BookingForm.query.get_or_404(form_id)
    
    role_name = request.form.get('role_name', '').strip()
    is_required = request.form.get('is_required') == 'on'
    
    if not role_name:
        flash('Rollenname ist erforderlich.', 'danger')
        return redirect(url_for('settings.booking_form_edit', form_id=form_id))
    
    # Get max role_order
    max_order = db.session.query(db.func.max(BookingFormRole.role_order)).filter_by(form_id=form_id).scalar() or 0
    
    role = BookingFormRole(
        form_id=form_id,
        role_name=role_name,
        is_required=is_required,
        role_order=max_order + 1
    )
    
    db.session.add(role)
    db.session.commit()
    
    flash(f'Rolle "{role_name}" wurde erstellt.', 'success')
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/roles/<int:role_id>/edit', methods=['POST'])
@login_required
def booking_role_edit(form_id, role_id):
    """Edit a role for a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm, BookingFormRole
    
    form = BookingForm.query.get_or_404(form_id)
    role = BookingFormRole.query.filter_by(id=role_id, form_id=form_id).first_or_404()
    
    role_name = request.form.get('role_name', '').strip()
    is_required = request.form.get('is_required') == 'on'
    
    if not role_name:
        flash('Rollenname ist erforderlich.', 'danger')
        return redirect(url_for('settings.booking_form_edit', form_id=form_id))
    
    role.role_name = role_name
    role.is_required = is_required
    
    db.session.commit()
    
    flash(f'Rolle "{role_name}" wurde aktualisiert.', 'success')
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/roles/<int:role_id>/delete', methods=['POST'])
@login_required
def booking_role_delete(form_id, role_id):
    """Delete a role from a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm, BookingFormRole
    
    form = BookingForm.query.get_or_404(form_id)
    role = BookingFormRole.query.filter_by(id=role_id, form_id=form_id).first_or_404()
    
    role_name = role.role_name
    db.session.delete(role)
    db.session.commit()
    
    flash(f'Rolle "{role_name}" wurde gelöscht.', 'success')
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/roles/<int:role_id>/users/add', methods=['POST'])
@login_required
def booking_role_user_add(form_id, role_id):
    """Add users to a role for a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.booking import BookingForm, BookingFormRole, BookingFormRoleUser
    
    form = BookingForm.query.get_or_404(form_id)
    role = BookingFormRole.query.filter_by(id=role_id, form_id=form_id).first_or_404()
    
    # Get selected user IDs
    user_ids = request.form.getlist('user_ids')
    user_ids = [int(uid) for uid in user_ids if uid.isdigit()]
    
    # Remove all existing users from this role
    BookingFormRoleUser.query.filter_by(role_id=role_id).delete()
    
    # Add selected users
    for user_id in user_ids:
        # Check if user exists and is active
        user = User.query.filter_by(id=user_id, is_active=True).first()
        if user:
            role_user = BookingFormRoleUser(role_id=role_id, user_id=user_id)
            db.session.add(role_user)
    
    db.session.commit()
    
    flash(f'Benutzer für Rolle "{role.role_name}" wurden aktualisiert.', 'success')
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/roles', methods=['GET'])
@login_required
def booking_roles(form_id):
    """Get roles for a booking form as JSON (admin only)."""
    if not current_user.is_admin:
        from flask import jsonify
        return jsonify({'error': 'Unauthorized'}), 403
    
    from app.models.booking import BookingForm, BookingFormRole
    from flask import jsonify
    
    form = BookingForm.query.get_or_404(form_id)
    
    roles = []
    for role in form.roles:
        roles.append({
            'id': role.id,
            'role_name': role.role_name,
            'is_required': role.is_required,
            'role_order': role.role_order,
            'users': [{'id': u.user_id, 'full_name': u.user.full_name} for u in role.users]
        })
    
    return jsonify({'roles': roles})


@settings_bp.route('/about')
@login_required
def about():
    """Über PrismaTeams Seite."""
    # Finde den ersten Administrator (ältester Admin-User nach created_at)
    first_admin = User.query.filter_by(is_admin=True).order_by(User.created_at.asc()).first()
    creator_name = first_admin.full_name if first_admin else "Unbekannt"
    
    # OnlyOffice Status prüfen
    from app.utils.onlyoffice import is_onlyoffice_enabled
    onlyoffice_enabled = is_onlyoffice_enabled()
    
    return render_template('settings/about.html', creator_name=creator_name, onlyoffice_enabled=onlyoffice_enabled)


LANGUAGE_FALLBACK_NAMES = {
    'de': 'Deutsch',
    'en': 'English',
    'pt': 'Português',
    'es': 'Español',
    'ru': 'Русский'
}

