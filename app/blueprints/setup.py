from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, current_user, login_required
from app import db
from app.models.user import User
from app.models.chat import Chat, ChatMember
from app.models.settings import SystemSettings
from app.models.whitelist import WhitelistEntry
from app.utils.backup import import_backup, SUPPORTED_CATEGORIES, CATEGORY_DEFINITIONS
from app.utils.common import AVAILABLE_MODULES
from app.utils.i18n import translate, available_languages
from datetime import datetime
import json
import logging
import os
import tempfile

setup_bp = Blueprint('setup', __name__)

SETUP_COMPLETED_KEY = 'setup_completed'

MODULE_META = [
    {'key': 'module_chat', 'icon': 'bi-chat-dots', 'label': 'Chat', 'settings_endpoint': None},
    {'key': 'module_files', 'icon': 'bi-folder', 'label': 'Dateien', 'settings_endpoint': 'settings.admin_file_settings'},
    {'key': 'module_calendar', 'icon': 'bi-calendar-event', 'label': 'Kalender', 'settings_endpoint': 'settings.admin_calendar_settings'},
    {'key': 'module_events', 'icon': 'bi-calendar2-week', 'label': 'Veranstaltungen', 'settings_endpoint': None},
    {'key': 'module_email', 'icon': 'bi-envelope', 'label': 'E-Mail', 'settings_endpoint': 'settings.admin_email_module'},
    {'key': 'module_contacts', 'icon': 'bi-person-lines-fill', 'label': 'Kontakte', 'settings_endpoint': None},
    {'key': 'module_credentials', 'icon': 'bi-key', 'label': 'Zugangsdaten', 'settings_endpoint': None},
    {'key': 'module_manuals', 'icon': 'bi-book', 'label': 'Anleitungen', 'settings_endpoint': None},
    {'key': 'module_inventory', 'icon': 'bi-box-seam', 'label': 'Lagerverwaltung', 'settings_endpoint': 'settings.admin_inventory_settings'},
    {'key': 'module_wiki', 'icon': 'bi-journal-text', 'label': 'Wiki', 'settings_endpoint': None},
    {'key': 'module_booking', 'icon': 'bi-calendar-check', 'label': 'Buchungen', 'settings_endpoint': 'settings.booking_forms'},
    {'key': 'module_music', 'icon': 'bi-music-note-beamed', 'label': 'Musik', 'settings_endpoint': 'settings.admin_music'},
    {'key': 'module_media_downloader', 'icon': 'bi-download', 'label': 'Media Downloader', 'settings_endpoint': None},
    {'key': 'module_file_converter', 'icon': 'bi-arrow-left-right', 'label': 'Dateikonverter', 'settings_endpoint': None},
    {'key': 'module_assessment', 'icon': 'bi-clipboard-check', 'label': 'Bewertungen', 'settings_endpoint': 'assessment.admin_settings.admin_settings_page'},
    {'key': 'module_shortlinks', 'icon': 'bi-link-45deg', 'label': 'Kurzlinks', 'settings_endpoint': None},
    {'key': 'module_kanban', 'icon': 'bi-kanban', 'label': 'Kanban', 'settings_endpoint': 'settings.admin_kanban_settings'},
    {'key': 'module_excalidraw', 'icon': 'bi-pencil-square', 'label': 'Excalidraw', 'settings_endpoint': None},
    {'key': 'module_surveys', 'icon': 'bi-ui-checks-grid', 'label': 'Umfragen', 'settings_endpoint': None},
]

LANGUAGE_NAMES = {
    'de': 'Deutsch',
    'en': 'English',
    'pt': 'Português',
    'es': 'Español',
    'ru': 'Русский',
}


def mark_setup_completed():
    """Markiert das Portal-Setup als abgeschlossen."""
    from app.utils.bot_protection import upsert_setting
    upsert_setting(SETUP_COMPLETED_KEY, 'true', 'Portal-Setup abgeschlossen')
    db.session.commit()


def mark_setup_incomplete():
    """Markiert Setup als laufend (Flag vorhanden, aber nicht abgeschlossen)."""
    from app.utils.bot_protection import upsert_setting
    upsert_setting(SETUP_COMPLETED_KEY, 'false', 'Portal-Setup abgeschlossen')


