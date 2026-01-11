from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_user
from app import db
from app.models.user import User
from app.models.email import EmailPermission
from app.models.chat import Chat, ChatMember
from app.models.settings import SystemSettings
from app.models.whitelist import WhitelistEntry
from app.utils.backup import import_backup, SUPPORTED_CATEGORIES
from app.utils.i18n import translate, available_languages
from datetime import datetime
import logging
import os
import tempfile

setup_bp = Blueprint('setup', __name__)


def is_setup_needed():
    """Prüft ob das Setup noch durchgeführt werden muss."""
    return User.query.count() == 0


def get_color_gradient():
    """Holt den Farbverlauf aus den System-Einstellungen."""
    try:
        # SystemSettings ist bereits global importiert
        gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
        return gradient_setting.value if gradient_setting else None
    except Exception:
        # Fallback auf Session-Daten bei Fehlern
        return session.get('setup_color_gradient')


@setup_bp.route('/setup')
def setup():
    """Setup-Seite für die Ersteinrichtung."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/index.html', color_gradient=current_gradient)


@setup_bp.route('/setup/import-backup', methods=['GET', 'POST'])
def setup_import_backup():
    """Backup-Import im Setup-Prozess (Schritt 0)."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    # Hole aktuellen Farbverlauf für Template
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'skip':
            # Backup-Import überspringen
            return redirect(url_for('setup.setup_step1'))
        
        elif action == 'import':
            # Backup importieren
            if 'backup_file' not in request.files:
                flash(translate('setup.flash.select_backup_file'), 'danger')
                return render_template('setup/import_backup.html', categories=SUPPORTED_CATEGORIES, color_gradient=current_gradient)
            
            file = request.files['backup_file']
            if file.filename == '':
                flash(translate('setup.flash.select_backup_file'), 'danger')
                return render_template('setup/import_backup.html', categories=SUPPORTED_CATEGORIES, color_gradient=current_gradient)
            
            if not file.filename.endswith('.prismateams'):
                flash(translate('setup.flash.invalid_file_extension'), 'danger')
                return render_template('setup/import_backup.html', categories=SUPPORTED_CATEGORIES, color_gradient=current_gradient)
            
            try:
                # Temporäre Datei speichern
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.prismateams', mode='wb')
                file.save(temp_file.name)
                temp_path = temp_file.name
                temp_file.close()
                
                # Kategorien auswählen (alle wenn nicht angegeben)
                import_categories = request.form.getlist('import_categories')
                if not import_categories:
                    # Wenn keine Kategorien ausgewählt, importiere alle verfügbaren
                    import_categories = ['all']
                
                # Backup importieren (im Setup gibt es noch keinen current_user, daher None)
                result = import_backup(temp_path, import_categories, None)
                
                # Temporäre Datei löschen
                os.unlink(temp_path)
                
                if result['success']:
                    imported = ', '.join(result.get('imported', []))
                    flash(f'Backup erfolgreich importiert! Importierte Kategorien: {imported}', 'success')
                    # Weiter zum nächsten Schritt
                    return redirect(url_for('setup.setup_step1'))
                else:
                    flash(f'Fehler beim Importieren des Backups: {result.get("error", "Unbekannter Fehler")}', 'danger')
            except Exception as e:
                current_app.logger.error(f"Fehler beim Import im Setup: {str(e)}")
                flash(f'Fehler beim Importieren des Backups: {str(e)}', 'danger')
                if 'temp_path' in locals():
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
    
    return render_template('setup/import_backup.html', categories=SUPPORTED_CATEGORIES, color_gradient=current_gradient)


