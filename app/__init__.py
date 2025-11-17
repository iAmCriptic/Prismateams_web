from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_socketio import SocketIO
from config import config
import json
import os
import subprocess
import sys
from app.utils.i18n import register_i18n, translate

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
socketio = SocketIO(cors_allowed_origins="*")


def create_app(config_name='default'):
    """Create and configure the Flask application."""
    import os
    basedir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(__name__, static_folder=os.path.join(basedir, 'static'))
    
    # Load configuration
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    socketio.init_app(app)
    register_i18n(app)
    
    # Configure login manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Bitte melden Sie sich an, um auf diese Seite zuzugreifen.'
    login_manager.login_message_category = 'info'
    
    # Custom unauthorized handler for API endpoints (returns JSON instead of redirecting)
    @login_manager.unauthorized_handler
    def unauthorized():
        # Check if this is an API request (OnlyOffice or other API endpoints)
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Authentication required'}), 401
        # For regular requests, redirect to login
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))
    
    # Add email confirmation check to all routes
    @app.before_request
    def check_email_confirmation():
        """Prüft E-Mail-Bestätigung für alle Routen außer Auth und Setup."""
        from flask import request, redirect, url_for, flash
        from flask_login import current_user
        
        # Skip check for auth routes, setup, static files, API, OnlyOffice endpoints, and portal logo
        if (request.endpoint and 
            (request.endpoint.startswith('auth.') or 
             request.endpoint.startswith('setup.') or
             request.endpoint.startswith('static') or
             request.endpoint.startswith('api.') or
             request.endpoint.startswith('files.onlyoffice') or  # OnlyOffice endpoints
             request.endpoint.startswith('files.share_onlyoffice') or  # OnlyOffice share endpoints
             request.endpoint == 'manifest' or
             request.endpoint == 'settings.portal_logo')):
            return
        
        # Skip check if user is not logged in
        if not current_user.is_authenticated:
            return
        
        # Check if email confirmation is required
        if not current_user.is_email_confirmed:
            # Allow access to confirmation page
            if request.endpoint == 'auth.confirm_email':
                return
            # Redirect to confirmation page
            flash('Bitte bestätigen Sie Ihre E-Mail-Adresse, um fortzufahren.', 'info')
            return redirect(url_for('auth.confirm_email'))
    
    # User loader for Flask-Login
    from app.models.user import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Internationalisierung initialisieren
    from app.utils.i18n import init_i18n
    init_i18n(app)

    # Create upload directories if they don't exist
    upload_dirs = [
        app.config['UPLOAD_FOLDER'],
        os.path.join(app.config['UPLOAD_FOLDER'], 'files'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'chat'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'chat', 'avatars'),  # For chat avatars
        os.path.join(app.config['UPLOAD_FOLDER'], 'manuals'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'inventory', 'product_images'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'inventory', 'product_documents'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'system'),  # For portal logo
        os.path.join(app.config['UPLOAD_FOLDER'], 'wiki'),  # For wiki pages
    ]
    for directory in upload_dirs:
        os.makedirs(directory, exist_ok=True)
    
    # Make app config available in all templates
    @app.context_processor
    def inject_app_config():
        # Load from SystemSettings first, fallback to config
        app_name = app.config.get('APP_NAME', 'Prismateams')
        app_logo = app.config.get('APP_LOGO')
        color_gradient = None
        portal_logo_filename = None
        
        try:
            from app.models.settings import SystemSettings
            
            # Load portal name from SystemSettings
            # Try portal_name first, then fallback to organization_name (for migration), then config
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
                app_name = portal_name_setting.value
            else:
                # Check for old organization_name key (migration support)
                org_name_setting = SystemSettings.query.filter_by(key='organization_name').first()
                if org_name_setting and org_name_setting.value and org_name_setting.value.strip():
                    app_name = org_name_setting.value
                else:
                    app_name = app.config.get('APP_NAME', 'Prismateams')
            
            # Load portal logo from SystemSettings
            portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
            if portal_logo_setting and portal_logo_setting.value:
                portal_logo_filename = portal_logo_setting.value
                # Portal logo is stored as filename in uploads/system/, not in static
                app_logo = None  # Will be handled via portal_logo route
            
            # Load color gradient from database
            gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
            if gradient_setting and gradient_setting.value:
                color_gradient = gradient_setting.value
        except:
            pass  # Ignore errors during setup
        
        # Fix logo path - remove 'static/' prefix if present since Flask adds it automatically
        if app_logo and app_logo.startswith('static/'):
            app_logo = app_logo[7:]  # Remove 'static/' prefix
        
        # Add ONLYOFFICE availability function
        from app.utils.onlyoffice import is_onlyoffice_enabled
        onlyoffice_available = is_onlyoffice_enabled()
        
        # Add Excalidraw availability function
        from app.utils.excalidraw import is_excalidraw_enabled
        excalidraw_available = is_excalidraw_enabled()
        
        # Add module check function
        from app.utils.common import is_module_enabled
        
        # Function to get chat display name (for private chats, show only other person's name)
        def get_chat_display_name(chat):
            """Returns the display name for a chat. For private chats, shows only the other person's name."""
            from flask_login import current_user
            if chat.is_direct_message and not chat.is_main_chat:
                # Get the other member (not the current user)
                from app.models.chat import ChatMember
                members = ChatMember.query.filter_by(chat_id=chat.id).all()
                for member in members:
                    if member.user_id != current_user.id:
                        return member.user.full_name
                # Fallback: return original name if something goes wrong
                return chat.name
            if chat.is_main_chat:
                return translate('chat.common.main_chat_name')
            return chat.name
        
        # Function to get back URL based on current endpoint
        def get_back_url():
            """Bestimmt die logische Zurück-URL basierend auf dem aktuellen Endpoint."""
            from flask import request, url_for
            
            if not request.endpoint:
                return url_for('dashboard.index')
            
            endpoint = request.endpoint
            
            # Spezifische Routen-Mappings (höchste Priorität)
            specific_mappings = {
                # Inventory: Bearbeitungs- und Detailseiten -> Bestandsübersicht
                'inventory.product_edit': 'inventory.stock',
                'inventory.product_new': 'inventory.stock',
                'inventory.product_documents': 'inventory.stock',
                'inventory.product_borrow': 'inventory.stock',
                'inventory.product_document_upload': 'inventory.stock',
                'inventory.product_document_delete': 'inventory.stock',
                'inventory.product_document_download': 'inventory.stock',
                # Inventory: Sets -> Sets-Übersicht
                'inventory.set_view': 'inventory.sets',
                'inventory.set_edit': 'inventory.sets',
                'inventory.set_borrow': 'inventory.sets',
                'inventory.set_form': 'inventory.sets',
                # Inventory: Ordner -> Bestandsübersicht
                'inventory.folders': 'inventory.stock',
                # Settings: Basis-Seiten -> Settings-Übersicht
                'settings.profile': 'settings.index',
                'settings.appearance': 'settings.index',
                'settings.notifications': 'settings.index',
                'settings.about': 'settings.index',
                'settings.admin': 'settings.index',
                # Settings Admin: Module & Aktionen -> Admin-Übersicht
                'settings.admin_users': 'settings.admin',
                'settings.admin_email_permissions': 'settings.admin',
                'settings.admin_email_footer': 'settings.admin',
                'settings.admin_system': 'settings.admin',
                'settings.admin_modules': 'settings.admin',
                'settings.admin_backup': 'settings.admin',
                'settings.admin_whitelist': 'settings.admin',
                'settings.add_whitelist_entry': 'settings.admin',
                'settings.toggle_whitelist_entry': 'settings.admin',
                'settings.delete_whitelist_entry': 'settings.admin',
                'settings.admin_inventory_categories': 'settings.admin',
                'settings.admin_delete_inventory_category': 'settings.admin',
                'settings.admin_inventory_permissions': 'settings.admin',
                'settings.admin_toggle_borrow_permission': 'settings.admin',
                # Auth: Admin-spezifische Seiten -> Admin-Übersicht
                'auth.show_confirmation_codes': 'settings.admin',
                'auth.test_email': 'settings.admin',
                # Calendar: Detailseiten -> Kalender-Übersicht
                'calendar.view': 'calendar.index',
                'calendar.edit_event': 'calendar.index',
                'calendar.create': 'calendar.index',
                # Email: Detailseiten -> Email-Übersicht
                'email.view_email': 'email.index',
                'email.compose': 'email.index',
                'email.reply': 'email.index',
                'email.reply_all': 'email.index',
                'email.forward': 'email.index',
                # Chat: Detailseiten -> Chat-Übersicht
                'chat.view_chat': 'chat.index',
                'chat.create': 'chat.index',
                # Wiki: Detailseiten -> Wiki-Übersicht
                'wiki.view': 'wiki.index',
                'wiki.edit': 'wiki.index',
                'wiki.create': 'wiki.index',
                # Canvas: Detailseiten -> Canvas-Übersicht
                'canvas.view': 'canvas.index',
                'canvas.edit': 'canvas.index',
                'canvas.create': 'canvas.index',
                # Credentials: Detailseiten -> Credentials-Übersicht
                'credentials.view': 'credentials.index',
                'credentials.edit': 'credentials.index',
                'credentials.create': 'credentials.index',
                # Manuals: Detailseiten -> Manuals-Übersicht
                'manuals.view': 'manuals.index',
                'manuals.edit': 'manuals.index',
                'manuals.create': 'manuals.index',
            }
            
            # Prüfe zuerst spezifische Mappings
            if endpoint in specific_mappings:
                return url_for(specific_mappings[endpoint])
            
            # Dateien: Ordnernavigation -> Elternordner oder Root
            if endpoint == 'files.browse_folder':
                folder_id = request.view_args.get('folder_id') if request.view_args else None
                if folder_id:
                    from app.models.file import Folder
                    folder = Folder.query.get(folder_id)
                    if folder and folder.parent_id:
                        return url_for('files.browse_folder', folder_id=folder.parent_id)
                return url_for('files.index')
            
            # Settings Admin: Fallback für alle weiteren Unterseiten
            if endpoint.startswith('settings.admin_'):
                return url_for('settings.admin')
            
            # Allgemeine Modul-Mappings
            module_mapping = {
                'inventory': 'inventory.dashboard',
                'email': 'email.index',
                'chat': 'chat.index',
                'files': 'files.index',
                'calendar': 'calendar.index',
                'credentials': 'credentials.index',
                'manuals': 'manuals.index',
                'canvas': 'canvas.index',
                'wiki': 'wiki.index',
                'settings': 'settings.index'
            }
            
            # Prüfe ob Endpoint zu einem Modul gehört
            for module_prefix, index_endpoint in module_mapping.items():
                if endpoint.startswith(module_prefix + '.'):
                    # Wenn es bereits die Index-Seite ist, zum Dashboard
                    if endpoint == index_endpoint:
                        return url_for('dashboard.index')
                    # Sonst zur Index-Seite des Moduls
                    return url_for(index_endpoint)
            
            # Fallback: Zum Dashboard
            return url_for('dashboard.index')
        
        return {
            'app_name': app_name,
            'app_logo': app_logo,
            'color_gradient': color_gradient,
            'portal_logo_filename': portal_logo_filename,
            'onlyoffice_available': onlyoffice_available,
            'excalidraw_available': excalidraw_available,
            'is_module_enabled': is_module_enabled,
            'get_back_url': get_back_url,
            'get_chat_display_name': get_chat_display_name
        }
    
    # Email header decoder filter
    @app.template_filter('decode_email_header')
    def decode_email_header_filter(header):
        """Decode email header fields properly."""
        if not header:
            return ''
        
        try:
            from email.header import decode_header
            decoded_parts = decode_header(str(header))
            decoded_string = ''
            
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        decoded_string += part.decode(encoding)
                    else:
                        decoded_string += part.decode('utf-8', errors='ignore')
                else:
                    decoded_string += str(part)
            
            return decoded_string.strip()
        except Exception:
            return str(header)
    
    # Email sender initials filter
    @app.template_filter('email_sender_initials')
    def email_sender_initials_filter(sender):
        """Extract initials from sender name or email."""
        if not sender:
            return '??'
        
        try:
            # Decode first if needed
            decoded = decode_email_header_filter(sender)
            
            # Remove email address if present (e.g., "Name <email@example.com>")
            import re
            name_match = re.match(r'^(.+?)\s*<.*?>$', decoded)
            if name_match:
                name = name_match.group(1).strip()
            else:
                # Try to extract name from email if no name found
                email_match = re.match(r'^(.+?)\s*<(.+?)>$', decoded)
                if email_match:
                    name = email_match.group(1).strip() or email_match.group(2).split('@')[0]
                else:
                    name = decoded.split('<')[0].strip() if '<' in decoded else decoded
            
            # Extract initials
            parts = name.split()
            if len(parts) >= 2:
                return (parts[0][0] + parts[1][0]).upper()
            elif len(parts) == 1 and len(parts[0]) >= 2:
                return parts[0][0:2].upper()
            elif len(parts) == 1 and len(parts[0]) == 1:
                return parts[0][0].upper() + parts[0][0].upper()
            else:
                return name[0:2].upper() if len(name) >= 2 else (name[0].upper() + name[0].upper() if name else '??')
        except Exception:
            return '??'
    
    
    # Template filters
    from app.utils import format_time, format_datetime
    
    @app.template_filter('localtime')
    def localtime_filter(dt, format_string='%H:%M'):
        """Filter to format datetime in local timezone."""
        return format_time(dt, format_string)
    
    @app.template_filter('localdatetime')
    def localdatetime_filter(dt, format_string='%d.%m.%Y %H:%M'):
        """Filter to format datetime in local timezone."""
        return format_datetime(dt, format_string)
    
    @app.template_filter('smart_datetime')
    def smart_datetime_filter(dt):
        """Smart datetime formatting: Today shows time only, Yesterday shows 'Gestern HH:MM', older shows date."""
        if not dt:
            return ''
        
        from datetime import datetime, date
        from app.utils.common import get_local_time
        
        local_dt = get_local_time(dt)
        if isinstance(local_dt, str):
            try:
                local_dt = datetime.fromisoformat(local_dt.replace('Z', '+00:00'))
            except:
                return str(dt)
        
        now = datetime.now()
        today = date.today()
        message_date = local_dt.date()
        
        # Calculate difference in days
        days_diff = (today - message_date).days
        
        if days_diff == 0:
            # Today: show only time
            return local_dt.strftime('%H:%M')
        elif days_diff == 1:
            # Yesterday: show "Gestern HH:MM"
            return f"Gestern {local_dt.strftime('%H:%M')}"
        else:
            # Older: show date and time
            return local_dt.strftime('%d.%m.%Y %H:%M')
    
    @app.template_filter('markdown')
    def markdown_filter(text):
        """Filter to render markdown text."""
        try:
            from app.utils.markdown import process_markdown
            # Nutze die zentrale Markdown-Verarbeitung für Konsistenz
            return process_markdown(text, wiki_mode=False)
            
        except Exception as e:
            # Fallback to plain text if markdown processing fails
            from flask import current_app
            current_app.logger.warning(f"Markdown processing failed: {e}, using plain text fallback")
            return text.replace('\n', '<br>')

    # Error handlers
    @app.errorhandler(400)
    def bad_request(error):
        return render_template('errors/400.html'), 400
    
    @app.errorhandler(403)
    def forbidden(error):
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(404)
    def not_found(error):
        # Log 404 errors for debugging
        app.logger.warning(f"404 Not Found: {request.url}")
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(429)
    def too_many_requests(error):
        return render_template('errors/429.html'), 429
    
    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle 413 Request Entity Too Large errors."""
        # Log the error
        app.logger.warning(f"413 Request Entity Too Large: {request.url}")
        # Return JSON for API endpoints
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'File too large', 'message': 'Die hochgeladene Datei überschreitet das maximale Größenlimit.'}), 413
        # Return user-friendly error page
        max_size_mb = app.config.get('MAX_CONTENT_LENGTH', 524288000) / (1024 * 1024)
        return render_template('errors/413.html', max_size_mb=max_size_mb), 413
    
    @app.errorhandler(500)
    def internal_error(error):
        # Log the error
        app.logger.error(f"500 Internal Server Error: {error}", exc_info=True)
        # Rollback any database transactions
        db.session.rollback()
        # Return JSON for API endpoints
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Internal server error', 'message': str(error)}), 500
        return render_template('errors/500.html'), 500
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        # Skip RequestEntityTooLarge - it has its own handler
        from werkzeug.exceptions import RequestEntityTooLarge
        if isinstance(e, RequestEntityTooLarge):
            raise  # Re-raise to let the 413 handler catch it
        
        # Log the error
        app.logger.error(f"Unhandled exception: {e}", exc_info=True)
        
        # Rollback any database transactions
        db.session.rollback()
        
        # Return JSON for API endpoints
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Internal server error', 'message': str(e)}), 500
        # Return 500 error page
        return render_template('errors/500.html'), 500
    
    # Custom error handler for application-specific errors
    @app.errorhandler(ValueError)
    def handle_value_error(e):
        app.logger.warning(f"Value error: {e}")
        return render_template('errors/generic.html', 
                             error_code='400',
                             error_title='Ungültige Eingabe',
                             error_message=str(e)), 400
    
    @app.errorhandler(PermissionError)
    def handle_permission_error(e):
        app.logger.warning(f"Permission error: {e}")
        return render_template('errors/403.html'), 403

    # Register blueprints
    from app.blueprints.setup import setup_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.dashboard import dashboard_bp
    from app.blueprints.chat import chat_bp
    from app.blueprints.files import files_bp
    from app.blueprints.calendar import calendar_bp
    from app.blueprints.email import email_bp, start_email_sync
    from app.blueprints.credentials import credentials_bp
    from app.blueprints.manuals import manuals_bp
    from app.blueprints.canvas import canvas_bp
    from app.blueprints.settings import settings_bp
    from app.blueprints.api import api_bp
    from app.blueprints.errors import errors_bp
    from app.blueprints.inventory import inventory_bp
    from app.blueprints.wiki import wiki_bp
    from app.blueprints.comments import comments_bp
    
    app.register_blueprint(setup_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(files_bp, url_prefix='/files')
    app.register_blueprint(calendar_bp, url_prefix='/calendar')
    app.register_blueprint(email_bp, url_prefix='/email')
    app.register_blueprint(credentials_bp, url_prefix='/credentials')
    app.register_blueprint(manuals_bp, url_prefix='/manuals')
    app.register_blueprint(canvas_bp, url_prefix='/canvas')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(errors_bp, url_prefix='/test')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(wiki_bp)
    app.register_blueprint(comments_bp)
    
    # PWA Manifest Route - Generate dynamically based on portal name
    @app.route('/manifest.json')
    def manifest():
        import json
        from app.models.settings import SystemSettings
        
        # Load portal name from SystemSettings
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else app.config.get('APP_NAME', 'Prismateams')
        
        # Load manifest.json and replace name dynamically
        manifest_path = os.path.join(app.static_folder, 'manifest.json')
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            
            # Update with current portal name
            manifest_data['name'] = portal_name
            manifest_data['short_name'] = portal_name
            
            return jsonify(manifest_data)
        except:
            # Fallback to static file if something goes wrong
            return app.send_static_file('manifest.json')
    
    # Service Worker unter Root-Scope ausliefern, damit er die gesamte App kontrolliert
    @app.route('/sw.js')
    def service_worker():
        return app.send_static_file('sw.js')
    
    # Create database tables
    with app.app_context():
        try:
            # Erstelle alle Tabellen (nur neue werden hinzugefügt)
            # Die Felder is_dropbox, dropbox_token, dropbox_password_hash werden automatisch erstellt,
            # da sie im Folder-Modell definiert sind (app/models/file.py)
            db.create_all()
            print("[OK] Datenbank-Tabellen erfolgreich erstellt/aktualisiert")
            
            # Führe Migration für bestehende Installationen aus (falls Felder fehlen)
            try:
                from sqlalchemy import inspect
                inspector = inspect(db.engine)
                if 'folders' in inspector.get_table_names():
                    columns = {col['name']: col for col in inspector.get_columns('folders')}
                    if 'is_dropbox' not in columns or 'dropbox_token' not in columns or 'dropbox_password_hash' not in columns:
                        print("[INFO] Führe Migration zu Version 1.5.2 aus...")
                        # Führe Migration direkt aus (ohne Import, da Python-Module mit Punkten nicht importierbar sind)
                        migrations_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations', 'Migrate_to_1.5.2.py')
                        if os.path.exists(migrations_path):
                            try:
                                result = subprocess.run([sys.executable, migrations_path], 
                                                       capture_output=True, text=True, timeout=30)
                                if result.returncode == 0:
                                    print("[OK] Migration erfolgreich ausgeführt")
                                else:
                                    print(f"[WARNUNG] Migration gab Fehler zurück: {result.stderr}")
                                    print("[INFO] Bitte führen Sie manuell aus: python migrations/Migrate_to_1.5.2.py")
                            except subprocess.TimeoutExpired:
                                print("[WARNUNG] Migration dauerte zu lange. Bitte manuell ausführen.")
                            except Exception as e:
                                print(f"[WARNUNG] Migration konnte nicht ausgeführt werden: {e}")
                                print("[INFO] Bitte führen Sie manuell aus: python migrations/Migrate_to_1.5.2.py")
                        else:
                            print("[WARNUNG] Migrationsdatei nicht gefunden. Bitte manuell ausführen: python migrations/Migrate_to_1.5.2.py")

                if ('users' in inspector.get_table_names() and
                        'language' not in {col['name'] for col in inspector.get_columns('users')} and
                        not os.getenv('RUNNING_LANGUAGE_MIGRATION')):
                    print("[INFO] Führe Sprachmigration aus...")
                    migrations_path = os.path.join(
                        os.path.dirname(os.path.dirname(__file__)),
                        'migrations',
                        'migrate_languages.py'
                    )
                    if os.path.exists(migrations_path):
                        env = os.environ.copy()
                        env.setdefault('RUNNING_LANGUAGE_MIGRATION', '1')
                        env.setdefault('PRISMATEAMS_SKIP_BACKGROUND_JOBS', '1')
                        try:
                            result = subprocess.run(
                                [sys.executable, migrations_path],
                                capture_output=True,
                                text=True,
                                timeout=60,
                                env=env
                            )
                            if result.returncode == 0:
                                print("[OK] Sprachmigration erfolgreich ausgeführt")
                            else:
                                print(f"[WARNUNG] Sprachmigration gab Fehler zurück: {result.stderr}")
                                print("[INFO] Bitte führen Sie manuell aus: python migrations/migrate_languages.py")
                        except subprocess.TimeoutExpired:
                            print("[WARNUNG] Sprachmigration dauerte zu lange. Bitte manuell ausführen.")
                        except Exception as exc:
                            print(f"[WARNUNG] Sprachmigration konnte nicht ausgeführt werden: {exc}")
                            print("[INFO] Bitte führen Sie manuell aus: python migrations/migrate_languages.py")
                    else:
                        print("[WARNUNG] Sprach-Migrationsdatei nicht gefunden. Bitte manuell ausführen: python migrations/migrate_languages.py")
            except Exception as migration_error:
                print(f"[WARNUNG] Migration konnte nicht automatisch ausgeführt werden: {migration_error}")
                print("[INFO] Bitte führen Sie manuell aus: python migrations/Migrate_to_1.5.2.py")
            
            # CRITICAL: Ensure standard email folders always exist
            from app.models.email import EmailFolder
            
            # Create standard folders if they don't exist
            standard_folders = [
                {'name': 'INBOX', 'display_name': 'Posteingang', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Sent', 'display_name': 'Gesendet', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Drafts', 'display_name': 'Entwürfe', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Trash', 'display_name': 'Papierkorb', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Spam', 'display_name': 'Spam', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Archive', 'display_name': 'Archiv', 'folder_type': 'standard', 'is_system': True}
            ]
            
            for folder_data in standard_folders:
                existing_folder = EmailFolder.query.filter_by(name=folder_data['name']).first()
                if not existing_folder:
                    folder = EmailFolder(**folder_data)
                    db.session.add(folder)
                    print(f"Created standard folder: {folder_data['display_name']}")
            
            db.session.commit()
            print("[OK] Standard email folders ensured")
            
        except Exception as e:
            print(f"[WARNUNG] Warnung beim Erstellen der Datenbank-Tabellen: {e}")
            # Versuche trotzdem fortzufahren
        
        # Initialize system settings
        from app.models.settings import SystemSettings
        from app.models.chat import Chat
        from app.models.user import User
        from sqlalchemy import inspect, text
        
        # Create default system settings if they don't exist
        if not SystemSettings.query.filter_by(key='email_footer_text').first():
            footer = SystemSettings(
                key='email_footer_text',
                value='Mit freundlichen Grüßen\nIhr Team',
                description='Standard-Footer für E-Mails'
            )
            db.session.add(footer)
        
        if not SystemSettings.query.filter_by(key='email_footer_image').first():
            footer_img = SystemSettings(
                key='email_footer_image',
                value='',
                description='Footer-Bild URL für E-Mails'
            )
            db.session.add(footer_img)

        if not SystemSettings.query.filter_by(key='default_language').first():
            db.session.add(SystemSettings(
                key='default_language',
                value='de',
                description='Standardsprache für die Benutzeroberfläche'
            ))

        if not SystemSettings.query.filter_by(key='email_language').first():
            db.session.add(SystemSettings(
                key='email_language',
                value='de',
                description='Standardsprache für System-E-Mails'
            ))

        if not SystemSettings.query.filter_by(key='available_languages').first():
            db.session.add(SystemSettings(
                key='available_languages',
                value='["de","en","pt","es","ru"]',
                description='Liste der aktivierten Sprachen'
            ))
        
        language_settings = {
            'default_language': (
                'de',
                'Standardsprache der Benutzeroberfläche für neue Benutzer.'
            ),
            'email_language': (
                'de',
                'Sprache für automatisch versendete System-E-Mails.'
            ),
            'available_languages': (
                json.dumps(['de', 'en', 'pt', 'es', 'ru']),
                'Aktivierte Sprachen im Portal (JSON-Liste).'
            )
        }
        
        for key, (value, description) in language_settings.items():
            setting = SystemSettings.query.filter_by(key=key).first()
            if not setting:
                db.session.add(SystemSettings(key=key, value=value, description=description))
            else:
                if not setting.value:
                    setting.value = value
                if description and not setting.description:
                    setting.description = description
        
        # Stelle sicher, dass bestehende Benutzer eine Sprache gesetzt haben
        try:
            inspector = inspect(db.engine)
            if 'users' in inspector.get_table_names():
                columns = {col['name'] for col in inspector.get_columns('users')}
                if 'language' in columns:
                    with db.engine.begin() as connection:
                        connection.execute(
                            text("""
                                UPDATE users
                                SET language = :default_lang
                                WHERE language IS NULL OR TRIM(language) = ''
                            """),
                            {'default_lang': 'de'}
                        )
        except Exception as e:
            app.logger.warning("Konnte Benutzersprachen nicht aktualisieren: %s", e)

        # Create main chat if it doesn't exist
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if not main_chat:
            main_chat = Chat(
                name='Team Chat',
                is_main_chat=True,
                is_direct_message=False
            )
            db.session.add(main_chat)
            db.session.flush()  # Get the ID
            
            # Add all active users to the main chat
            from app.models.chat import ChatMember
            active_users = User.query.filter_by(is_active=True).all()
            for user in active_users:
                member = ChatMember(
                    chat_id=main_chat.id,
                    user_id=user.id
                )
                db.session.add(member)
        
        # Also ensure all new users are added to the main chat
        else:
            from app.models.chat import ChatMember
            try:
                # Get all active users
                active_users = User.query.filter_by(is_active=True).all()
                # Get existing members of main chat
                existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                existing_user_ids = [member.user_id for member in existing_members]
                
                # Add any users who aren't already members
                for user in active_users:
                    if user.id not in existing_user_ids:
                        member = ChatMember(
                            chat_id=main_chat.id,
                            user_id=user.id
                        )
                        db.session.add(member)
            except Exception as e:
                print(f"WARNING: Could not update main chat members: {e}")
                # Continue without failing
        
        db.session.commit()
    
    if not os.getenv('PRISMATEAMS_SKIP_BACKGROUND_JOBS'):
        # Start email auto-sync
        start_email_sync(app)
        
        # Start notification scheduler
        from app.tasks.notification_scheduler import start_notification_scheduler
        start_notification_scheduler(app)
    
    # Import SocketIO handlers
    from app.blueprints import canvas
    
    return app