def ensure_setup_flag_started(commit=True):
    """Setzt setup_completed=false sobald der Wizard läuft.

    Muss VOR dem ersten Admin-User greifen. Sonst sieht bei Multi-Worker
    (Gunicorn) ein anderer Worker kurz „User vorhanden, kein Flag“ und
    markiert Setup fälschlich als abgeschlossen → Redirect zum Login.
    """
    setting = SystemSettings.query.filter_by(key=SETUP_COMPLETED_KEY).first()
    if setting is not None:
        return setting
    mark_setup_incomplete()
    if commit:
        db.session.commit()
    return SystemSettings.query.filter_by(key=SETUP_COMPLETED_KEY).first()


def is_setup_needed():
    """Prüft ob das Setup noch durchgeführt werden muss.

    Neue Logik: SystemSettings.setup_completed.
    Legacy: vorhandene User ohne Flag gelten als abgeschlossen (einmalig nachziehen).
    Während des Wizards muss das Flag bereits auf false stehen (vor Admin-Anlage).
    """
    try:
        setting = SystemSettings.query.filter_by(key=SETUP_COMPLETED_KEY).first()
        if setting is not None:
            return str(setting.value).lower() not in ('true', '1', 'yes')

        user_count = User.query.count()
        if user_count > 0:
            # Race-Schutz: während Setup-Routen niemals als fertig markieren.
            # Anderer Worker kann User schon sehen, Flag aber noch nicht.
            try:
                endpoint = getattr(request, 'endpoint', None) or ''
            except RuntimeError:
                endpoint = ''
            if str(endpoint).startswith('setup.'):
                return True

            # Nochmal lesen – paralleler Worker kann Flag inzwischen gesetzt haben
            setting = SystemSettings.query.filter_by(key=SETUP_COMPLETED_KEY).first()
            if setting is not None:
                return str(setting.value).lower() not in ('true', '1', 'yes')

            # Bestehende Installation ohne Flag → als erledigt behandeln
            try:
                mark_setup_completed()
            except Exception:
                logging.exception('Could not persist legacy setup_completed flag')
            return False

        return True
    except Exception:
        logging.exception('is_setup_needed failed')
        try:
            return User.query.count() == 0
        except Exception:
            return True


def _has_portal_org():
    if session.get('setup_portal_name'):
        return True
    row = SystemSettings.query.filter_by(key='portal_name').first()
    return bool(row and row.value)


def _has_admin_user():
    return User.query.count() > 0


def _setup_unlocked_steps():
    """Welche Steps per Icon erreichbar sind (1–4). Bis Abschluss alle erreichten Steps editierbar."""
    unlocked = {1}
    if _has_portal_org():
        unlocked.add(2)
    if _has_admin_user():
        unlocked.update({1, 2, 3, 4})
    elif session.get('setup_reg_completed'):
        unlocked.add(4)
    return unlocked


def _default_roles_dict():
    roles = {'full_access': True}
    for key in AVAILABLE_MODULES:
        roles[key] = True
    return roles


def _apply_setup_gradient_style(gradient):
    """CSS-Wert für Setup-Hintergrund (leerer Wert = Standard-Gradient)."""
    return gradient or 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'


def _require_setup():
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    return None


def _require_step_access(step_num):
    """Redirect falls Step noch gesperrt."""
    blocked = _require_setup()
    if blocked:
        return blocked
    if step_num not in _setup_unlocked_steps():
        if step_num >= 3 and not _has_admin_user():
            return redirect(url_for('setup.setup_step2'))
        if step_num >= 2 and not _has_portal_org():
            return redirect(url_for('setup.setup_step1'))
        return redirect(url_for('setup.setup_step1'))
    if step_num >= 3 and _has_admin_user() and not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=url_for(f'setup.setup_step{step_num}')))
    return None


def _current_gradient():
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    if gradient_setting and gradient_setting.value:
        return gradient_setting.value
    return session.get('setup_color_gradient') or ''


def _languages_context():
    available_langs = list(available_languages())
    languages = [(lang, LANGUAGE_NAMES.get(lang, lang.upper())) for lang in available_langs]
    current_language = session.get('setup_default_language', 'de')
    return languages, current_language


