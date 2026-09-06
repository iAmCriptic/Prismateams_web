from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, abort, current_app, send_file, g, after_this_request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.email import EmailPermission
from app.models.settings import SystemSettings
from app.models.notification import NotificationSettings, ChatNotificationSettings, PushSubscription, NotificationLog
from app.models.chat import Chat, ChatMember
from app.models.whitelist import WhitelistEntry
from app.utils.notifications import get_or_create_notification_settings, sync_user_notification_flags
from app.utils.backup import export_backup, import_backup, SUPPORTED_CATEGORIES, CATEGORY_DEFINITIONS
from werkzeug.utils import secure_filename
from datetime import datetime
from collections import defaultdict
import json
import os
import secrets
import tempfile
from app.utils.i18n import available_languages, translate
from app.utils.totp import (
    generate_totp_secret,
    get_totp_uri,
    get_totp_issuer_name,
    generate_qr_code,
    encrypt_secret,
    verify_totp,
)
from app.utils.webauthn_helper import passkeys_supported_for_request, localhost_passkey_url
from app.utils.session_manager import get_user_sessions, revoke_session, revoke_all_sessions
from app.utils.password_policy import validate_password
from app.utils.common import get_timezone_choices, DEFAULT_TIMEZONE, now_in_portal_timezone, portal_now_naive
from datetime import datetime, timedelta
from sqlalchemy import func, or_

from app.blueprints.settings._bp import (
    LANGUAGE_COMPLETENESS,
    LANGUAGE_FALLBACK_NAMES,
    _guest_account_form_options,
    _language_badge_grade,
    _settings_redirect,
    _settings_save_response,
    _wants_json_response,
    settings_bp,
)

@settings_bp.route('/')
@login_required
def index():
    """User settings page."""
    return render_template('settings/index.html', user=current_user)


