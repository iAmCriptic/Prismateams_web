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

@settings_bp.route('/admin/visibility/<module>', methods=['GET', 'POST'])
@login_required
def admin_module_visibility(module):
    """Legacy route — visibility moved to module settings."""
    return redirect(url_for('settings.admin_modules'))


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

    from app.utils.multi_mailboxes import (
        is_email_multi_enabled,
        get_max_private_mailboxes,
        is_email_html_design_default,
    )
    
    now = now_in_portal_timezone()
    return render_template(
        'settings/admin_email_module.html',
        footer_template=current_footer,
        storage_days=storage_days,
        sync_interval=sync_interval,
        footer_preview_date=now.strftime('%d.%m.%Y'),
        footer_preview_time=now.strftime('%H:%M'),
        email_multi_enabled=is_email_multi_enabled(),
        email_max_private_mailboxes=get_max_private_mailboxes(),
        email_compose_html_design_default=is_email_html_design_default(),
    )


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

        # Multi-Postfach-Einstellungen (optional im gleichen Formular)
        if 'email_multi_enabled' in request.form or request.form.get('save_multi') == '1':
            multi_enabled = request.form.get('email_multi_enabled') == 'on'
            max_private_raw = request.form.get('email_max_private_mailboxes', '3').strip()
            try:
                max_private = max(0, int(max_private_raw))
            except ValueError:
                max_private = 3
            html_design_default = request.form.get('email_compose_html_design_default') == 'on'

            def _upsert_setting(key, value, description):
                row = SystemSettings.query.filter_by(key=key).first()
                if row:
                    row.value = str(value)
                else:
                    db.session.add(SystemSettings(key=key, value=str(value), description=description))

            _upsert_setting('email_multi_enabled', 'True' if multi_enabled else 'False', 'Multi-Postfach aktiv')
            _upsert_setting('email_max_private_mailboxes', str(max_private), 'Max. private Postfächer pro Nutzer')
            _upsert_setting(
                'email_compose_html_design_default',
                'True' if html_design_default else 'False',
                'Standard: HTML-Design beim Verfassen',
            )
        
        db.session.commit()
        redirect_ep = 'settings.admin_email_module' if request.form.get('return_to') == 'module' else 'settings.admin_email_settings'
        return _settings_save_response(True, translate('settings.admin.email_settings.flash_saved'), redirect_ep)
    
    # Lade aktuelle Einstellungen
    storage_setting = SystemSettings.query.filter_by(key='email_storage_days').first()
    storage_days = int(storage_setting.value) if storage_setting and storage_setting.value else 0
    
    sync_setting = SystemSettings.query.filter_by(key='email_sync_interval_minutes').first()
    sync_interval = int(sync_setting.value) if sync_setting and sync_setting.value else 30
    
    return render_template('settings/admin_email_settings.html', 
                         storage_days=storage_days, 
                         sync_interval=sync_interval)