def _setup_template_kwargs(step, **extra):
    languages, current_language = _languages_context()
    gradient = _current_gradient()
    return {
        'color_gradient': gradient,
        'setup_bg': _apply_setup_gradient_style(gradient),
        'setup_step': step,
        'setup_unlocked': sorted(_setup_unlocked_steps()),
        'languages': languages,
        'current_language': current_language,
        **extra,
    }



def get_color_gradient():
    """Holt den Farbverlauf aus den System-Einstellungen."""
    try:
        gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
        return gradient_setting.value if gradient_setting else None
    except Exception:
        return session.get('setup_color_gradient')


def _default_modules_dict():
    return {key: True for key in AVAILABLE_MODULES}


@setup_bp.route('/setup')
def setup():
    """Setup-Seite für die Ersteinrichtung."""
    blocked = _require_setup()
    if blocked:
        return blocked

    # Flag früh setzen, bevor Admin-User existiert (Multi-Worker-sicher)
    ensure_setup_flag_started()

    # Expliziter Step-Parameter: freie Navigation bis Abschluss
    step = request.args.get('step', type=int)
    if step in (1, 2, 3, 4) and step in _setup_unlocked_steps():
        return redirect(url_for(f'setup.setup_step{step}'))

    if _has_admin_user() and current_user.is_authenticated:
        if session.get('setup_reg_completed'):
            return redirect(url_for('setup.setup_step4'))
        return redirect(url_for('setup.setup_step3'))
    if _has_portal_org():
        return redirect(url_for('setup.setup_step2'))
    if request.args.get('welcome'):
        return render_template('setup/index.html', **_setup_template_kwargs(1))
    return redirect(url_for('setup.setup_step1'))


@setup_bp.route('/setup/import-backup', methods=['GET', 'POST'])
def setup_import_backup():
    """Backup-Import im Setup-Prozess (Schritt 0)."""
    blocked = _require_setup()
    if blocked:
        return blocked

    ensure_setup_flag_started()

    current_gradient = _current_gradient()
    backup_ctx = {
        'categories': SUPPORTED_CATEGORIES,
        'category_definitions': CATEGORY_DEFINITIONS,
        'color_gradient': current_gradient,
    }

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'skip':
            return redirect(url_for('setup.setup_step1'))

        if action == 'import':
            if 'backup_file' not in request.files:
                flash(translate('setup.flash.select_backup_file'), 'danger')
                return render_template('setup/import_backup.html', **backup_ctx)

            file = request.files['backup_file']
            if file.filename == '':
                flash(translate('setup.flash.select_backup_file'), 'danger')
                return render_template('setup/import_backup.html', **backup_ctx)

            if not file.filename.endswith('.prismateams'):
                flash(translate('setup.flash.invalid_file_extension'), 'danger')
                return render_template('setup/import_backup.html', **backup_ctx)

            try:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.prismateams', mode='wb')
                file.save(temp_file.name)
                temp_path = temp_file.name
                temp_file.close()

                import_categories = request.form.getlist('import_categories')
                if not import_categories:
                    import_categories = ['all']

                result = import_backup(temp_path, import_categories, None)
                os.unlink(temp_path)

                if result['success']:
                    imported = ', '.join(result.get('imported', []))
                    flash(f'Backup erfolgreich importiert! Importierte Kategorien: {imported}', 'success')
                    return redirect(url_for('setup.setup_step1'))
                flash(f'Fehler beim Importieren des Backups: {result.get("error", "Unbekannter Fehler")}', 'danger')
            except Exception as e:
                current_app.logger.error(f"Fehler beim Import im Setup: {str(e)}")
                flash(f'Fehler beim Importieren des Backups: {str(e)}', 'danger')
                if 'temp_path' in locals():
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass

    return render_template('setup/import_backup.html', **backup_ctx)


@setup_bp.route('/setup/complete', methods=['GET', 'POST'])
def setup_complete():
    """Komplettes Setup in einem Schritt (Legacy)."""
    blocked = _require_setup()
    if blocked:
        return blocked
    return redirect(url_for('setup.setup_step1'))