@setup_bp.route('/setup/complete', methods=['GET', 'POST'])
def setup_complete():
    """Komplettes Setup in einem Schritt."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        # Alle Formulardaten abrufen
        portal_name = request.form.get('portal_name', '').strip()
        default_accent_color = request.form.get('default_accent_color', '#0d6efd').strip()
        color_gradient = request.form.get('color_gradient', '').strip()
        default_language = request.form.get('default_language', 'de').strip()
        
        # Handle portal logo upload
        portal_logo_filename = None
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
                        return render_template('setup/complete.html')
                    
                    # Create filename with timestamp
                    from werkzeug.utils import secure_filename
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"portal_logo_{timestamp}_{filename}"
                    
                    # Ensure upload directory exists
                    from flask import current_app
                    import os
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    # Save file
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    portal_logo_filename = filename
                else:
                    flash(translate('setup.flash.invalid_file_type'), 'danger')
                    return render_template('setup/complete.html')
        
        # Whitelist-Einträge
        whitelist_emails = []
        for i in range(1, 6):
            email = request.form.get(f'whitelist_email_{i}', '').strip().lower()
            if email:
                whitelist_emails.append(email)
        
        # Administrator-Daten
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        dark_mode = request.form.get('dark_mode') == 'on'
        
        # Validierung
        if not all([portal_name, email, password, first_name, last_name]):
            flash(translate('setup.flash.fill_all_fields'), 'danger')
            return render_template('setup/complete.html')
        
        if password != password_confirm:
            flash(translate('setup.flash.passwords_dont_match'), 'danger')
            return render_template('setup/complete.html')
        
        if len(password) < 8:
            flash(translate('setup.flash.password_too_short'), 'danger')
            return render_template('setup/complete.html')
        
        try:
            logging.info("Starting complete setup")
            
            # Get values from session (set in step1) or form
            portal_name = session.get('setup_portal_name', portal_name if 'portal_name' in locals() else '')
            portal_logo_filename = session.get('setup_portal_logo', portal_logo_filename if 'portal_logo_filename' in locals() else None)
            default_accent_color = session.get('setup_default_accent_color', '#0d6efd')
            color_gradient = session.get('setup_color_gradient', None)
            default_language = session.get('setup_default_language', 'de')
            
            # Ersten Administrator erstellen
            admin_user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_active=True,
                is_admin=True,
                is_super_admin=True,  # Erster Admin ist Hauptadministrator
                dark_mode=dark_mode,
                accent_color=default_accent_color
            )
            admin_user.set_password(password)
            
            db.session.add(admin_user)
            db.session.commit()
            logging.info(f"Admin user created with ID: {admin_user.id}")
            
            # E-Mail-Berechtigungen für Admin erstellen
            email_perm = EmailPermission.query.filter_by(user_id=admin_user.id).first()
            if not email_perm:
                email_perm = EmailPermission(
                    user_id=admin_user.id,
                    can_read=True,
                    can_send=True
                )
                db.session.add(email_perm)
                logging.info("EmailPermission created for admin")
            else:
                # Falls bereits vorhanden, Berechtigungen aktualisieren
                email_perm.can_read = True
                email_perm.can_send = True
                logging.info("EmailPermission updated for admin")
            
            # Haupt-Chat erstellen
            main_chat = Chat(
                name="Haupt-Chat",
                is_main_chat=True,
                created_by=admin_user.id
            )
            db.session.add(main_chat)
            db.session.flush()
            
            # Admin zum Haupt-Chat hinzufügen
            chat_member = ChatMember(
                chat_id=main_chat.id,
                user_id=admin_user.id
            )
            db.session.add(chat_member)
            
            # System-Einstellungen erstellen
            if portal_name:
                portal_name_setting = SystemSettings(
                    key='portal_name',
                    value=portal_name,
                    description='Name des Portals'
                )
                db.session.add(portal_name_setting)
                logging.info(f"Portal name setting created: {portal_name}")
            
            # Portal logo speichern
            if portal_logo_filename:
                logo_setting = SystemSettings(
                    key='portal_logo',
                    value=portal_logo_filename,
                    description='Portalslogo'
                )
                db.session.add(logo_setting)
                logging.info(f"Portal logo setting created: {portal_logo_filename}")
            
            # Default-Akzentfarbe speichern
            accent_color_setting = SystemSettings(
                key='default_accent_color',
                value=default_accent_color,
                description='Standard-Akzentfarbe für neue Benutzer'
            )
            db.session.add(accent_color_setting)
            logging.info(f"Default accent color setting created: {default_accent_color}")
            
            # Standardsprache speichern
            default_language = session.get('setup_default_language', 'de')
            language_setting = SystemSettings(
                key='default_language',
                value=default_language,
                description='Standardsprache der Benutzeroberfläche für neue Benutzer.'
            )
            db.session.add(language_setting)
            logging.info(f"Default language setting created: {default_language}")
            
            # Farbverlauf speichern
            if color_gradient:
                gradient_setting = SystemSettings(
                    key='color_gradient',
                    value=color_gradient,
                    description='Farbverlauf für Login/Register-Seiten'
                )
                db.session.add(gradient_setting)
                logging.info("Color gradient setting created")
            
            # Whitelist-Einträge hinzufügen
            for email_addr in whitelist_emails:
                whitelist_entry = WhitelistEntry(
                    email=email_addr,
                    added_by=admin_user.id,
                    reason="Hinzugefügt beim Setup"
                )
                db.session.add(whitelist_entry)
            
            # Admin-E-Mail zur Whitelist hinzufügen
            admin_whitelist_entry = WhitelistEntry(
                email=email,
                added_by=admin_user.id,
                reason="Automatisch hinzugefügt beim Setup"
            )
            db.session.add(admin_whitelist_entry)
            
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
                module_setting = SystemSettings(
                    key=module_key,
                    value=str(enabled),
                    description=f'Modul {module_key} aktiviert'
                )
                db.session.add(module_setting)
                logging.info(f"Module setting created: {module_key}={enabled}")
            
            db.session.commit()
            logging.info("All data committed successfully")
            
            # Admin automatisch einloggen
            login_user(admin_user)
            logging.info("Admin user logged in")
            
            flash(translate('setup.flash.completed'), 'success')
            return redirect(url_for('dashboard.index'))
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error during setup: {str(e)}")
            flash(f'Fehler beim Setup: {str(e)}', 'danger')
            return render_template('setup/complete.html')
    # Verfügbare Sprachen und deren Namen
    language_names = {
        'de': 'Deutsch',
        'en': 'English',
        'pt': 'Português',
        'es': 'Español',
        'ru': 'Русский'
    }
    available_langs = list(available_languages())
    languages = [(lang, language_names.get(lang, lang.upper())) for lang in available_langs]
    current_language = session.get('setup_default_language', 'de')
    
    return render_template('setup/complete.html', languages=languages, current_language=current_language)


@setup_bp.route('/setup/step1', methods=['GET', 'POST'])
def setup_step1():
    """Schritt 1: Organisationsname und Farbverlauf."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        portal_name = request.form.get('portal_name', '').strip()
        default_accent_color = request.form.get('default_accent_color', '#0d6efd').strip()
        color_gradient = request.form.get('color_gradient', '').strip()
        
        if not portal_name:
            flash(translate('setup.flash.enter_portal_name'), 'danger')
            return render_template('setup/step1.html')
        
        # Handle portal logo upload
        portal_logo_filename = None
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
                        return render_template('setup/step1.html')
                    
                    # Create filename with timestamp
                    from werkzeug.utils import secure_filename
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"portal_logo_{timestamp}_{filename}"
                    
                    # Ensure upload directory exists
                    from flask import current_app
                    import os
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    # Save file
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    portal_logo_filename = filename
                else:
                    flash(translate('setup.flash.invalid_file_type'), 'danger')
                    return render_template('setup/step1.html')
        
        # Standardsprache lesen
        default_language = request.form.get('default_language', 'de').strip()
        
        # Speichere in Session für später
        session['setup_portal_name'] = portal_name
        session['setup_portal_logo'] = portal_logo_filename
        session['setup_default_accent_color'] = default_accent_color
        session['setup_color_gradient'] = color_gradient
        session['setup_default_language'] = default_language
        
        # Speichere direkt in die Datenbank, damit die Werte sofort verfügbar sind
        try:
            
            # Portal name speichern/aktualisieren
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            if portal_name_setting:
                portal_name_setting.value = portal_name
            else:
                portal_name_setting = SystemSettings(
                    key='portal_name',
                    value=portal_name,
                    description='Name des Portals'
                )
                db.session.add(portal_name_setting)
            logging.info(f"Portal name saved to database: {portal_name}")
            
            # Portal logo speichern/aktualisieren
            if portal_logo_filename:
                portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
                if portal_logo_setting:
                    # Altes Logo löschen wenn vorhanden
                    old_logo = portal_logo_setting.value
                    if old_logo and old_logo != portal_logo_filename:
                        try:
                            from flask import current_app
                            import os
                            project_root = os.path.dirname(current_app.root_path)
                            upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system')
                            old_path = os.path.join(upload_dir, old_logo)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except:
                            pass
                    portal_logo_setting.value = portal_logo_filename
                else:
                    portal_logo_setting = SystemSettings(
                        key='portal_logo',
                        value=portal_logo_filename,
                        description='Portalslogo'
                    )
                    db.session.add(portal_logo_setting)
                logging.info(f"Portal logo saved to database: {portal_logo_filename}")
            
            # Default accent color speichern/aktualisieren
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
            logging.info(f"Default accent color saved to database: {default_accent_color}")
            
            # Color gradient speichern/aktualisieren
            if color_gradient:
                gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
                if gradient_setting:
                    gradient_setting.value = color_gradient
                else:
                    gradient_setting = SystemSettings(
                        key='color_gradient',
                        value=color_gradient,
                        description='Farbverlauf für Login/Register-Seiten'
                    )
                    db.session.add(gradient_setting)
                logging.info("Color gradient saved to database")
            else:
                # Wenn kein Farbverlauf gesetzt, entferne vorhandenen
                gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
                if gradient_setting:
                    db.session.delete(gradient_setting)
            
            db.session.commit()
            logging.info("System settings committed to database in step 1")
        except Exception as e:
            logging.error(f"Error saving system settings in step 1: {e}")
            db.session.rollback()
        
        return redirect(url_for('setup.setup_step2'))
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/step1.html', color_gradient=current_gradient)