@settings_bp.route('/admin/email-module/test-smtp', methods=['POST'])
@login_required
def admin_email_test_smtp():
    """SMTP-Test: sendet eine Test-E-Mail an den Admin (JSON)."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': translate('settings.admin.flash_unauthorized')}), 403

    from flask import current_app
    from app.utils.email_sender import send_smtp_test_email
    import smtplib

    mail_server = current_app.config.get('MAIL_SERVER')
    mail_username = current_app.config.get('MAIL_USERNAME')
    mail_password = current_app.config.get('MAIL_PASSWORD')

    if not mail_server or not mail_username or not mail_password:
        return jsonify({
            'success': False,
            'message': translate('settings.admin.email_module.test.smtp_incomplete'),
        })

    try:
        send_smtp_test_email(current_user.email)
        return jsonify({
            'success': True,
            'message': translate('settings.admin.email_module.test.smtp_ok', email=current_user.email),
        })
    except smtplib.SMTPAuthenticationError as e:
        return jsonify({
            'success': False,
            'message': translate('settings.admin.email_module.test.smtp_fail', error=f'Auth: {e}'),
        })
    except (smtplib.SMTPConnectError, TimeoutError, OSError) as e:
        return jsonify({
            'success': False,
            'message': translate(
                'settings.admin.email_module.test.smtp_fail',
                error=f'Verbindung zu {mail_server}: {e}',
            ),
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': translate('settings.admin.email_module.test.smtp_fail', error=str(e)),
        })


@settings_bp.route('/admin/email-module/test-imap', methods=['POST'])
@login_required
def admin_email_test_imap():
    """IMAP-Test: prüft eingehende Verbindung (JSON)."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': translate('settings.admin.flash_unauthorized')}), 403

    from flask import current_app
    from app.blueprints.email import (
        _is_placeholder_imap_config,
        probe_imap_connection,
    )

    imap_server = current_app.config.get('IMAP_SERVER')
    imap_port = int(current_app.config.get('IMAP_PORT', 993) or 993)
    username = current_app.config.get('MAIL_USERNAME')
    password = current_app.config.get('MAIL_PASSWORD')
    imap_timeout = int(current_app.config.get('MAIL_TIMEOUT', 20) or 20)

    if not all([imap_server, username, password]):
        return jsonify({
            'success': False,
            'message': translate('settings.admin.email_module.test.imap_incomplete'),
        })

    if _is_placeholder_imap_config(imap_server, username, password):
        return jsonify({
            'success': False,
            'message': translate('settings.admin.email_module.test.imap_placeholder'),
        })

    try:
        ok, detail, meta = probe_imap_connection(
            timeout=imap_timeout,
            retries=3,
            wait_for_sync_seconds=10,
        )
        if ok:
            server = (meta or {}).get('server', imap_server)
            port = (meta or {}).get('port', imap_port)
            msg = translate(
                'settings.admin.email_module.test.imap_ok',
                server=server,
                port=port,
            )
            if (meta or {}).get('sync_was_busy'):
                msg = f"{msg} (Hinweis: Sync war parallel aktiv)"
            return jsonify({'success': True, 'message': msg})

        return jsonify({
            'success': False,
            'message': translate('settings.admin.email_module.test.imap_fail', error=detail),
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': translate('settings.admin.email_module.test.imap_fail', error=str(e)),
        })


def _require_email_multi_or_redirect():
    from app.utils.multi_mailboxes import is_email_multi_enabled
    if not is_email_multi_enabled():
        flash(translate('settings.mailboxes.flash_multi_disabled'), 'warning')
        return False
    return True


def _save_mailbox_logo(file_storage, mailbox_id):
    """Validate and save mailbox logo. Returns (filename, error_key_or_None)."""
    from app.utils.multi_mailboxes import mailbox_upload_dir
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None, None
    filename = file_storage.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
        return None, 'settings.mailboxes.flash_logo_invalid'
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > 2 * 1024 * 1024:
        return None, 'settings.mailboxes.flash_logo_too_large'
    safe_name = f"{mailbox_id}_{secrets.token_hex(6)}{ext}"
    file_storage.save(os.path.join(mailbox_upload_dir(), safe_name))
    return safe_name, None


def _replace_mailbox_logo(mb, file_storage):
    """Save new logo for team mailbox only. Returns error translation key or None."""
    if mb.mailbox_type != 'team':
        return None
    filename, err = _save_mailbox_logo(file_storage, mb.id)
    if err:
        return err
    if not filename:
        return None
    if mb.logo_filename:
        try:
            from app.utils.multi_mailboxes import mailbox_upload_dir
            old = os.path.join(mailbox_upload_dir(), mb.logo_filename)
            if os.path.exists(old):
                os.remove(old)
        except Exception:
            pass
    mb.logo_filename = filename
    return None


