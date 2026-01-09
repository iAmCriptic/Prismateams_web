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

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

# SocketIO mit optionaler Redis Message Queue für Multi-Worker-Setups
def create_socketio():
    """Erstellt SocketIO-Instanz mit optionaler Redis Message Queue."""
    # Initial ohne Config (wird später in create_app konfiguriert)
    return SocketIO(cors_allowed_origins="*")

socketio = create_socketio()


def create_app(config_name='default'):
    """Create and configure the Flask application."""
    import os
    basedir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(__name__, static_folder=os.path.join(basedir, 'static'))
    
    app.config.from_object(config[config_name])
    
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    
    # Konfiguriere SocketIO mit optionaler Redis Message Queue
    redis_enabled = app.config.get('REDIS_ENABLED', False)
    if redis_enabled:
        try:
            redis_url = app.config.get('REDIS_URL', 'redis://localhost:6379/0')
            # Verwende Redis als Message Queue für Multi-Worker-Setups
            socketio.init_app(
                app,
                message_queue=redis_url,
                async_mode='threading'
            )
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"SocketIO mit Redis Message Queue konfiguriert: {redis_url}")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Redis nicht verfügbar, verwende SocketIO ohne Message Queue: {e}")
            logger.warning("Hinweis: Multi-Worker-Setups funktionieren nur mit Redis!")
            # Fallback: SocketIO ohne Message Queue (nur für Single-Worker)
            socketio.init_app(app)
    else:
        # Kein Redis konfiguriert - nur für Single-Worker oder Development
        socketio.init_app(app)
        if config_name == 'production':
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Redis nicht aktiviert! Multi-Worker-Setups funktionieren nicht korrekt.")
            logger.warning("Setze REDIS_ENABLED=True in der .env für Production mit mehreren Workern.")
    
    register_i18n(app)
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Bitte melden Sie sich an, um auf diese Seite zuzugreifen.'
    login_manager.login_message_category = 'info'
    
    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Authentication required'}), 401
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))
    
    @app.before_request
    def check_email_confirmation():
        """Prüft E-Mail-Bestätigung für alle Routen außer Auth und Setup."""
        from flask import request, redirect, url_for, flash
        from flask_login import current_user
        
        if (request.endpoint and 
            (request.endpoint.startswith('auth.') or 
             request.endpoint.startswith('setup.') or
             request.endpoint.startswith('static') or
             request.endpoint.startswith('api.') or
             request.endpoint.startswith('files.onlyoffice') or
             request.endpoint.startswith('files.share_onlyoffice') or
             request.endpoint.startswith('booking.public') or
             request.endpoint.startswith('booking.public_') or
             request.endpoint == 'booking.public_booking' or
             request.endpoint == 'booking.public_form' or
             request.endpoint == 'booking.public_view' or
             request.endpoint == 'manifest' or
             request.endpoint == 'settings.portal_logo')):
            return
        
        if not current_user.is_authenticated:
            return
        
        if not current_user.is_email_confirmed:
            if request.endpoint == 'auth.confirm_email':
                return
            flash('Bitte bestätigen Sie Ihre E-Mail-Adresse, um fortzufahren.', 'info')
            return redirect(url_for('auth.confirm_email'))
    
    from app.models.user import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    from app.utils.i18n import init_i18n
    init_i18n(app)

    upload_dirs = [
        app.config['UPLOAD_FOLDER'],
        os.path.join(app.config['UPLOAD_FOLDER'], 'files'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'chat'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'chat', 'avatars'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'manuals'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'inventory', 'product_images'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'inventory', 'product_documents'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'system'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'wiki'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'bookings'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'booking_forms'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'veranstaltungen'),
    ]
    for directory in upload_dirs:
        os.makedirs(directory, exist_ok=True)
    
    @app.context_processor
    def inject_app_config():
        from app.utils.common import is_module_enabled
        from app.utils.access_control import has_module_access
        from flask_login import current_user
        app_name = app.config.get('APP_NAME', 'Prismateams')
        app_logo = app.config.get('APP_LOGO')
        color_gradient = None
        portal_logo_filename = None
        
        try:
            from app.models.settings import SystemSettings
            
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
                app_name = portal_name_setting.value
            else:
                org_name_setting = SystemSettings.query.filter_by(key='organization_name').first()
                if org_name_setting and org_name_setting.value and org_name_setting.value.strip():
                    app_name = org_name_setting.value
                else:
                    app_name = app.config.get('APP_NAME', 'Prismateams')
            
            portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
            if portal_logo_setting and portal_logo_setting.value:
                portal_logo_filename = portal_logo_setting.value
                app_logo = None
            
            gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
            if gradient_setting and gradient_setting.value:
                color_gradient = gradient_setting.value
        except:
            pass
        
        if app_logo and app_logo.startswith('static/'):
            app_logo = app_logo[7:]
        
        from app.utils.onlyoffice import is_onlyoffice_enabled
        onlyoffice_available = is_onlyoffice_enabled()
        
        from app.utils.excalidraw import is_excalidraw_enabled
        excalidraw_available = is_excalidraw_enabled()
        
        from app.utils.common import is_module_enabled
        
        def get_chat_display_name(chat):
            """Returns the display name for a chat. For private chats, shows only the other person's name."""
            from flask_login import current_user
            if chat.is_direct_message and not chat.is_main_chat:
                from app.models.chat import ChatMember
                members = ChatMember.query.filter_by(chat_id=chat.id).all()
                for member in members:
                    if member.user_id != current_user.id:
                        return member.user.full_name
                return chat.name
            if chat.is_main_chat:
                return translate('chat.common.main_chat_name')
            return chat.name
        
        def get_back_url():
            """Bestimmt die logische Zurück-URL basierend auf dem aktuellen Endpoint."""
            from flask import request, url_for
            
            if not request.endpoint:
                return url_for('dashboard.index')
            
            endpoint = request.endpoint
            
            specific_mappings = {
                'inventory.product_edit': 'inventory.stock',
                'inventory.product_new': 'inventory.stock',
                'inventory.product_documents': 'inventory.stock',
                'inventory.product_borrow': 'inventory.stock',
                'inventory.product_document_upload': 'inventory.stock',
                'inventory.product_document_delete': 'inventory.stock',
                'inventory.product_document_download': 'inventory.stock',
                'inventory.set_view': 'inventory.sets',
                'inventory.set_edit': 'inventory.sets',
                'inventory.set_borrow': 'inventory.sets',
                'inventory.set_form': 'inventory.sets',
                'inventory.folders': 'inventory.stock',
                'settings.profile': 'settings.index',
                'settings.appearance': 'settings.index',
                'settings.notifications': 'settings.index',
                'settings.about': 'settings.index',
                'settings.admin': 'settings.index',
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
                'settings.admin_file_settings': 'settings.admin',
                'settings.booking_forms': 'settings.admin',
                'settings.booking_form_create': 'settings.admin',
                'settings.booking_form_edit': 'settings.admin',
                'settings.booking_form_delete': 'settings.admin',
                'settings.booking_field_add': 'settings.admin',
                'settings.booking_field_edit': 'settings.admin',
                'settings.booking_field_delete': 'settings.admin',
                'settings.booking_field_order': 'settings.admin',
                'settings.booking_image_upload': 'settings.admin',
                'settings.booking_image_delete': 'settings.admin',
                'settings.booking_image': 'settings.admin',
                'auth.show_confirmation_codes': 'settings.admin',
                'auth.test_email': 'settings.admin',
                'calendar.view': 'calendar.index',
                'calendar.edit_event': 'calendar.index',
                'calendar.create': 'calendar.index',
                'email.view_email': 'email.index',
                'email.compose': 'email.index',
                'email.reply': 'email.index',
                'email.reply_all': 'email.index',
                'email.forward': 'email.index',
                'chat.view_chat': 'chat.index',
                'chat.create': 'chat.index',
                'wiki.view': 'wiki.index',
                'wiki.edit': 'wiki.index',
                'wiki.create': 'wiki.index',
                'canvas.view': 'canvas.index',
                'canvas.edit': 'canvas.index',
                'canvas.create': 'canvas.index',
                'credentials.view': 'credentials.index',
                'credentials.edit': 'credentials.index',
                'credentials.create': 'credentials.index',
                'manuals.view': 'manuals.index',
                'manuals.edit': 'manuals.index',
                'manuals.create': 'manuals.index',
            }
            
            if endpoint in specific_mappings:
                return url_for(specific_mappings[endpoint])
            
            if endpoint == 'files.browse_folder':
                folder_id = request.view_args.get('folder_id') if request.view_args else None
                if folder_id:
                    from app.models.file import Folder
                    folder = Folder.query.get(folder_id)
                    if folder and folder.parent_id:
                        return url_for('files.browse_folder', folder_id=folder.parent_id)
                return url_for('files.index')
            
            if endpoint.startswith('settings.admin_'):
                return url_for('settings.admin')
            
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
            
            for module_prefix, index_endpoint in module_mapping.items():
                if endpoint.startswith(module_prefix + '.'):
                    if endpoint == index_endpoint:
                        return url_for('dashboard.index')
                    return url_for(index_endpoint)
            
            return url_for('dashboard.index')
        
        return {
            'app_name': app_name,
            'app_logo': app_logo,
            'color_gradient': color_gradient,
            'portal_logo_filename': portal_logo_filename,
            'onlyoffice_available': onlyoffice_available,
            'excalidraw_available': excalidraw_available,
            'is_module_enabled': is_module_enabled,
            'has_module_access': has_module_access,
            'get_back_url': get_back_url,
            'get_chat_display_name': get_chat_display_name
        }
    
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
    
    @app.template_filter('email_sender_initials')
    def email_sender_initials_filter(sender):
        """Extract initials from sender name or email."""
        if not sender:
            return '??'
        
        try:
            decoded = decode_email_header_filter(sender)
            
            import re
            name_match = re.match(r'^(.+?)\s*<.*?>$', decoded)
            if name_match:
                name = name_match.group(1).strip()
            else:
                email_match = re.match(r'^(.+?)\s*<(.+?)>$', decoded)
                if email_match:
                    name = email_match.group(1).strip() or email_match.group(2).split('@')[0]
                else:
                    name = decoded.split('<')[0].strip() if '<' in decoded else decoded
            
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
        
        days_diff = (today - message_date).days
        
        if days_diff == 0:
            return local_dt.strftime('%H:%M')
        elif days_diff == 1:
            return f"Gestern {local_dt.strftime('%H:%M')}"
        else:
            return local_dt.strftime('%d.%m.%Y %H:%M')
    
    @app.template_filter('markdown')
    def markdown_filter(text):
        """Filter to render markdown text."""
        try:
            from app.utils.markdown import process_markdown
            return process_markdown(text, wiki_mode=False)
            
        except Exception as e:
            from flask import current_app
            current_app.logger.warning(f"Markdown processing failed: {e}, using plain text fallback")
            return text.replace('\n', '<br>')

    @app.errorhandler(400)
    def bad_request(error):
        return render_template('errors/400.html'), 400
    
    @app.errorhandler(403)
    def forbidden(error):
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(404)
    def not_found(error):
        app.logger.warning(f"404 Not Found: {request.url}")
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(429)
    def too_many_requests(error):
        return render_template('errors/429.html'), 429
    
    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle 413 Request Entity Too Large errors."""
        app.logger.warning(f"413 Request Entity Too Large: {request.url}")
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'File too large', 'message': 'Die hochgeladene Datei überschreitet das maximale Größenlimit.'}), 413
        max_size_mb = app.config.get('MAX_CONTENT_LENGTH', 524288000) / (1024 * 1024)
        return render_template('errors/413.html', max_size_mb=max_size_mb), 413
    
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"500 Internal Server Error: {error}", exc_info=True)
        db.session.rollback()
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Internal server error', 'message': str(error)}), 500
        return render_template('errors/500.html'), 500
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        from werkzeug.exceptions import RequestEntityTooLarge
        if isinstance(e, RequestEntityTooLarge):
            raise
        
        app.logger.error(f"Unhandled exception: {e}", exc_info=True)
        
        db.session.rollback()
        
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Internal server error', 'message': str(e)}), 500
        return render_template('errors/500.html'), 500
    
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
    from app.blueprints.booking import booking_bp
    from app.blueprints.music import music_bp
    
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
    app.register_blueprint(booking_bp, url_prefix='/booking')
    app.register_blueprint(music_bp)
    
    @app.route('/manifest.json')
    def manifest():
        import json
        from app.models.settings import SystemSettings
        
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else app.config.get('APP_NAME', 'Prismateams')
        
        manifest_path = os.path.join(app.static_folder, 'manifest.json')
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            
            manifest_data['name'] = portal_name
            manifest_data['short_name'] = portal_name
            
            return jsonify(manifest_data)
        except:
            return app.send_static_file('manifest.json')
    
    @app.route('/sw.js')
    def service_worker():
        return app.send_static_file('sw.js')
    
    # Initialisierung nur im Hauptprozess ausführen (verhindert doppelte Ausführung durch Flask Reloader)
    # WERKZEUG_RUN_MAIN ist nur im Hauptprozess gesetzt (nach "Restarting with stat"), nicht im Reloader-Prozess
    # Im Debug-Modus: Nur initialisieren wenn WERKZEUG_RUN_MAIN='true' (Hauptprozess)
    # Ohne Debug-Modus: Immer initialisieren (kein Reloader)
    werkzeug_run_main = os.environ.get('WERKZEUG_RUN_MAIN')
    is_debug = app.config.get('DEBUG', False)
    # Initialisierung nur wenn: (Hauptprozess nach Reload) ODER (kein Debug-Modus)
    is_main_process = (werkzeug_run_main == 'true') or (not is_debug)
    
    with app.app_context():
        if is_main_process:
            try:
                db.create_all()
                print("[OK] Datenbank-Tabellen erfolgreich erstellt/aktualisiert")
                
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
                
                from app.models.email import EmailFolder
                
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
                
                from app.models.settings import SystemSettings
                from app.models.chat import Chat
                from app.models.user import User
                from sqlalchemy import inspect, text
                
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

                main_chat = Chat.query.filter_by(is_main_chat=True).first()
                main_chat = Chat.query.filter_by(is_main_chat=True).first()
                if not main_chat:
                    main_chat = Chat(
                        name='Team Chat',
                        is_main_chat=True,
                        is_direct_message=False
                    )
                    db.session.add(main_chat)
                    db.session.flush()
                    
                    from app.models.chat import ChatMember
                    # Prüfe ob has_full_access Spalte existiert
                    try:
                        from sqlalchemy import inspect
                        inspector = inspect(db.engine)
                        if 'users' in inspector.get_table_names():
                            columns = {col['name'] for col in inspector.get_columns('users')}
                            if 'has_full_access' in columns:
                                from app.utils.access_control import has_module_access
                                active_users = User.query.filter_by(is_active=True).all()
                                for user in active_users:
                                    if has_module_access(user, 'module_chat'):
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                            else:
                                # Spalte existiert noch nicht - füge alle aktiven Benutzer hinzu (Rückwärtskompatibilität)
                                active_users = User.query.filter_by(is_active=True).all()
                                for user in active_users:
                                    member = ChatMember(
                                        chat_id=main_chat.id,
                                        user_id=user.id
                                    )
                                    db.session.add(member)
                    except Exception as e:
                        print(f"WARNING: Could not check has_full_access column: {e}")
                        # Fallback: Füge alle aktiven Benutzer hinzu
                        from app.models.chat import ChatMember
                        active_users = User.query.filter_by(is_active=True).all()
                        for user in active_users:
                            member = ChatMember(
                                chat_id=main_chat.id,
                                user_id=user.id
                            )
                            db.session.add(member)
                else:
                    from app.models.chat import ChatMember
                    try:
                        # Prüfe ob has_full_access Spalte existiert
                        from sqlalchemy import inspect
                        inspector = inspect(db.engine)
                        if 'users' in inspector.get_table_names():
                            columns = {col['name'] for col in inspector.get_columns('users')}
                            if 'has_full_access' in columns:
                                from app.utils.access_control import has_module_access
                                active_users = User.query.filter_by(is_active=True).all()
                                existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                                existing_user_ids = [member.user_id for member in existing_members]
                                
                                for user in active_users:
                                    if user.id not in existing_user_ids and has_module_access(user, 'module_chat'):
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                            else:
                                # Spalte existiert noch nicht - füge alle aktiven Benutzer hinzu (Rückwärtskompatibilität)
                                active_users = User.query.filter_by(is_active=True).all()
                                existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                                existing_user_ids = [member.user_id for member in existing_members]
                                
                                for user in active_users:
                                    if user.id not in existing_user_ids:
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                        else:
                            # Fallback: Füge alle aktiven Benutzer hinzu
                            active_users = User.query.filter_by(is_active=True).all()
                            existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                            existing_user_ids = [member.user_id for member in existing_members]
                            
                            for user in active_users:
                                if user.id not in existing_user_ids:
                                    member = ChatMember(
                                        chat_id=main_chat.id,
                                        user_id=user.id
                                    )
                                    db.session.add(member)
                    except Exception as e:
                        print(f"WARNING: Could not update main chat members: {e}")
                
                db.session.commit()
                
            except Exception as e:
                print(f"[WARNUNG] Warnung beim Erstellen der Datenbank-Tabellen: {e}")
    
    # Background-Jobs nur im Hauptprozess starten
    if is_main_process and not os.getenv('PRISMATEAMS_SKIP_BACKGROUND_JOBS'):
        start_email_sync(app)
        
        from app.tasks.notification_scheduler import start_notification_scheduler
        start_notification_scheduler(app)
    
    from app.blueprints import canvas
    
    return app



