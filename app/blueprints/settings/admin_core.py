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
        redirect_ep = 'settings.admin_email_module' if request.form.get('return_to') == 'module' else 'settings.admin_email_footer'
        return _settings_save_response(True, translate('settings.admin.email_footer.flash_saved'), redirect_ep)
    
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
    
    now = now_in_portal_timezone()
    return render_template(
        'settings/admin_email_footer.html',
        footer_template=current_template,
        footer_preview_date=now.strftime('%d.%m.%Y'),
        footer_preview_time=now.strftime('%H:%M'),
    )


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
        
        # Handle portal logo removal (checkbox / hidden from UI)
        if request.form.get('remove_portal_logo') == '1':
            logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
            if logo_setting and logo_setting.value:
                try:
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                    old_path = os.path.join(upload_dir, logo_setting.value)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except OSError:
                    pass
                db.session.delete(logo_setting)
                flash(translate('settings.admin.system.flash_logo_removed'), 'success')

        # Handle portal logo upload (replaces existing; skips if only removal flagged without new file)
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

        auth_brand_color = request.form.get('auth_brand_color', '#667eea').strip()
        if not auth_brand_color.startswith('#'):
            auth_brand_color = f'#{auth_brand_color.lstrip("#")}'
        brand_color_setting = SystemSettings.query.filter_by(key='auth_brand_color').first()
        if brand_color_setting:
            brand_color_setting.value = auth_brand_color
        else:
            db.session.add(SystemSettings(
                key='auth_brand_color',
                value=auth_brand_color,
                description='Hintergrundfarbe Auth-Brand-Seite ohne Bild',
            ))

        from app.utils.auth_branding import normalize_auth_brand_logo_position

        auth_brand_text = request.form.get('auth_brand_text', '').strip()
        text_setting = SystemSettings.query.filter_by(key='auth_brand_text').first()
        if text_setting:
            text_setting.value = auth_brand_text
        else:
            db.session.add(SystemSettings(
                key='auth_brand_text',
                value=auth_brand_text,
                description='Optionaler Text auf der Login/Register Brand-Seite',
            ))

        logo_position = normalize_auth_brand_logo_position(
            request.form.get('auth_brand_logo_position', '').strip()
        )
        position_setting = SystemSettings.query.filter_by(key='auth_brand_logo_position').first()
        if position_setting:
            position_setting.value = logo_position
        else:
            db.session.add(SystemSettings(
                key='auth_brand_logo_position',
                value=logo_position,
                description='Logo-Position auf der Auth-Brand-Seite',
            ))

        if request.form.get('remove_auth_brand_image') == '1':
            image_setting = SystemSettings.query.filter_by(key='auth_brand_image').first()
            if image_setting and image_setting.value:
                try:
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                    old_path = os.path.join(upload_dir, image_setting.value)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except OSError:
                    pass
                db.session.delete(image_setting)
                flash(translate('settings.admin.system.flash_auth_brand_image_removed'), 'success')

        if 'auth_brand_image' in request.files:
            file = request.files['auth_brand_image']
            if file and file.filename:
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
                if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    file.seek(0, 2)
                    file_size = file.tell()
                    file.seek(0)
                    max_size = 8 * 1024 * 1024
                    if file_size > max_size:
                        flash(translate('settings.admin.system.flash_auth_brand_image_too_large'), 'danger')
                        return redirect(url_for('settings.admin_system'))

                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"auth_brand_{timestamp}_{filename}"

                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                    os.makedirs(upload_dir, exist_ok=True)
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)

                    old_image_setting = SystemSettings.query.filter_by(key='auth_brand_image').first()
                    if old_image_setting and old_image_setting.value:
                        try:
                            old_path = os.path.join(upload_dir, old_image_setting.value)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except OSError:
                            pass

                    if old_image_setting:
                        old_image_setting.value = filename
                    else:
                        db.session.add(SystemSettings(
                            key='auth_brand_image',
                            value=filename,
                            description='Hintergrundbild Auth-Brand-Seite',
                        ))
                    flash(translate('settings.admin.system.flash_auth_brand_image_uploaded'), 'success')
                else:
                    flash(translate('settings.admin.system.flash_auth_brand_image_invalid_type'), 'danger')
                    return redirect(url_for('settings.admin_system'))

        # Update portal timezone
        timezone_choices = dict(get_timezone_choices())
        portal_timezone = request.form.get('portal_timezone', DEFAULT_TIMEZONE).strip()
        if portal_timezone not in timezone_choices:
            portal_timezone = DEFAULT_TIMEZONE

        timezone_setting = SystemSettings.query.filter_by(key='portal_timezone').first()
        if timezone_setting:
            timezone_setting.value = portal_timezone
        else:
            timezone_setting = SystemSettings(
                key='portal_timezone',
                value=portal_timezone,
                description='Globale Zeitzone für Datums- und Zeitangaben'
            )
            db.session.add(timezone_setting)

        # Gast-E-Mail-Domain (ohne @), gilt für alle Gast-Accounts
        from app.utils.guest_accounts import (
            GUEST_EMAIL_DOMAIN_SETTING_KEY,
            get_guest_email_domain,
            normalize_guest_email_domain,
        )
        old_guest_domain = get_guest_email_domain()
        guest_domain_raw = request.form.get('guest_email_domain', '').strip()
        guest_email_domain = normalize_guest_email_domain(guest_domain_raw)
        if not guest_email_domain:
            flash(translate('settings.admin.system.flash_guest_domain_invalid'), 'danger')
            return redirect(url_for('settings.admin_system'))

        guest_domain_setting = SystemSettings.query.filter_by(key=GUEST_EMAIL_DOMAIN_SETTING_KEY).first()
        if guest_domain_setting:
            guest_domain_setting.value = guest_email_domain
        else:
            guest_domain_setting = SystemSettings(
                key=GUEST_EMAIL_DOMAIN_SETTING_KEY,
                value=guest_email_domain,
                description='Domain-Suffix für Gast-Login-Adressen (ohne @)'
            )
            db.session.add(guest_domain_setting)

        if guest_email_domain != old_guest_domain:
            guests = User.query.filter_by(is_guest=True).all()
            for guest in guests:
                if guest.guest_username:
                    guest.email = f"{guest.guest_username}@{guest_email_domain}"

        from app.utils.search_indexing import SETTING_DESCRIPTION as INDEXING_DESC
        from app.utils.search_indexing import SETTING_KEY as INDEXING_KEY
        indexing_enabled = request.form.get('search_indexing_enabled') == 'on'
        indexing_setting = SystemSettings.query.filter_by(key=INDEXING_KEY).first()
        if indexing_setting:
            indexing_setting.value = str(indexing_enabled)
            if not indexing_setting.description:
                indexing_setting.description = INDEXING_DESC
        else:
            db.session.add(SystemSettings(
                key=INDEXING_KEY,
                value=str(indexing_enabled),
                description=INDEXING_DESC,
            ))

        from app.utils.access_log_retention import (
            set_session_record_retention_days,
            set_share_access_log_retention_days,
        )
        try:
            session_ret_days = int(request.form.get('session_record_retention_days', '30') or 30)
        except (TypeError, ValueError):
            session_ret_days = 30
        try:
            share_log_days = int(request.form.get('share_access_log_retention_days', '90') or 90)
        except (TypeError, ValueError):
            share_log_days = 90
        set_session_record_retention_days(session_ret_days)
        set_share_access_log_retention_days(share_log_days)
        
        db.session.commit()
        return _settings_save_response(True, translate('settings.autosave.saved'), 'settings.admin_system')
    
    # Get current settings
    from app.utils.guest_accounts import get_guest_email_domain
    from app.utils.search_indexing import is_search_indexing_enabled
    from app.utils.access_log_retention import (
        get_session_record_retention_days,
        get_share_access_log_retention_days,
    )

    portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
    portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
    accent_color_setting = SystemSettings.query.filter_by(key='default_accent_color').first()
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    timezone_setting = SystemSettings.query.filter_by(key='portal_timezone').first()
    auth_brand_image_setting = SystemSettings.query.filter_by(key='auth_brand_image').first()
    auth_brand_color_setting = SystemSettings.query.filter_by(key='auth_brand_color').first()
    auth_brand_text_setting = SystemSettings.query.filter_by(key='auth_brand_text').first()
    auth_brand_position_setting = SystemSettings.query.filter_by(key='auth_brand_logo_position').first()
    from app.utils.auth_branding import AUTH_BRAND_LOGO_POSITIONS, normalize_auth_brand_logo_position
    
    portal_name = portal_name_setting.value if portal_name_setting else ''
    portal_logo = portal_logo_setting.value if portal_logo_setting else None
    default_accent_color = accent_color_setting.value if accent_color_setting else '#0d6efd'
    color_gradient = gradient_setting.value if gradient_setting else ''
    portal_timezone = timezone_setting.value if timezone_setting and timezone_setting.value else DEFAULT_TIMEZONE
    auth_brand_image = auth_brand_image_setting.value if auth_brand_image_setting else None
    auth_brand_color = auth_brand_color_setting.value if auth_brand_color_setting else '#667eea'
    auth_brand_text = auth_brand_text_setting.value if auth_brand_text_setting else ''
    auth_brand_logo_position = normalize_auth_brand_logo_position(
        auth_brand_position_setting.value if auth_brand_position_setting else None
    )
    guest_email_domain = get_guest_email_domain()
    search_indexing_enabled = is_search_indexing_enabled()
    session_record_retention_days = get_session_record_retention_days()
    share_access_log_retention_days = get_share_access_log_retention_days()
    session_cookie_secure = bool(current_app.config.get('SESSION_COOKIE_SECURE'))
    remember_cookie_secure = bool(current_app.config.get('REMEMBER_COOKIE_SECURE'))
    flask_env = (os.environ.get('FLASK_ENV') or ('development' if current_app.debug else 'production')).strip()
    
    return render_template('settings/admin_system.html', 
                         portal_name=portal_name, 
                         portal_logo=portal_logo,
                         default_accent_color=default_accent_color,
                         color_gradient=color_gradient,
                         portal_timezone=portal_timezone,
                         auth_brand_image=auth_brand_image,
                         auth_brand_color=auth_brand_color,
                         auth_brand_text=auth_brand_text,
                         auth_brand_logo_position=auth_brand_logo_position,
                         auth_brand_logo_positions=AUTH_BRAND_LOGO_POSITIONS,
                         guest_email_domain=guest_email_domain,
                         search_indexing_enabled=search_indexing_enabled,
                         session_record_retention_days=session_record_retention_days,
                         share_access_log_retention_days=share_access_log_retention_days,
                         session_cookie_secure=session_cookie_secure,
                         remember_cookie_secure=remember_cookie_secure,
                         flask_env=flask_env,
                         timezone_choices=get_timezone_choices())


