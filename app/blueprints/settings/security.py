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

@settings_bp.route('/security')
@login_required
def security():
    """Sicherheits-Einstellungen Hauptseite."""
    return _render_security_page()


def _render_security_page(scroll_to_devices=False):
    """Rendert die Sicherheitsseite (Passwort, 2FA, Geräte) im Pill-Layout."""
    qr_code_data = None
    totp_secret = None
    show_setup = False
    setup_mode = request.args.get('setup') == '1'

    if not current_user.totp_enabled:
        from flask import session as flask_session
        setup_started = flask_session.get('2fa_setup_started', False)
        if setup_mode and setup_started:
            if '2fa_setup_secret' not in flask_session:
                flask_session['2fa_setup_secret'] = generate_totp_secret()
            totp_secret = flask_session['2fa_setup_secret']
            totp_uri = get_totp_uri(current_user.email, totp_secret)
            logo_path = None
            portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
            if portal_logo_setting and portal_logo_setting.value:
                project_root = os.path.dirname(current_app.root_path)
                candidate = os.path.join(
                    project_root,
                    current_app.config['UPLOAD_FOLDER'],
                    'system',
                    portal_logo_setting.value,
                )
                if os.path.isfile(candidate):
                    logo_path = candidate
            qr_code_data = generate_qr_code(totp_uri, logo_path=logo_path)
            show_setup = True
        elif not setup_mode:
            # Setup nicht aktiv angefordert: sensible Setup-Daten verwerfen
            flask_session.pop('2fa_setup_started', None)
            flask_session.pop('2fa_setup_secret', None)

    sessions = get_user_sessions(current_user.id)

    from app.models.passkey import UserPasskey

    passkeys = []
    if not current_user.is_guest:
        passkeys = (
            UserPasskey.query.filter_by(user_id=current_user.id)
            .order_by(UserPasskey.created_at.desc())
            .all()
        )

    return render_template(
        'settings/security.html',
        user=current_user,
        qr_code_data=qr_code_data,
        totp_secret=totp_secret,
        totp_issuer_name=get_totp_issuer_name(),
        show_setup=show_setup,
        sessions=sessions,
        scroll_to_devices=scroll_to_devices,
        google_linked=bool(getattr(current_user, 'google_sub', None)),
        google_email=getattr(current_user, 'google_email', None),
        google_login_ready=_google_ready(),
        passkeys=passkeys,
        passkeys_supported=passkeys_supported_for_request(),
        passkeys_localhost_url=localhost_passkey_url(),
    )


def _google_ready():
    try:
        from app.utils.google_login import google_login_ready
        return google_login_ready()
    except Exception:
        return False


@settings_bp.route('/security/google/link')
@login_required
def security_google_link():
    """Startet Google-Verknüpfung (kein Register)."""
    from app.utils.google_login import google_login_ready, build_google_login_url
    if current_user.is_guest:
        flash(translate('auth.google.link_guest_forbidden'), 'danger')
        return redirect(url_for('settings.security'))
    if not google_login_ready():
        flash(translate('auth.google.not_configured'), 'warning')
        return redirect(url_for('settings.security'))
    try:
        return redirect(build_google_login_url(purpose='link'))
    except Exception as exc:
        flash(translate('auth.google.error', error=str(exc)), 'danger')
        return redirect(url_for('settings.security'))


@settings_bp.route('/security/google/unlink', methods=['POST'])
@login_required
def security_google_unlink():
    """Entfernt die Google-Verknüpfung (Postfach bleibt bestehen)."""
    if not getattr(current_user, 'google_sub', None):
        flash(translate('auth.google.not_linked_account'), 'info')
        return redirect(url_for('settings.security'))
    current_user.google_sub = None
    current_user.google_email = None
    current_user.google_linked_at = None
    db.session.commit()
    flash(translate('auth.google.unlink_success'), 'success')
    return redirect(url_for('settings.security'))


@settings_bp.route('/security/passwords', methods=['GET', 'POST'])
@login_required
def security_passwords():
    """Passwörter & 2FA Einstellungen."""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'start_2fa_setup':
            # Starte 2FA-Einrichtung
            from flask import session as flask_session
            flask_session['2fa_setup_started'] = True
            flask_session['2fa_setup_secret'] = generate_totp_secret()
            flash(translate('settings.security.2fa.setup_started'), 'info')
            return redirect(url_for('settings.security_passwords', setup=1))
        
        if action == 'cancel_2fa_setup':
            # Bricht 2FA-Einrichtung ab
            from flask import session as flask_session
            flask_session.pop('2fa_setup_started', None)
            flask_session.pop('2fa_setup_secret', None)
            flash(translate('settings.security.2fa.setup_cancelled'), 'info')
            return redirect(url_for('settings.security_passwords'))
        
        if action == 'change_password':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            if not current_password or not new_password or not confirm_password:
                flash(translate('settings.security.password.fill_all_fields'), 'danger')
                return redirect(url_for('settings.security_passwords'))
            
            if not current_user.check_password(current_password):
                flash(translate('settings.security.password.current_wrong'), 'danger')
                return redirect(url_for('settings.security_passwords'))
            
            if new_password != confirm_password:
                flash(translate('settings.security.password.passwords_dont_match'), 'danger')
                return redirect(url_for('settings.security_passwords'))
            
            # Validiere Passwort-Policy (einheitlich)
            is_valid, error_msg = validate_password(new_password)
            if not is_valid:
                flash(error_msg or translate('settings.security.password.invalid'), 'danger')
                return redirect(url_for('settings.security_passwords'))
            
            # Prüfe ob neues Passwort gleich dem aktuellen ist
            if current_user.check_password(new_password):
                flash(translate('settings.security.password.must_differ'), 'danger')
                return redirect(url_for('settings.security_passwords'))
            
            # Passwort ändern
            current_user.set_password(new_password)
            current_user.password_changed_at = datetime.utcnow()
            revoke_all_sessions(current_user.id, exclude_current=True)
            db.session.commit()
            
            flash(translate('settings.security.password.changed_success'), 'success')
            return redirect(url_for('settings.security'))
    
    return _render_security_page()