@setup_bp.route('/setup/step2', methods=['GET', 'POST'])
def setup_step2():
    """Schritt 2: Einstellungen und Whitelist."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    if 'setup_portal_name' not in session:
        return redirect(url_for('setup.setup_step1'))
    
    if request.method == 'POST':
        # Whitelist-Einträge verarbeiten
        whitelist_entries = []
        for i in range(1, 6):  # Bis zu 5 Einträge
            entry = request.form.get(f'whitelist_entry_{i}', '').strip().lower()
            entry_type = request.form.get(f'whitelist_type_{i}', 'email')
            if entry:
                whitelist_entries.append({
                    'entry': entry,
                    'type': entry_type
                })
        
        # Speichere in Session
        session['setup_whitelist_entries'] = whitelist_entries
        
        # Standardrollen verarbeiten
        all_modules = [
            'module_chat', 'module_files', 'module_calendar', 'module_email',
            'module_credentials', 'module_manuals', 'module_inventory',
            'module_wiki', 'module_booking', 'module_music'
        ]
        
        default_roles = {
            'full_access': request.form.get('default_full_access') == 'on'
        }
        
        # Modulspezifische Rollen
        for module_key in all_modules:
            default_roles[module_key] = request.form.get(f'default_{module_key}') == 'on'
        
        # Speichere in Session
        session['setup_default_roles'] = default_roles
        
        return redirect(url_for('setup.setup_step3'))
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/step2.html', color_gradient=current_gradient)


@setup_bp.route('/setup/step3', methods=['GET', 'POST'])
def setup_step3():
    """Schritt 3: Module aktivieren."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    if 'setup_portal_name' not in session:
        return redirect(url_for('setup.setup_step1'))
    
    if request.method == 'POST':
        # Module-Einstellungen in Session speichern
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
        
        session['setup_modules'] = modules
        return redirect(url_for('setup.setup_step4'))
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/step3.html', color_gradient=current_gradient)


