from flask import Flask
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
    ]
    for directory in upload_dirs:
        os.makedirs(directory, exist_ok=True)
    
    # Make app config available in all templates
    @app.context_processor
    def inject_app_config():
        app_name = app.config.get('APP_NAME', 'Team Portal')
        app_logo = app.config.get('APP_LOGO')
        
        # Fix logo path - remove 'static/' prefix if present since Flask adds it automatically
        if app_logo and app_logo.startswith('static/'):
            app_logo = app_logo[7:]  # Remove 'static/' prefix
        
        # Debug output
        print(f"DEBUG: app_name = {app_name}")
        print(f"DEBUG: app_logo = {app_logo}")
        
        return {
            'app_name': app_name,
            'app_logo': app_logo
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

    # Register blueprints
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
    
    # PWA Manifest Route
    @app.route('/manifest.json')
    def manifest():
        return app.send_static_file('manifest.json')
    
    # Create database tables
    with app.app_context():
        db.create_all()
        
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
        
        db.session.commit()
    
    # Start email auto-sync
    start_email_sync(app)
    
    return app