def _mailbox_test_payload():
    """Credentials from JSON body or form for connection tests."""
    data = request.get_json(silent=True, force=True)
    if isinstance(data, dict) and data:
        src = data
    else:
        src = request.form

    def _s(key):
        return str(src.get(key) or '').strip()

    def _on(key, default=False):
        raw = src.get(key)
        if raw is None and default:
            return True
        return raw in ('on', 'true', True, '1', 1)

    try:
        smtp_port = int(src.get('smtp_port') or 587)
    except (TypeError, ValueError):
        smtp_port = 587
    try:
        imap_port = int(src.get('imap_port') or 993)
    except (TypeError, ValueError):
        imap_port = 993

    return {
        'smtp_server': _s('smtp_server'),
        'smtp_port': smtp_port,
        'smtp_use_tls': _on('smtp_use_tls'),
        'smtp_use_ssl': _on('smtp_use_ssl'),
        'smtp_username': _s('smtp_username'),
        'smtp_password': _s('smtp_password'),
        'imap_server': _s('imap_server'),
        'imap_port': imap_port,
        'imap_use_ssl': _on('imap_use_ssl', default=True),
        'imap_username': _s('imap_username'),
        'imap_password': _s('imap_password'),
    }


@settings_bp.route('/mailboxes/test-smtp', methods=['POST'])
@login_required
def mailbox_test_smtp():
    """SMTP-Verbindungstest mit Formular-Credentials (JSON)."""
    import smtplib
    import ssl as ssl_mod

    from app.utils.multi_mailboxes import is_email_multi_enabled
    if not is_email_multi_enabled():
        return jsonify({'success': False, 'message': translate('settings.mailboxes.flash_multi_disabled')}), 403

    p = _mailbox_test_payload()
    server = p['smtp_server']
    user = p['smtp_username']
    password = p['smtp_password']
    if not server or not user or not password or password == '••••••••':
        return jsonify({
            'success': False,
            'message': translate('settings.mailboxes.test_smtp_incomplete'),
        })

    use_ssl = p['smtp_use_ssl']
    use_tls = p['smtp_use_tls'] and not use_ssl
    port = p['smtp_port'] or (465 if use_ssl else 587)
    try:
        if use_ssl:
            context = ssl_mod.create_default_context()
            with smtplib.SMTP_SSL(server, port, timeout=20, context=context) as smtp:
                smtp.login(user, password)
        else:
            with smtplib.SMTP(server, port, timeout=20) as smtp:
                smtp.ehlo()
                if use_tls:
                    context = ssl_mod.create_default_context()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(user, password)
        return jsonify({
            'success': True,
            'message': translate('settings.mailboxes.test_smtp_ok', server=server, port=port),
        })
    except smtplib.SMTPAuthenticationError as e:
        return jsonify({
            'success': False,
            'message': translate('settings.mailboxes.test_fail', error=f'Auth: {e}'),
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': translate('settings.mailboxes.test_fail', error=str(e)),
        })


@settings_bp.route('/mailboxes/test-imap', methods=['POST'])
@login_required
def mailbox_test_imap():
    """IMAP-Verbindungstest mit Formular-Credentials (JSON)."""
    import imaplib
    import ssl as ssl_mod

    from app.utils.multi_mailboxes import is_email_multi_enabled
    if not is_email_multi_enabled():
        return jsonify({'success': False, 'message': translate('settings.mailboxes.flash_multi_disabled')}), 403

    p = _mailbox_test_payload()
    server = p['imap_server']
    user = p['imap_username'] or p['smtp_username']
    password = p['imap_password'] or p['smtp_password']
    placeholder_pw = password in ('••••••••', '********', '••••••••••••')
    if not server or not user or not password or placeholder_pw:
        missing = []
        if not server:
            missing.append('Server')
        if not user:
            missing.append('Benutzer')
        if not password or placeholder_pw:
            missing.append('Passwort')
        return jsonify({
            'success': False,
            'message': translate(
                'settings.mailboxes.test_imap_incomplete_fields',
                fields=', '.join(missing),
            ) if missing else translate('settings.mailboxes.test_imap_incomplete'),
        })

    port = p['imap_port'] or 993
    use_ssl = p['imap_use_ssl']
    try:
        if use_ssl:
            context = ssl_mod.create_default_context()
            try:
                imap = imaplib.IMAP4_SSL(server, port, ssl_context=context, timeout=20)
            except TypeError:
                imap = imaplib.IMAP4_SSL(server, port, ssl_context=context)
                imap.sock.settimeout(20)
        else:
            try:
                imap = imaplib.IMAP4(server, port, timeout=20)
            except TypeError:
                imap = imaplib.IMAP4(server, port)
                imap.sock.settimeout(20)
        try:
            typ, _ = imap.login(user, password)
            if typ != 'OK':
                raise RuntimeError(f'Login fehlgeschlagen: {typ}')
            imap.select('INBOX', readonly=True)
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        return jsonify({
            'success': True,
            'message': translate('settings.mailboxes.test_imap_ok', server=server, port=port),
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': translate('settings.mailboxes.test_fail', error=str(e)),
        })