@settings_bp.route('/admin/legal', methods=['GET', 'POST'])
@login_required
def admin_legal():
    """Datenschutz, Impressum & Nutzungsbedingungen bearbeiten (admin only)."""
    from app.utils.legal_pages import get_legal_content, set_legal_content

    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    if request.method == 'POST':
        set_legal_content('terms', request.form.get('terms_text', ''))
        set_legal_content('privacy', request.form.get('privacy_text', ''))
        set_legal_content('imprint', request.form.get('imprint_text', ''))
        db.session.commit()
        return _settings_save_response(True, translate('settings.autosave.saved'), 'settings.admin_legal')

    return render_template(
        'settings/admin_legal.html',
        terms_text=get_legal_content('terms'),
        privacy_text=get_legal_content('privacy'),
        imprint_text=get_legal_content('imprint'),
    )


@settings_bp.route('/admin/registration', methods=['GET', 'POST'])
@login_required
def admin_registration():
    """Registration and login bot protection settings (admin only)."""
    from app.utils.bot_protection import (
        SETTING_KEYS,
        VALID_PROVIDERS,
        VALID_RECAPTCHA_VERSIONS,
        generate_honeypot_field_name,
        get_config,
        is_configured,
        upsert_setting,
    )

    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    if request.method == 'POST':
        provider = request.form.get('portal_bot_protection', 'none').strip()
        if provider not in VALID_PROVIDERS:
            provider = 'none'

        recaptcha_version = request.form.get('portal_recaptcha_version', 'v2').strip()
        if recaptcha_version not in VALID_RECAPTCHA_VERSIONS:
            recaptcha_version = 'v2'

        register_enabled = request.form.get('portal_bot_protection_register') == 'on'
        login_enabled = request.form.get('portal_bot_protection_login') == 'on'
        share_edit_enabled = request.form.get('portal_bot_protection_share_edit') == 'on'
        mailbox_enabled = request.form.get('portal_bot_protection_mailbox') == 'on'
        surveys_enabled = request.form.get('portal_bot_protection_surveys') == 'on'

        recaptcha_site_key = request.form.get('portal_recaptcha_site_key', '').strip()
        recaptcha_secret_key = request.form.get('portal_recaptcha_secret_key', '').strip()
        turnstile_site_key = request.form.get('portal_turnstile_site_key', '').strip()
        turnstile_secret_key = request.form.get('portal_turnstile_secret_key', '').strip()

        existing = get_config()
        if not recaptcha_secret_key:
            recaptcha_secret_key = existing.get('recaptcha_secret_key', '')
        if not turnstile_secret_key:
            turnstile_secret_key = existing.get('turnstile_secret_key', '')

        pending_config = {
            'provider': provider,
            'register_enabled': register_enabled,
            'login_enabled': login_enabled,
            'share_edit_enabled': share_edit_enabled,
            'mailbox_enabled': mailbox_enabled,
            'surveys_enabled': surveys_enabled,
            'recaptcha_version': recaptcha_version,
            'recaptcha_site_key': recaptcha_site_key,
            'recaptcha_secret_key': recaptcha_secret_key,
            'turnstile_site_key': turnstile_site_key,
            'turnstile_secret_key': turnstile_secret_key,
            'honeypot_field': _get_setting_value_for_admin(SETTING_KEYS['honeypot_field']),
        }

        if provider in {'recaptcha', 'turnstile'} and not is_configured(pending_config):
            flash(translate('settings.admin.registration.flash_keys_required'), 'danger')
            return redirect(url_for('settings.admin_registration'))

        upsert_setting(SETTING_KEYS['provider'], provider)
        upsert_setting(SETTING_KEYS['register_enabled'], 'true' if register_enabled else 'false')
        upsert_setting(SETTING_KEYS['login_enabled'], 'true' if login_enabled else 'false')
        upsert_setting(SETTING_KEYS['share_edit_enabled'], 'true' if share_edit_enabled else 'false')
        upsert_setting(SETTING_KEYS['mailbox_enabled'], 'true' if mailbox_enabled else 'false')
        upsert_setting(SETTING_KEYS['surveys_enabled'], 'true' if surveys_enabled else 'false')
        upsert_setting(SETTING_KEYS['recaptcha_version'], recaptcha_version)
        upsert_setting(SETTING_KEYS['recaptcha_site_key'], recaptcha_site_key)
        upsert_setting(SETTING_KEYS['recaptcha_secret_key'], recaptcha_secret_key)
        upsert_setting(SETTING_KEYS['turnstile_site_key'], turnstile_site_key)
        upsert_setting(SETTING_KEYS['turnstile_secret_key'], turnstile_secret_key)

        if provider == 'honeypot':
            honeypot_field = pending_config['honeypot_field'] or generate_honeypot_field_name()
            upsert_setting(SETTING_KEYS['honeypot_field'], honeypot_field)

        db.session.commit()
        return _settings_save_response(True, translate('settings.autosave.saved'), 'settings.admin_registration')

    config = get_config()
    return render_template('settings/admin_registration.html', config=config)


