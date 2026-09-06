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

@settings_bp.route('/admin/music', methods=['GET', 'POST'])
@login_required
def admin_music():
    """Musikmodul-Einstellungen (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    
    from app.models.music import MusicSettings
    
    if request.method == 'POST':
        enabled_providers = []
        available_providers = ['spotify', 'youtube', 'deezer', 'musicbrainz']
        for provider in available_providers:
            if request.form.get(f'provider_enabled_{provider}') == 'on':
                enabled_providers.append(provider)
        MusicSettings.set_enabled_providers(enabled_providers)
        
        provider_order_json = request.form.get('provider_order', '')
        if provider_order_json:
            import json as _json
            try:
                provider_order = _json.loads(provider_order_json)
                provider_order = [p for p in provider_order if p in enabled_providers]
                MusicSettings.set_provider_order(provider_order)
            except Exception:
                pass

        show_provider_badges = request.form.get('show_provider_badges') == 'on'
        MusicSettings.set_show_provider_badges(show_provider_badges)
        
        db.session.commit()
        flash(translate('settings.admin.music.flash_saved'), 'success')
        return _settings_redirect('settings.admin_music')
    
    # GET: Zeige Einstellungsseite
    enabled_providers = MusicSettings.get_enabled_providers()
    provider_order = MusicSettings.get_provider_order()
    show_provider_badges = MusicSettings.get_show_provider_badges()
    
    return render_template('settings/admin_music.html',
                         enabled_providers=enabled_providers,
                         provider_order=provider_order,
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
            'module_chat',
            'module_files',
            'module_calendar',
            'module_events',
            'module_email',
            'module_contacts',
            'module_credentials',
            'module_manuals',
            'module_inventory',
            'module_wiki',
            'module_booking',
            'module_music',
            'module_media_downloader',
            'module_file_converter',
            'module_assessment',
            'module_shortlinks',
            'module_kanban',
            'module_excalidraw',
            'module_surveys',
            'module_protocols',
            'module_meetings',
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
    
    # Liste aller Module
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
    
    from app.utils.access_control import load_default_module_roles, _roles_flag_enabled

    if request.method == 'POST':
        # Sammle Standardrollen-Einstellungen
        default_roles = {
            'full_access': request.form.get('default_full_access') == 'on'
        }
        
        # Modulspezifische Rollen (auch bei Vollzugriff mitspeichern, damit Umschalten Werte behält)
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
    
    # GET: Lade aktuelle Standardrollen (Fallback: Vollzugriff)
    raw_roles = load_default_module_roles()
    default_roles = {
        'full_access': _roles_flag_enabled(raw_roles.get('full_access', True)),
    }
    for module_key, _ in all_modules:
        default_roles[module_key] = _roles_flag_enabled(raw_roles.get(module_key, False))
    
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
    """Create a new booking form (admin only) — opens full editor in one step."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.models.booking import BookingForm

    # Ein Schritt: Entwurf anlegen und direkt in den vollen Editor.
    form = BookingForm(
        title=translate('settings.admin.booking_forms.draft_title'),
        description=None,
        archive_days=30,
        enable_mailbox=False,
        enable_shared_folder=False,
        created_by=current_user.id,
        is_active=True,
    )
    db.session.add(form)
    db.session.commit()
    return redirect(url_for('settings.booking_form_edit', form_id=form.id, new=1))