def _mailbox_wizard_context(**extra):
    from app.utils.mailbox_oauth import (
        peek_oauth_result,
        provider_oauth_ready,
    )
    ctx = {
        'google_oauth_ready': provider_oauth_ready('google'),
        'microsoft_oauth_ready': provider_oauth_ready('microsoft'),
        'oauth_result': peek_oauth_result(),
        'show_logo': False,
        'show_owner': False,
        'team_id': None,
        'users': None,
    }
    ctx.update(extra)
    return ctx


@settings_bp.route('/mailboxes/oauth/<provider>/start')
@login_required
def mailbox_oauth_start(provider):
    """Startet Google/Microsoft OAuth (Popup oder Redirect)."""
    from app.utils.mailbox_oauth import build_oauth_authorize_url, provider_oauth_ready
    provider = (provider or '').strip().lower()
    if provider not in ('google', 'microsoft'):
        flash(translate('settings.mailboxes.oauth_unknown_provider'), 'danger')
        return redirect(url_for('settings.my_mailboxes'))
    if not provider_oauth_ready(provider):
        flash(translate('settings.mailboxes.oauth_not_configured'), 'warning')
        if current_user.is_admin:
            return redirect(url_for('settings.admin_integrations'))
        return redirect(url_for('settings.my_mailboxes'))
    popup = request.args.get('popup') == '1'
    try:
        return redirect(build_oauth_authorize_url(provider, popup=popup))
    except Exception as e:
        flash(translate('settings.mailboxes.oauth_error', error=str(e)), 'danger')
        return redirect(url_for('settings.my_mailboxes'))


@settings_bp.route('/mailboxes/oauth/<provider>/callback')
@login_required
def mailbox_oauth_callback(provider):
    """OAuth-Callback: Microsoft hier; Google primär über /google/callback (Legacy-URI bleibt kompatibel)."""
    from app.utils.mailbox_oauth import (
        handle_oauth_callback,
        mailbox_oauth_popup_error_html,
        mailbox_oauth_popup_success_html,
    )
    from flask import session
    provider = (provider or '').strip().lower()
    err = request.args.get('error')
    if err:
        msg = request.args.get('error_description') or err
        if session.get('mailbox_oauth_popup'):
            return mailbox_oauth_popup_error_html(msg)
        flash(translate('settings.mailboxes.oauth_error', error=msg), 'danger')
        return redirect(url_for('settings.my_mailbox_new'))

    code = request.args.get('code')
    state = request.args.get('state')
    try:
        # Legacy-Google-URI: Exchange muss dieselbe Redirect-URI wie Authorize nutzen
        legacy_google_uri = None
        if provider == 'google':
            legacy_google_uri = url_for('settings.mailbox_oauth_callback', provider='google', _external=True)
        result = handle_oauth_callback(provider, code, state, redirect_uri=legacy_google_uri)
    except Exception as e:
        if session.get('mailbox_oauth_popup'):
            return mailbox_oauth_popup_error_html(str(e))
        flash(translate('settings.mailboxes.oauth_error', error=str(e)), 'danger')
        return redirect(url_for('settings.my_mailbox_new'))

    if session.get('mailbox_oauth_popup'):
        return mailbox_oauth_popup_success_html(result)
    flash(translate('settings.mailboxes.oauth_connected'), 'success')
    return redirect(url_for('settings.my_mailbox_new'))