@setup_bp.route('/setup/step1', methods=['GET', 'POST'])
def setup_step1():
    """Schritt 1: Organisation."""
    blocked = _require_step_access(1)
    if blocked:
        return blocked

    ensure_setup_flag_started()

    if request.method == 'POST':
        portal_name = request.form.get('portal_name', '').strip()
        default_accent_color = request.form.get('default_accent_color', '#0d6efd').strip()
        color_gradient = request.form.get('color_gradient', '').strip()
        default_language = request.form.get('default_language', 'de').strip()

        if not portal_name:
            flash(translate('setup.flash.enter_portal_name'), 'danger')
            return render_template('setup/step1.html', **_setup_template_kwargs(1))

        portal_logo_filename = session.get('setup_portal_logo')
        if 'portal_logo' in request.files:
            file = request.files['portal_logo']
            if file and file.filename:
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    file.seek(0, 2)
                    file_size = file.tell()
                    file.seek(0)
                    max_size = 5 * 1024 * 1024
                    if file_size > max_size:
                        flash(f'Logo ist zu groß. Maximale Größe: 5MB. Ihre Datei: {file_size / (1024*1024):.1f}MB', 'danger')
                        return render_template('setup/step1.html', **_setup_template_kwargs(1))

                    from werkzeug.utils import secure_filename
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"portal_logo_{timestamp}_{filename}"
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                    os.makedirs(upload_dir, exist_ok=True)
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    portal_logo_filename = filename
                else:
                    flash(translate('setup.flash.invalid_file_type'), 'danger')
                    return render_template('setup/step1.html', **_setup_template_kwargs(1))

        session['setup_portal_name'] = portal_name
        session['setup_portal_logo'] = portal_logo_filename
        session['setup_default_accent_color'] = default_accent_color
        session['setup_color_gradient'] = color_gradient or 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
        session['setup_default_language'] = default_language

        try:
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            if portal_name_setting:
                portal_name_setting.value = portal_name
            else:
                db.session.add(SystemSettings(key='portal_name', value=portal_name, description='Name des Portals'))

            if portal_logo_filename:
                portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
                if portal_logo_setting:
                    old_logo = portal_logo_setting.value
                    if old_logo and old_logo != portal_logo_filename:
                        try:
                            project_root = os.path.dirname(current_app.root_path)
                            upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                            old_path = os.path.join(upload_dir, old_logo)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except Exception:
                            pass
                    portal_logo_setting.value = portal_logo_filename
                else:
                    db.session.add(SystemSettings(key='portal_logo', value=portal_logo_filename, description='Portalslogo'))

            accent_color_setting = SystemSettings.query.filter_by(key='default_accent_color').first()
            if accent_color_setting:
                accent_color_setting.value = default_accent_color
            else:
                db.session.add(SystemSettings(
                    key='default_accent_color',
                    value=default_accent_color,
                    description='Standard-Akzentfarbe für neue Benutzer',
                ))

            language_setting = SystemSettings.query.filter_by(key='default_language').first()
            if language_setting:
                language_setting.value = default_language
            else:
                db.session.add(SystemSettings(
                    key='default_language',
                    value=default_language,
                    description='Standardsprache der Benutzeroberfläche für neue Benutzer.',
                ))

            # Immer konkreten CSS-Wert speichern, damit Setup-Hintergrund auf allen Steps stimmt
            gradient_value = color_gradient or 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
            session['setup_color_gradient'] = gradient_value
            gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
            if gradient_setting:
                gradient_setting.value = gradient_value
            else:
                db.session.add(SystemSettings(
                    key='color_gradient',
                    value=gradient_value,
                    description='Farbverlauf für Login/Register-Seiten',
                ))

            db.session.commit()
        except Exception as e:
            logging.error(f"Error saving system settings in step 1: {e}")
            db.session.rollback()

        return redirect(url_for('setup.setup_step2'))

    portal_name = session.get('setup_portal_name', '')
    if not portal_name:
        row = SystemSettings.query.filter_by(key='portal_name').first()
        portal_name = row.value if row else ''
    default_accent = session.get('setup_default_accent_color')
    if not default_accent:
        row = SystemSettings.query.filter_by(key='default_accent_color').first()
        default_accent = row.value if row else '#0d6efd'
    selected_gradient = session.get('setup_color_gradient')
    if selected_gradient is None:
        row = SystemSettings.query.filter_by(key='color_gradient').first()
        selected_gradient = row.value if row else ''

    return render_template(
        'setup/step1.html',
        **_setup_template_kwargs(
            1,
            portal_name=portal_name,
            default_accent_color=default_accent,
            selected_gradient=selected_gradient or '',
        ),
    )