@settings_bp.route('/security/enable-2fa', methods=['POST'])
@login_required
def enable_2fa():
    """Aktiviere 2FA für den Benutzer."""
    from flask import session as flask_session
    totp_code = request.form.get('totp_code', '').strip()
    secret = flask_session.get('2fa_setup_secret')
    
    if not totp_code or not secret:
        flash(translate('settings.security.2fa.enter_code'), 'danger')
        return redirect(url_for('settings.security_passwords', setup=1))
    
    # Verifiziere TOTP-Code
    if not verify_totp(secret, totp_code):
        flash(translate('settings.security.2fa.invalid_code'), 'danger')
        return redirect(url_for('settings.security_passwords', setup=1))
    
    # Verschlüssele und speichere Secret
    current_user.totp_secret = encrypt_secret(secret)
    current_user.totp_enabled = True
    db.session.commit()
    
    # Entferne Secret aus Session
    flask_session.pop('2fa_setup_secret', None)
    flask_session.pop('2fa_setup_started', None)
    
    flash(translate('settings.security.2fa.enabled_success'), 'success')
    return redirect(url_for('settings.security'))


@settings_bp.route('/security/disable-2fa', methods=['POST'])
@login_required
def disable_2fa():
    """Deaktiviere 2FA für den Benutzer."""
    password = request.form.get('password', '')
    
    if not password:
        flash(translate('settings.security.2fa.enter_password'), 'danger')
        return redirect(url_for('settings.security'))
    
    if not current_user.check_password(password):
        flash(translate('settings.security.2fa.wrong_password'), 'danger')
        return redirect(url_for('settings.security'))
    
    current_user.totp_secret = None
    current_user.totp_enabled = False
    db.session.commit()
    
    flash(translate('settings.security.2fa.disabled_success'), 'success')
    return redirect(url_for('settings.security'))


@settings_bp.route('/security/passkey/register/options', methods=['POST'])
@login_required
def passkey_register_options():
    """WebAuthn-Registrierungsoptionen für Passkey."""
    from app.utils.webauthn_helper import (
        WebAuthnError,
        build_registration_options,
        passkeys_supported_for_request,
    )

    if current_user.is_guest:
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.guest_not_allowed')}), 403

    if not passkeys_supported_for_request():
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.https_required')}), 400

    try:
        options = build_registration_options(current_user)
        return jsonify({'success': True, 'options': options})
    except WebAuthnError as exc:
        return jsonify({'success': False, 'error': str(exc)}), exc.status_code
    except Exception:
        current_app.logger.exception('Passkey register options failed')
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.register_failed')}), 500


@settings_bp.route('/security/passkey/register/verify', methods=['POST'])
@login_required
def passkey_register_verify():
    """Passkey-Registrierung abschließen."""
    from app.models.passkey import UserPasskey
    from app.utils.webauthn_helper import (
        WebAuthnError,
        passkeys_supported_for_request,
        verify_registration,
    )

    if current_user.is_guest:
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.guest_not_allowed')}), 403

    if not passkeys_supported_for_request():
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.https_required')}), 400

    data = request.get_json(silent=True) or {}
    credential = data.get('credential')
    device_label = data.get('device_label')

    if not credential:
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.invalid_response')}), 400

    try:
        result = verify_registration(current_user, credential, device_label=device_label)
        if UserPasskey.query.filter_by(credential_id=result['credential_id']).first():
            return jsonify({'success': False, 'error': translate('settings.security.passkeys.already_registered')}), 409

        passkey = UserPasskey(
            user_id=current_user.id,
            credential_id=result['credential_id'],
            public_key=result['public_key'],
            sign_count=result['sign_count'],
            transports=result['transports'],
            aaguid=result['aaguid'],
            backed_up=result['backed_up'],
            device_label=result['device_label'],
        )
        db.session.add(passkey)
        db.session.commit()
        return jsonify({
            'success': True,
            'passkey': {
                'id': passkey.id,
                'device_label': passkey.device_label or translate('settings.security.passkeys.unnamed_device'),
            },
        })
    except WebAuthnError as exc:
        return jsonify({'success': False, 'error': str(exc)}), exc.status_code
    except Exception:
        current_app.logger.exception('Passkey register verify failed')
        db.session.rollback()
        return jsonify({'success': False, 'error': translate('settings.security.passkeys.register_failed')}), 500