@settings_bp.route('/admin/mailboxes')
@login_required
def admin_mailboxes():
    """Alle Multi-Postfächer (Admin)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    if not _require_email_multi_or_redirect():
        return redirect(url_for('settings.admin_email_module'))

    from app.models.email import Mailbox
    mailboxes = Mailbox.query.order_by(Mailbox.mailbox_type, Mailbox.display_name).all()
    return render_template('settings/admin_mailboxes.html', mailboxes=mailboxes)


@settings_bp.route('/admin/mailboxes/create', methods=['GET', 'POST'])
@login_required
def admin_mailbox_create():
    """Admin legt nur private Postfächer an (Team nur über Teams-Reiter)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    if not _require_email_multi_or_redirect():
        return redirect(url_for('settings.admin_email_module'))

    from app.models.email import Mailbox
    from app.utils.multi_mailboxes import apply_mailbox_credentials
    from app.utils.mailbox_oauth import pop_oauth_result, apply_oauth_tokens_to_mailbox

    users = User.query.filter(
        User.is_active == True,
        User.email != 'anonymous@system.local',
    ).order_by(User.last_name, User.first_name).all()

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip() or 'Postfach'
        mb = Mailbox(
            name=name,
            display_name=name,
            mailbox_type='private',
            owner_id=request.form.get('owner_id', type=int) or current_user.id,
            team_id=None,
            is_active=True,
        )
        apply_mailbox_credentials(mb, request.form)
        oauth = pop_oauth_result()
        if oauth and (request.form.get('auth_type') == 'oauth' or request.form.get('provider') in ('google', 'microsoft')):
            apply_oauth_tokens_to_mailbox(mb, oauth)
        db.session.add(mb)
        db.session.commit()
        flash(translate('settings.mailboxes.flash_created'), 'success')
        return redirect(url_for('settings.admin_mailboxes'))

    return render_template(
        'settings/mailbox_wizard.html',
        **_mailbox_wizard_context(
            mailbox=None,
            mailbox_type='private',
            cancel_url=url_for('settings.admin_mailboxes'),
            show_owner=True,
            users=users,
        ),
    )