@settings_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Edit user profile."""
    from app.models.team import TeamMember

    def _profile_teams():
        memberships = TeamMember.query.filter_by(user_id=current_user.id).all()
        return sorted(
            [m.team for m in memberships if m.team],
            key=lambda t: (t.name or '').lower()
        )

    if request.method == 'POST':
        current_user.first_name = request.form.get('first_name', '').strip()
        current_user.last_name = request.form.get('last_name', '').strip()
        current_user.email = request.form.get('email', '').strip().lower()
        current_user.phone = request.form.get('phone', '').strip()
        
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
                        return _settings_save_response(
                            False,
                            translate('settings.profile.flash_picture_too_large', size=file_size / (1024*1024)),
                            'settings.profile',
                            status=400,
                        )
                    
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
                else:
                    return _settings_save_response(
                        False,
                        translate('settings.profile.flash_picture_invalid_type'),
                        'settings.profile',
                        status=400,
                    )
        
        db.session.commit()
        return _settings_save_response(True, translate('settings.autosave.saved'), 'settings.profile')
    
    return render_template('settings/profile.html', user=current_user, user_teams=_profile_teams())


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
            current_app.logger.debug("[PROFILE PIC] Requested filename: %s", filename)
            current_app.logger.debug("[PROFILE PIC] Full path: %s", full_path)
            current_app.logger.debug("[PROFILE PIC] File exists: %s", os.path.isfile(full_path))
            current_app.logger.debug(
                "[PROFILE PIC] Directory contents: %s",
                os.listdir(directory) if os.path.exists(directory) else 'Directory not found',
            )
        
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


@settings_bp.route('/auth-brand-image/<path:filename>')
def auth_brand_image(filename):
    """Serve auth brand panel background image (public access)."""
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

        # Buchungsanfragen
        settings.booking_notifications_enabled = 'booking_notifications_enabled' in request.form
        settings.booking_message_notifications_enabled = 'booking_message_notifications_enabled' in request.form

        # Kanban-Benachrichtigungen
        from app.utils.common import is_module_enabled
        if is_module_enabled('module_kanban'):
            settings.kanban_notifications_enabled = 'kanban_notifications_enabled' in request.form
            settings.kanban_upload_notifications = 'kanban_upload_notifications' in request.form
            settings.kanban_change_notifications = 'kanban_change_notifications' in request.form
            settings.kanban_checklist_notifications = 'kanban_checklist_notifications' in request.form
        
        # Kalender-Benachrichtigungen
        settings.calendar_notifications_enabled = 'calendar_notifications_enabled' in request.form
        settings.calendar_all_events = request.form.get('calendar_event_filter') == 'all'
        settings.calendar_participating_only = 'calendar_participating_only' in request.form
        settings.calendar_not_participating = 'calendar_not_participating' in request.form
        settings.calendar_no_response = 'calendar_no_response' in request.form
        
        # Erinnerungszeiten
        reminder_times = request.form.getlist('reminder_times')
        settings.set_reminder_times([int(t) for t in reminder_times])
        
        # Chat-spezifische Einstellungen: nur deaktivierte Chats speichern
        ChatNotificationSettings.query.filter_by(user_id=current_user.id).delete()
        memberships = ChatMember.query.filter_by(user_id=current_user.id).all()
        for membership in memberships:
            field_name = f'chat_{membership.chat_id}'
            if field_name not in request.form:
                db.session.add(ChatNotificationSettings(
                    user_id=current_user.id,
                    chat_id=membership.chat_id,
                    notifications_enabled=False,
                ))

        sync_user_notification_flags(current_user, settings)

        db.session.commit()
        return _settings_save_response(True, translate('settings.autosave.saved'), 'settings.notifications')
    
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

    from app.utils.common import is_module_enabled

    return render_template(
        'settings/notifications.html',
        settings=settings,
        user_chats=user_chats,
        chat_notification_settings=chat_notification_settings,
        kanban_module_enabled=is_module_enabled('module_kanban'),
    )


@settings_bp.route('/appearance', methods=['GET', 'POST'])
@login_required
def appearance():
    """Edit appearance settings."""
    language_codes = list(available_languages())
    selected_language = request.form.get('language') if request.method == 'POST' else current_user.language
    is_guest = hasattr(current_user, 'is_guest') and current_user.is_guest
    previous_language = current_user.language

    if request.method == 'POST':
        color_type = request.form.get('color_type', 'solid')
        accent_color = request.form.get('accent_color', '#0d6efd')
        accent_gradient = request.form.get('accent_gradient', '').strip()
        dark_mode = request.form.get('dark_mode') == 'on'
        oled_mode = request.form.get('oled_mode') == 'on'
        preferred_layout = request.form.get('preferred_layout', 'auto')

        if selected_language and selected_language not in language_codes:
            return _settings_save_response(
                False,
                translate('settings.appearance.flash_invalid_language'),
                'settings.appearance',
                status=400,
            )

        if preferred_layout not in ['auto', 'mobile', 'desktop']:
            preferred_layout = 'auto'

        current_user.accent_color = accent_color
        current_user.dark_mode = dark_mode
        current_user.oled_mode = oled_mode if dark_mode else False
        current_user.preferred_layout = preferred_layout

        if color_type == 'gradient' and accent_gradient:
            current_user.accent_gradient = accent_gradient
            # Keep solid accent_color in sync with first gradient stop for highlights
            import re
            matches = re.findall(r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b', accent_gradient)
            if matches:
                raw = matches[0]
                if len(raw) == 3:
                    raw = ''.join(ch * 2 for ch in raw)
                current_user.accent_color = f'#{raw.lower()}'
        else:
            current_user.accent_gradient = None

        language_changed = False
        if selected_language and selected_language != previous_language:
            current_user.language = selected_language
            g.language = selected_language
            language_changed = True

        db.session.commit()
        return _settings_save_response(
            True,
            translate('settings.autosave.saved'),
            'settings.appearance',
            accent_color=current_user.accent_color,
            accent_gradient=current_user.accent_gradient,
            dark_mode=current_user.dark_mode,
            oled_mode=current_user.oled_mode,
            language=current_user.language,
            preferred_layout=current_user.preferred_layout,
            reload=language_changed,
        )

    language_options = []
    for code in language_codes:
        key = f'languages.{code}'
        label = translate(key)
        if label == key:
            label = LANGUAGE_FALLBACK_NAMES.get(code, code.upper())
        completeness = LANGUAGE_COMPLETENESS.get(code)
        badge = f'{completeness}%' if completeness is not None else None
        language_options.append({
            'code': code,
            'label': label,
            'completeness': completeness,
            'badge': badge,
            'badge_grade': _language_badge_grade(completeness) if completeness is not None else None,
        })

    return render_template(
        'settings/appearance.html',
        user=current_user,
        language_options=language_options,
        is_guest=is_guest,
    )
