from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, abort, current_app, send_file, g, after_this_request, jsonify, session
from flask_login import login_required, current_user, logout_user
from app import db, limiter
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
    
    from app.utils.account_deletion import can_self_delete, user_requires_second_factor, passkey_recently_verified
    from app.models.passkey import UserPasskey

    can_delete, delete_block_reason = can_self_delete(current_user)
    has_passkeys = UserPasskey.query.filter_by(user_id=current_user.id).count() > 0
    requires_2fa = user_requires_second_factor(current_user)

    return render_template(
        'settings/profile.html',
        user=current_user,
        user_teams=_profile_teams(),
        can_delete_account=can_delete,
        delete_block_reason=delete_block_reason,
        requires_second_factor=requires_2fa,
        has_passkeys=has_passkeys,
        totp_enabled=bool(current_user.totp_enabled),
        passkey_verified=passkey_recently_verified(session),
    )


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


@settings_bp.route('/privacy')
@login_required
def privacy():
    """Privacy & personal data settings (export / rights info)."""
    return render_template('settings/privacy.html', user=current_user)


@settings_bp.route('/privacy/export', methods=['POST'])
@login_required
@limiter.limit('5 per hour')
def privacy_export():
    """Download a machine-readable export of the current user's personal data."""
    from app.utils.user_data_export import export_user_data_json_bytes
    import zipfile
    import io

    try:
        json_bytes = export_user_data_json_bytes(current_user)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('personal_data.json', json_bytes)
            zf.writestr(
                'README.txt',
                (
                    'PrismaTeams personal data export (GDPR Art. 20)\n'
                    f'User ID: {current_user.id}\n'
                    f'Generated (UTC): {timestamp}\n\n'
                    'Secrets (passwords, 2FA secrets, session tokens, push keys) are excluded.\n'
                    'Uploaded file binaries are listed as metadata only.\n'
                ).encode('utf-8'),
            )
        zip_buffer.seek(0)

        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=f'prismateams_personal_data_{current_user.id}_{timestamp}.zip',
            mimetype='application/zip',
        )
    except Exception as exc:
        current_app.logger.exception('Personal data export failed for user %s: %s', current_user.id, exc)
        flash(translate('settings.privacy.export_error'), 'danger')
        return redirect(url_for('settings.privacy'))


@settings_bp.route('/profile/delete/request', methods=['POST'])
@login_required
@limiter.limit('5 per hour')
def profile_delete_request():
    """Validate password (+ 2FA) and send account-deletion confirmation email."""
    from app.utils.account_deletion import (
        can_self_delete,
        clear_passkey_verified,
        generate_deletion_token,
        second_factor_ok,
        send_account_deletion_email,
    )

    allowed, reason = can_self_delete(current_user)
    if not allowed:
        flash(translate(f'settings.profile.delete.{reason}'), 'danger')
        return redirect(url_for('settings.profile'))

    password = request.form.get('password', '')
    totp_code = request.form.get('totp_code', '').strip()
    confirm_text = (request.form.get('confirm_text') or '').strip().upper()

    if confirm_text not in ('LÖSCHEN', 'LOESCHEN', 'DELETE'):
        flash(translate('settings.profile.delete.flash_confirm_text'), 'danger')
        return redirect(url_for('settings.profile'))

    if not password or not current_user.check_password(password):
        flash(translate('settings.profile.delete.flash_wrong_password'), 'danger')
        return redirect(url_for('settings.profile'))

    if not second_factor_ok(current_user, totp_code=totp_code, session=session):
        flash(translate('settings.profile.delete.flash_2fa_required'), 'danger')
        return redirect(url_for('settings.profile'))

    token = generate_deletion_token(current_user.id)
    sent = send_account_deletion_email(current_user, token)
    clear_passkey_verified(session)

    if not sent:
        flash(translate('settings.profile.delete.flash_email_failed'), 'danger')
        return redirect(url_for('settings.profile'))

    flash(translate('settings.profile.delete.flash_email_sent'), 'success')
    return redirect(url_for('settings.profile'))


@settings_bp.route('/profile/delete/passkey/options', methods=['POST'])
@login_required
@limiter.limit('30 per hour')
def profile_delete_passkey_options():
    from app.models.passkey import UserPasskey
    from app.utils.webauthn_helper import WebAuthnError, build_2fa_options

    if getattr(current_user, 'is_guest', False):
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.guest_not_allowed')}), 403

    passkeys = UserPasskey.query.filter_by(user_id=current_user.id).all()
    if not passkeys:
        return jsonify({'success': False, 'error': translate('settings.profile.delete.flash_no_passkey')}), 400

    try:
        options = build_2fa_options(passkeys)
        return jsonify({'success': True, 'options': options})
    except WebAuthnError as exc:
        return jsonify({'success': False, 'error': str(exc)}), exc.status_code
    except Exception:
        current_app.logger.exception('Passkey options for account deletion failed')
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.register_failed')}), 500


@settings_bp.route('/profile/delete/passkey/verify', methods=['POST'])
@login_required
@limiter.limit('30 per hour')
def profile_delete_passkey_verify():
    from app.models.passkey import UserPasskey
    from app.utils.account_deletion import mark_passkey_verified
    from app.utils.webauthn_helper import WebAuthnError, verify_2fa

    if getattr(current_user, 'is_guest', False):
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.guest_not_allowed')}), 403

    credential = request.get_json(silent=True) or {}
    if isinstance(credential, dict) and 'credential' in credential:
        credential = credential.get('credential') or {}
    passkeys = UserPasskey.query.filter_by(user_id=current_user.id).all()
    if not passkeys:
        return jsonify({'success': False, 'error': translate('settings.profile.delete.flash_no_passkey')}), 400

    try:
        passkey, verification = verify_2fa(passkeys, credential)
        from app.utils.webauthn_helper import apply_verification_result
        apply_verification_result(passkey, verification)
        db.session.commit()
        mark_passkey_verified(session)
        return jsonify({'success': True})
    except WebAuthnError as exc:
        return jsonify({'success': False, 'error': str(exc)}), exc.status_code
    except Exception:
        current_app.logger.exception('Passkey verify for account deletion failed')
        return jsonify({'success': False, 'error': translate('auth.passkey.verify_failed')}), 500


@settings_bp.route('/profile/delete/confirm/<token>', methods=['GET', 'POST'])
@limiter.limit('20 per hour')
def profile_delete_confirm(token):
    """Confirm account deletion via emailed token (login optional but user must match if logged in)."""
    from app.utils.account_deletion import erase_user_account, verify_deletion_token

    user_id = verify_deletion_token(token)
    if not user_id:
        flash(translate('settings.profile.delete.flash_token_invalid'), 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.get(user_id)
    if not user:
        flash(translate('settings.profile.delete.flash_token_invalid'), 'danger')
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated and current_user.id != user.id:
        flash(translate('settings.profile.delete.flash_wrong_user'), 'danger')
        return redirect(url_for('settings.profile'))

    if request.method == 'GET':
        return render_template(
            'settings/profile_delete_confirm.html',
            token=token,
            user=user,
        )

    # POST — final delete
    if current_user.is_authenticated and current_user.id == user.id:
        logout_user()
    session.clear()

    try:
        erase_user_account(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Account deletion failed for user_id=%s', user_id)
        flash(translate('settings.profile.delete.flash_failed'), 'danger')
        return redirect(url_for('auth.login'))

    flash(translate('settings.profile.delete.flash_deleted'), 'success')
    return redirect(url_for('auth.login'))