@settings_bp.route('/security/passkey/<int:passkey_id>/delete', methods=['POST'])
@login_required
def passkey_delete(passkey_id):
    """Passkey entfernen (Passwort-Bestätigung)."""
    from app.models.passkey import UserPasskey

    password = request.form.get('password', '')
    if not password:
        flash(translate('settings.security.passkeys.enter_password'), 'danger')
        return redirect(url_for('settings.security'))

    if not current_user.check_password(password):
        flash(translate('settings.security.passkeys.wrong_password'), 'danger')
        return redirect(url_for('settings.security'))

    passkey = UserPasskey.query.filter_by(id=passkey_id, user_id=current_user.id).first()
    if not passkey:
        flash(translate('settings.security.passkeys.not_found'), 'danger')
        return redirect(url_for('settings.security'))

    db.session.delete(passkey)
    db.session.commit()
    flash(translate('settings.security.passkeys.deleted_success'), 'success')
    return redirect(url_for('settings.security'))


@settings_bp.route('/security/devices')
@login_required
def security_devices():
    """Angemeldete Geräte anzeigen (gleiche Seite, Scroll zu Geräte)."""
    return _render_security_page(scroll_to_devices=True)


@settings_bp.route('/security/revoke-session', methods=['POST'])
@login_required
def revoke_session_route():
    """Meldet eine spezifische Session ab."""
    session_id = request.form.get('session_id', '')
    
    if not session_id:
        flash(translate('settings.security.devices.invalid_session'), 'danger')
        return redirect(url_for('settings.security_devices'))
    
    if revoke_session(current_user.id, session_id):
        flash(translate('settings.security.devices.session_revoked'), 'success')
    else:
        flash(translate('settings.security.devices.session_not_found'), 'danger')
    
    return redirect(url_for('settings.security_devices'))


@settings_bp.route('/security/revoke-all-sessions', methods=['POST'])
@login_required
def revoke_all_sessions_route():
    """Meldet alle anderen Sessions ab."""
    revoked_count = revoke_all_sessions(current_user.id, exclude_current=True)
    
    if revoked_count > 0:
        flash(translate('settings.security.devices.all_sessions_revoked', count=revoked_count), 'success')
    else:
        flash(translate('settings.security.devices.no_sessions_to_revoke'), 'info')
    
    return redirect(url_for('settings.security_devices'))


@settings_bp.route('/about')
@login_required
def about():
    """Über PrismaTeams Seite."""
    # Finde den ersten Administrator (ältester Admin-User nach created_at)
    first_admin = User.query.filter_by(is_admin=True).order_by(User.created_at.asc()).first()
    creator_name = first_admin.full_name if first_admin else translate('settings.about.creator_unknown')

    portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
    portal_name = (portal_name_setting.value or '').strip() if portal_name_setting else ''

    # OnlyOffice Status prüfen
    from app.utils.onlyoffice import is_onlyoffice_enabled, get_onlyoffice_version
    from app.utils.media_downloader import is_media_downloader_compatible, get_ffmpeg_version
    from app.utils.file_converter import is_libreoffice_available, get_libreoffice_version
    from app.utils.excalidraw import is_excalidraw_collab_enabled, get_excalidraw_package_version
    from app.utils.mirotalk import mirotalk_configured, get_mirotalk_version
    onlyoffice_enabled = is_onlyoffice_enabled()
    onlyoffice_version = get_onlyoffice_version() if onlyoffice_enabled else None
    media_downloader_compatible = is_media_downloader_compatible()
    ffmpeg_version = get_ffmpeg_version() if media_downloader_compatible else None
    libreoffice_available = is_libreoffice_available()
    libreoffice_version = get_libreoffice_version() if libreoffice_available else None
    excalidraw_enabled = is_excalidraw_collab_enabled()
    excalidraw_version = get_excalidraw_package_version() if excalidraw_enabled else None
    mirotalk_enabled = mirotalk_configured()
    mirotalk_version = get_mirotalk_version() if mirotalk_enabled else None

    return render_template(
        'settings/about.html',
        creator_name=creator_name,
        portal_name=portal_name,
        release_version=current_app.config.get('ABOUT_RELEASE_VERSION', 'v0.0.0'),
        build_number=current_app.config.get('ABOUT_BUILD_NUMBER', ''),
        onlyoffice_enabled=onlyoffice_enabled,
        onlyoffice_version=onlyoffice_version,
        media_downloader_compatible=media_downloader_compatible,
        ffmpeg_version=ffmpeg_version,
        libreoffice_available=libreoffice_available,
        libreoffice_version=libreoffice_version,
        excalidraw_enabled=excalidraw_enabled,
        excalidraw_version=excalidraw_version,
        mirotalk_enabled=mirotalk_enabled,
        mirotalk_version=mirotalk_version,
    )