@setup_bp.route('/setup/step2', methods=['GET', 'POST'])
def setup_step2():
    """Schritt 2: Administrator-Account anlegen oder bearbeiten."""
    blocked = _require_step_access(2)
    if blocked:
        return blocked

    ensure_setup_flag_started()

    existing_admin = User.query.filter_by(is_super_admin=True).order_by(User.id.asc()).first()
    if not existing_admin:
        existing_admin = User.query.filter_by(is_admin=True).order_by(User.id.asc()).first()

    if existing_admin and not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=url_for('setup.setup_step2')))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        dark_mode = request.form.get('dark_mode') == 'on'
        editing = existing_admin is not None

        if not all([email, first_name, last_name]):
            flash(translate('setup.flash.fill_all_fields'), 'danger')
            return render_template(
                'setup/step2.html',
                **_setup_template_kwargs(2, admin_user=existing_admin, editing=editing),
            )

        if not editing and not password:
            flash(translate('setup.flash.fill_all_fields'), 'danger')
            return render_template('setup/step2.html', **_setup_template_kwargs(2, editing=False))

        if password or password_confirm:
            if password != password_confirm:
                flash(translate('setup.flash.passwords_dont_match'), 'danger')
                return render_template(
                    'setup/step2.html',
                    **_setup_template_kwargs(2, admin_user=existing_admin, editing=editing),
                )
            from app.utils.password_policy import validate_password
            is_valid, _ = validate_password(password, min_length=8, require_complexity=False)
            if not is_valid:
                flash(translate('setup.flash.password_too_short'), 'danger')
                return render_template(
                    'setup/step2.html',
                    **_setup_template_kwargs(2, admin_user=existing_admin, editing=editing),
                )

        try:
            default_accent_color = session.get('setup_default_accent_color', '#0d6efd')
            if editing:
                admin_user = existing_admin
                old_email = (admin_user.email or '').lower()
                admin_user.email = email
                admin_user.first_name = first_name
                admin_user.last_name = last_name
                admin_user.phone = phone
                admin_user.dark_mode = dark_mode
                if password:
                    admin_user.set_password(password)
                if old_email != email:
                    old_wl = WhitelistEntry.query.filter_by(entry=old_email).first()
                    if old_wl:
                        existing_new = WhitelistEntry.query.filter_by(entry=email).first()
                        if existing_new:
                            db.session.delete(old_wl)
                        else:
                            old_wl.entry = email
                    elif not WhitelistEntry.query.filter_by(entry=email).first():
                        db.session.add(WhitelistEntry(
                            entry=email,
                            entry_type='email',
                            description='Automatisch hinzugefügt beim Setup',
                            created_by=admin_user.id,
                        ))
                db.session.commit()
                session['setup_admin_email'] = email
                return redirect(url_for('setup.setup_step3'))

            # Flag ZUERST (vor sichtbarem User) – sonst Multi-Worker-Race:
            # anderer Worker sieht User ohne Flag → mark_setup_completed() → Login.
            mark_setup_incomplete()

            admin_user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_active=True,
                is_admin=True,
                is_super_admin=True,
                is_email_confirmed=True,
                dark_mode=dark_mode,
                accent_color=default_accent_color,
            )
            admin_user.set_password(password)
            db.session.add(admin_user)
            db.session.flush()

            # Kein ensure_email_permissions(): das commitet früh und öffnet die Race erneut.
            from app.models.email import EmailPermission
            if not EmailPermission.query.filter_by(user_id=admin_user.id).first():
                db.session.add(EmailPermission(
                    user_id=admin_user.id,
                    can_read=True,
                    can_send=True,
                ))

            main_chat = Chat.query.filter_by(is_main_chat=True).order_by(Chat.id.asc()).first()
            if not main_chat:
                main_chat = Chat(name='Haupt-Chat', is_main_chat=True, created_by=admin_user.id)
                db.session.add(main_chat)
                db.session.flush()
            elif (main_chat.name or '').strip().lower() in {'team chat', 'team-chat', ''}:
                main_chat.name = 'Haupt-Chat'
                if not main_chat.created_by:
                    main_chat.created_by = admin_user.id

            chat_member = ChatMember.query.filter_by(chat_id=main_chat.id, user_id=admin_user.id).first()
            if not chat_member:
                db.session.add(ChatMember(chat_id=main_chat.id, user_id=admin_user.id))

            if not WhitelistEntry.query.filter_by(entry=email).first():
                db.session.add(WhitelistEntry(
                    entry=email,
                    entry_type='email',
                    description='Automatisch hinzugefügt beim Setup',
                    created_by=admin_user.id,
                ))

            # Ein Commit: setup_completed=false + Admin + Nebenobjekte
            db.session.commit()
            # Wie beim normalen Login: Flask-Login + Portal-Session (session_id).
            # Ohne create_session wirft ensure_portal_session_tracking den User
            # beim Redirect auf Step 3 sofort wieder zum Login.
            from app.utils.session_manager import create_session
            login_user(admin_user)
            session['user_scope'] = 'portal'
            create_session(admin_user.id)
            session['setup_in_progress'] = True
            session['setup_admin_email'] = email
            return redirect(url_for('setup.setup_step3'))
        except Exception as e:
            db.session.rollback()
            logging.error(f'Error in setup step2: {e}', exc_info=True)
            flash(f'Fehler beim Setup: {str(e)}', 'danger')
            return render_template(
                'setup/step2.html',
                **_setup_template_kwargs(2, admin_user=existing_admin, editing=editing),
            )

    return render_template(
        'setup/step2.html',
        **_setup_template_kwargs(2, admin_user=existing_admin, editing=bool(existing_admin)),
    )


