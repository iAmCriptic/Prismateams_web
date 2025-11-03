from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from config import config
import os

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()


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
    
    # Configure login manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Bitte melden Sie sich an, um auf diese Seite zuzugreifen.'
    login_manager.login_message_category = 'info'
    
    # Add email confirmation check to all routes
    @app.before_request
    def check_email_confirmation():
        """Prüft E-Mail-Bestätigung für alle Routen außer Auth und Setup."""
        from flask import request, redirect, url_for, flash
        from flask_login import current_user
        
        # Skip check for auth routes, setup, static files, and API
        if (request.endpoint and 
            (request.endpoint.startswith('auth.') or 
             request.endpoint.startswith('setup.') or
             request.endpoint.startswith('static') or
             request.endpoint.startswith('api.') or
             request.endpoint == 'manifest')):
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
    
    # Create upload directories if they don't exist
    upload_dirs = [
        app.config['UPLOAD_FOLDER'],
        os.path.join(app.config['UPLOAD_FOLDER'], 'files'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'chat'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'manuals'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'inventory', 'product_images'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'system'),  # For portal logo
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
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            if portal_name_setting and portal_name_setting.value:
                app_name = portal_name_setting.value
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
        
        return {
            'app_name': app_name,
            'app_logo': app_logo,
            'color_gradient': color_gradient,
            'portal_logo_filename': portal_logo_filename
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
    
    @app.template_filter('markdown')
    def markdown_filter(text):
        """Filter to render markdown text."""
        try:
            import markdown
            from flask import current_app
            
            # Test if tables extension is available
            try:
                import markdown.extensions.tables
                tables_available = True
            except ImportError:
                tables_available = False
            
            current_app.logger.info(f"Tables extension available: {tables_available}")
            
            if tables_available:
                # Create markdown instance with tables extension
                md = markdown.Markdown(
                    extensions=[
                        'tables',
                        'fenced_code',
                        'codehilite',
                        'nl2br'
                    ]
                )
            else:
                # Fallback without tables extension
                md = markdown.Markdown(
                    extensions=[
                        'fenced_code',
                        'codehilite',
                        'nl2br'
                    ]
                )
            
            # Convert markdown to HTML
            html = md.convert(text)
            
            # Debug logging
            current_app.logger.info(f"Markdown input: {text[:200]}...")
            current_app.logger.info(f"Markdown output: {html[:200]}...")
            current_app.logger.info(f"Table detected in output: {'<table>' in html}")
            
            return html
            
        except ImportError:
            # Fallback to plain text if markdown is not installed
            from flask import current_app
            current_app.logger.warning("Markdown library not available, using plain text fallback")
            return text.replace('\n', '<br>')
        except Exception as e:
            # Fallback if markdown processing fails
            from flask import current_app
            current_app.logger.error(f"Markdown processing error: {e}")
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
    
    @app.errorhandler(500)
    def internal_error(error):
        # Log the error
        app.logger.error(f"500 Internal Server Error: {error}", exc_info=True)
        # Rollback any database transactions
        db.session.rollback()
        return render_template('errors/500.html'), 500
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        # Log the error
        app.logger.error(f"Unhandled exception: {e}", exc_info=True)
        
        # Rollback any database transactions
        db.session.rollback()
        
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
            db.create_all()
            print("[OK] Datenbank-Tabellen erfolgreich erstellt/aktualisiert")
            
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
    
    # Start email auto-sync
    start_email_sync(app)
    
    # Start notification scheduler
    from app.tasks.notification_scheduler import start_notification_scheduler
    start_notification_scheduler(app)
    
    return app



