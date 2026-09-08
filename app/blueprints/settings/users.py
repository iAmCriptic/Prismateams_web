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

@settings_bp.route('/admin')
@login_required
def admin():
    """Admin settings hub — redirects to Start dashboard (sidebar has all admin links)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    return redirect(url_for('settings.index') + '#admin')


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
        ('module_events', 'Veranstaltungen'),
        ('module_email', 'E-Mail'),
        ('module_contacts', 'Kontakte'),
        ('module_credentials', 'Zugangsdaten'),
        ('module_manuals', 'Anleitungen'),
        ('module_inventory', 'Lagerverwaltung'),
        ('module_wiki', 'Wiki'),
        ('module_booking', 'Buchungen'),
        ('module_music', 'Musik'),
        ('module_media_downloader', 'Media Downloader'),
        ('module_file_converter', 'Dateikonverter'),
        ('module_assessment', 'Bewertung'),
        ('module_shortlinks', 'Kurzlinks'),
        ('module_kanban', 'Kanban'),
        ('module_excalidraw', 'Excalidraw'),
        ('module_surveys', 'Umfragen'),
        ('module_protocols', 'Protokollführung'),
        ('module_meetings', 'Meetings'),
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
    
    # Get all guest accounts.
    # Inaktive Gäste bleiben 7 Tage sichtbar (reaktivierbar), danach verschwinden sie aus der Liste.
    # guest_expires_at mit Portal-Wandzeit vergleichen; Retention an updated_at (UTC).
    now_portal = portal_now_naive()
    guest_retention_cutoff = datetime.utcnow() - timedelta(days=7)
    guest_users = User.query.filter(
        User.is_guest == True
    ).filter(
        or_(
            User.is_active == True,
            User.updated_at >= guest_retention_cutoff
        )
    ).order_by(User.created_at.desc()).all()

    from app.models.guest import GuestShareAccess

    role_map = defaultdict(dict)
    all_role_user_ids = [u.id for u in active_users] + [g.id for g in guest_users]
    if all_role_user_ids:
        for role in UserModuleRole.query.filter(UserModuleRole.user_id.in_(all_role_user_ids)).all():
            role_map[role.user_id][role.module_key] = role.has_access

    users_with_roles = [
        {
            'user': user,
            'has_full_access': user.has_full_access,
            'module_roles': role_map[user.id],
        }
        for user in active_users
    ]

    share_counts = defaultdict(int)
    guest_ids = [g.id for g in guest_users]
    if guest_ids:
        for uid, cnt in (
            db.session.query(GuestShareAccess.user_id, func.count(GuestShareAccess.id))
            .filter(GuestShareAccess.user_id.in_(guest_ids))
            .group_by(GuestShareAccess.user_id)
            .all()
        ):
            share_counts[uid] = int(cnt)

    guest_users_with_roles = [
        {
            'user': guest,
            'module_roles': role_map[guest.id],
            'share_count': share_counts.get(guest.id, 0),
        }
        for guest in guest_users
    ]
    
    now = now_portal

    # Ausstehende E-Mail-Bestätigungscodes (nur aktive Konten — Code startet erst nach Freischaltung)
    pending_code_users = User.query.filter(
        User.is_email_confirmed == False,
        User.is_active == True,
        User.confirmation_code.isnot(None),
        ~User.is_guest,
        User.email != 'anonymous@system.local',
    ).all()
    confirmation_code_users = []
    for user in pending_code_users:
        if user.confirmation_code_expires is None or user.confirmation_code_expires > now:
            confirmation_code_users.append(user)
    confirmation_code_users.sort(key=lambda u: u.created_at or now, reverse=True)

    guest_modules, assignable_shares, all_chats = _guest_account_form_options()
    guest_chats_json = [
        {'id': c.id, 'name': c.name, 'is_main_chat': bool(c.is_main_chat)}
        for c in all_chats
    ]
    from app.utils.guest_accounts import get_guest_email_domain, get_guest_email_suffix
    from app.models.team import Team, TeamMember

    all_teams = Team.query.order_by(Team.name).all()
    user_team_ids = {}
    for membership in TeamMember.query.all():
        user_team_ids.setdefault(membership.user_id, []).append(membership.team_id)

    return render_template('settings/admin_users.html', 
                         active_users=active_users, 
                         pending_users=pending_users,
                         users_with_roles=users_with_roles,
                         guest_users_with_roles=guest_users_with_roles,
                         confirmation_code_users=confirmation_code_users,
                         all_modules=all_modules,
                         guest_modules=guest_modules,
                         assignable_shares=assignable_shares,
                         guest_chats_json=guest_chats_json,
                         guest_email_domain=get_guest_email_domain(),
                         guest_email_suffix=get_guest_email_suffix(),
                         all_teams=all_teams,
                         user_team_ids=user_team_ids,
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
            
            from app.utils.access_control import apply_default_roles_to_user
            apply_default_roles_to_user(new_user)
            
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
            
            # Email-Format: {guest_username}@{konfigurierte Domain}
            from app.utils.guest_accounts import build_guest_email
            email = build_guest_email(guest_username)
            
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
            from app.models.public_share import PublicShare
            for share_token in share_tokens:
                share = PublicShare.query.filter_by(token=share_token, enabled=True).first()
                if share:
                    share_access = GuestShareAccess(
                        user_id=new_user.id,
                        share_token=share_token,
                        share_type=share.resource_type,
                    )
                    db.session.add(share_access)
                    has_file_access = True
                    continue
                file_item = File.query.filter_by(share_token=share_token, share_enabled=True).first()
                folder_item = Folder.query.filter_by(share_token=share_token, share_enabled=True).first()
                if file_item:
                    share_access = GuestShareAccess(
                        user_id=new_user.id,
                        share_token=share_token,
                        share_type='file',
                    )
                    db.session.add(share_access)
                    has_file_access = True
                elif folder_item:
                    share_access = GuestShareAccess(
                        user_id=new_user.id,
                        share_token=share_token,
                        share_type='folder',
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
                'module_events',
                'module_contacts',
                'module_manuals',
                'module_inventory',
                'module_wiki',
                'module_music',
                'module_media_downloader',
                'module_file_converter',
                'module_assessment',
                'module_shortlinks',
                'module_kanban',
                'module_excalidraw',
                'module_surveys',
                'module_meetings',
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
    
    guest_modules, assignable_shares, all_chats = _guest_account_form_options()
    from app.utils.guest_accounts import get_guest_email_domain, get_guest_email_suffix
    return render_template('settings/admin_create_user.html',
                         guest_modules=guest_modules,
                         assignable_shares=assignable_shares,
                         all_chats=all_chats,
                         guest_email_domain=get_guest_email_domain(),
                         guest_email_suffix=get_guest_email_suffix())


@settings_bp.route('/admin/users/guest-credentials/pdf', methods=['POST'])
@login_required
def guest_credentials_pdf():
    """PDF mit Gast-Zugangsdaten, QR und Login-Link (Admin only)."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': translate('settings.admin.flash_unauthorized')}), 403

    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    full_name = (data.get('full_name') or '').strip()
    if not username or not password:
        return jsonify({'success': False, 'message': translate('settings.admin.create_user.guest_credentials_missing')}), 400

    from app.utils.pdf_generator import generate_guest_credentials_pdf
    from io import BytesIO

    login_url = url_for('auth.login', _external=True)
    pdf_buf = generate_guest_credentials_pdf(
        full_name=full_name,
        username=username,
        password=password,
        login_url=login_url,
    )
    if isinstance(pdf_buf, BytesIO):
        pdf_buf.seek(0)
    return send_file(
        pdf_buf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='gast-zugangsdaten.pdf',
    )