@setup_bp.route('/setup/step4', methods=['GET', 'POST'])
def setup_step4():
    """Schritt 4: Administrator-Account erstellen."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    if 'setup_portal_name' not in session:
        return redirect(url_for('setup.setup_step1'))
    
    if request.method == 'POST':
        # Formulardaten abrufen
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        dark_mode = request.form.get('dark_mode') == 'on'
        
        # Validierung
        if not all([email, password, first_name, last_name]):
            flash(translate('setup.flash.fill_all_fields'), 'danger')
            return render_template('setup/step3.html')
        
        if password != password_confirm:
            flash(translate('setup.flash.passwords_dont_match'), 'danger')
            return render_template('setup/step3.html')
        
        if len(password) < 8:
            flash(translate('setup.flash.password_too_short'), 'danger')
            return render_template('setup/step3.html')
        
        try:
            logging.info(f"Creating admin user with email: {email}")
            # Get default accent color from session
            default_accent_color = session.get('setup_default_accent_color', '#0d6efd')
            
            # Ersten Administrator erstellen
            admin_user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_active=True,
                is_admin=True,
                is_super_admin=True,  # Erster Admin ist Hauptadministrator
                is_email_confirmed=True,  # Admin ist automatisch bestätigt
                dark_mode=dark_mode,
                accent_color=default_accent_color
            )
            admin_user.set_password(password)
            
            db.session.add(admin_user)
            db.session.commit()
            logging.info(f"Admin user created successfully with ID: {admin_user.id}")
            
            # E-Mail-Berechtigungen für Admin erstellen
            logging.info(f"Creating email permissions for admin user {admin_user.id}")
            email_perm = admin_user.ensure_email_permissions()
            logging.info(f"Email permissions created for admin user - can_read: {email_perm.can_read}, can_send: {email_perm.can_send}")
            
            # Haupt-Chat erstellen
            main_chat = Chat(
                name="Haupt-Chat",
                is_main_chat=True,
                created_by=admin_user.id
            )
            db.session.add(main_chat)
            db.session.flush()  # Um die ID zu erhalten
            
            # Admin zum Haupt-Chat hinzufügen
            chat_member = ChatMember(
                chat_id=main_chat.id,
                user_id=admin_user.id
            )
            db.session.add(chat_member)
            
            # System-Einstellungen erstellen oder aktualisieren
            logging.info("Creating/updating system settings")
            portal_name = session.get('setup_portal_name', '')
            portal_logo_filename = session.get('setup_portal_logo', None)
            
            if portal_name:
                portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
                if portal_name_setting:
                    portal_name_setting.value = portal_name
                    logging.info(f"Portal name setting updated: {portal_name}")
                else:
                    portal_name_setting = SystemSettings(
                        key='portal_name',
                        value=portal_name,
                        description='Name des Portals'
                    )
                    db.session.add(portal_name_setting)
                    logging.info(f"Portal name setting created: {portal_name}")
            else:
                logging.warning("Portal name is empty, skipping creation")
            
            # Portal logo speichern
            if portal_logo_filename:
                logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
                if logo_setting:
                    logo_setting.value = portal_logo_filename
                    logging.info(f"Portal logo setting updated: {portal_logo_filename}")
                else:
                    logo_setting = SystemSettings(
                        key='portal_logo',
                        value=portal_logo_filename,
                        description='Portalslogo'
                    )
                    db.session.add(logo_setting)
                    logging.info(f"Portal logo setting created: {portal_logo_filename}")
            else:
                logging.info("No portal logo provided, skipping logo creation")
            
            # Default-Akzentfarbe speichern
            default_accent_color = session.get('setup_default_accent_color', '#0d6efd')
            accent_color_setting = SystemSettings.query.filter_by(key='default_accent_color').first()
            if accent_color_setting:
                accent_color_setting.value = default_accent_color
                logging.info("Default accent color setting updated")
            else:
                accent_color_setting = SystemSettings(
                    key='default_accent_color',
                    value=default_accent_color,
                    description='Standard-Akzentfarbe für neue Benutzer'
                )
                db.session.add(accent_color_setting)
                logging.info("Default accent color setting created")
            
            # Farbverlauf speichern
            if session.get('setup_color_gradient'):
                logging.info("Creating/updating color gradient setting")
                gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
                if gradient_setting:
                    gradient_setting.value = session.get('setup_color_gradient', '')
                    logging.info("Color gradient setting updated")
                else:
                    gradient_setting = SystemSettings(
                        key='color_gradient',
                        value=session.get('setup_color_gradient', ''),
                        description='Farbverlauf für Login/Register-Seiten'
                    )
                    db.session.add(gradient_setting)
                    logging.info("Color gradient setting created")
            
            # Standardsprache speichern
            default_language = session.get('setup_default_language', 'de')
            language_setting = SystemSettings.query.filter_by(key='default_language').first()
            if language_setting:
                language_setting.value = default_language
                logging.info(f"Default language setting updated: {default_language}")
            else:
                language_setting = SystemSettings(
                    key='default_language',
                    value=default_language,
                    description='Standardsprache der Benutzeroberfläche für neue Benutzer.'
                )
                db.session.add(language_setting)
                logging.info(f"Default language setting created: {default_language}")
            
            # Whitelist-Einträge hinzufügen
            whitelist_entries = session.get('setup_whitelist_entries', [])
            for entry_data in whitelist_entries:
                entry = entry_data['entry']
                entry_type = entry_data['type']
                
                # Domain-Format korrigieren
                if entry_type == 'domain' and not entry.startswith('@'):
                    entry = '@' + entry
                
                whitelist_entry = WhitelistEntry(
                    entry=entry,
                    entry_type=entry_type,
                    description="Hinzugefügt beim Setup",
                    created_by=admin_user.id
                )
                db.session.add(whitelist_entry)
            
            # Admin-E-Mail zur Whitelist hinzufügen
            admin_whitelist_entry = WhitelistEntry(
                entry=email,
                entry_type='email',
                description="Automatisch hinzugefügt beim Setup",
                created_by=admin_user.id
            )
            db.session.add(admin_whitelist_entry)
            
            # Standardrollen speichern (aus Session)
            import json
            default_roles = session.get('setup_default_roles', {})
            if default_roles:
                default_roles_setting = SystemSettings(
                    key='default_module_roles',
                    value=json.dumps(default_roles),
                    description='Standardrollen für neue Benutzer'
                )
                db.session.add(default_roles_setting)
                logging.info("Default module roles setting created")
            
            # Module-Einstellungen speichern (aus Session)
            modules = session.get('setup_modules', {
                'module_chat': True,
                'module_files': True,
                'module_calendar': True,
                'module_email': True,
                'module_credentials': True,
                'module_manuals': True,
                'module_inventory': True,
                'module_wiki': True,
                'module_booking': True,
                'module_music': True
            })
            
            for module_key, enabled in modules.items():
                module_setting = SystemSettings(
                    key=module_key,
                    value=str(enabled),
                    description=f'Modul {module_key} aktiviert'
                )
                db.session.add(module_setting)
                logging.info(f"Module setting created: {module_key}={enabled}")
            
            logging.info("Committing all changes to database")
            db.session.commit()
            logging.info("Database commit successful")
            
            # Überprüfe E-Mail-Berechtigungen für Admin
            admin_email_perm = EmailPermission.query.filter_by(user_id=admin_user.id).first()
            if admin_email_perm:
                logging.info(f"Admin email permissions verified - can_read: {admin_email_perm.can_read}, can_send: {admin_email_perm.can_send}")
            else:
                logging.error("Admin email permissions not found!")
                # E-Mail-Berechtigungen erneut erstellen falls sie fehlen
                email_perm = EmailPermission(
                    user_id=admin_user.id,
                    can_read=True,
                    can_send=True
                )
                db.session.add(email_perm)
                db.session.commit()
                logging.info("Admin email permissions recreated")
            
            # Session-Daten löschen
            session.pop('setup_portal_name', None)
            session.pop('setup_portal_logo', None)
            session.pop('setup_default_accent_color', None)
            session.pop('setup_color_gradient', None)
            session.pop('setup_whitelist_entries', None)
            session.pop('setup_modules', None)
            logging.info("Session data cleared")
            
            # Admin automatisch einloggen
            logging.info("Logging in admin user")
            login_user(admin_user)
            logging.info("Admin user logged in successfully")
            
            # Setup-Abschluss-Markierung für Dashboard
            session['setup_completed'] = True
            
            # Erfolgreiche Setup-Abschluss-Meldung
            flash(translate('setup.flash.completed_emoji'), 'success')
            flash(translate('setup.flash.add_users_info'), 'info')
            flash(translate('setup.flash.admin_account_created'), 'info')
            logging.info("Redirecting to dashboard")
            return redirect(url_for('dashboard.index'))
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error during setup: {str(e)}", exc_info=True)
            flash(f'Fehler beim Setup: {str(e)}', 'danger')
            # Verwende Session-Daten statt Datenbank-Abfrage nach Rollback
            current_gradient = session.get('setup_color_gradient')
            return render_template('setup/step4.html', color_gradient=current_gradient)
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/step4.html', color_gradient=current_gradient)


@setup_bp.route('/setup/check')
def setup_check():
    """API-Endpoint um zu prüfen ob Setup nötig ist."""
    return {'setup_needed': is_setup_needed()}