@settings_bp.route('/admin/booking-forms/<int:form_id>/edit', methods=['GET', 'POST'])
@login_required
def booking_form_edit(form_id):
    """Edit a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.models.booking import BookingForm, BookingFormField

    form = BookingForm.query.get_or_404(form_id)
    is_new = request.args.get('new') == '1'

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        pdf_application_text = request.form.get('pdf_application_text', '').strip()
        pdf_footer_text = request.form.get('pdf_footer_text', '').strip()
        archive_days = int(request.form.get('archive_days', 30) or 30)
        enable_mailbox = request.form.get('enable_mailbox') == 'on'
        enable_shared_folder = request.form.get('enable_shared_folder') == 'on'
        is_active = request.form.get('is_active') == 'on'

        if not title:
            flash(translate('settings.admin.booking_forms.flash_title_required'), 'danger')
            fields = BookingFormField.query.filter_by(form_id=form_id).order_by(BookingFormField.field_order).all()
            return render_template(
                'booking/admin/form_edit.html',
                form=form,
                fields=fields,
                all_users=User.query.filter_by(is_active=True).all(),
                is_new=is_new,
            )

        form.title = title
        form.description = description or None
        form.pdf_application_text = pdf_application_text or None
        form.pdf_footer_text = pdf_footer_text or None
        form.archive_days = archive_days
        form.enable_mailbox = enable_mailbox
        form.enable_shared_folder = enable_shared_folder
        form.is_active = is_active

        db.session.commit()
        flash(translate('settings.admin.booking_forms.flash_form_updated', title=title), 'success')
        return _settings_redirect('settings.booking_forms')

    fields = BookingFormField.query.filter_by(form_id=form_id).order_by(BookingFormField.field_order).all()
    return render_template(
        'booking/admin/form_edit.html',
        form=form,
        fields=fields,
        all_users=User.query.filter_by(is_active=True).all(),
        is_new=is_new,
    )


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
    return _settings_redirect('settings.booking_forms')


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
        flash(translate('settings.admin.booking_forms.flash_field_label_required'), 'danger')
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
    
    flash(translate('settings.admin.booking_forms.flash_field_added', label=field_label), 'success')
    return redirect(url_for('settings.booking_form_edit', form_id=form_id))


@settings_bp.route('/admin/booking-forms/<int:form_id>/fields/<int:field_id>/edit', methods=['POST'])
@login_required
def booking_field_edit(form_id, field_id):
    """Edit a field on a booking form (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.booking_forms.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.models.booking import BookingForm, BookingFormField
    import json
    import re

    BookingForm.query.get_or_404(form_id)
    field = BookingFormField.query.filter_by(id=field_id, form_id=form_id).first_or_404()

    field_type = request.form.get('field_type', '').strip() or field.field_type
    field_label = request.form.get('field_label', '').strip()
    field_name = request.form.get('field_name', '').strip()
    placeholder = request.form.get('placeholder', '').strip()
    is_required = request.form.get('is_required') == 'on'
    field_options = request.form.get('field_options', '').strip()

    if not field_label:
        flash(translate('settings.admin.booking_forms.flash_field_label_required'), 'danger')
        return redirect(url_for('settings.booking_form_edit', form_id=form_id))

    if not field_name:
        field_name = re.sub(r'[^a-zA-Z0-9_]', '_', field_label.lower())
        field_name = re.sub(r'_+', '_', field_name)

    options_json = None
    if field_type in ['select', 'checkbox'] and field_options:
        options = [opt.strip() for opt in field_options.split('\n') if opt.strip()]
        if options:
            options_json = json.dumps(options)

    field.field_type = field_type
    field.field_label = field_label
    field.field_name = field_name
    field.placeholder = placeholder or None
    field.is_required = is_required
    field.field_options = options_json

    db.session.commit()
    flash(translate('settings.admin.booking_forms.flash_field_updated', label=field_label), 'success')
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
    
    flash(translate('settings.admin.booking_forms.flash_field_deleted', label=field_label), 'success')
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
        flash(translate('settings.admin.booking_forms.flash_role_name_required'), 'danger')
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
    
    flash(translate('settings.admin.booking_forms.flash_role_added', name=role_name), 'success')
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
        flash(translate('settings.admin.booking_forms.flash_role_name_required'), 'danger')
        return redirect(url_for('settings.booking_form_edit', form_id=form_id))
    
    role.role_name = role_name
    role.is_required = is_required
    
    db.session.commit()
    
    flash(translate('settings.admin.booking_forms.flash_role_updated'), 'success')
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
    
    flash(translate('settings.admin.booking_forms.flash_role_deleted'), 'success')
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