def _get_setting_value_for_admin(key: str) -> str:
    setting = SystemSettings.query.filter_by(key=key).first()
    return setting.value.strip() if setting and setting.value else ''


@settings_bp.route('/admin/file-settings', methods=['GET', 'POST'])
@login_required
def admin_file_settings():
    """File settings (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.file_settings.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.models.file import FileStorageException
    from app.utils.file_storage_limits import (
        SETTING_MAX_FILE,
        SETTING_QUOTA_BYTES,
        SETTING_QUOTA_ENABLED,
        bytes_from_value_unit,
        format_bytes_de,
        get_default_quota,
        get_global_max_file_size,
        is_quota_enabled,
        split_bytes_for_ui,
        sync_flask_max_content_length,
    )

    def _upsert_text(key: str, value: str, description: str | None = None):
        setting = SystemSettings.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            db.session.add(SystemSettings(key=key, value=value, description=description))

    if request.method == 'POST':
        action = (request.form.get('storage_action') or 'save').strip().lower()

        if action == 'delete_exception':
            exc_id = request.form.get('exception_id', type=int)
            row = FileStorageException.query.get(exc_id) if exc_id else None
            if row:
                db.session.delete(row)
                db.session.commit()
                try:
                    sync_flask_max_content_length(current_app._get_current_object())
                except Exception:
                    pass
                flash(translate('settings.admin.file_settings.flash_exception_deleted'), 'success')
            return _settings_redirect('settings.admin_file_settings')

        if action == 'add_exception':
            user_id = request.form.get('exception_user_id', type=int)
            user = User.query.filter_by(id=user_id, is_active=True).first() if user_id else None
            if not user or user.is_guest:
                flash(translate('settings.admin.file_settings.flash_exception_user_invalid'), 'danger')
                return _settings_redirect('settings.admin_file_settings')
            if FileStorageException.query.filter_by(user_id=user.id).first():
                flash(translate('settings.admin.file_settings.flash_exception_exists'), 'warning')
                return _settings_redirect('settings.admin_file_settings')

            max_override = None
            if request.form.get('exception_max_file_custom') == 'on':
                max_override = bytes_from_value_unit(
                    request.form.get('exception_max_file_value', '100'),
                    request.form.get('exception_max_file_unit', 'MB'),
                )
                if max_override < 1:
                    flash(translate('settings.admin.file_settings.flash_invalid_size'), 'danger')
                    return _settings_redirect('settings.admin_file_settings')

            quota_override = None
            if request.form.get('exception_quota_custom') == 'on':
                quota_override = bytes_from_value_unit(
                    request.form.get('exception_quota_value', '15'),
                    request.form.get('exception_quota_unit', 'GB'),
                )

            if max_override is None and quota_override is None:
                flash(translate('settings.admin.file_settings.flash_exception_empty'), 'warning')
                return _settings_redirect('settings.admin_file_settings')

            db.session.add(FileStorageException(
                user_id=user.id,
                max_file_size_bytes=max_override,
                quota_bytes=quota_override,
            ))
            db.session.commit()
            try:
                sync_flask_max_content_length(current_app._get_current_object())
            except Exception:
                pass
            flash(translate('settings.admin.file_settings.flash_exception_added'), 'success')
            return _settings_redirect('settings.admin_file_settings')

        # Feature Flags: Dateien
        from app.utils.document_formats import (
            FORMAT_OFFICE,
            FORMAT_OPENDOCUMENT,
            SETTING_DOCUMENT_FORMAT,
        )

        dropbox_enabled = request.form.get('files_dropbox_enabled') == 'on'
        sharing_enabled = request.form.get('files_sharing_enabled') == 'on'
        webdav_enabled = request.form.get('files_webdav_enabled') == 'on'
        document_format = (request.form.get('files_document_format') or FORMAT_OFFICE).strip().lower()
        if document_format not in (FORMAT_OFFICE, FORMAT_OPENDOCUMENT):
            document_format = FORMAT_OFFICE
        _upsert_text('files_dropbox_enabled', str(dropbox_enabled))
        _upsert_text('files_sharing_enabled', str(sharing_enabled))
        _upsert_text('files_webdav_enabled', str(webdav_enabled))
        _upsert_text(
            SETTING_DOCUMENT_FORMAT,
            document_format,
            'Format für neue Dokumente: office (docx/xlsx/pptx) oder opendocument (odt/ods/odp)',
        )

        max_file_bytes = bytes_from_value_unit(
            request.form.get('files_max_file_value', '100'),
            request.form.get('files_max_file_unit', 'MB'),
        )
        if max_file_bytes < 1:
            flash(translate('settings.admin.file_settings.flash_invalid_size'), 'danger')
            return _settings_redirect('settings.admin_file_settings')

        quota_enabled = request.form.get('files_storage_quota_enabled') == 'on'
        quota_bytes = bytes_from_value_unit(
            request.form.get('files_quota_value', '15'),
            request.form.get('files_quota_unit', 'GB'),
        )

        _upsert_text(SETTING_MAX_FILE, str(max_file_bytes), 'Maximale Dateigroesse in Bytes (global)')
        _upsert_text(SETTING_QUOTA_ENABLED, str(quota_enabled).lower(), 'Speicherkontingente aktiv')
        _upsert_text(SETTING_QUOTA_BYTES, str(max(0, quota_bytes)), 'Standard-Speicherkontingent pro Nutzer')

        from app.utils.files_trash_retention import set_trash_retention_days
        try:
            trash_days = int(request.form.get('files_trash_retention_days', '30') or 30)
        except (TypeError, ValueError):
            trash_days = 30
        if trash_days < 0:
            trash_days = 0
        if trash_days > 3650:
            trash_days = 3650
        set_trash_retention_days(trash_days)

        db.session.commit()
        try:
            sync_flask_max_content_length(current_app._get_current_object())
        except Exception as sync_err:
            current_app.logger.warning('MAX_CONTENT_LENGTH sync failed: %s', sync_err)

        return _settings_save_response(
            True,
            translate('settings.admin.file_settings.flash_updated'),
            'settings.admin_file_settings',
        )

    # GET
    from app.utils.document_formats import FORMAT_OFFICE, get_document_format

    dropbox_setting = SystemSettings.query.filter_by(key='files_dropbox_enabled').first()
    sharing_setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
    webdav_setting = SystemSettings.query.filter_by(key='files_webdav_enabled').first()
    private_setting = SystemSettings.query.filter_by(key='files_private_folders_enabled').first()
    team_setting = SystemSettings.query.filter_by(key='files_team_folders_enabled').first()

    files_dropbox_enabled = (dropbox_setting and str(dropbox_setting.value).lower() == 'true') or False
    files_sharing_enabled = (sharing_setting and str(sharing_setting.value).lower() == 'true') or False
    files_webdav_enabled = (webdav_setting and str(webdav_setting.value).lower() == 'true') or False
    files_private_folders_enabled = (private_setting and str(private_setting.value).lower() == 'true') or False
    files_team_folders_enabled = (team_setting and str(team_setting.value).lower() == 'true') or False
    files_document_format = get_document_format() or FORMAT_OFFICE
    webdav_url = f"{request.url_root.rstrip('/')}/webdav"

    max_file_value, max_file_unit = split_bytes_for_ui(get_global_max_file_size())
    quota_value, quota_unit = split_bytes_for_ui(get_default_quota())
    quota_enabled = is_quota_enabled()

    from app.utils.files_trash_retention import get_trash_retention_days
    files_trash_retention_days = get_trash_retention_days()

    exceptions = (
        FileStorageException.query
        .order_by(FileStorageException.id.desc())
        .all()
    )
    exception_user_ids = {e.user_id for e in exceptions}
    users_q = User.query.filter(User.is_active.is_(True), User.is_guest.is_(False))
    if exception_user_ids:
        users_q = users_q.filter(~User.id.in_(exception_user_ids))
    users_for_exceptions = users_q.order_by(User.last_name.asc(), User.first_name.asc()).all()

    exception_rows = []
    for exc in exceptions:
        u = exc.user
        name = ''
        if u:
            name = f'{u.first_name or ""} {u.last_name or ""}'.strip() or (u.email or f'#{u.id}')
        else:
            name = f'#{exc.user_id}'
        exception_rows.append({
            'id': exc.id,
            'user_id': exc.user_id,
            'name': name,
            'email': getattr(u, 'email', '') or '',
            'max_file_label': format_bytes_de(exc.max_file_size_bytes) if exc.max_file_size_bytes else None,
            'quota_label': format_bytes_de(exc.quota_bytes) if exc.quota_bytes is not None else None,
        })

    return render_template(
        'settings/admin_file_settings.html',
        files_dropbox_enabled=files_dropbox_enabled,
        files_sharing_enabled=files_sharing_enabled,
        files_webdav_enabled=files_webdav_enabled,
        webdav_url=webdav_url,
        files_private_folders_enabled=files_private_folders_enabled,
        files_team_folders_enabled=files_team_folders_enabled,
        files_document_format=files_document_format,
        max_file_value=max_file_value,
        max_file_unit=max_file_unit,
        quota_enabled=quota_enabled,
        quota_value=quota_value,
        quota_unit=quota_unit,
        exception_rows=exception_rows,
        users_for_exceptions=users_for_exceptions,
        size_units=('KB', 'MB', 'GB', 'TB'),
        files_trash_retention_days=files_trash_retention_days,
    )


def _upsert_bool_setting(key, enabled):
    setting = SystemSettings.query.filter_by(key=key).first()
    if setting:
        setting.value = str(enabled)
    else:
        db.session.add(SystemSettings(key=key, value=str(enabled)))


@settings_bp.route('/admin/calendar-settings', methods=['GET', 'POST'])
@login_required
def admin_calendar_settings():
    """Calendar module settings (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.calendar_settings.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    if request.method == 'POST':
        export_enabled = request.form.get('calendar_export_enabled') == 'on'
        import_enabled = request.form.get('calendar_import_enabled') == 'on'

        _upsert_bool_setting('calendar_export_enabled', export_enabled)
        _upsert_bool_setting('calendar_import_enabled', import_enabled)
        db.session.commit()

        from app.utils.multi_calendars import (
            backfill_space_calendars,
            ensure_imported_calendar_for_source,
            fold_events_calendar_into_public,
            get_or_create_events_calendar,
            get_public_calendar,
            is_calendar_personal_enabled,
            is_calendar_team_enabled,
        )
        from app.models.calendar import CalendarEvent, CalendarSyncSource

        multi_enabled = is_calendar_personal_enabled() or is_calendar_team_enabled()
        if multi_enabled:
            try:
                backfill_space_calendars()
                public = get_public_calendar()
                events_cal = get_or_create_events_calendar()
                CalendarEvent.query.filter(CalendarEvent.calendar_id.is_(None)).update(
                    {CalendarEvent.calendar_id: public.id},
                    synchronize_session=False,
                )
                booking_or_event_ids = set()
                for row in CalendarEvent.query.filter(
                    CalendarEvent.calendar_id == public.id,
                    CalendarEvent.booking_request_id.isnot(None),
                ).with_entities(CalendarEvent.id).all():
                    booking_or_event_ids.add(row[0])
                try:
                    from app.models.event import EventAppointment
                    for row in EventAppointment.query.filter(
                        EventAppointment.calendar_event_id.isnot(None)
                    ).with_entities(EventAppointment.calendar_event_id).all():
                        booking_or_event_ids.add(row[0])
                except Exception:
                    pass
                if booking_or_event_ids:
                    CalendarEvent.query.filter(
                        CalendarEvent.id.in_(list(booking_or_event_ids)),
                        CalendarEvent.calendar_id == public.id,
                    ).update(
                        {CalendarEvent.calendar_id: events_cal.id},
                        synchronize_session=False,
                    )
                for source in CalendarSyncSource.query.all():
                    cal = ensure_imported_calendar_for_source(source)
                    CalendarEvent.query.filter_by(sync_source_id=source.id).update(
                        {CalendarEvent.calendar_id: cal.id},
                        synchronize_session=False,
                    )
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error('Fehler beim Aktivieren Multi-Kalender: %s', exc)
        else:
            try:
                fold_events_calendar_into_public()
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error('Fehler beim Deaktivieren Multi-Kalender: %s', exc)

        return _settings_save_response(
            True,
            translate('settings.admin.calendar_settings.flash_updated'),
            'settings.admin_calendar_settings',
        )

    from app.utils.multi_calendars import (
        is_calendar_export_enabled,
        is_calendar_import_enabled,
        is_calendar_personal_enabled,
        is_calendar_team_enabled,
    )
    return render_template(
        'settings/admin_calendar_settings.html',
        calendar_personal_enabled=is_calendar_personal_enabled(),
        calendar_team_enabled=is_calendar_team_enabled(),
        calendar_export_enabled=is_calendar_export_enabled(),
        calendar_import_enabled=is_calendar_import_enabled(),
    )


@settings_bp.route('/admin/modules', methods=['GET', 'POST'])
@login_required
def admin_modules():
    """Module settings (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    if request.method == 'POST':
        from app.utils.common import AVAILABLE_MODULES
        from app.utils.bot_protection import upsert_setting
        from app.utils.module_visibility_settings import (
            SETTING_ALLOW_PRIVATE,
            SETTING_ALLOW_PUBLIC,
            SETTING_ALLOW_TEAM,
            sync_legacy_visibility_keys,
        )

        modules = {key: request.form.get(key) == 'on' for key in AVAILABLE_MODULES}
        from app.utils.mirotalk import mirotalk_configured
        from app.utils.common import is_module_enabled
        if not mirotalk_configured():
            modules['module_meetings'] = is_module_enabled('module_meetings')
        for module_key, enabled in modules.items():
            module_setting = SystemSettings.query.filter_by(key=module_key).first()
            if module_setting:
                module_setting.value = str(enabled)
            else:
                db.session.add(SystemSettings(key=module_key, value=str(enabled), description=f'Modul {module_key} aktiviert'))

        allow_private = request.form.get('modules_allow_private') == 'on'
        allow_team = request.form.get('modules_allow_team') == 'on'
        allow_public = request.form.get('modules_allow_public') == 'on'
        upsert_setting(SETTING_ALLOW_PRIVATE, str(allow_private).lower(), 'Module: Private Varianten')
        upsert_setting(SETTING_ALLOW_TEAM, str(allow_team).lower(), 'Module: Team-Varianten')
        upsert_setting(SETTING_ALLOW_PUBLIC, str(allow_public).lower(), 'Module: Public-Varianten')
        sync_legacy_visibility_keys(allow_private, allow_team, allow_public)

        db.session.commit()
        return _settings_save_response(True, translate('settings.autosave.saved'), 'settings.admin_modules')
    
    # Get module settings
    from app.utils.common import is_module_enabled, AVAILABLE_MODULES
    from app.utils.module_visibility_settings import (
        is_global_private_enabled,
        is_global_public_enabled,
        is_global_team_enabled,
    )
    from app.utils.mirotalk import mirotalk_configured
    module_flags = {f'{key}_enabled': is_module_enabled(key) for key in AVAILABLE_MODULES}
    
    return render_template(
        'settings/admin_modules.html',
        modules_allow_private=is_global_private_enabled(),
        modules_allow_team=is_global_team_enabled(),
        modules_allow_public=is_global_public_enabled(),
        mirotalk_ready=mirotalk_configured(),
        **module_flags,
    )


@settings_bp.route('/admin/integrations', methods=['GET', 'POST'])
@login_required
def admin_integrations():
    """Google Cloud + Microsoft Azure Verknüpfungen (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.utils.integrations import (
        get_google_credentials,
        get_microsoft_credentials,
        save_integrations_from_form,
        migrate_youtube_keys_to_system,
    )

    migrate_youtube_keys_to_system()

    if request.method == 'POST':
        save_integrations_from_form(request.form)
        from app.models.music import MusicSettings

        spotify_client_id = request.form.get('spotify_client_id', '').strip()
        spotify_client_secret = request.form.get('spotify_client_secret', '').strip()

        for key, value, desc in (
            ('spotify_client_id', spotify_client_id, 'Spotify OAuth Client ID'),
            ('spotify_client_secret', spotify_client_secret, 'Spotify Client Secret'),
        ):
            row = MusicSettings.query.filter_by(key=key).first()
            if row:
                row.value = value
            else:
                db.session.add(MusicSettings(key=key, value=value, description=desc))

        db.session.commit()
        return _settings_save_response(True, translate('settings.autosave.saved'), 'settings.admin_integrations')

    google = get_google_credentials()
    microsoft = get_microsoft_credentials()
    from app.utils.integrations import google_oauth_redirect_uri
    from app.models.music import MusicSettings

    spotify_client_id = MusicSettings.query.filter_by(key='spotify_client_id').first()
    spotify_client_secret = MusicSettings.query.filter_by(key='spotify_client_secret').first()

    return render_template(
        'settings/admin_integrations.html',
        google=google,
        microsoft=microsoft,
        google_redirect=google_oauth_redirect_uri(),
        microsoft_redirect=url_for('settings.mailbox_oauth_callback', provider='microsoft', _external=True),
        spotify_client_id=spotify_client_id.value if spotify_client_id else '',
        spotify_client_secret=spotify_client_secret.value if spotify_client_secret else '',
        spotify_redirect_uri=url_for('music.spotify_callback', _external=True),
    )


@settings_bp.route('/admin/push-subscriptions', methods=['GET', 'POST'])
@login_required
def admin_push_subscriptions():
    """Legacy route — admin push page removed."""
    return redirect(url_for('settings.admin_system'))


def _admin_backup_ctx():
    return {
        'categories': SUPPORTED_CATEGORIES,
        'category_definitions': CATEGORY_DEFINITIONS,
    }


@settings_bp.route('/admin/backup', methods=['GET', 'POST'])
@login_required
def admin_backup():
    """Backup Import/Export (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    ctx = _admin_backup_ctx()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'export':
            categories = request.form.getlist('export_categories')
            if not categories:
                flash(translate('settings.admin.backup.flash_no_export_categories'), 'danger')
                return render_template('settings/admin_backup.html', **ctx)

            try:
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.prismateams', mode='w', encoding='utf-8')
                temp_path = temp_file.name
                temp_file.close()

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
            if 'backup_file' not in request.files:
                flash(translate('settings.admin.backup.flash_no_file'), 'danger')
                return render_template('settings/admin_backup.html', **ctx)

            file = request.files['backup_file']
            if file.filename == '':
                flash(translate('settings.admin.backup.flash_no_file'), 'danger')
                return render_template('settings/admin_backup.html', **ctx)

            if not file.filename.endswith('.prismateams'):
                flash(translate('settings.admin.backup.flash_invalid_extension'), 'danger')
                return render_template('settings/admin_backup.html', **ctx)

            try:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.prismateams', mode='wb')
                file.save(temp_file.name)
                temp_path = temp_file.name
                temp_file.close()

                import_categories = request.form.getlist('import_categories')
                if not import_categories:
                    flash(translate('settings.admin.backup.flash_no_import_categories'), 'danger')
                    os.unlink(temp_path)
                    return render_template('settings/admin_backup.html', **ctx)

                result = import_backup(temp_path, import_categories, current_user.id)
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
                    except OSError:
                        pass

    return render_template('settings/admin_backup.html', **ctx)


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

    from app.utils.inventory_features import (
        FEATURE_KEYS,
        is_inventory_accounting_enabled,
        is_inventory_borrow_enabled,
        is_inventory_dguv_enabled,
        is_inventory_owners_enabled,
        is_inventory_quick_scan_enabled,
        is_inventory_stocktake_enabled,
    )
    
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

        for key in FEATURE_KEYS:
            enabled = request.form.get(key) == 'on'
            _upsert_bool_setting(key, enabled)
        
        db.session.commit()
        return _settings_save_response(True, translate('settings.autosave.saved'), 'settings.admin_inventory_settings')
    
    # Lade aktuelle Einstellungen
    ownership_setting = SystemSettings.query.filter_by(key='inventory_ownership_text').first()
    ownership_text = ownership_setting.value if ownership_setting and ownership_setting.value else 'Eigentum der Technik'
    
    return render_template(
        'settings/admin_inventory_settings.html',
        ownership_text=ownership_text,
        inventory_borrow_enabled=is_inventory_borrow_enabled(),
        inventory_quick_scan_enabled=is_inventory_quick_scan_enabled(),
        inventory_dguv_enabled=is_inventory_dguv_enabled(),
        inventory_owners_enabled=is_inventory_owners_enabled(),
        inventory_accounting_enabled=is_inventory_accounting_enabled(),
        inventory_stocktake_enabled=is_inventory_stocktake_enabled(),
    )


@settings_bp.route('/admin/kanban-settings', methods=['GET', 'POST'])
@login_required
def admin_kanban_settings():
    """Legacy URL: Sichtbarkeit über Module, Import unter Board-Import."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    from app.utils.common import is_module_enabled
    if is_module_enabled('module_kanban'):
        return redirect(url_for('settings.kanban_import'))
    return redirect(url_for('settings.admin_modules'))


@settings_bp.route('/kanban-import')
@login_required
def kanban_import():
    """User-facing Kanban board import (JSON/CSV/ZIP)."""
    from app.utils.common import is_module_enabled
    from app.utils.kanban_access import allowed_import_board_targets
    from app.utils.access_control import has_module_access

    if not is_module_enabled('module_kanban') or not has_module_access(current_user, 'module_kanban'):
        flash(translate('settings.kanban_import.unavailable'), 'warning')
        return redirect(url_for('settings.index'))

    targets = allowed_import_board_targets(current_user)
    if not targets:
        flash(translate('settings.kanban_import.no_targets'), 'warning')
        return redirect(url_for('settings.index'))

    return render_template(
        'settings/kanban_import.html',
        import_targets=targets,
        kanban_import_url=url_for('kanban.api_import_board'),
    )


VISIBILITY_SETTINGS_MODULES = {
    'credentials': {
        'module_key': 'module_credentials',
        'label_key': 'layout.nav.credentials',
        'icon': 'bi-key',
    },
    'manuals': {
        'module_key': 'module_manuals',
        'label_key': 'layout.nav.manuals',
        'icon': 'bi-book',
    },
    'contacts': {
        'module_key': 'module_contacts',
        'label_key': 'layout.nav.contacts',
        'icon': 'bi-people',
    },
    'wiki': {
        'module_key': 'module_wiki',
        'label_key': 'layout.nav.wiki',
        'icon': 'bi-journal-text',
    },
    'shortlinks': {
        'module_key': 'module_shortlinks',
        'label_key': 'layout.nav.shortlinks',
        'icon': 'bi-link-45deg',
    },
    'excalidraw': {
        'module_key': 'module_excalidraw',
        'label_key': 'layout.nav.excalidraw',
        'icon': 'bi-pencil-square',
    },
    'surveys': {
        'module_key': 'module_surveys',
        'label_key': 'layout.nav.surveys',
        'icon': 'bi-ui-checks-grid',
    },
    'protocols': {
        'module_key': 'module_protocols',
        'label_key': 'layout.nav.protocols',
        'icon': 'bi-journal-richtext',
    },
}