@settings_bp.route('/admin/mailboxes/<int:mailbox_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_mailbox_edit(mailbox_id):
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    if not _require_email_multi_or_redirect():
        return redirect(url_for('settings.admin_email_module'))

    from app.models.email import Mailbox
    from app.utils.multi_mailboxes import apply_mailbox_credentials

    mb = Mailbox.query.get_or_404(mailbox_id)
    users = User.query.filter(
        User.is_active == True,
        User.email != 'anonymous@system.local',
    ).order_by(User.last_name, User.first_name).all()

    if request.method == 'POST':
        apply_mailbox_credentials(mb, request.form)
        mb.is_active = request.form.get('is_active') == 'on'
        if mb.mailbox_type == 'private':
            mb.owner_id = request.form.get('owner_id', type=int) or mb.owner_id
            mb.team_id = None
        # Typ bleibt unverändert
        err = _replace_mailbox_logo(mb, request.files.get('logo'))
        if err:
            flash(translate(err), 'danger')
            return render_template(
                'settings/admin_mailbox_form.html',
                mailbox=mb, users=users,
            )
        db.session.commit()
        flash(translate('settings.mailboxes.flash_saved'), 'success')
        return redirect(url_for('settings.admin_mailboxes'))

    return render_template(
        'settings/admin_mailbox_form.html',
        mailbox=mb, users=users,
    )


@settings_bp.route('/admin/mailboxes/<int:mailbox_id>/delete', methods=['POST'])
@login_required
def admin_mailbox_delete(mailbox_id):
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    from app.models.email import Mailbox
    mb = Mailbox.query.get_or_404(mailbox_id)
    from app.utils.multi_mailboxes import delete_mailbox
    delete_mailbox(mb)
    db.session.commit()
    flash(translate('settings.mailboxes.flash_deleted'), 'success')
    return redirect(url_for('settings.admin_mailboxes'))


@settings_bp.route('/my-mailboxes', methods=['GET', 'POST'])
@login_required
def my_mailboxes():
    """Private Postfächer + Logo-Präferenz für Team-Postfächer."""
    from app.models.email import Mailbox
    from app.utils.multi_mailboxes import (
        is_email_multi_enabled,
        can_add_private_mailbox,
        get_max_private_mailboxes,
        count_private_mailboxes,
        get_accessible_mailboxes,
        get_mailbox_use_logo,
        set_mailbox_use_logo,
        user_has_mailbox_access,
    )

    if not is_email_multi_enabled():
        flash(translate('settings.mailboxes.flash_multi_disabled'), 'warning')
        return redirect(url_for('settings.index'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            mid = request.form.get('mailbox_id', type=int)
            mb = Mailbox.query.filter_by(id=mid, owner_id=current_user.id, mailbox_type='private').first_or_404()
            from app.utils.multi_mailboxes import delete_mailbox
            delete_mailbox(mb)
            db.session.commit()
            flash(translate('settings.mailboxes.flash_deleted'), 'success')
            return redirect(url_for('settings.my_mailboxes'))

        if action == 'set_use_logo':
            mid = request.form.get('mailbox_id', type=int)
            mb = Mailbox.query.get_or_404(mid)
            if not user_has_mailbox_access(current_user, mb, 'read'):
                flash(translate('settings.admin.flash_unauthorized'), 'danger')
                return redirect(url_for('settings.my_mailboxes'))
            set_mailbox_use_logo(current_user, mb, request.form.get('use_logo') == 'on')
            db.session.commit()
            flash(translate('settings.mailboxes.flash_logo_pref_saved'), 'success')
            return redirect(url_for('settings.my_mailboxes'))

    private = Mailbox.query.filter_by(
        owner_id=current_user.id, mailbox_type='private'
    ).order_by(Mailbox.display_name).all()
    accessible = get_accessible_mailboxes(current_user)
    team_mailboxes_prefs = [
        {
            'mailbox': mb,
            'use_logo': get_mailbox_use_logo(current_user, mb),
        }
        for mb in accessible
        if mb.mailbox_type == 'team'
    ]
    return render_template(
        'settings/my_mailboxes.html',
        private_mailboxes=private,
        accessible_mailboxes=accessible,
        team_mailboxes_prefs=team_mailboxes_prefs,
        can_add=can_add_private_mailbox(current_user),
        max_private=get_max_private_mailboxes(),
        used_private=count_private_mailboxes(current_user.id),
    )


@settings_bp.route('/my-mailboxes/new', methods=['GET', 'POST'])
@login_required
def my_mailbox_new():
    from app.models.email import Mailbox
    from app.utils.multi_mailboxes import (
        is_email_multi_enabled,
        can_add_private_mailbox,
        get_max_private_mailboxes,
        apply_mailbox_credentials,
    )
    from app.utils.mailbox_oauth import pop_oauth_result, apply_oauth_tokens_to_mailbox

    if not is_email_multi_enabled():
        flash(translate('settings.mailboxes.flash_multi_disabled'), 'warning')
        return redirect(url_for('settings.index'))
    if not can_add_private_mailbox(current_user):
        flash(translate('settings.mailboxes.flash_limit_reached', max=get_max_private_mailboxes()), 'danger')
        return redirect(url_for('settings.my_mailboxes'))

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip() or 'Mein Postfach'
        mb = Mailbox(
            name=name,
            display_name=name,
            mailbox_type='private',
            owner_id=current_user.id,
            is_active=True,
        )
        apply_mailbox_credentials(mb, request.form)
        oauth = pop_oauth_result()
        if oauth and (request.form.get('auth_type') == 'oauth' or request.form.get('provider') in ('google', 'microsoft')):
            apply_oauth_tokens_to_mailbox(mb, oauth)
        elif request.form.get('auth_type') == 'oauth' and request.form.get('provider') in ('google', 'microsoft'):
            flash(translate('settings.mailboxes.oauth_required'), 'danger')
            return render_template(
                'settings/mailbox_wizard.html',
                **_mailbox_wizard_context(
                    mailbox=None,
                    mailbox_type='private',
                    cancel_url=url_for('settings.my_mailboxes'),
                ),
            )
        db.session.add(mb)
        db.session.commit()
        flash(translate('settings.mailboxes.flash_created'), 'success')
        return redirect(url_for('settings.my_mailboxes'))

    return render_template(
        'settings/mailbox_wizard.html',
        **_mailbox_wizard_context(
            mailbox=None,
            mailbox_type='private',
            cancel_url=url_for('settings.my_mailboxes'),
        ),
    )


@settings_bp.route('/my-mailboxes/<int:mailbox_id>/edit', methods=['GET', 'POST'])
@login_required
def my_mailbox_edit(mailbox_id):
    from app.models.email import Mailbox
    from app.utils.multi_mailboxes import is_email_multi_enabled, apply_mailbox_credentials
    from app.utils.mailbox_oauth import pop_oauth_result, apply_oauth_tokens_to_mailbox

    if not is_email_multi_enabled():
        flash(translate('settings.mailboxes.flash_multi_disabled'), 'warning')
        return redirect(url_for('settings.index'))

    mb = Mailbox.query.filter_by(
        id=mailbox_id, owner_id=current_user.id, mailbox_type='private'
    ).first_or_404()

    if request.method == 'POST':
        apply_mailbox_credentials(mb, request.form)
        oauth = pop_oauth_result()
        if oauth and (request.form.get('auth_type') == 'oauth' or request.form.get('provider') in ('google', 'microsoft')):
            apply_oauth_tokens_to_mailbox(mb, oauth)
        mb.is_active = request.form.get('is_active') == 'on'
        db.session.commit()
        flash(translate('settings.mailboxes.flash_saved'), 'success')
        return redirect(url_for('settings.my_mailboxes'))

    return render_template(
        'settings/mailbox_wizard.html',
        **_mailbox_wizard_context(
            mailbox=mb,
            mailbox_type='private',
            cancel_url=url_for('settings.my_mailboxes'),
        ),
    )


@settings_bp.route('/mailbox-logo/<path:filename>')
@login_required
def mailbox_logo(filename):
    from app.utils.multi_mailboxes import mailbox_upload_dir
    from flask import send_from_directory
    return send_from_directory(mailbox_upload_dir(), filename)


@settings_bp.route('/admin/teams/<int:team_id>/mailboxes', methods=['GET', 'POST'])
@login_required
def team_mailboxes(team_id):
    """Team-Postfächer: Admin oder Teamleitung (Liste + Löschen)."""
    from app.models.team import Team
    from app.models.email import Mailbox
    from app.utils.multi_mailboxes import can_manage_team, is_email_multi_enabled

    team = Team.query.get_or_404(team_id)
    if not can_manage_team(current_user, team.id):
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    from app.utils.team_module_settings import is_team_section_enabled
    if not is_team_section_enabled(team.id, 'email'):
        flash(translate('settings.team_settings.flash_email_disabled'), 'warning')
        return redirect(url_for('settings.team_settings', team_id=team.id))
    if not is_email_multi_enabled():
        flash(translate('settings.mailboxes.flash_multi_disabled'), 'warning')
        return redirect(url_for('settings.admin_team_detail', team_id=team.id))

    if request.method == 'POST' and request.form.get('action') == 'delete':
        mid = request.form.get('mailbox_id', type=int)
        mb = Mailbox.query.filter_by(id=mid, team_id=team.id, mailbox_type='team').first_or_404()
        from app.utils.multi_mailboxes import delete_mailbox
        delete_mailbox(mb)
        db.session.commit()
        flash(translate('settings.mailboxes.flash_deleted'), 'success')
        return redirect(url_for('settings.team_mailboxes', team_id=team.id))

    mailboxes = Mailbox.query.filter_by(
        team_id=team.id, mailbox_type='team'
    ).order_by(Mailbox.display_name).all()
    return render_template('settings/team_mailboxes.html', team=team, mailboxes=mailboxes)


@settings_bp.route('/admin/teams/<int:team_id>/mailboxes/new', methods=['GET', 'POST'])
@login_required
def team_mailbox_new(team_id):
    from app.models.team import Team
    from app.models.email import Mailbox
    from app.utils.multi_mailboxes import (
        can_manage_team,
        is_email_multi_enabled,
        apply_mailbox_credentials,
    )
    from app.utils.mailbox_oauth import pop_oauth_result, apply_oauth_tokens_to_mailbox

    team = Team.query.get_or_404(team_id)
    if not can_manage_team(current_user, team.id):
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    if not is_email_multi_enabled():
        flash(translate('settings.mailboxes.flash_multi_disabled'), 'warning')
        return redirect(url_for('settings.admin_team_detail', team_id=team.id))

    wizard_kw = dict(
        mailbox_type='team',
        team_id=team.id,
        cancel_url=url_for('settings.team_mailboxes', team_id=team.id),
        show_logo=True,
    )

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip() or f'{team.name} Postfach'
        mb = Mailbox(
            name=name,
            display_name=name,
            mailbox_type='team',
            team_id=team.id,
            is_active=True,
        )
        apply_mailbox_credentials(mb, request.form)
        oauth = pop_oauth_result()
        if oauth and (request.form.get('auth_type') == 'oauth' or request.form.get('provider') in ('google', 'microsoft')):
            apply_oauth_tokens_to_mailbox(mb, oauth)
        db.session.add(mb)
        db.session.flush()
        err = _replace_mailbox_logo(mb, request.files.get('logo'))
        if err:
            db.session.rollback()
            flash(translate(err), 'danger')
            return render_template(
                'settings/mailbox_wizard.html',
                **_mailbox_wizard_context(mailbox=None, **wizard_kw),
            )
        db.session.commit()
        flash(translate('settings.mailboxes.flash_created'), 'success')
        return redirect(url_for('settings.team_mailboxes', team_id=team.id))

    return render_template(
        'settings/mailbox_wizard.html',
        **_mailbox_wizard_context(mailbox=None, **wizard_kw),
    )


@settings_bp.route('/admin/teams/<int:team_id>/mailboxes/<int:mailbox_id>/edit', methods=['GET', 'POST'])
@login_required
def team_mailbox_edit(team_id, mailbox_id):
    from app.models.team import Team
    from app.models.email import Mailbox
    from app.utils.multi_mailboxes import (
        can_manage_team,
        is_email_multi_enabled,
        apply_mailbox_credentials,
    )
    from app.utils.mailbox_oauth import pop_oauth_result, apply_oauth_tokens_to_mailbox

    team = Team.query.get_or_404(team_id)
    if not can_manage_team(current_user, team.id):
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    if not is_email_multi_enabled():
        flash(translate('settings.mailboxes.flash_multi_disabled'), 'warning')
        return redirect(url_for('settings.admin_team_detail', team_id=team.id))

    mb = Mailbox.query.filter_by(id=mailbox_id, team_id=team.id, mailbox_type='team').first_or_404()
    wizard_kw = dict(
        mailbox_type='team',
        team_id=team.id,
        cancel_url=url_for('settings.team_mailboxes', team_id=team.id),
        show_logo=True,
    )

    if request.method == 'POST':
        apply_mailbox_credentials(mb, request.form)
        oauth = pop_oauth_result()
        if oauth and (request.form.get('auth_type') == 'oauth' or request.form.get('provider') in ('google', 'microsoft')):
            apply_oauth_tokens_to_mailbox(mb, oauth)
        mb.is_active = request.form.get('is_active') == 'on'
        err = _replace_mailbox_logo(mb, request.files.get('logo'))
        if err:
            flash(translate(err), 'danger')
            return render_template(
                'settings/mailbox_wizard.html',
                **_mailbox_wizard_context(mailbox=mb, **wizard_kw),
            )
        db.session.commit()
        flash(translate('settings.mailboxes.flash_saved'), 'success')
        return redirect(url_for('settings.team_mailboxes', team_id=team.id))

    return render_template(
        'settings/mailbox_wizard.html',
        **_mailbox_wizard_context(mailbox=mb, **wizard_kw),
    )
