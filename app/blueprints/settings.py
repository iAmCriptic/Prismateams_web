from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, abort, current_app, send_file, g, after_this_request
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.email import EmailPermission
from app.models.settings import SystemSettings
from app.models.notification import NotificationSettings, ChatNotificationSettings
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
    flash('Profilbild wurde entfernt.', 'success')
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
        flash('Benachrichtigungseinstellungen wurden gespeichert.', 'success')
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

        if selected_language and selected_language not in language_codes:
            flash(translate('settings.appearance.flash_invalid_language'), 'danger')
            return redirect(url_for('settings.appearance'))

        current_user.accent_color = accent_color
        current_user.dark_mode = dark_mode
        current_user.oled_mode = oled_mode if dark_mode else False

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
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
        return redirect(url_for('settings.index'))
    
    return render_template('settings/admin.html')


@settings_bp.route('/admin/users')
@login_required
def admin_users():
    """Manage users (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
        return redirect(url_for('settings.index'))
    
    # Get all users
    active_users = User.query.filter_by(is_active=True).order_by(User.last_name, User.first_name).all()
    pending_users = User.query.filter_by(is_active=False).order_by(User.created_at.desc()).all()
    
    return render_template('settings/admin_users.html', active_users=active_users, pending_users=pending_users)


@settings_bp.route('/admin/users/<int:user_id>/activate', methods=['POST'])
@login_required
def activate_user(user_id):
    """Activate a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    user = User.query.get_or_404(user_id)
    user.is_active = True
    
    # Ensure user is added to main chat when activated
    from app.models.chat import Chat, ChatMember
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
    
    flash(f'Benutzer {user.full_name} wurde aktiviert.', 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
def deactivate_user(user_id):
    """Deactivate a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    if user_id == current_user.id:
        flash('Sie können sich nicht selbst deaktivieren.', 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user = User.query.get_or_404(user_id)
    
    # Super-Admins können nicht deaktiviert werden
    if user.is_super_admin:
        flash('Der Hauptadministrator kann nicht deaktiviert werden.', 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user.is_active = False
    db.session.commit()
    
    flash(f'Benutzer {user.full_name} wurde deaktiviert.', 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/users/<int:user_id>/make-admin', methods=['POST'])
@login_required
def make_admin(user_id):
    """Make a user an admin (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    user = User.query.get_or_404(user_id)
    user.is_admin = True
    db.session.commit()
    
    flash(f'{user.full_name} ist jetzt Administrator.', 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/users/<int:user_id>/remove-admin', methods=['POST'])
@login_required
def remove_admin(user_id):
    """Remove admin rights from a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    if user_id == current_user.id:
        flash('Sie können sich nicht selbst die Admin-Rechte entziehen.', 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user = User.query.get_or_404(user_id)
    
    # Super-Admins können ihre Rechte nicht entzogen bekommen
    if user.is_super_admin:
        flash('Die Admin-Rechte des Hauptadministrators können nicht entzogen werden.', 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user.is_admin = False
    db.session.commit()
    
    flash(f'{user.full_name} ist kein Administrator mehr.', 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    """Delete a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    if user_id == current_user.id:
        flash('Sie können sich nicht selbst löschen.', 'danger')
        return redirect(url_for('settings.admin_users'))
    
    user = User.query.get_or_404(user_id)
    
    # Super-Admins können nicht gelöscht werden
    if user.is_super_admin:
        flash('Der Hauptadministrator kann nicht gelöscht werden.', 'danger')
        return redirect(url_for('settings.admin_users'))
    
    # Delete profile picture
    if user.profile_picture:
        project_root = os.path.dirname(current_app.root_path)
        upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
        old_path = os.path.join(upload_dir, user.profile_picture)
        if os.path.exists(old_path):
            os.remove(old_path)
    
    db.session.delete(user)
    db.session.commit()
    
    flash(f'Benutzer {user.full_name} wurde gelöscht.', 'success')
    return redirect(url_for('settings.admin_users'))


@settings_bp.route('/admin/email-footer', methods=['GET', 'POST'])
@login_required
def admin_email_footer():
    """Configure email footer template (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
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
        flash('E-Mail-Footer wurde erfolgreich gespeichert.', 'success')
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
    """Manage email permissions (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
        return redirect(url_for('settings.index'))
    
    users = User.query.filter_by(is_active=True).order_by(User.last_name, User.first_name).all()
    permissions = {}
    
    for user in users:
        perm = EmailPermission.query.filter_by(user_id=user.id).first()
        permissions[user.id] = perm
    
    return render_template('settings/admin_email_permissions.html', users=users, permissions=permissions)


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
    status = "aktiviert" if perm.can_read else "deaktiviert"
    flash(f'E-Mail-Leseberechtigung für {user.full_name} wurde {status}.', 'success')
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
    status = "aktiviert" if perm.can_send else "deaktiviert"
    flash(f'E-Mail-Sendeberechtigung für {user.full_name} wurde {status}.', 'success')
    return redirect(url_for('settings.admin_email_permissions'))


@settings_bp.route('/admin/system', methods=['GET', 'POST'])
@login_required
def admin_system():
    """System settings (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
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
                        flash(f'Logo ist zu groß. Maximale Größe: 5MB. Ihre Datei: {file_size / (1024*1024):.1f}MB', 'danger')
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
                    flash('Portalslogo wurde erfolgreich hochgeladen.', 'success')
                else:
                    flash('Ungültiger Dateityp. Nur PNG, JPG, JPEG, GIF und SVG Dateien sind erlaubt.', 'danger')
                    return redirect(url_for('settings.admin_system'))
        
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
        flash('System-Einstellungen wurden aktualisiert.', 'success')
        return redirect(url_for('settings.admin_system'))
    
    # Get current settings
    portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
    portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
    dropbox_setting = SystemSettings.query.filter_by(key='files_dropbox_enabled').first()
    sharing_setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
    
    portal_name = portal_name_setting.value if portal_name_setting else ''
    portal_logo = portal_logo_setting.value if portal_logo_setting else None
    files_dropbox_enabled = (dropbox_setting and str(dropbox_setting.value).lower() == 'true') or False
    files_sharing_enabled = (sharing_setting and str(sharing_setting.value).lower() == 'true') or False
    
    return render_template('settings/admin_system.html', portal_name=portal_name, portal_logo=portal_logo,
                           files_dropbox_enabled=files_dropbox_enabled, files_sharing_enabled=files_sharing_enabled)


@settings_bp.route('/admin/modules', methods=['GET', 'POST'])
@login_required
def admin_modules():
    """Module settings (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
        return redirect(url_for('settings.index'))
    
    # Prüfe Excalidraw-Verfügbarkeit
    from app.utils.excalidraw import is_excalidraw_enabled
    excalidraw_available = is_excalidraw_enabled()
    
    if request.method == 'POST':
        # Module-Einstellungen speichern
        modules = {
            'module_chat': request.form.get('module_chat') == 'on',
            'module_files': request.form.get('module_files') == 'on',
            'module_calendar': request.form.get('module_calendar') == 'on',
            'module_email': request.form.get('module_email') == 'on',
            'module_credentials': request.form.get('module_credentials') == 'on',
            'module_manuals': request.form.get('module_manuals') == 'on',
            'module_canvas': request.form.get('module_canvas') == 'on' if excalidraw_available else False,
            'module_inventory': request.form.get('module_inventory') == 'on',
            'module_wiki': request.form.get('module_wiki') == 'on'
        }
        
        # Canvas kann nur aktiviert werden wenn Excalidraw verfügbar ist
        if modules['module_canvas'] and not excalidraw_available:
            flash('Canvas-Modul kann nur aktiviert werden, wenn Excalidraw verfügbar ist.', 'warning')
            modules['module_canvas'] = False
        
        for module_key, enabled in modules.items():
            module_setting = SystemSettings.query.filter_by(key=module_key).first()
            if module_setting:
                module_setting.value = str(enabled)
            else:
                db.session.add(SystemSettings(key=module_key, value=str(enabled), description=f'Modul {module_key} aktiviert'))
        
        db.session.commit()
        flash('Module-Einstellungen wurden aktualisiert.', 'success')
        return redirect(url_for('settings.admin_modules'))
    
    # Get module settings
    from app.utils.common import is_module_enabled
    module_chat_enabled = is_module_enabled('module_chat')
    module_files_enabled = is_module_enabled('module_files')
    module_calendar_enabled = is_module_enabled('module_calendar')
    module_email_enabled = is_module_enabled('module_email')
    module_credentials_enabled = is_module_enabled('module_credentials')
    module_manuals_enabled = is_module_enabled('module_manuals')
    module_canvas_enabled = is_module_enabled('module_canvas') and excalidraw_available
    module_inventory_enabled = is_module_enabled('module_inventory')
    module_wiki_enabled = is_module_enabled('module_wiki')
    
    return render_template('settings/admin_modules.html',
                           module_chat_enabled=module_chat_enabled,
                           module_files_enabled=module_files_enabled,
                           module_calendar_enabled=module_calendar_enabled,
                           module_email_enabled=module_email_enabled,
                           module_credentials_enabled=module_credentials_enabled,
                           module_manuals_enabled=module_manuals_enabled,
                           module_canvas_enabled=module_canvas_enabled,
                           module_inventory_enabled=module_inventory_enabled,
                           module_wiki_enabled=module_wiki_enabled,
                           excalidraw_available=excalidraw_available)


@settings_bp.route('/admin/backup', methods=['GET', 'POST'])
@login_required
def admin_backup():
    """Backup Import/Export (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'export':
            # Export-Backup erstellen
            categories = request.form.getlist('export_categories')
            if not categories:
                flash('Bitte wählen Sie mindestens eine Kategorie zum Exportieren aus.', 'danger')
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
                    flash('Fehler beim Erstellen des Backups.', 'danger')
            except Exception as e:
                current_app.logger.error(f"Fehler beim Export: {str(e)}")
                try:
                    if 'temp_path' in locals() and os.path.exists(temp_path):
                        os.unlink(temp_path)
                except OSError as cleanup_error:
                    current_app.logger.warning(f'Temporäre Backup-Datei konnte nach Fehler nicht gelöscht werden: {cleanup_error}')
                flash(f'Fehler beim Erstellen des Backups: {str(e)}', 'danger')
        
        elif action == 'import':
            # Import-Backup hochladen
            if 'backup_file' not in request.files:
                flash('Bitte wählen Sie eine Backup-Datei aus.', 'danger')
                return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)
            
            file = request.files['backup_file']
            if file.filename == '':
                flash('Bitte wählen Sie eine Backup-Datei aus.', 'danger')
                return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)
            
            if not file.filename.endswith('.prismateams'):
                flash('Ungültige Dateiendung. Bitte wählen Sie eine .prismateams-Datei aus.', 'danger')
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
                    flash('Bitte wählen Sie mindestens eine Kategorie zum Importieren aus.', 'danger')
                    os.unlink(temp_path)
                    return render_template('settings/admin_backup.html', categories=SUPPORTED_CATEGORIES)
                
                # Backup importieren
                result = import_backup(temp_path, import_categories, current_user.id)
                
                # Temporäre Datei löschen
                os.unlink(temp_path)
                
                if result['success']:
                    imported = ', '.join(result.get('imported', []))
                    flash(f'Backup erfolgreich importiert! Importierte Kategorien: {imported}', 'success')
                else:
                    flash(f'Fehler beim Importieren des Backups: {result.get("error", "Unbekannter Fehler")}', 'danger')
            except Exception as e:
                current_app.logger.error(f"Fehler beim Import: {str(e)}")
                flash(f'Fehler beim Importieren des Backups: {str(e)}', 'danger')
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
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
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
        flash('Bitte geben Sie einen gültigen Eintrag und Typ an.', 'danger')
        return redirect(url_for('settings.admin_whitelist'))
    
    # Validate entry format
    if entry_type == 'email':
        if '@' not in entry:
            flash('Bitte geben Sie eine gültige E-Mail-Adresse ein.', 'danger')
            return redirect(url_for('settings.admin_whitelist'))
    elif entry_type == 'domain':
        if not entry.startswith('@'):
            entry = '@' + entry
    
    # Add entry
    result = WhitelistEntry.add_entry(entry, entry_type, description, current_user.id)
    
    if result:
        flash(f'Whitelist-Eintrag "{entry}" wurde hinzugefügt.', 'success')
    else:
        flash('Fehler beim Hinzufügen des Whitelist-Eintrags. Möglicherweise existiert er bereits.', 'danger')
    
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
        status = "aktiviert" if entry.is_active else "deaktiviert"
        flash(f'Whitelist-Eintrag "{entry.entry}" wurde {status}.', 'success')
    else:
        flash('Fehler beim Ändern des Whitelist-Eintrags.', 'danger')
    
    return redirect(url_for('settings.admin_whitelist'))


@settings_bp.route('/admin/whitelist/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_whitelist_entry(entry_id):
    """Delete a whitelist entry (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    entry = WhitelistEntry.query.get(entry_id)
    if not entry:
        flash('Whitelist-Eintrag nicht gefunden.', 'danger')
        return redirect(url_for('settings.admin_whitelist'))
    
    result = WhitelistEntry.remove_entry(entry_id)
    
    if result:
        flash(f'Whitelist-Eintrag "{entry.entry}" wurde gelöscht.', 'success')
    else:
        flash('Fehler beim Löschen des Whitelist-Eintrags.', 'danger')
    
    return redirect(url_for('settings.admin_whitelist'))



@settings_bp.route('/admin/inventory-categories', methods=['GET', 'POST'])
@login_required
def admin_inventory_categories():
    """Manage inventory categories (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
        return redirect(url_for('settings.index'))
    
    # Lade Kategorien aus SystemSettings
    categories_setting = SystemSettings.query.filter_by(key='inventory_categories').first()
    categories = []
    if categories_setting and categories_setting.value:
        import json
        try:
            categories = json.loads(categories_setting.value)
        except:
            categories = []
    
    if request.method == 'POST':
        category_name = request.form.get('category_name', '').strip()
        if category_name:
            if category_name not in categories:
                categories.append(category_name)
                categories.sort()
                
                # Speichere in SystemSettings
                import json
                if categories_setting:
                    categories_setting.value = json.dumps(categories)
                else:
                    categories_setting = SystemSettings(
                        key='inventory_categories',
                        value=json.dumps(categories),
                        description='Verfügbare Kategorien für Produkte'
                    )
                    db.session.add(categories_setting)
                db.session.commit()
                flash(f'Kategorie "{category_name}" wurde hinzugefügt.', 'success')
            else:
                flash(f'Kategorie "{category_name}" existiert bereits.', 'warning')
        
        return redirect(url_for('settings.admin_inventory_categories'))
    
    return render_template('settings/admin_inventory_categories.html', categories=categories)


@settings_bp.route('/admin/inventory-settings', methods=['GET', 'POST'])
@login_required
def admin_inventory_settings():
    """Lagerverwaltung-Einstellungen (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
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
        flash('Lagerverwaltung-Einstellungen wurden gespeichert.', 'success')
        return redirect(url_for('settings.admin_inventory_settings'))
    
    # Lade aktuelle Einstellungen
    ownership_setting = SystemSettings.query.filter_by(key='inventory_ownership_text').first()
    ownership_text = ownership_setting.value if ownership_setting and ownership_setting.value else 'Eigentum der Technik'
    
    return render_template('settings/admin_inventory_settings.html', ownership_text=ownership_text)


@settings_bp.route('/admin/inventory-categories/<category_name>/delete', methods=['POST'])
@login_required
def admin_delete_inventory_category(category_name):
    """Delete an inventory category (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
        return redirect(url_for('settings.index'))
    
    # Lade Kategorien aus SystemSettings
    categories_setting = SystemSettings.query.filter_by(key='inventory_categories').first()
    if categories_setting and categories_setting.value:
        import json
        try:
            categories = json.loads(categories_setting.value)
            if category_name in categories:
                categories.remove(category_name)
                categories_setting.value = json.dumps(categories)
                db.session.commit()
                flash(f'Kategorie "{category_name}" wurde gelöscht.', 'success')
            else:
                flash(f'Kategorie "{category_name}" wurde nicht gefunden.', 'warning')
        except:
            flash('Fehler beim Löschen der Kategorie.', 'danger')
    
    return redirect(url_for('settings.admin_inventory_categories'))


@settings_bp.route('/admin/inventory-permissions')
@login_required
def admin_inventory_permissions():
    """Manage inventory borrow permissions (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren haben Zugriff auf diese Seite.', 'danger')
        return redirect(url_for('settings.index'))
    
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    
    return render_template('settings/admin_inventory_permissions.html', users=users)


@settings_bp.route('/admin/inventory-permissions/<int:user_id>/toggle', methods=['POST'])
@login_required
def admin_toggle_borrow_permission(user_id):
    """Toggle borrow permission for a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    user = User.query.get_or_404(user_id)
    user.can_borrow = not user.can_borrow
    db.session.commit()
    
    status = "erlaubt" if user.can_borrow else "gesperrt"
    flash(f'Ausleihe-Berechtigung für {user.full_name} wurde {status}.', 'success')
    
    return redirect(url_for('settings.admin_inventory_permissions'))


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
    
    # Excalidraw Status prüfen
    from app.utils.excalidraw import is_excalidraw_enabled
    excalidraw_enabled = is_excalidraw_enabled()
    
    return render_template('settings/about.html', creator_name=creator_name, onlyoffice_enabled=onlyoffice_enabled, excalidraw_enabled=excalidraw_enabled)


LANGUAGE_FALLBACK_NAMES = {
    'de': 'Deutsch',
    'en': 'English',
    'pt': 'Português',
    'es': 'Español',
    'ru': 'Русский'
}