@setup_bp.route('/setup/step3', methods=['GET', 'POST'])
@login_required
def setup_step3():
    """Schritt 3: Registrierung, Whitelist, Standardrollen, Bot-Schutz."""
    blocked = _require_step_access(3)
    if blocked:
        return blocked

    if request.method == 'POST':
        whitelist_entries = []
        for i in range(1, 6):
            entry = request.form.get(f'whitelist_entry_{i}', '').strip().lower()
            entry_type = request.form.get(f'whitelist_type_{i}', 'email')
            if entry:
                whitelist_entries.append({'entry': entry, 'type': entry_type})

        session['setup_whitelist_entries'] = whitelist_entries

        default_roles = {'full_access': request.form.get('default_full_access') == 'on'}
        for module_key in AVAILABLE_MODULES:
            default_roles[module_key] = request.form.get(f'default_{module_key}') == 'on'
        session['setup_default_roles'] = default_roles

        from app.utils.bot_protection import VALID_PROVIDERS, VALID_RECAPTCHA_VERSIONS, apply_bot_protection_settings, upsert_setting

        bot_provider = request.form.get('portal_bot_protection', 'none').strip()
        if bot_provider not in VALID_PROVIDERS:
            bot_provider = 'none'
        recaptcha_version = request.form.get('portal_recaptcha_version', 'v2').strip()
        if recaptcha_version not in VALID_RECAPTCHA_VERSIONS:
            recaptcha_version = 'v2'

        bot_data = {
            'provider': bot_provider,
            'register_enabled': request.form.get('portal_bot_protection_register') == 'on',
            'login_enabled': request.form.get('portal_bot_protection_login') == 'on',
            'mailbox_enabled': request.form.get('portal_bot_protection_mailbox') == 'on',
            'share_edit_enabled': request.form.get('portal_bot_protection_share_edit') == 'on',
            'recaptcha_version': recaptcha_version,
            'recaptcha_site_key': request.form.get('portal_recaptcha_site_key', '').strip(),
            'recaptcha_secret_key': request.form.get('portal_recaptcha_secret_key', '').strip(),
            'turnstile_site_key': request.form.get('portal_turnstile_site_key', '').strip(),
            'turnstile_secret_key': request.form.get('portal_turnstile_secret_key', '').strip(),
        }
        session['setup_bot_protection'] = bot_data

        try:
            admin_id = current_user.id
            for entry_data in whitelist_entries:
                entry = entry_data['entry']
                entry_type = entry_data['type']
                if entry_type == 'domain' and not entry.startswith('@'):
                    entry = '@' + entry
                if not WhitelistEntry.query.filter_by(entry=entry).first():
                    db.session.add(WhitelistEntry(
                        entry=entry,
                        entry_type=entry_type,
                        description='Hinzugefügt beim Setup',
                        created_by=admin_id,
                    ))

            upsert_setting('default_module_roles', json.dumps(default_roles), 'Standardrollen für neue Benutzer')
            apply_bot_protection_settings(bot_data)
            db.session.commit()
            session['setup_reg_completed'] = True
        except Exception as e:
            db.session.rollback()
            logging.error(f'Error saving setup step3: {e}', exc_info=True)
            flash(f'Fehler beim Speichern: {str(e)}', 'danger')
            return render_template(
                'setup/step3.html',
                **_setup_template_kwargs(
                    3,
                    setup_bot=bot_data,
                    setup_modules=AVAILABLE_MODULES,
                    module_meta=MODULE_META,
                    default_roles=default_roles,
                ),
            )

        return redirect(url_for('setup.setup_step4'))

    setup_bot = session.get('setup_bot_protection', {})
    default_roles = session.get('setup_default_roles') or _default_roles_dict()
    return render_template(
        'setup/step3.html',
        **_setup_template_kwargs(
            3,
            setup_bot=setup_bot,
            setup_modules=AVAILABLE_MODULES,
            module_meta=MODULE_META,
            default_roles=default_roles,
            whitelist_entries=session.get('setup_whitelist_entries', []),
        ),
    )