@settings_bp.route('/admin/users/guest-credentials/email', methods=['POST'])
@login_required
def guest_credentials_email():
    """Sendet Gast-Zugangsdaten manuell an eine Empfänger-Adresse (Admin only)."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': translate('settings.admin.flash_unauthorized')}), 403

    data = request.get_json(silent=True) or {}
    recipient = (data.get('recipient') or '').strip().lower()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    full_name = (data.get('full_name') or '').strip()

    if not recipient or '@' not in recipient or '.' not in recipient.split('@')[-1]:
        return jsonify({'success': False, 'message': translate('settings.admin.create_user.guest_email_invalid')}), 400
    if not username or not password:
        return jsonify({'success': False, 'message': translate('settings.admin.create_user.guest_credentials_missing')}), 400

    from app.utils.email_sender import send_guest_credentials_email
    ok = send_guest_credentials_email(
        recipient=recipient,
        full_name=full_name,
        username=username,
        password=password,
    )
    if not ok:
        return jsonify({'success': False, 'message': translate('settings.admin.create_user.guest_email_failed')}), 500
    return jsonify({
        'success': True,
        'message': translate('settings.admin.create_user.guest_email_sent', email=recipient),
    })


@settings_bp.route('/admin/users/<int:user_id>/activate', methods=['POST'])
@login_required
def activate_user(user_id):
    """Activate a user (admin only)."""
    if not current_user.is_admin:
        return redirect(url_for('settings.index'))
    
    user = User.query.get_or_404(user_id)
    user.is_active = True

    # Fehlende Standardrollen nachziehen (z.B. nach fehlgeschlagener Zuweisung bei Registrierung)
    from app.utils.access_control import apply_default_roles_to_user, user_lacks_module_access
    if not user.is_guest and user_lacks_module_access(user):
        apply_default_roles_to_user(user)
    
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

    # Bestätigungscode erst nach Freischaltung — Gültigkeit (1 Tag) startet jetzt
    confirmation_sent = False
    if (
        not user.is_guest
        and not user.is_email_confirmed
        and user.email
        and user.email != 'anonymous@system.local'
    ):
        from app.utils.email_sender import send_confirmation_email
        confirmation_sent = send_confirmation_email(user)

    if confirmation_sent:
        flash(translate('settings.admin.users.flash_user_activated_email', name=user.full_name), 'success')
    else:
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
    
    # Gäste können mit demselben Button reaktiviert werden.
    if user.is_guest and not user.is_active:
        user.is_active = True
        db.session.commit()
        flash(translate('settings.admin.users.flash_user_activated', name=user.full_name), 'success')
        return redirect(url_for('settings.admin_users'))

    user.is_active = False
    db.session.commit()
    try:
        from app.utils.session_manager import revoke_all_sessions
        revoke_all_sessions(user.id, exclude_current=False)
        db.session.commit()
    except Exception:
        pass

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
    """Edit a guest account (admin only). JSON/AJAX für Modal; HTML-GET → Benutzerliste."""
    if not current_user.is_admin:
        if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': translate('settings.admin.users.flash_unauthorized')}), 403
        return redirect(url_for('settings.index'))

    user = User.query.get_or_404(user_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json'

    if not user.is_guest:
        msg = translate('settings.admin.users.flash_guest_not_guest')
        if is_ajax:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'danger')
        return redirect(url_for('settings.admin_users'))

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()

        if not first_name or not last_name:
            msg = translate('settings.admin.users.flash_guest_name_required')
            if is_ajax:
                return jsonify({'success': False, 'error': msg}), 400
            flash(msg, 'danger')
            return redirect(url_for('settings.admin_users'))

        user.first_name = first_name
        user.last_name = last_name

        guest_expires_at_str = request.form.get('guest_expires_at', '').strip()
        if guest_expires_at_str:
            try:
                user.guest_expires_at = datetime.fromisoformat(guest_expires_at_str.replace('T', ' '))
            except Exception:
                msg = translate('settings.admin.users.flash_guest_invalid_expiry')
                if is_ajax:
                    return jsonify({'success': False, 'error': msg}), 400
                flash(msg, 'danger')
                return redirect(url_for('settings.admin_users'))
        else:
            user.guest_expires_at = None

        from app.models.role import UserModuleRole
        from app.utils.common import is_module_enabled
        from app.models.guest import GuestShareAccess
        from app.models.file import File, Folder
        from app.models.public_share import PublicShare

        allowed_modules = [
            'module_calendar',
            'module_events',
            'module_contacts',
            'module_manuals',
            'module_inventory',
            'module_wiki',
            'module_music',
            'module_media_downloader',
            'module_file_converter',
            'module_assessment',
            'module_shortlinks',
            'module_kanban',
            'module_excalidraw',
            'module_surveys',
            'module_meetings',
        ]

        existing_roles = UserModuleRole.query.filter_by(user_id=user.id).all()
        for role in existing_roles:
            if role.module_key in ['module_chat', 'module_files']:
                if role.module_key == 'module_chat':
                    has_chat = ChatMember.query.filter_by(user_id=user.id).first() is not None
                    if not has_chat:
                        db.session.delete(role)
                elif role.module_key == 'module_files':
                    has_file_access = GuestShareAccess.query.filter_by(user_id=user.id).first() is not None
                    if not has_file_access:
                        db.session.delete(role)
            elif role.module_key in allowed_modules:
                db.session.delete(role)

        selected_modules = request.form.getlist('allowed_modules')
        for module_key in selected_modules:
            if module_key in allowed_modules and is_module_enabled(module_key):
                db.session.add(UserModuleRole(
                    user_id=user.id,
                    module_key=module_key,
                    has_access=True,
                ))

        ChatMember.query.filter_by(user_id=user.id).delete()
        chat_ids = request.form.getlist('chat_ids')
        has_chat_access = False
        for chat_id_str in chat_ids:
            try:
                chat_id = int(chat_id_str)
                chat = Chat.query.get(chat_id)
                if chat:
                    db.session.add(ChatMember(chat_id=chat_id, user_id=user.id))
                    has_chat_access = True
            except (ValueError, TypeError):
                pass

        chat_role = UserModuleRole.query.filter_by(user_id=user.id, module_key='module_chat').first()
        if has_chat_access and is_module_enabled('module_chat'):
            if not chat_role:
                db.session.add(UserModuleRole(user_id=user.id, module_key='module_chat', has_access=True))
        elif chat_role:
            db.session.delete(chat_role)

        GuestShareAccess.query.filter_by(user_id=user.id).delete()
        share_tokens = request.form.getlist('share_tokens')
        has_file_access = False
        for share_token in share_tokens:
            share = PublicShare.query.filter_by(token=share_token, enabled=True).first()
            if share:
                db.session.add(GuestShareAccess(
                    user_id=user.id,
                    share_token=share_token,
                    share_type=share.resource_type,
                ))
                has_file_access = True
                continue
            file_item = File.query.filter_by(share_token=share_token, share_enabled=True).first()
            folder_item = Folder.query.filter_by(share_token=share_token, share_enabled=True).first()
            if file_item:
                db.session.add(GuestShareAccess(user_id=user.id, share_token=share_token, share_type='file'))
                has_file_access = True
            elif folder_item:
                db.session.add(GuestShareAccess(user_id=user.id, share_token=share_token, share_type='folder'))
                has_file_access = True

        file_role = UserModuleRole.query.filter_by(user_id=user.id, module_key='module_files').first()
        if has_file_access and is_module_enabled('module_files'):
            if not file_role:
                db.session.add(UserModuleRole(user_id=user.id, module_key='module_files', has_access=True))
        elif file_role:
            db.session.delete(file_role)

        db.session.commit()
        msg = translate('settings.admin.users.flash_guest_updated', name=user.full_name)
        if is_ajax:
            return jsonify({'success': True, 'message': msg})
        flash(msg, 'success')
        return redirect(url_for('settings.admin_users'))

    # GET
    from app.models.role import UserModuleRole
    from app.models.guest import GuestShareAccess

    current_modules = [role.module_key for role in UserModuleRole.query.filter_by(user_id=user.id).all()]
    current_chat_ids = [member.chat_id for member in ChatMember.query.filter_by(user_id=user.id).all()]
    current_share_tokens = [access.share_token for access in GuestShareAccess.query.filter_by(user_id=user.id).all()]

    if request.args.get('format') == 'json':
        expires = ''
        if user.guest_expires_at:
            expires = user.guest_expires_at.strftime('%Y-%m-%dT%H:%M')
        return jsonify({
            'success': True,
            'id': user.id,
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
            'full_name': user.full_name,
            'email': user.email or '',
            'guest_username': user.guest_username or '',
            'guest_expires_at': expires,
            'current_modules': current_modules,
            'current_chat_ids': current_chat_ids,
            'current_share_tokens': current_share_tokens,
        })

    return redirect(url_for('settings.admin_users'))


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

    from app.utils.account_deletion import erase_user_account
    name = user.full_name
    erase_user_account(user)
    db.session.commit()
    
    flash(translate('settings.admin.users.flash_user_deleted', name=name), 'success')
    return redirect(url_for('settings.admin_users'))
