from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user
from app import db
from app.models.user import User
from app.models.email import EmailPermission
from app.models.chat import Chat, ChatMember
from app.models.settings import SystemSettings
from app.models.whitelist import WhitelistEntry
from datetime import datetime
import logging

setup_bp = Blueprint('setup', __name__)


def is_setup_needed():
    """Prüft ob das Setup noch durchgeführt werden muss."""
    return User.query.count() == 0


def get_color_gradient():
    """Holt den Farbverlauf aus den System-Einstellungen."""
    from app.models.settings import SystemSettings
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    return gradient_setting.value if gradient_setting else None


@setup_bp.route('/setup')
def setup():
    """Setup-Seite für die Ersteinrichtung."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    from app.models.settings import SystemSettings
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/index.html', color_gradient=current_gradient)


@setup_bp.route('/setup/complete', methods=['GET', 'POST'])
def setup_complete():
    """Komplettes Setup in einem Schritt."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        # Alle Formulardaten abrufen
        organization_name = request.form.get('organization_name', '').strip()
        color_gradient = request.form.get('color_gradient', '').strip()
        
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
        if not all([organization_name, email, password, first_name, last_name]):
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('setup/complete.html')
        
        if password != password_confirm:
            flash('Die Passwörter stimmen nicht überein.', 'danger')
            return render_template('setup/complete.html')
        
        if len(password) < 8:
            flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'danger')
            return render_template('setup/complete.html')
        
        try:
            logging.info("Starting complete setup")
            
            # Ersten Administrator erstellen
            admin_user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_active=True,
                is_admin=True,
                dark_mode=dark_mode
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
                description="Der Haupt-Chat für alle Teammitglieder",
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
            system_settings = SystemSettings(
                key='organization_name',
                value=organization_name,
                description='Name der Organisation'
            )
            db.session.add(system_settings)
            
            # Farbverlauf speichern
            if color_gradient:
                gradient_setting = SystemSettings(
                    key='color_gradient',
                    value=color_gradient,
                    description='Farbverlauf für Login/Register-Seiten'
                )
                db.session.add(gradient_setting)
            
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
            
            db.session.commit()
            logging.info("All data committed successfully")
            
            # Admin automatisch einloggen
            login_user(admin_user)
            logging.info("Admin user logged in")
            
            flash('Setup erfolgreich abgeschlossen! Willkommen in Ihrem Team-Portal.', 'success')
            return redirect(url_for('dashboard.index'))
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error during setup: {str(e)}")
            flash(f'Fehler beim Setup: {str(e)}', 'danger')
            return render_template('setup/complete.html')
    
    return render_template('setup/complete.html')


@setup_bp.route('/setup/step1', methods=['GET', 'POST'])
def setup_step1():
    """Schritt 1: Organisationsname und Farbverlauf."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        organization_name = request.form.get('organization_name', '').strip()
        color_gradient = request.form.get('color_gradient', '').strip()
        
        if not organization_name:
            flash('Bitte geben Sie einen Organisationsnamen ein.', 'danger')
            return render_template('setup/step1.html')
        
        # Speichere in Session für später
        session['setup_organization_name'] = organization_name
        session['setup_color_gradient'] = color_gradient
        
        # Debug: Session-Daten prüfen
        
        return redirect(url_for('setup.setup_step2'))
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    from app.models.settings import SystemSettings
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/step1.html', color_gradient=current_gradient)


@setup_bp.route('/setup/step2', methods=['GET', 'POST'])
def setup_step2():
    """Schritt 2: Einstellungen und Whitelist."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    if 'setup_organization_name' not in session:
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
        
        # Debug: Session-Daten prüfen
        
        return redirect(url_for('setup.setup_step3'))
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    from app.models.settings import SystemSettings
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/step2.html', color_gradient=current_gradient)


@setup_bp.route('/setup/step3', methods=['GET', 'POST'])
def setup_step3():
    """Schritt 3: Administrator-Account erstellen."""
    if not is_setup_needed():
        return redirect(url_for('auth.login'))
    
    # Debug: Session-Daten prüfen
    
    if 'setup_organization_name' not in session:
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
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('setup/step3.html')
        
        if password != password_confirm:
            flash('Die Passwörter stimmen nicht überein.', 'danger')
            return render_template('setup/step3.html')
        
        if len(password) < 8:
            flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'danger')
            return render_template('setup/step3.html')
        
        try:
            logging.info(f"Creating admin user with email: {email}")
            # Ersten Administrator erstellen
            admin_user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_active=True,
                is_admin=True,
                is_email_confirmed=True,  # Admin ist automatisch bestätigt
                dark_mode=dark_mode
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
                description="Der Haupt-Chat für alle Teammitglieder",
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
            
            # System-Einstellungen erstellen
            logging.info("Creating system settings")
            system_settings = SystemSettings(
                key='organization_name',
                value=session.get('setup_organization_name', ''),
                description='Name der Organisation'
            )
            db.session.add(system_settings)
            logging.info("Organization name setting created")
            
            # Farbverlauf speichern
            if session.get('setup_color_gradient'):
                logging.info("Creating color gradient setting")
                gradient_setting = SystemSettings(
                    key='color_gradient',
                    value=session.get('setup_color_gradient', ''),
                    description='Farbverlauf für Login/Register-Seiten'
                )
                db.session.add(gradient_setting)
                logging.info("Color gradient setting created")
            
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
            session.pop('setup_organization_name', None)
            session.pop('setup_color_gradient', None)
            session.pop('setup_whitelist_entries', None)
            logging.info("Session data cleared")
            
            # Admin automatisch einloggen
            logging.info("Logging in admin user")
            login_user(admin_user)
            logging.info("Admin user logged in successfully")
            
            # Setup-Abschluss-Markierung für Dashboard
            session['setup_completed'] = True
            
            # Erfolgreiche Setup-Abschluss-Meldung
            flash('🎉 Setup erfolgreich abgeschlossen! Willkommen in Ihrem Team-Portal.', 'success')
            flash('Sie können jetzt weitere Benutzer über die Einstellungen hinzufügen.', 'info')
            flash('Ihr Administrator-Account wurde erstellt und Sie sind automatisch eingeloggt.', 'info')
            logging.info("Redirecting to dashboard")
            return redirect(url_for('dashboard.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Setup: {str(e)}', 'danger')
            return render_template('setup/step3.html', color_gradient=get_color_gradient())
    
    # Hole aktuellen Farbverlauf aus den System-Einstellungen oder Session
    from app.models.settings import SystemSettings
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    current_gradient = gradient_setting.value if gradient_setting else session.get('setup_color_gradient')
    
    return render_template('setup/step3.html', color_gradient=current_gradient)


@setup_bp.route('/setup/check')
def setup_check():
    """API-Endpoint um zu prüfen ob Setup nötig ist."""
    return {'setup_needed': is_setup_needed()}