@setup_bp.route('/setup/step4', methods=['GET', 'POST'])
@login_required
def setup_step4():
    """Schritt 4: Module aktivieren + Setup abschließen."""
    blocked = _require_step_access(4)
    if blocked:
        return blocked

    if request.method == 'POST':
        modules = {}
        for key in AVAILABLE_MODULES:
            modules[key] = request.form.get(key) == 'on'
        session['setup_modules'] = modules

        try:
            from app.utils.bot_protection import upsert_setting

            for module_key, enabled in modules.items():
                upsert_setting(module_key, str(enabled), f'Modul {module_key} aktiviert')

            mark_setup_completed()

            for key in (
                'setup_portal_name', 'setup_portal_logo', 'setup_default_accent_color',
                'setup_color_gradient', 'setup_whitelist_entries', 'setup_modules',
                'setup_bot_protection', 'setup_default_roles', 'setup_in_progress',
                'setup_reg_completed', 'setup_admin_email', 'setup_default_language',
            ):
                session.pop(key, None)

            flash(translate('setup.flash.completed_summary'), 'success')
            return redirect(url_for('dashboard.index'))
        except Exception as e:
            db.session.rollback()
            logging.error(f'Error finishing setup step4: {e}', exc_info=True)
            flash(f'Fehler beim Setup: {str(e)}', 'danger')

    saved = session.get('setup_modules') or _default_modules_dict()
    modules_for_ui = []
    for meta in MODULE_META:
        if meta['key'] not in AVAILABLE_MODULES:
            continue
        item = dict(meta)
        item['enabled'] = saved.get(meta['key'], True)
        item['settings_url'] = None
        if meta.get('settings_endpoint'):
            try:
                item['settings_url'] = url_for(meta['settings_endpoint'], embed=1)
            except Exception:
                item['settings_url'] = None
        modules_for_ui.append(item)

    return render_template(
        'setup/step4.html',
        **_setup_template_kwargs(4, modules=modules_for_ui),
    )


@setup_bp.route('/setup/check')
def setup_check():
    """API-Endpoint um zu prüfen ob Setup nötig ist."""
    return {'setup_needed': is_setup_needed()}
